"""Pinned upstream golden-state upgrade and rollback evidence."""

from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import timedelta
from functools import partial
from pathlib import Path
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
from custom_components.jackery.child_migration import ChildMigrationResult, migrate_child_identities
from custom_components.jackery.identity import child_device_identifier, child_unique_id
from custom_components.jackery.sensor import JackeryDataCoordinator

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
                "icon": entity.icon,
                "disabled_by": entity.disabled_by,
                "area_id": entity.area_id,
                "device_id": entity.device_id,
            }
            for role, entity in state.entities.items()
        },
    }


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
        return state.entities[role].unique_id
    if role == "main_eps_switch":
        return "jackery_SVHOST0001_switch_swEps"
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
    community_plug = next(item for item in community["entities"] if item["role"] == "plug_power")
    assert official_plug["unique_id"] == "jackery_SVHOST0001_plug_PLUG0001_power"
    assert community_plug["unique_id"] == "jackery_plug_PLUG0001_power"


async def test_official_upgrade_migrates_supported_children_in_place(hass):
    """Red before Official host-prefixed legacy identities are recognized."""
    state = seed_fixture(hass, "official_2_0_0")
    registry = er.async_get(hass)
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
    # Official's richer generic-CT entity has no proven one-to-one NG target.
    assert not result.allows("METER0001")
    assert devices["meter"].identifiers == {(DOMAIN, "sub_SVHOST0001_METER0001")}
    assert entities["meter_power"].unique_id == "jackery_SVHOST0001_ct_METER0001_powertotalforward"
    assert devices["main"].identifiers == {(DOMAIN, "SVHOST0001")}
    _assert_customizations_preserved(hass, state, before)
    _assert_no_duplicates(hass, state)


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
