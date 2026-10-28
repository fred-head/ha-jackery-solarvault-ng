"""Pinned upstream golden-state upgrade and rollback evidence."""

from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import timedelta
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.components.recorder.history import get_significant_states
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import async_wait_recording_done

from custom_components.jackery import DOMAIN, _migrate_unique_ids
from custom_components.jackery import button as button_platform
from custom_components.jackery import select as select_platform
from custom_components.jackery.child_migration import ChildMigrationResult, migrate_child_identities
from custom_components.jackery.entities.sensor_definitions import SUBDEVICE_SENSORS
from custom_components.jackery.identity import (
    auto_standby_select_unique_id,
    child_device_identifier,
    child_unique_id,
    official_work_mode_sensor_unique_id,
)
from custom_components.jackery.registry_identity import find_owned_main_entity
from custom_components.jackery.sensor import (
    JackeryDataCoordinator,
    JackeryLegacyWorkModeSensor,
    JackerySensor,
    JackerySubDeviceSensor,
)

from .test_multi_instance_identity import coordinator_for, discover

FIXTURES = Path(__file__).parent / "fixtures" / "upgrades"
ROUTES = ("official_2_0_0", "community_2_5_0", "ng_pre_host_scope")
SERIALS = {
    "plug": "PLUG0001",
    "meter": "METER0001",
    "battery": "BATTERY0001",
    "collector": "COLLECTOR0001",
}
TARGETS = {
    "plug_power": ("plug", "power"),
    "plug_switch": ("plug", "switch"),
    "meter_power": ("smartmeter", "importtotal"),
    "battery_energy": ("battery", "chargeenergy"),
    "collector_power": ("collector", "importpower"),
}
OFFICIAL_CT3_KEYS = {
    "ct3_import_total": "import_total",
    "ct3_import_l1": "import_l1",
    "ct3_import_l2": "import_l2",
    "ct3_import_l3": "import_l3",
    "ct3_export_total": "export_total",
    "ct3_export_l1": "export_l1",
    "ct3_export_l2": "export_l2",
    "ct3_export_l3": "export_l3",
    "ct3_import_energy_total": "import_energy_total",
    "ct3_export_energy_total": "export_energy_total",
}


@dataclass
class SeededState:
    """Real HA registry objects replayed from an upstream-generated fixture."""

    fixture: dict[str, Any]
    entry: MockConfigEntry
    devices: dict[str, dr.DeviceEntry]
    entities: dict[str, er.RegistryEntry]


def load_fixture(name: str) -> dict[str, Any]:
    """Load a deterministic, sanitized pinned-source fixture."""
    return json.loads((FIXTURES / f"{name}.json").read_text())


def _area(hass, name: str) -> str:
    registry = ar.async_get(hass)
    existing = registry.async_get_area_by_name(name)
    return existing.id if existing else registry.async_create(name).id


def seed_fixture(hass, name: str, *, entry: MockConfigEntry | None = None) -> SeededState:
    """Replay constructor output into real HA config/device/entity registries."""
    fixture = load_fixture(name)
    config = fixture["config_entry"]
    if entry is None:
        entry = MockConfigEntry(
            domain=DOMAIN,
            data=config["data"],
            unique_id=config["unique_id"],
            entry_id=config["entry_id"],
            title="Pinned upgrade fixture",
        )
        entry.add_to_hass(hass)

    device_registry = dr.async_get(hass)
    devices: dict[str, dr.DeviceEntry] = {}
    for source in fixture["devices"]:
        device = device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={tuple(item) for item in source["identifiers"]},
            via_device=tuple(source["via_device"]) if source["via_device"] else None,
            name=source["name"],
            manufacturer=source["manufacturer"],
            model=source["model"],
            serial_number=source["serial_number"],
        )
        devices[source["key"]] = device_registry.async_update_device(
            device.id,
            area_id=_area(hass, source["area"]),
            name_by_user=source["name_by_user"],
        )

    entity_registry = er.async_get(hass)
    entities: dict[str, er.RegistryEntry] = {}
    for source in fixture["entities"]:
        customization = source["customization"]
        entity = entity_registry.async_get_or_create(
            source["domain"],
            DOMAIN,
            source["unique_id"],
            config_entry=entry,
            device_id=devices[source["device_key"]].id,
            suggested_object_id=source["role"],
            original_name=source.get("original_name"),
        )
        entities[source["role"]] = entity_registry.async_update_entity(
            entity.entity_id,
            new_entity_id=customization["entity_id"],
            name=customization["name"],
            icon=customization.get("icon"),
            area_id=_area(hass, customization["area"]),
            disabled_by=(
                er.RegistryEntryDisabler.USER
                if customization.get("disabled_by") == "user"
                else None
            ),
        )
    return SeededState(fixture, entry, devices, entities)


def _customization_snapshot(state: SeededState) -> dict[str, Any]:
    return {
        "entry": {
            "entry_id": state.entry.entry_id,
            "unique_id": state.entry.unique_id,
            "data": dict(state.entry.data),
        },
        "devices": {
            key: {
                "id": device.id,
                "name_by_user": device.name_by_user,
                "area_id": device.area_id,
                "via_device_id": device.via_device_id,
            }
            for key, device in state.devices.items()
        },
        "entities": {
            role: {
                "id": entity.id,
                "entity_id": entity.entity_id,
                "name": entity.name,
                "original_name": entity.original_name,
                "icon": entity.icon,
                "disabled_by": entity.disabled_by,
                "area_id": entity.area_id,
                "device_id": entity.device_id,
            }
            for role, entity in state.entities.items()
        },
    }


def _entity_registry_snapshot(entity: er.RegistryEntry) -> tuple[Any, ...]:
    return (
        entity.id, entity.entity_id, entity.unique_id, entity.domain, entity.platform,
        entity.config_entry_id, entity.device_id, entity.name, entity.original_name,
        entity.icon, entity.disabled_by, entity.area_id,
    )


def _device_registry_snapshot(device: dr.DeviceEntry) -> tuple[Any, ...]:
    return (
        device.id, device.identifiers, device.via_device_id,
        device.name, device.name_by_user, device.area_id, device.manufacturer, device.model,
    )


def _semantic_snapshot(hass, state: SeededState) -> dict[str, Any]:
    """Snapshot restorable user semantics without HA's generated registry UUIDs."""
    return {
        "entry": {
            "entry_id": state.entry.entry_id,
            "unique_id": state.entry.unique_id,
            "data": dict(state.entry.data),
        },
        "devices": {
            key: {
                "identifiers": sorted(device.identifiers),
                "name_by_user": device.name_by_user,
                "area": ar.async_get(hass).async_get_area(device.area_id).name,
            }
            for key, device in state.devices.items()
        },
        "entities": {
            role: {
                "entity_id": entity.entity_id,
                "unique_id": entity.unique_id,
                "name": entity.name,
                "original_name": entity.original_name,
                "icon": entity.icon,
                "disabled_by": entity.disabled_by,
                "area": ar.async_get(hass).async_get_area(entity.area_id).name,
                "device_key": next(key for key, device in state.devices.items() if device.id == entity.device_id),
            }
            for role, entity in state.entities.items()
        },
    }


async def run_migration(hass, state: SeededState) -> ChildMigrationResult:
    result = migrate_child_identities(hass, state.entry)
    await _migrate_unique_ids(hass, state.entry, protected_entities=result.protected_entities)
    return result


async def setup_current_ng_entry(hass, entry: MockConfigEntry) -> JackeryDataCoordinator:
    """Set up the integration with mocked MQTT while retaining real HA platforms."""
    async def idle_poll(_coordinator):
        await asyncio.Future()

    with (
        patch("homeassistant.components.mqtt.async_wait_for_mqtt_client", return_value=True),
        patch("homeassistant.components.mqtt.async_subscribe", new=AsyncMock(return_value=Mock())),
        patch.object(JackeryDataCoordinator, "_periodic_data_request", idle_poll),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return hass.data[DOMAIN][entry.entry_id]["coordinator"]


def _current_records(hass, state: SeededState) -> tuple[dict[str, dr.DeviceEntry], dict[str, er.RegistryEntry]]:
    devices = {key: dr.async_get(hass).async_get(device.id) for key, device in state.devices.items()}
    entities = {role: er.async_get(hass).async_get(entity.entity_id) for role, entity in state.entities.items()}
    assert all(devices.values()) and all(entities.values())
    return devices, entities


def _assert_customizations_preserved(hass, state: SeededState, before: dict[str, Any]) -> None:
    devices, entities = _current_records(hass, state)
    for key, device in devices.items():
        expected = before["devices"][key]
        assert device.id == expected["id"]
        assert device.name_by_user == expected["name_by_user"]
        assert device.area_id == expected["area_id"]
        assert device.via_device_id == expected["via_device_id"]
    for role, entity in entities.items():
        expected = before["entities"][role]
        assert entity.id == expected["id"]
        assert entity.entity_id == expected["entity_id"]
        assert entity.name == expected["name"]
        assert entity.original_name == expected["original_name"]
        assert entity.icon == expected["icon"]
        assert entity.disabled_by == expected["disabled_by"]
        assert entity.area_id == expected["area_id"]
        assert entity.device_id == expected["device_id"]
    assert state.entry.entry_id == before["entry"]["entry_id"]
    assert state.entry.unique_id == before["entry"]["unique_id"]
    assert dict(state.entry.data) == before["entry"]["data"]


def _assert_no_duplicates(hass, state: SeededState, *, runtime_entities: bool = False) -> None:
    entries = hass.config_entries.async_entries(DOMAIN)
    assert [entry.entry_id for entry in entries] == [state.entry.entry_id]
    own_entities = er.async_entries_for_config_entry(er.async_get(hass), state.entry.entry_id)
    own_devices = dr.async_entries_for_config_entry(dr.async_get(hass), state.entry.entry_id)
    assert len({entry.id for entry in own_entities}) == len(own_entities)
    assert len({device.id for device in own_devices}) == len(own_devices)
    if not runtime_entities:
        assert len(own_entities) == len(state.entities)
        assert len(own_devices) == len(state.devices)


def _expected_target(state: SeededState, role: str) -> str | None:
    if role == "main_soc":
        if state.fixture["provenance"]["source_repository"].endswith("Jackery-Official/jackery"):
            coordinator = SimpleNamespace(_device_sn=state.entry.data["device_sn"])
            return JackerySensor("bms_soc", coordinator, state.entry.entry_id)._attr_unique_id
        return state.entities[role].unique_id
    if role == "main_reboot":
        coordinator = SimpleNamespace(_device_sn=state.entry.data["device_sn"])
        return button_platform.JackeryRebootButton(coordinator, state.entry.entry_id)._attr_unique_id
    if role == "main_auto_standby":
        coordinator = SimpleNamespace(_device_sn=state.entry.data["device_sn"])
        return select_platform.JackeryAutoStandbySelect(coordinator, state.entry.entry_id)._attr_unique_id
    if role == "main_work_mode":
        return official_work_mode_sensor_unique_id(state.entry.data["device_sn"])
    if role == "main_eps_switch":
        return "jackery_SVHOST0001_switch_swEps"
    if role in OFFICIAL_CT3_KEYS:
        coordinator = SimpleNamespace(_device_sn=state.entry.data["device_sn"])
        sensor_key = OFFICIAL_CT3_KEYS[role]
        return JackerySubDeviceSensor(
            "SHELLY0001", 3, sensor_key, SUBDEVICE_SENSORS["ct_3phase"][sensor_key],
            coordinator, state.entry.entry_id, data_key="cts", sensor_group="ct_3phase",
        )._attr_unique_id
    if state.fixture["provenance"]["source_repository"].endswith("Jackery-Official/jackery") and role == "meter_power":
        return None
    family, key = TARGETS[role]
    device_key = next(item["device_key"] for item in state.fixture["entities"] if item["role"] == role)
    serial = SERIALS[device_key]
    return child_unique_id(state.entry.data["device_sn"], serial, family, key)


def test_fixture_provenance_and_upstream_identity_difference():
    official = load_fixture("official_2_0_0")
    community = load_fixture("community_2_5_0")
    older_ng = load_fixture("ng_pre_host_scope")
    assert official["provenance"]["source_repository"] == "https://github.com/Jackery-Official/jackery"
    assert community["provenance"]["source_repository"] == "https://github.com/csoscd/ha-solarvault"
    assert older_ng["provenance"]["source_repository"] == "https://github.com/fred-head/ha-jackery-solarvault-ng"
    assert official["provenance"]["source_commit"] == "af97223ff17fc8f14314cbc6da7213a5eee7004d"
    assert community["provenance"]["source_commit"] == "77d218f6f531c1b5cd0b2ae5b9f2edfe0c61879c"
    assert older_ng["provenance"]["source_commit"] == "ed89e745fd7ceab35a52593122f28969cafd3bba"
    for fixture in (official, community, older_ng):
        assert fixture["schema_version"] == 1
        assert fixture["provenance"]["home_assistant_version"] == "2026.2.3"
        assert len(fixture["provenance"]["source_files_sha256"]) == 64
        rendered = json.dumps(fixture).lower()
        assert "synthetic-upgrade-token" in rendered
        assert "credential" not in rendered and "password" not in rendered
    official_plug = next(item for item in official["entities"] if item["role"] == "plug_power")
    official_auto_standby = next(item for item in official["entities"] if item["role"] == "main_auto_standby")
    official_work_mode = next(item for item in official["entities"] if item["role"] == "main_work_mode")
    community_plug = next(item for item in community["entities"] if item["role"] == "plug_power")
    assert official_plug["unique_id"] == "jackery_SVHOST0001_plug_PLUG0001_power"
    assert official_auto_standby["unique_id"] == "jackery_SVHOST0001_main_autoStandby"
    assert official_auto_standby["domain"] == "select"
    assert official_work_mode["unique_id"] == "jackery_SVHOST0001_work_mode"
    assert official_work_mode["domain"] == "sensor"
    assert community_plug["unique_id"] == "jackery_plug_PLUG0001_power"


async def test_official_upgrade_migrates_supported_children_in_place(hass):
    """Migrate exact Official main and Type 3 identities in place."""
    state = seed_fixture(hass, "official_2_0_0")
    registry = er.async_get(hass)
    assert state.entities["main_auto_standby"].unique_id == "jackery_SVHOST0001_main_autoStandby"
    assert state.entities["main_work_mode"].unique_id == "jackery_SVHOST0001_work_mode"
    main_number = registry.async_get_or_create(
        "number",
        DOMAIN,
        "jackery_SVHOST0001_main_socChgLimit",
        config_entry=state.entry,
        device_id=state.devices["main"].id,
    )
    state.entities["main_charge_number"] = registry.async_update_entity(
        main_number.entity_id,
        new_entity_id="number.custom_charge_limit",
        name="Custom charge limit",
        disabled_by=er.RegistryEntryDisabler.USER,
    )
    unknown_control = registry.async_get_or_create(
        "switch",
        DOMAIN,
        "jackery_SVHOST0001_main_unknownControl",
        config_entry=state.entry,
        device_id=state.devices["main"].id,
    )
    state.entities["unknown_main_control"] = registry.async_update_entity(
        unknown_control.entity_id,
        new_entity_id="switch.unknown_legacy_control",
        name="Unknown legacy control",
    )
    before = _customization_snapshot(state)
    result = await run_migration(hass, state)
    devices, entities = _current_records(hass, state)
    assert result.allows("PLUG0001")
    assert devices["plug"].identifiers == {(DOMAIN, child_device_identifier("SVHOST0001", "PLUG0001"))}
    assert entities["plug_power"].unique_id == child_unique_id("SVHOST0001", "PLUG0001", "plug", "power")
    assert entities["plug_switch"].unique_id == child_unique_id("SVHOST0001", "PLUG0001", "plug", "switch")
    assert entities["main_eps_switch"].unique_id == "jackery_SVHOST0001_switch_swEps"
    assert entities["main_charge_number"].unique_id == "jackery_SVHOST0001_number_socChgLimit"
    assert entities["unknown_main_control"].unique_id == "jackery_SVHOST0001_main_unknownControl"
    assert entities["main_reboot"].unique_id == _expected_target(state, "main_reboot")
    assert entities["main_soc"].unique_id == _expected_target(state, "main_soc")
    assert entities["main_auto_standby"].unique_id == _expected_target(state, "main_auto_standby")
    assert entities["main_work_mode"].unique_id == _expected_target(state, "main_work_mode")
    assert entities["main_reboot"].entity_id == "button.my_solarvault_reboot"
    assert entities["main_soc"].entity_id == "sensor.my_solarvault_soc"
    assert entities["main_auto_standby"].id == state.entities["main_auto_standby"].id
    assert entities["main_auto_standby"].entity_id == "select.my_auto_standby_mode"
    assert entities["main_work_mode"].id == state.entities["main_work_mode"].id
    assert entities["main_work_mode"].entity_id == "sensor.my_work_mode"
    assert entities["main_reboot"].original_name == "Reboot"
    assert entities["main_soc"].original_name == "Average SOC"
    assert entities["main_reboot"].unique_id == "jackery_SVHOST0001_reboot"
    assert entities["main_soc"].unique_id == "jackery_SVHOST0001_bms_soc"
    assert entities["main_auto_standby"].unique_id == auto_standby_select_unique_id("SVHOST0001")
    assert entities["main_work_mode"].unique_id == "jackery_SVHOST0001_work_mode"
    own = er.async_entries_for_config_entry(registry, state.entry.entry_id)
    assert [entity for entity in own if entity.domain == "button"] == [entities["main_reboot"]]
    assert [entity for entity in own if entity.unique_id == "jackery_SVHOST0001_average_soc"] == []
    assert [entity for entity in own if entity.unique_id == "jackery_SVHOST0001_bms_soc"] == [entities["main_soc"]]
    assert [entity for entity in own if entity.domain == "select"] == [entities["main_auto_standby"]]
    # Official's richer generic-CT entity has no proven one-to-one NG target.
    assert not result.allows("METER0001")
    assert devices["meter"].identifiers == {(DOMAIN, "sub_SVHOST0001_METER0001")}
    assert entities["meter_power"].unique_id == "jackery_SVHOST0001_ct_METER0001_powertotalforward"
    assert result.allows("SHELLY0001")
    discovery_coordinator = JackeryDataCoordinator(hass, "hb", None, None, "SVHOST0001")
    discovery_coordinator._child_migration = result
    assert discovery_coordinator.child_identity_allowed("SHELLY0001")
    assert devices["ct3"].identifiers == {
        (DOMAIN, child_device_identifier("SVHOST0001", "SHELLY0001")),
    }
    assert devices["ct3"].id == state.devices["ct3"].id
    fixture_entities = {item["role"]: item for item in state.fixture["entities"]}
    for role in OFFICIAL_CT3_KEYS:
        assert entities[role].unique_id == _expected_target(state, role)
        assert entities[role].id == state.entities[role].id
        assert entities[role].entity_id == state.entities[role].entity_id
        assert entities[role].original_name == fixture_entities[role]["original_name"]
    ct3_devices = [device for device in devices.values() if device.model == "Sub-device Type 3"]
    assert [device.id for device in ct3_devices] == [state.devices["ct3"].id]
    assert all(not entity.entity_id.endswith(("_2", "_3")) for entity in own)
    assert devices["main"].identifiers == {(DOMAIN, "SVHOST0001")}
    _assert_customizations_preserved(hass, state, before)
    _assert_no_duplicates(hass, state)
    after = _customization_snapshot(state)
    second = await run_migration(hass, state)
    assert second.allows("SHELLY0001") and not second.block_all
    assert _customization_snapshot(state) == after
    _assert_no_duplicates(hass, state)


@pytest.mark.parametrize(
    "conflict",
    ["unknown_only", "mixed_unknown", "target_entity", "target_device", "foreign_entity", "wrong_domain", "malformed_device"],
)
async def test_official_type3_ct_conflicts_retain_the_complete_child(hass, conflict):
    """No Type 3 device or entity is changed unless all ten mappings preflight."""
    state = seed_fixture(hass, "official_2_0_0")
    devices, entities = dr.async_get(hass), er.async_get(hass)
    child = devices.async_get(state.devices["ct3"].id)
    assert child is not None
    other = None
    foreign_target = None
    if conflict == "unknown_only":
        for index, role in enumerate(OFFICIAL_CT3_KEYS):
            row = entities.async_get(state.entities[role].entity_id)
            assert row is not None
            entities.async_update_entity(
                row.entity_id,
                new_unique_id=f"jackery_SVHOST0001_ct_SHELLY0001_unknown{index}",
            )
    elif conflict == "mixed_unknown":
        entities.async_get_or_create(
            "sensor", DOMAIN, "jackery_SVHOST0001_ct_SHELLY0001_unknownphase",
            config_entry=state.entry, device_id=child.id,
        )
    elif conflict in {"target_entity", "target_device", "foreign_entity"}:
        other = MockConfigEntry(domain=DOMAIN, data={"device_sn": "OTHER"}, unique_id="OTHER")
        other.add_to_hass(hass)
        if conflict == "target_entity":
            target = _expected_target(state, "ct3_import_total")
            assert target
            foreign_target = entities.async_get_or_create("sensor", DOMAIN, target, config_entry=other)
        elif conflict == "target_device":
            devices.async_get_or_create(
                config_entry_id=other.entry_id,
                identifiers={(DOMAIN, child_device_identifier("SVHOST0001", "SHELLY0001"))},
            )
        else:
            entities.async_get_or_create(
                "sensor", DOMAIN, "jackery_SVHOST0001_ct_SHELLY0001_unknownforeign",
                config_entry=other, device_id=child.id,
            )
    elif conflict == "wrong_domain":
        entities.async_get_or_create(
            "button", DOMAIN, "jackery_SVHOST0001_ct_SHELLY0001_powertotalforward",
            config_entry=state.entry, device_id=child.id,
        )
    else:
        devices.async_update_device(child.id, new_identifiers={(DOMAIN, "sub_SHELLY0001")})

    before_device = _device_registry_snapshot(devices.async_get(child.id))
    before_entities = {
        role: _entity_registry_snapshot(entities.async_get(state.entities[role].entity_id))
        for role in OFFICIAL_CT3_KEYS
    }
    before_child_entities = {
        row.entity_id: _entity_registry_snapshot(row)
        for row in er.async_entries_for_device(entities, child.id, include_disabled_entities=True)
    }
    result = migrate_child_identities(hass, state.entry)

    assert not result.allows("SHELLY0001")
    current_child = devices.async_get(child.id)
    assert current_child is not None and _device_registry_snapshot(current_child) == before_device
    assert {
        role: _entity_registry_snapshot(entities.async_get(state.entities[role].entity_id))
        for role in OFFICIAL_CT3_KEYS
    } == before_entities
    assert {
        row.entity_id: _entity_registry_snapshot(row)
        for row in er.async_entries_for_device(entities, child.id, include_disabled_entities=True)
    } == before_child_entities
    if foreign_target is not None:
        current_target = entities.async_get(foreign_target.entity_id)
        assert current_target is not None and _entity_registry_snapshot(current_target) == _entity_registry_snapshot(foreign_target)
    if conflict == "target_device":
        foreign_devices = dr.async_entries_for_config_entry(devices, other.entry_id)
        assert any(
            (DOMAIN, child_device_identifier("SVHOST0001", "SHELLY0001")) in row.identifiers
            for row in foreign_devices
        )


@pytest.mark.parametrize("role", ["main_reboot", "main_soc", "main_auto_standby"])
async def test_official_main_identity_target_conflict_retains_both_rows(hass, role, caplog):
    state = seed_fixture(hass, "official_2_0_0")
    source = state.entities[role]
    target_uid = _expected_target(state, role)
    assert target_uid
    other = MockConfigEntry(domain=DOMAIN, data={"device_sn": "OTHER"}, unique_id="OTHER")
    other.add_to_hass(hass)
    registry = er.async_get(hass)
    target = registry.async_get_or_create(source.domain, DOMAIN, target_uid, config_entry=other)
    before_source = _entity_registry_snapshot(source)
    before_target = _entity_registry_snapshot(target)
    caplog.clear()

    await _migrate_unique_ids(hass, state.entry)

    assert _entity_registry_snapshot(registry.async_get(source.entity_id)) == before_source
    assert _entity_registry_snapshot(registry.async_get(target.entity_id)) == before_target
    assert sum(
        entity.unique_id == target_uid and entity.domain == source.domain and entity.platform == DOMAIN
        for entity in er.async_entries_for_config_entry(registry, other.entry_id)
    ) == 1
    assert "target" in caplog.text and "retaining both records" in caplog.text


@pytest.mark.parametrize("ownership", ["unlinked", "foreign_device"])
@pytest.mark.parametrize("role", ["main_reboot", "main_soc", "main_auto_standby"])
async def test_official_main_identity_requires_owned_host_device(hass, role, ownership):
    state = seed_fixture(hass, "official_2_0_0")
    source = state.entities[role]
    registry = er.async_get(hass)
    if ownership == "unlinked":
        registry.async_update_entity(source.entity_id, device_id=None)
    else:
        other = MockConfigEntry(domain=DOMAIN, data={"device_sn": "OTHER"}, unique_id="OTHER")
        other.add_to_hass(hass)
        foreign_main = dr.async_get(hass).async_get_or_create(
            config_entry_id=other.entry_id, identifiers={(DOMAIN, "OTHER_MAIN")},
        )
        registry.async_update_entity(source.entity_id, device_id=foreign_main.id)
    before = _entity_registry_snapshot(registry.async_get(source.entity_id))

    await _migrate_unique_ids(hass, state.entry)

    assert _entity_registry_snapshot(registry.async_get(source.entity_id)) == before
    target_uid = _expected_target(state, role)
    assert target_uid
    assert not any(
        entity.unique_id == target_uid and entity.domain == source.domain and entity.platform == DOMAIN
        for entity in er.async_entries_for_config_entry(registry, state.entry.entry_id)
    )


async def test_official_main_reboot_identity_does_not_migrate_across_domains(hass):
    state = seed_fixture(hass, "official_2_0_0")
    registry = er.async_get(hass)
    wrong_domain = registry.async_get_or_create(
        "sensor", DOMAIN, "jackery_SVHOST0001_main_reboot",
        config_entry=state.entry, device_id=state.devices["main"].id,
    )
    before = _entity_registry_snapshot(wrong_domain)

    await _migrate_unique_ids(hass, state.entry)

    assert _entity_registry_snapshot(registry.async_get(wrong_domain.entity_id)) == before
    assert registry.async_get(state.entities["main_reboot"].entity_id).unique_id == "jackery_SVHOST0001_reboot"


async def test_official_auto_standby_identity_does_not_migrate_across_domains(hass):
    """The exact legacy select identity is migrated only in the select domain."""
    state = seed_fixture(hass, "official_2_0_0")
    registry = er.async_get(hass)
    wrong_domain = registry.async_get_or_create(
        "sensor", DOMAIN, "jackery_SVHOST0001_main_autoStandby",
        config_entry=state.entry, device_id=state.devices["main"].id,
    )
    before = _entity_registry_snapshot(wrong_domain)

    await _migrate_unique_ids(hass, state.entry)

    assert _entity_registry_snapshot(registry.async_get(wrong_domain.entity_id)) == before
    assert registry.async_get(state.entities["main_auto_standby"].entity_id).unique_id == (
        auto_standby_select_unique_id("SVHOST0001")
    )


async def test_official_auto_standby_user_disabled_customization_survives(hass):
    """An in-place Auto Standby migration retains the registry's user settings."""
    state = seed_fixture(hass, "official_2_0_0")
    registry = er.async_get(hass)
    source = state.entities["main_auto_standby"]
    registry.async_update_entity(source.entity_id, disabled_by=er.RegistryEntryDisabler.USER)
    before = _entity_registry_snapshot(registry.async_get(source.entity_id))

    await _migrate_unique_ids(hass, state.entry)

    current = registry.async_get(source.entity_id)
    assert current is not None
    assert current.id == source.id
    assert current.entity_id == "select.my_auto_standby_mode"
    assert current.unique_id == auto_standby_select_unique_id("SVHOST0001")
    assert current.name == before[7] and current.original_name == before[8]
    assert current.icon == before[9]
    assert current.disabled_by is er.RegistryEntryDisabler.USER
    assert current.area_id == before[11]


async def test_official_work_mode_sensor_keeps_its_sensor_identity(hass):
    """The Official sensor row remains separate from the writable NG selector."""
    state = seed_fixture(hass, "official_2_0_0")
    registry = er.async_get(hass)
    select = registry.async_get_or_create(
        "select", DOMAIN, "jackery_SVHOST0001_work_mode_select",
        config_entry=state.entry, device_id=state.devices["main"].id,
    )
    sensor = state.entities["main_work_mode"]
    before_sensor = _entity_registry_snapshot(sensor)
    before_select = _entity_registry_snapshot(select)

    await _migrate_unique_ids(hass, state.entry)

    assert _entity_registry_snapshot(registry.async_get(sensor.entity_id)) == before_sensor
    assert _entity_registry_snapshot(registry.async_get(select.entity_id)) == before_select
    assert sensor.unique_id == official_work_mode_sensor_unique_id("SVHOST0001")


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_official_auto_standby_and_work_mode_bind_existing_registry_rows(hass):
    """Bind both current controls while preserving the old select and sensor rows."""
    state = seed_fixture(hass, "official_2_0_0")
    auto_before = _entity_registry_snapshot(state.entities["main_auto_standby"])
    work_mode_before = _entity_registry_snapshot(state.entities["main_work_mode"])

    coordinator = await setup_current_ng_entry(hass, state.entry)
    registry = er.async_get(hass)
    auto = registry.async_get(state.entities["main_auto_standby"].entity_id)
    work_mode = registry.async_get(state.entities["main_work_mode"].entity_id)
    assert auto is not None and auto.id == state.entities["main_auto_standby"].id
    assert auto.unique_id == _expected_target(state, "main_auto_standby")
    assert auto.entity_id == "select.my_auto_standby_mode"
    assert auto.name == "My Auto Standby Mode"
    assert auto.icon == "mdi:sleep"
    assert auto.area_id == state.entities["main_auto_standby"].area_id
    assert work_mode is not None and work_mode.id == state.entities["main_work_mode"].id
    assert _entity_registry_snapshot(work_mode) == work_mode_before
    assert _entity_registry_snapshot(auto)[:2] == auto_before[:2]
    assert work_mode.unique_id == official_work_mode_sensor_unique_id("SVHOST0001")
    assert isinstance(coordinator._sensors.get("main_legacy_work_mode"), JackeryLegacyWorkModeSensor)

    coordinator._distribute_data({"autoStandby": 2, "workMode": 4})
    await hass.async_block_till_done()
    assert hass.states.get("select.my_auto_standby_mode").state == "on"
    assert hass.states.get("sensor.my_work_mode").state == "4.0"
    own = er.async_entries_for_config_entry(registry, state.entry.entry_id)
    assert [row for row in own if row.domain == "select" and row.unique_id == auto.unique_id] == [auto]
    assert sum(
        row.domain == "select" and row.unique_id == auto_standby_select_unique_id("SVHOST0001")
        for row in own
    ) == 1
    work_select_id = registry.async_get_entity_id(
        "select", DOMAIN, "jackery_SVHOST0001_work_mode_select",
    )
    assert work_select_id is not None
    assert hass.states.get(work_select_id).state == "custom"
    work_mode = coordinator._sensors["main_legacy_work_mode"]
    assert work_mode.available
    coordinator._mark_all_offline()
    await hass.async_block_till_done()
    assert hass.states.get("sensor.my_work_mode").state == "unavailable"
    coordinator._distribute_data({"workMode": 2})
    await hass.async_block_till_done()
    assert hass.states.get("sensor.my_work_mode").state == "2.0"
    assert hass.states.get(work_select_id).state == "self_consumption"
    assert not any(row.unique_id == "jackery_SVHOST0001_main_autoStandby" for row in own)
    assert not any(row.entity_id.endswith(("_2", "_3")) for row in own)

    assert await hass.config_entries.async_unload(state.entry.entry_id)
    await hass.async_block_till_done()
    assert "main_legacy_work_mode" not in coordinator._sensors


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_fresh_ng_setup_has_work_mode_select_without_legacy_sensor(hass):
    """A new NG installation does not acquire Official-only compatibility state."""
    state = seed_fixture(hass, "community_2_5_0")
    coordinator = await setup_current_ng_entry(hass, state.entry)
    registry = er.async_get(hass)
    legacy_uid = official_work_mode_sensor_unique_id("SVHOST0001")
    assert not any(
        row.domain == "sensor" and row.platform == DOMAIN and row.unique_id == legacy_uid
        for row in er.async_entries_for_config_entry(registry, state.entry.entry_id)
    )
    assert "main_legacy_work_mode" not in coordinator._sensors
    work_select = registry.async_get_entity_id("select", DOMAIN, "jackery_SVHOST0001_work_mode_select")
    assert work_select is not None
    assert hass.states.get(work_select) is not None
    assert await hass.config_entries.async_unload(state.entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_disabled_official_work_mode_stays_disabled_without_listener(hass):
    """A disabled legacy row stays user-disabled and is never replaced."""
    state = seed_fixture(hass, "official_2_0_0")
    registry = er.async_get(hass)
    original = state.entities["main_work_mode"]
    registry.async_update_entity(original.entity_id, disabled_by=er.RegistryEntryDisabler.USER)
    before = _entity_registry_snapshot(registry.async_get(original.entity_id))

    coordinator = await setup_current_ng_entry(hass, state.entry)

    current = registry.async_get(original.entity_id)
    assert current is not None and _entity_registry_snapshot(current) == before
    assert current.disabled_by is er.RegistryEntryDisabler.USER
    assert "main_legacy_work_mode" not in coordinator._sensors
    assert hass.states.get(original.entity_id) is None
    work_select_id = registry.async_get_entity_id(
        "select", DOMAIN, "jackery_SVHOST0001_work_mode_select",
    )
    assert work_select_id is not None and hass.states.get(work_select_id) is not None
    assert await hass.config_entries.async_unload(state.entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.parametrize("invalid_case", ["foreign_entry", "foreign_device", "shared_main", "wrong_domain", "wrong_platform"])
@pytest.mark.usefixtures("enable_custom_integrations")
async def test_work_mode_legacy_bridge_rejects_unproven_registry_ownership(hass, invalid_case):
    """Only the exact sensor row on the exclusively owned host device is adopted."""
    state = seed_fixture(hass, "official_2_0_0")
    registry = er.async_get(hass)
    original = state.entities["main_work_mode"]
    other = None
    if invalid_case in {"foreign_entry", "foreign_device", "shared_main"}:
        other = MockConfigEntry(domain=DOMAIN, data={"device_sn": "OTHER"}, unique_id="OTHER")
        other.add_to_hass(hass)
    if invalid_case == "foreign_entry":
        registry.async_remove(original.entity_id)
        other_main = dr.async_get(hass).async_get_or_create(
            config_entry_id=other.entry_id, identifiers={(DOMAIN, "OTHER")},
        )
        invalid = registry.async_get_or_create(
            "sensor", DOMAIN, official_work_mode_sensor_unique_id("SVHOST0001"),
            config_entry=other, device_id=other_main.id,
        )
    elif invalid_case == "foreign_device":
        other_main = dr.async_get(hass).async_get_or_create(
            config_entry_id=other.entry_id, identifiers={(DOMAIN, "OTHER")},
        )
        registry.async_update_entity(original.entity_id, device_id=other_main.id)
        invalid = registry.async_get(original.entity_id)
    elif invalid_case == "shared_main":
        dr.async_get(hass).async_update_device(
            state.devices["main"].id,
            add_config_entry_id=other.entry_id,
        )
        invalid = registry.async_get(original.entity_id)
    elif invalid_case == "wrong_domain":
        registry.async_remove(original.entity_id)
        invalid = registry.async_get_or_create(
            "select", DOMAIN, official_work_mode_sensor_unique_id("SVHOST0001"),
            config_entry=state.entry, device_id=state.devices["main"].id,
        )
    else:
        registry.async_remove(original.entity_id)
        invalid = registry.async_get_or_create(
            "sensor", "foreign_platform", official_work_mode_sensor_unique_id("SVHOST0001"),
            config_entry=state.entry, device_id=state.devices["main"].id,
        )
    assert invalid is not None

    assert find_owned_main_entity(
        hass,
        domain="sensor",
        host="SVHOST0001",
        platform=DOMAIN,
        config_entry_id=state.entry.entry_id,
        unique_id=official_work_mode_sensor_unique_id("SVHOST0001"),
    ) is None
    coordinator = await setup_current_ng_entry(hass, state.entry)
    assert "main_legacy_work_mode" not in coordinator._sensors
    assert registry.async_get(invalid.entity_id) is not None
    assert await hass.config_entries.async_unload(state.entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_work_mode_legacy_listener_is_removed_and_reload_does_not_accumulate(hass):
    """The bridge owns one fan-out listener and adds no MQTT subscription per entity."""
    state = seed_fixture(hass, "official_2_0_0")

    async def idle_poll(_coordinator):
        await asyncio.Future()

    subscribe = AsyncMock(return_value=Mock())
    registry = er.async_get(hass)
    auto_standby = state.entities["main_auto_standby"]
    with (
        patch("homeassistant.components.mqtt.async_wait_for_mqtt_client", return_value=True),
        patch("homeassistant.components.mqtt.async_subscribe", new=subscribe),
        patch.object(JackeryDataCoordinator, "_periodic_data_request", idle_poll),
    ):
        for cycle in range(1, 4):
            assert await hass.config_entries.async_setup(state.entry.entry_id)
            await hass.async_block_till_done()
            coordinator = hass.data[DOMAIN][state.entry.entry_id]["coordinator"]
            assert isinstance(coordinator._sensors.get("main_legacy_work_mode"), JackeryLegacyWorkModeSensor)
            assert sum(key == "main_legacy_work_mode" for key in coordinator._sensors) == 1
            auto_current = registry.async_get(auto_standby.entity_id)
            assert auto_current is not None
            assert auto_current.id == auto_standby.id
            assert auto_current.entity_id == "select.my_auto_standby_mode"
            assert auto_current.unique_id == auto_standby_select_unique_id("SVHOST0001")
            assert sum(
                row.domain == "select"
                and row.platform == DOMAIN
                and row.unique_id == auto_current.unique_id
                for row in er.async_entries_for_config_entry(registry, state.entry.entry_id)
            ) == 1
            assert subscribe.await_count == cycle * 2
            assert await hass.config_entries.async_unload(state.entry.entry_id)
            await hass.async_block_till_done()
            assert "main_legacy_work_mode" not in coordinator._sensors


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_official_work_mode_recorder_history_continues_under_existing_entity_id(recorder_mock, hass):
    """The legacy bridge appends the new workMode state to the existing recorder row."""
    state = seed_fixture(hass, "official_2_0_0")
    source = state.entities["main_work_mode"]
    start = dt_util.utcnow() - timedelta(seconds=1)
    hass.states.async_set(source.entity_id, "2.0", {"phase": "before-upgrade"})
    await async_wait_recording_done(hass)
    # HA restarts between code replacement and the new platform setup. The
    # recorder row survives, while the in-memory state is rebuilt by NG.
    hass.states.async_remove(source.entity_id)
    await hass.async_block_till_done()

    await run_migration(hass, state)
    coordinator = await setup_current_ng_entry(hass, state.entry)
    coordinator._distribute_data({"workMode": 4})
    await hass.async_block_till_done()
    assert hass.states.get(source.entity_id).state == "4.0"
    await async_wait_recording_done(hass)

    current = er.async_get(hass).async_get(source.entity_id)
    assert current is not None and current.id == source.id
    assert current.entity_id == source.entity_id
    assert current.unique_id == official_work_mode_sensor_unique_id("SVHOST0001")
    history = await recorder_mock.async_add_executor_job(partial(
        get_significant_states,
        hass,
        start,
        entity_ids=[source.entity_id],
        include_start_time_state=False,
        significant_changes_only=False,
    ))
    values = [item.state for item in history[source.entity_id]]
    assert "2.0" in values and "4.0" in values
    select_id = er.async_get(hass).async_get_entity_id(
        "select", DOMAIN, "jackery_SVHOST0001_work_mode_select",
    )
    assert select_id is not None and select_id in hass.states.async_entity_ids("select")
    assert await hass.config_entries.async_unload(state.entry.entry_id)
    await hass.async_block_till_done()


async def test_community_child_serial_starting_with_host_is_not_split(hass):
    """Official disambiguation must not reinterpret a Community child serial."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"device_sn": "SVHOST0001", "token": "synthetic", "topic_prefix": "hb"},
        unique_id="SVHOST0001",
    )
    entry.add_to_hass(hass)
    serial = "SVHOST0001_PLUG0001"
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, f"sub_{serial}")},
    )
    entity = er.async_get(hass).async_get_or_create(
        "sensor",
        DOMAIN,
        f"jackery_plug_{serial}_power",
        config_entry=entry,
        device_id=device.id,
    )
    result = migrate_child_identities(hass, entry)
    assert result.allows(serial)
    assert dr.async_get(hass).async_get(device.id).identifiers == {
        (DOMAIN, child_device_identifier("SVHOST0001", serial)),
    }
    assert er.async_get(hass).async_get(entity.entity_id).unique_id == child_unique_id(
        "SVHOST0001", serial, "plug", "power",
    )


@pytest.mark.parametrize("fixture_name", ["community_2_5_0", "ng_pre_host_scope"])
async def test_global_legacy_upgrade_migrates_all_children_in_place(hass, fixture_name):
    state = seed_fixture(hass, fixture_name)
    before = _customization_snapshot(state)
    result = await run_migration(hass, state)
    devices, entities = _current_records(hass, state)
    for key, serial in SERIALS.items():
        assert result.allows(serial)
        assert devices[key].identifiers == {(DOMAIN, child_device_identifier("SVHOST0001", serial))}
    for role, entity in entities.items():
        target = _expected_target(state, role)
        assert target is not None and entity.unique_id == target
    _assert_customizations_preserved(hass, state, before)
    _assert_no_duplicates(hass, state)
    after = deepcopy((
        {key: device.identifiers for key, device in devices.items()},
        {role: entity.unique_id for role, entity in entities.items()},
    ))
    assert (await run_migration(hass, state)).blocked_children == set()
    current_devices, current_entities = _current_records(hass, state)
    assert after == (
        {key: device.identifiers for key, device in current_devices.items()},
        {role: entity.unique_id for role, entity in current_entities.items()},
    )


@pytest.mark.parametrize("fixture_name", ROUTES)
async def test_recorder_history_continues_on_same_entity_ids(recorder_mock, hass, fixture_name):
    state = seed_fixture(hass, fixture_name)
    start = dt_util.utcnow() - timedelta(seconds=1)
    roles = ("main_soc", "plug_power", "meter_power")
    for index, role in enumerate(roles, start=1):
        hass.states.async_set(state.entities[role].entity_id, str(index * 100), {"fixture": fixture_name})
    await async_wait_recording_done(hass)
    await run_migration(hass, state)
    for index, role in enumerate(roles, start=1):
        current = er.async_get(hass).async_get(state.entities[role].entity_id)
        assert current.id == state.entities[role].id
        hass.states.async_set(current.entity_id, str(index * 100 + 1), {"fixture": fixture_name})
    await async_wait_recording_done(hass)
    entity_ids = [state.entities[role].entity_id for role in roles]
    history = await recorder_mock.async_add_executor_job(partial(
        get_significant_states,
        hass,
        start,
        entity_ids=entity_ids,
        include_start_time_state=False,
    ))
    assert set(history) == set(entity_ids)
    for index, role in enumerate(roles, start=1):
        assert [item.state for item in history[state.entities[role].entity_id]] == [str(index * 100), str(index * 100 + 1)]


async def test_official_type3_ct_recorder_history_continues(recorder_mock, hass):
    """Mapped import/export power and energy append to the existing history rows."""
    state = seed_fixture(hass, "official_2_0_0")
    roles = ("ct3_import_total", "ct3_export_total", "ct3_import_energy_total")
    start = dt_util.utcnow() - timedelta(seconds=1)
    for index, role in enumerate(roles, start=1):
        hass.states.async_set(state.entities[role].entity_id, str(index * 10), {"phase": "before"})
    await async_wait_recording_done(hass)

    result = await run_migration(hass, state)
    assert result.allows("SHELLY0001")
    for index, role in enumerate(roles, start=1):
        original = state.entities[role]
        current = er.async_get(hass).async_get(original.entity_id)
        assert current is not None and current.id == original.id
        assert current.unique_id == _expected_target(state, role)
        hass.states.async_set(current.entity_id, str(index * 10 + 1), {"phase": "after"})
    await async_wait_recording_done(hass)

    history = await recorder_mock.async_add_executor_job(partial(
        get_significant_states,
        hass,
        start,
        entity_ids=[state.entities[role].entity_id for role in roles],
        include_start_time_state=False,
    ))
    for index, role in enumerate(roles, start=1):
        assert [item.state for item in history[state.entities[role].entity_id]] == [
            str(index * 10), str(index * 10 + 1),
        ]


async def test_golden_state_conflict_preserves_child_and_migrates_safe_siblings(hass, caplog):
    state = seed_fixture(hass, "community_2_5_0")
    other = MockConfigEntry(domain=DOMAIN, data={"device_sn": "OTHER"}, unique_id="OTHER")
    other.add_to_hass(hass)
    target = child_unique_id("SVHOST0001", "PLUG0001", "plug", "power")
    er.async_get(hass).async_get_or_create("sensor", DOMAIN, target, config_entry=other)
    before_plug = _customization_snapshot(state)["entities"]["plug_power"]
    main = state.devices["main"]
    main_source = er.async_get(hass).async_get_or_create(
        "switch", DOMAIN, "jackery_SVHOST0001_main_swEps",
        config_entry=state.entry, device_id=main.id,
    )
    main_target = er.async_get(hass).async_get_or_create(
        "switch", DOMAIN, "jackery_SVHOST0001_switch_swEps",
        config_entry=state.entry, device_id=main.id,
    )
    caplog.clear()
    result = await run_migration(hass, state)
    plug = er.async_get(hass).async_get(state.entities["plug_power"].entity_id)
    meter = er.async_get(hass).async_get(state.entities["meter_power"].entity_id)
    assert not result.allows("PLUG0001")
    assert plug.id == before_plug["id"] and plug.unique_id == "jackery_plug_PLUG0001_power"
    assert meter.unique_id == child_unique_id("SVHOST0001", "METER0001", "smartmeter", "importtotal")
    assert er.async_get(hass).async_get(main_source.entity_id).unique_id == "jackery_SVHOST0001_main_swEps"
    assert er.async_get(hass).async_get(main_target.entity_id).unique_id == "jackery_SVHOST0001_switch_swEps"
    assert "PLUG0001" not in caplog.text
    assert "retained" in caplog.text


def _register_upstream_code_again(hass, state: SeededState) -> tuple[int, int]:
    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)
    devices: dict[str, dr.DeviceEntry] = {}
    for source in state.fixture["devices"]:
        devices[source["key"]] = device_registry.async_get_or_create(
            config_entry_id=state.entry.entry_id,
            identifiers={tuple(item) for item in source["identifiers"]},
            via_device=tuple(source["via_device"]) if source["via_device"] else None,
            name=source["name"],
        )
    for source in state.fixture["entities"]:
        entity_registry.async_get_or_create(
            source["domain"], DOMAIN, source["unique_id"],
            config_entry=state.entry,
            device_id=devices[source["device_key"]].id,
            suggested_object_id=source["role"],
        )
    return (
        len(dr.async_entries_for_config_entry(device_registry, state.entry.entry_id)),
        len(er.async_entries_for_config_entry(entity_registry, state.entry.entry_id)),
    )


@pytest.mark.parametrize("fixture_name", ["official_2_0_0", "community_2_5_0"])
async def test_code_only_downgrade_creates_parallel_child_records(hass, fixture_name):
    state = seed_fixture(hass, fixture_name)
    await run_migration(hass, state)
    before = (
        len(dr.async_entries_for_config_entry(dr.async_get(hass), state.entry.entry_id)),
        len(er.async_entries_for_config_entry(er.async_get(hass), state.entry.entry_id)),
    )
    after = _register_upstream_code_again(hass, state)
    assert after[0] > before[0]
    assert after[1] > before[1]


@pytest.mark.parametrize("fixture_name", ["official_2_0_0", "community_2_5_0"])
async def test_full_semantic_snapshot_can_restore_pre_upgrade_state(hass, fixture_name):
    state = seed_fixture(hass, fixture_name)
    before = _semantic_snapshot(hass, state)
    await run_migration(hass, state)
    entities = er.async_get(hass)
    devices = dr.async_get(hass)
    for entity in list(er.async_entries_for_config_entry(entities, state.entry.entry_id)):
        entities.async_remove(entity.entity_id)
    for device in list(dr.async_entries_for_config_entry(devices, state.entry.entry_id)):
        devices.async_remove_device(device.id)
    restored = seed_fixture(hass, fixture_name, entry=state.entry)
    assert _semantic_snapshot(hass, restored) == before


@pytest.mark.parametrize("fixture_name", ["official_2_0_0", "community_2_5_0"])
@pytest.mark.usefixtures("enable_custom_integrations")
async def test_current_ng_setup_reuses_migrated_selected_records(hass, fixture_name):
    state = seed_fixture(hass, fixture_name)
    original_ids = {role: entity.id for role, entity in state.entities.items()}

    async def idle_poll(_coordinator):
        await asyncio.Future()

    with (
        patch("homeassistant.components.mqtt.async_wait_for_mqtt_client", return_value=True),
        patch("homeassistant.components.mqtt.async_subscribe", new=AsyncMock(return_value=Mock())),
        patch.object(JackeryDataCoordinator, "_periodic_data_request", idle_poll),
    ):
        assert await hass.config_entries.async_setup(state.entry.entry_id)
        await hass.async_block_till_done()
        coordinator = coordinator_for(hass, state.entry)
        await discover(hass, coordinator, "PLUG0001", "plug", 6, 0, "plugs")
        if fixture_name == "community_2_5_0":
            await discover(hass, coordinator, "METER0001", "ct_3phase", 3, 5, "cts")
            await discover(hass, coordinator, "BATTERY0001", "expansion_battery", 1, 0, "expansion_batteries")
            await discover(hass, coordinator, "COLLECTOR0001", "collector", 4, 7, "collectors")
        else:
            assert not coordinator.child_identity_allowed("METER0001")
        await hass.async_block_till_done()
        registry = er.async_get(hass)
        for role, registry_id in original_ids.items():
            assert registry.async_get(state.entities[role].entity_id).id == registry_id
        _assert_no_duplicates(hass, state, runtime_entities=True)
        assert await hass.config_entries.async_unload(state.entry.entry_id)
        await hass.async_block_till_done()
