"""Cause classification and entry-scoped registry/runtime consistency tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import DATA_ENTITY_PLATFORM
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.jackery import DOMAIN
from custom_components.jackery.diagnostics_adapter import _registry_inputs


def _entry(hass, entry_id: str = "diagnostic-entry") -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id=entry_id,
        unique_id=f"HOST-{entry_id}",
        data={"device_sn": f"HOST-{entry_id}"},
    )
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.LOADED)
    return entry


def _registry_entity(hass, entry, domain: str, unique_id: str, *, disabled_by=None):
    return er.async_get(hass).async_get_or_create(
        domain,
        DOMAIN,
        unique_id,
        config_entry=entry,
        disabled_by=disabled_by,
    )


def _entity(entity_id: str | None, *, key: str | None = None, callback: str | None = None):
    entity = SimpleNamespace(entity_id=entity_id)
    if key is not None:
        entity._sensor_id = key
    if callback == "mqtt":
        entity._update_from_coordinator = lambda _data: None
    elif callback == "http":
        entity._update_from_http = lambda _data: None
    return entity


def _platform(entry, domain: str, entities: list[object], *, setup_complete=True):
    return SimpleNamespace(
        config_entry=entry,
        domain=domain,
        entities={entity.entity_id: entity for entity in entities if entity.entity_id},
        _setup_complete=setup_complete,
    )


def _set_platforms(hass, entry, platforms) -> None:
    hass.data.setdefault(DATA_ENTITY_PLATFORM, {}).setdefault(DOMAIN, [])
    hass.data[DATA_ENTITY_PLATFORM][DOMAIN].extend(
        platform for platform in platforms if platform.config_entry is entry
    )


def test_primary_classifications_and_registry_runtime_inventory_are_disjoint(
    hass, coordinator
) -> None:
    entry = _entry(hass)
    coordinator._runtime_state.data_cache.update(
        {"ethPort": 1, "wname": "   ", "wsig": 0, "workMode": 2}
    )

    records = {
        "wifi": _registry_entity(hass, entry, "sensor", "jackery_HOST_wifi_signal"),
        "follow": _registry_entity(hass, entry, "switch", "jackery_HOST_isFollowMeterPw"),
        "capability": _registry_entity(
            hass,
            entry,
            "sensor",
            "jackery_HOST_device_capability",
            disabled_by=er.RegistryEntryDisabler.INTEGRATION,
        ),
        "func_enable": _registry_entity(
            hass,
            entry,
            "sensor",
            "jackery_HOST_func_enable",
            disabled_by=er.RegistryEntryDisabler.USER,
        ),
        "unknown": _registry_entity(hass, entry, "sensor", "mystery-unknown"),
        "unavailable": _registry_entity(
            hass, entry, "sensor", "jackery_HOST_unknown_unavailable"
        ),
        "battery": _registry_entity(hass, entry, "sensor", "jackery_HOST_battery_soc"),
        "button": _registry_entity(hass, entry, "button", "jackery_HOST_button"),
        "missing_listener": _registry_entity(
            hass, entry, "sensor", "jackery_HOST_ct_import_energy"
        ),
        "http": _registry_entity(hass, entry, "sensor", "jackery_HOST_http_energy"),
    }
    hass.states.async_set(records["wifi"].entity_id, "unknown")
    hass.states.async_set(records["follow"].entity_id, "unavailable")
    hass.states.async_set(records["unavailable"].entity_id, "unavailable")
    hass.states.async_set(records["battery"].entity_id, "45")
    hass.states.async_set(records["button"].entity_id, "pressed")
    hass.states.async_set(records["missing_listener"].entity_id, "17")
    hass.states.async_set(records["http"].entity_id, "20")

    wifi = _entity(records["wifi"].entity_id, key="wifi_signal", callback="mqtt")
    follow = _entity(records["follow"].entity_id, key="isFollowMeterPw", callback="mqtt")
    battery = _entity(records["battery"].entity_id, key="battery_soc", callback="mqtt")
    button = _entity(records["button"].entity_id)
    missing_listener = _entity(records["missing_listener"].entity_id, key="ct_import_energy")
    http = _entity(records["http"].entity_id, callback="http")
    extra = _entity("sensor.unregistered_runtime", key="wifi_signal")
    unresolved = _entity(None, key="wifi_signal")
    _set_platforms(
        hass,
        entry,
        [
            _platform(entry, "sensor", [wifi, battery, button, missing_listener, http, extra]),
            _platform(entry, "switch", [follow]),
        ],
    )
    coordinator._sensors = {
        "wifi": wifi,
        "follow": follow,
        "battery": battery,
        "http": http,
        "unresolved": unresolved,
    }

    diagnostics = _registry_inputs(hass, entry, coordinator)

    assert diagnostics.registry_total == len(records)
    assert sum(diagnostics.classification_counts.values()) == len(records)
    assert diagnostics.classification_counts == {
        "available": 4,
        "disabled": 2,
        "expected_no_data": 1,
        "expected_inactive": 1,
        "integration_inactive": 0,
        "pending_initialization": 0,
        "unexpected_unknown": 1,
        "unexpected_unavailable": 1,
    }
    assert diagnostics.state_counts == {
        "available": 4,
        "unavailable": 2,
        "unknown": 4,
    }
    assert diagnostics.enabled_registry_entities == 8
    assert diagnostics.runtime_entity_count == 8
    assert diagnostics.runtime_listener_counts == {"mqtt": 3, "http": 1}
    assert diagnostics.expected_non_listener_count == 1
    assert diagnostics.missing_runtime_count == 2
    assert diagnostics.unregistered_runtime_count == 1
    assert diagnostics.unresolved_identity_count == 1
    assert diagnostics.missing_coordinator_listener_count == 1
    assert diagnostics.mismatch_count == 5
    serialized_details = repr(
        (diagnostics.classification_details, diagnostics.consistency_details)
    )
    assert "jackery_HOST" not in serialized_details
    assert "mystery-unknown" not in serialized_details
    assert {row["classification"] for row in diagnostics.classification_details} == {
        "expected_no_data",
        "expected_inactive",
        "unexpected_unknown",
        "unexpected_unavailable",
    }


@pytest.mark.parametrize("mode", [2, 7, 8])
def test_follow_meter_unavailable_is_expected_only_for_known_non_custom_modes(
    hass, coordinator, mode
) -> None:
    entry = _entry(hass, f"mode-{mode}")
    registry = _registry_entity(hass, entry, "switch", "jackery_HOST_isFollowMeterPw")
    hass.states.async_set(registry.entity_id, "unavailable")
    coordinator._runtime_state.data_cache["workMode"] = mode

    result = _registry_inputs(hass, entry, coordinator)

    assert result.classification_counts["expected_inactive"] == 1
    assert result.classification_counts["unexpected_unavailable"] == 0


def test_follow_meter_mode_four_is_available_and_unexplained_failure_stays_visible(
    hass, coordinator
) -> None:
    entry = _entry(hass, "mode-four")
    registry = _registry_entity(hass, entry, "switch", "jackery_HOST_isFollowMeterPw")
    hass.states.async_set(registry.entity_id, "off")
    coordinator._runtime_state.data_cache["workMode"] = 4

    available = _registry_inputs(hass, entry, coordinator)
    assert available.classification_counts["available"] == 1

    hass.states.async_set(registry.entity_id, "unavailable")
    unavailable = _registry_inputs(hass, entry, coordinator)
    assert unavailable.classification_counts["unexpected_unavailable"] == 1

    coordinator._runtime_state.data_cache.pop("workMode")
    coordinator._runtime_state.data_cache["workModel"] = 2
    missing_mode = _registry_inputs(hass, entry, coordinator)
    assert missing_mode.classification_counts["unexpected_unavailable"] == 1
    assert missing_mode.classification_counts["expected_inactive"] == 0

    coordinator._runtime_state.data_cache["workMode"] = "invalid"
    invalid_mode = _registry_inputs(hass, entry, coordinator)
    assert invalid_mode.classification_counts["unexpected_unavailable"] == 1


def test_platform_setup_in_progress_is_pending_and_not_a_registry_mismatch(
    hass, coordinator
) -> None:
    entry = _entry(hass, "pending")
    _registry_entity(hass, entry, "sensor", "jackery_HOST_battery_soc")
    _set_platforms(
        hass,
        entry,
        [_platform(entry, "sensor", [], setup_complete=False)],
    )
    coordinator._sensors = {}
    entry.mock_state(hass, ConfigEntryState.SETUP_IN_PROGRESS)

    result = _registry_inputs(hass, entry, coordinator)

    assert result.classification_counts["pending_initialization"] == 1
    assert result.classification_counts["unexpected_unknown"] == 0
    assert result.missing_runtime_count == 0
    assert result.mismatch_count == 0


def test_unloaded_entry_entities_are_inactive_not_faults(hass) -> None:
    entry = _entry(hass, "unloaded")
    _registry_entity(hass, entry, "sensor", "jackery_HOST_battery_soc")
    entry.mock_state(hass, ConfigEntryState.NOT_LOADED)

    result = _registry_inputs(hass, entry, None)

    assert result.classification_counts["integration_inactive"] == 1
    assert result.classification_counts["unexpected_unknown"] == 0
    assert result.missing_runtime_count == 0
    assert result.mismatch_count == 0
