"""Compatibility tests for legacy and config-entry-scoped device registries."""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from importlib import import_module
from pkgutil import walk_packages
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.jackery as jackery_package
from custom_components.jackery import DOMAIN, _migrate_unique_ids
from custom_components.jackery.child_migration import migrate_child_identities
from custom_components.jackery.identity import (
    auto_standby_select_unique_id,
    child_device_identifier,
    child_unique_id,
)
from custom_components.jackery.registry_identity import (
    build_device_info,
    device_owned_by_entry,
    find_device_by_identifier,
    find_devices_by_identifier,
    get_device_by_id,
    iter_all_devices,
    iter_devices_for_entry,
    resolve_parent_device_id,
)


@pytest.fixture
def fail_on_device_registry_deprecation(hass):
    """Turn HA's registry deprecation hook into a failure during the test body."""
    def fail(*args: Any, **kwargs: Any) -> None:
        raise AssertionError(f"Deprecated Device Registry API used: {args!r} {kwargs!r}")

    with patch.object(dr, "report_usage", fail):
        yield


@dataclass
class LegacyDevice:
    """HA 2025.8 DeviceEntry ownership shape."""

    id: str
    identifiers: set[tuple[str, str]]
    config_entries: set[str]


@dataclass
class ModernDevice:
    """HA 2026.8+ DeviceEntry ownership shape."""

    id: str
    identifiers: set[tuple[str, str]]
    config_entry_id: str

    @property
    def config_entries(self) -> set[str]:
        raise AssertionError("modern code accessed deprecated DeviceEntry.config_entries")


class LegacyRegistry:
    """Old globally keyed DeviceRegistry shape."""

    def __init__(self, devices: list[LegacyDevice]) -> None:
        self.devices = {device.id: device for device in devices}
        self.lookup_calls: list[set[tuple[str, str]]] = []

    def async_get_device(self, *, identifiers: set[tuple[str, str]]) -> LegacyDevice | None:
        self.lookup_calls.append(identifiers)
        return next((device for device in self.devices.values() if device.identifiers & identifiers), None)

    def async_get(self, device_id: str) -> LegacyDevice | None:
        return self.devices.get(device_id)


class ModernRegistry:
    """Modern entry-scoped API shape with deprecated surfaces that fail loudly."""

    def __init__(self, devices: list[ModernDevice]) -> None:
        self._devices = tuple(devices)
        self.scoped_lookup_calls: list[tuple[tuple[str, str], str]] = []
        self.child_devices: tuple[ModernDevice, ...] = ()

    @property
    def devices(self) -> tuple[ModernDevice, ...]:
        """Model HA's public iterable collection, which is not a mapping."""
        return self._devices

    def async_get_device(self, **kwargs: Any) -> None:
        raise AssertionError("modern code called deprecated async_get_device")

    def async_get_devices(
        self,
        *,
        identifiers: set[tuple[str, str]] | None = None,
    ) -> tuple[ModernDevice, ...]:
        if identifiers is None:
            return ()
        return tuple(device for device in self._devices if device.identifiers & identifiers)

    def async_get_device_by_identifier(
        self,
        identifier: tuple[str, str],
        config_entry_id: str,
    ) -> ModernDevice | None:
        self.scoped_lookup_calls.append((identifier, config_entry_id))
        return next(
            (
                device
                for device in self._devices
                if identifier in device.identifiers and device.config_entry_id == config_entry_id
            ),
            None,
        )

    def async_get_device_by_id(self, device_id: str) -> ModernDevice | None:
        return next((device for device in self._devices if device.id == device_id), None)


def test_all_integration_modules_import() -> None:
    """The minimum HA install can import every production module."""
    for module in walk_packages(jackery_package.__path__, f"{jackery_package.__name__}."):
        import_module(module.name)


def test_legacy_registry_ownership_lookup_iteration_and_parent_link(monkeypatch: pytest.MonkeyPatch) -> None:
    """The 2025.8 path keeps exact exclusive ownership and identifier parent links."""
    identifier = (DOMAIN, "HOST-A")
    own = LegacyDevice("device-a", {identifier}, {"entry-a"})
    shared = LegacyDevice("device-shared", {(DOMAIN, "SHARED")}, {"entry-a", "entry-b"})
    foreign = LegacyDevice("device-b", {(DOMAIN, "HOST-B")}, {"entry-b"})
    registry = LegacyRegistry([own, shared, foreign])

    assert device_owned_by_entry(own, "entry-a")
    assert not device_owned_by_entry(shared, "entry-a")
    assert not device_owned_by_entry(foreign, "entry-a")
    assert find_device_by_identifier(registry, identifier, "entry-a") is own  # type: ignore[arg-type]
    assert find_device_by_identifier(registry, (DOMAIN, "HOST-B"), "entry-a") is None  # type: ignore[arg-type]
    assert iter_devices_for_entry(registry, "entry-a") == (own,)  # type: ignore[arg-type]
    assert iter_all_devices(registry) == (own, shared, foreign)  # type: ignore[arg-type]
    assert resolve_parent_device_id(registry, identifier, "entry-a") == "device-a"  # type: ignore[arg-type]
    monkeypatch.setattr("custom_components.jackery.registry_identity.dr.async_get", lambda _hass: registry)
    info = build_device_info(
        object(),  # Device registry access is patched above.
        "entry-a",
        identifiers={(DOMAIN, "sub_CHILD")},
        parent_identifier=identifier,
        name="Jackery Child",
        manufacturer="Jackery",
        model="Sub-device Type 2",
    )
    assert info["via_device"] == identifier
    assert "via_device_id" not in info


def test_modern_registry_uses_scoped_lookup_and_via_device_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """Modern lookups avoid all deprecated members and use HA's actual parent ID."""
    identifier = (DOMAIN, "HOST-A")
    own = ModernDevice("ha-device-17", {identifier}, "entry-a")
    foreign = ModernDevice("ha-device-23", {(DOMAIN, "HOST-B")}, "entry-b")
    registry = ModernRegistry([own, foreign])
    monkeypatch.setattr("custom_components.jackery.registry_identity.dr.async_get", lambda _hass: registry)

    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        assert find_device_by_identifier(registry, identifier, "entry-a") is own  # type: ignore[arg-type]
        assert find_device_by_identifier(registry, (DOMAIN, "HOST-B"), "entry-a") is None  # type: ignore[arg-type]
        assert iter_devices_for_entry(registry, "entry-a") == (own,)  # type: ignore[arg-type]
        assert find_devices_by_identifier(registry, identifier) == (own,)  # type: ignore[arg-type]
        assert resolve_parent_device_id(registry, identifier, "entry-a") == own.id  # type: ignore[arg-type]
        info = build_device_info(
            object(),  # Device registry access is patched above.
            "entry-a",
            identifiers={(DOMAIN, "child:HOST-A:CHILD-1")},
            parent_identifier=identifier,
            name="Jackery Child",
            manufacturer="Jackery",
            model="Sub-device Type 3",
        )

    assert registry.scoped_lookup_calls
    assert info["via_device_id"] == "ha-device-17"
    assert "via_device" not in info


def test_modern_cross_entry_identifier_collision_is_not_guessed() -> None:
    """A repeated identifier across entries is visible as a conflict, never first-match ownership."""
    identifier = (DOMAIN, "COLLIDING-HOST")
    entry_a = ModernDevice("device-a", {identifier}, "entry-a")
    entry_b = ModernDevice("device-b", {identifier}, "entry-b")
    registry = ModernRegistry([entry_a, entry_b])

    assert find_device_by_identifier(registry, identifier, "entry-a") is entry_a  # type: ignore[arg-type]
    assert find_device_by_identifier(registry, identifier, "entry-b") is entry_b  # type: ignore[arg-type]
    assert find_devices_by_identifier(registry, identifier) == (entry_a, entry_b)  # type: ignore[arg-type]
    assert resolve_parent_device_id(registry, identifier, "entry-a") == "device-a"  # type: ignore[arg-type]
    assert resolve_parent_device_id(registry, identifier, "entry-b") == "device-b"  # type: ignore[arg-type]


def test_modern_ownership_rejects_another_entry() -> None:
    device = ModernDevice("device-a", {(DOMAIN, "HOST-A")}, "entry-a")
    assert device_owned_by_entry(device, "entry-a")
    assert not device_owned_by_entry(device, "entry-b")


async def test_installed_home_assistant_device_info_contract(hass, fail_on_device_registry_deprecation) -> None:
    """Use the installed HA registry to verify the supported parent link contract."""

    entry_id = "registry-compat-entry"
    MockConfigEntry(domain=DOMAIN, entry_id=entry_id).add_to_hass(hass)
    parent_identifier = (DOMAIN, "REGISTRY-COMPAT-HOST")
    registry = dr.async_get(hass)
    parent = registry.async_get_or_create(
        config_entry_id=entry_id,
        identifiers={parent_identifier},
        name="Jackery",
        manufacturer="Jackery",
        model="Energy Monitor",
    )

    modern_registry = callable(getattr(registry, "async_get_device_by_identifier", None))
    if modern_registry:
        assert registry.async_get_device_by_identifier(parent_identifier, entry_id) == parent
        assert parent in iter_all_devices(registry)  # type: ignore[arg-type]
        assert find_devices_by_identifier(registry, parent_identifier) == (parent,)  # type: ignore[arg-type]
        assert device_owned_by_entry(parent, entry_id)
        assert find_device_by_identifier(registry, parent_identifier, entry_id) == parent  # type: ignore[arg-type]

        second_entry_id = "registry-compat-entry-b"
        MockConfigEntry(domain=DOMAIN, entry_id=second_entry_id).add_to_hass(hass)
        second_parent = registry.async_get_or_create(
            config_entry_id=second_entry_id,
            identifiers={parent_identifier},
            name="Other Jackery",
            manufacturer="Jackery",
            model="Energy Monitor",
        )
        assert second_parent.id != parent.id
        assert find_device_by_identifier(registry, parent_identifier, entry_id).id == parent.id  # type: ignore[union-attr,arg-type]
        assert find_device_by_identifier(registry, parent_identifier, second_entry_id).id == second_parent.id  # type: ignore[union-attr,arg-type]
        assert resolve_parent_device_id(registry, parent_identifier, entry_id) == parent.id  # type: ignore[arg-type]

    info = build_device_info(
        hass,
        entry_id,
        identifiers={(DOMAIN, "child:REGISTRY-COMPAT-HOST:CHILD-1")},
        parent_identifier=parent_identifier,
        name="Jackery child",
        manufacturer="Jackery",
        model="Sub-device Type 3",
    )
    child = registry.async_get_or_create(config_entry_id=entry_id, **info)

    if callable(getattr(registry, "async_get_device_by_identifier", None)):
        assert info["via_device_id"] == parent.id
        assert child.via_device_id == parent.id
    else:
        assert info["via_device"] == parent_identifier
        assert child.via_device_id == parent.id


async def test_installed_home_assistant_child_migration_contract(hass, fail_on_device_registry_deprecation) -> None:
    """Run the Official devType=3 identity plan on the installed registry model."""

    from homeassistant.helpers import entity_registry as er

    entry_id = "registry-migration-entry"
    host, serial = "SYNTHETIC-HOST-01", "SYNTHETIC-CT-01"
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id=entry_id,
        unique_id=host,
        data={"device_sn": host},
    )
    entry.add_to_hass(hass)
    devices = dr.async_get(hass)
    parent = devices.async_get_or_create(
        config_entry_id=entry_id,
        identifiers={(DOMAIN, host)},
        name="Jackery",
        manufacturer="Jackery",
        model="Energy Monitor",
    )
    source_device = devices.async_get_or_create(
        config_entry_id=entry_id,
        **build_device_info(
            hass,
            entry_id,
            identifiers={(DOMAIN, f"sub_{host}_{serial}")},
            parent_identifier=(DOMAIN, host),
            name=f"Jackery CT {serial}",
            manufacturer="Jackery",
            model="Sub-device Type 3",
        ),
    )

    suffixes = (
        "powertotalforward", "poweraforward", "powerbforward", "powercforward",
        "powertotalreverse", "powerareverse", "powerbreverse", "powercreverse",
        "energyforward", "energyreverse",
    )
    old_entities = [
        er.async_get(hass).async_get_or_create(
            "sensor",
            DOMAIN,
            f"jackery_{host}_ct_{serial}_{suffix}",
            config_entry=entry,
            device_id=source_device.id,
            suggested_object_id=f"synthetic_ct_{index}",
        )
        for index, suffix in enumerate(suffixes)
    ]

    result = migrate_child_identities(hass, entry)

    assert result.blocked_children == set()
    migrated_device = get_device_by_id(devices, source_device.id)
    assert migrated_device is not None
    assert migrated_device.id == source_device.id
    assert migrated_device.identifiers == {(DOMAIN, child_device_identifier(host, serial))}
    assert migrated_device.via_device_id == parent.id
    expected_keys = (
        "importtotal", "importl1", "importl2", "importl3",
        "exporttotal", "exportl1", "exportl2", "exportl3",
        "importenergytotal", "exportenergytotal",
    )
    for source, key in zip(old_entities, expected_keys, strict=True):
        current = er.async_get(hass).async_get(source.entity_id)
        assert current is not None
        assert current.entity_id == source.entity_id
        assert current.unique_id == child_unique_id(host, serial, "smartmeter", key)
    second = migrate_child_identities(hass, entry)
    assert second.blocked_children == set()
    assert len(er.async_entries_for_config_entry(er.async_get(hass), entry_id)) == len(old_entities)


async def test_installed_home_assistant_main_identity_migrations(hass, fail_on_device_registry_deprecation) -> None:
    """Main Reboot, SOC and Auto Standby migrations use modern ownership APIs."""

    from homeassistant.helpers import entity_registry as er

    host = "SYNTHETIC-MAIN-HOST"
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="registry-main-migration-entry",
        unique_id=host,
        data={"device_sn": host},
    )
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, host)},
        name="Jackery",
        manufacturer="Jackery",
        model="Energy Monitor",
    )
    registry = er.async_get(hass)
    sources = (
        ("button", f"jackery_{host}_main_reboot", "synthetic_reboot"),
        ("sensor", f"jackery_{host}_average_soc", "synthetic_average_soc"),
        ("select", f"jackery_{host}_main_autoStandby", "synthetic_auto_standby"),
    )
    records = [
        registry.async_get_or_create(
            domain,
            DOMAIN,
            unique_id,
            config_entry=entry,
            device_id=device.id,
            suggested_object_id=entity_id,
        )
        for domain, unique_id, entity_id in sources
    ]

    await _migrate_unique_ids(hass, entry)

    targets = (
        f"jackery_{host}_reboot",
        f"jackery_{host}_bms_soc",
        auto_standby_select_unique_id(host),
    )
    for record, target in zip(records, targets, strict=True):
        current = registry.async_get(record.entity_id)
        assert current is not None
        assert current.entity_id == record.entity_id
        assert current.unique_id == target
        assert current.device_id == device.id
    await _migrate_unique_ids(hass, entry)
