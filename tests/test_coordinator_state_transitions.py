"""Characterize coordinator-owned runtime state before its extraction."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from custom_components.jackery import sensor as sensor_module
from custom_components.jackery.sensor import OFFLINE_TIMEOUT, JackeryDataCoordinator

from .conftest import FakeMqttMsg


class RecordingEntity:
    """Minimal MQTT entity exposing observable availability and fan-out."""

    def __init__(self, child_sn: str | None = None) -> None:
        self._plug_sn = child_sn
        self._attr_available = False
        self.updates: list[dict] = []
        self.async_write_ha_state = Mock()

    @property
    def available(self) -> bool:
        return self._attr_available

    def _update_from_coordinator(self, data: dict) -> None:
        self.updates.append(dict(data))
        self._attr_available = True
        self.async_write_ha_state()


@pytest.fixture
def state_runtime(monkeypatch):
    clock = SimpleNamespace(now=1000.0)
    monkeypatch.setattr(sensor_module.time, "time", lambda: clock.now)
    coordinator = JackeryDataCoordinator(
        None,
        "hb",
        "synthetic-token",
        "localhost",
        "HOST",
    )
    coordinator.config_entry_id = "ENTRY"
    return SimpleNamespace(coordinator=coordinator, clock=clock)


def receive(state_runtime, message_type, body, *, advance=1.0):
    state_runtime.clock.now += advance
    state_runtime.coordinator._handle_message(
        FakeMqttMsg(
            "hb/device/HOST/status",
            json.dumps({"type": message_type, "body": body}),
        )
    )


def test_host_message_records_activity_and_cache(state_runtime):
    receive(state_runtime, 2, {"batSoc": 42}, advance=20)

    coordinator = state_runtime.coordinator
    assert coordinator._last_update_time == 1020.0
    assert coordinator._ever_received
    assert coordinator._data_cache["batSoc"] == 42


def test_child_message_records_independent_activity(state_runtime):
    receive(
        state_runtime,
        101,
        {"plugs": [{"deviceSn": "CHILD", "devType": 6, "outPw": 10}]},
        advance=10,
    )

    coordinator = state_runtime.coordinator
    assert coordinator._subdevice_last_seen == {"CHILD": 1010.0}
    assert coordinator._last_update_time == 1010.0
    assert coordinator._subdevice_is_available("CHILD", 1010.0)


def test_child_stale_transition_and_recovery(state_runtime):
    coordinator = state_runtime.coordinator
    entity = RecordingEntity("CHILD")
    coordinator.register_sensor("child", entity)
    receive(
        state_runtime,
        101,
        {"plugs": [{"deviceSn": "CHILD", "devType": 6, "outPw": 10}]},
    )
    assert entity.available

    state_runtime.clock.now += OFFLINE_TIMEOUT + 1
    coordinator._update_subdevice_availability()
    assert not entity.available
    stale_writes = entity.async_write_ha_state.call_count

    receive(
        state_runtime,
        102,
        {"deviceSn": "CHILD", "devType": 6, "outPw": 0},
    )
    assert entity.available
    assert coordinator._subdevice_last_seen["CHILD"] == state_runtime.clock.now
    # Recovery writes once for the availability edge, then once for data fan-out.
    assert entity.async_write_ha_state.call_count == stale_writes + 2


def test_missing_child_deletion_timer_state(state_runtime):
    coordinator = state_runtime.coordinator
    coordinator._known_plugs.add("MISSING")
    coordinator._subdevice_last_seen["MISSING"] = state_runtime.clock.now
    present = {"deviceSn": "PRESENT", "devType": 6}

    coordinator._check_for_new_plugs({"plugs": [present]})
    assert coordinator._subdevice_missing_since == {"MISSING": 1000.0}

    state_runtime.clock.now += OFFLINE_TIMEOUT + 1
    coordinator._check_for_new_plugs({"plugs": [present]})
    assert "MISSING" not in coordinator._known_plugs
    assert "MISSING" not in coordinator._subdevice_last_seen
    assert coordinator._subdevice_missing_since == {}


def test_expansion_battery_retains_availability_and_skips_deletion(state_runtime):
    coordinator = state_runtime.coordinator
    battery = RecordingEntity("BATTERY")
    coordinator.register_sensor("battery", battery)
    receive(
        state_runtime,
        23,
        {"deviceSn": "BATTERY", "devType": 1, "inEgy": 1234},
    )

    state_runtime.clock.now += 600
    coordinator._update_subdevice_availability()
    coordinator._check_for_new_plugs(
        {"plugs": [{"deviceSn": "PRESENT", "devType": 6}]}
    )
    coordinator._mark_all_offline()

    assert battery.available
    assert coordinator._subdevice_is_available("BATTERY", state_runtime.clock.now)
    assert "BATTERY" not in coordinator._subdevice_missing_since


def test_repeated_type106_updates_snapshot_state(state_runtime):
    receive(state_runtime, 106, {"pvPw": 10})
    receive(state_runtime, 106, {"pvPw": 20})

    coordinator = state_runtime.coordinator
    assert coordinator._data_cache["pvPw"] == 20
    assert coordinator._power_live_seen == {}
    assert coordinator._power_106_samples == {"pvPw": (20, 1002.0)}


@pytest.mark.parametrize("message_type", [2, 107])
def test_live_message_overrides_snapshot_and_retains_bounded_priority(
    state_runtime,
    message_type,
):
    receive(state_runtime, 106, {"pvPw": 10})
    receive(state_runtime, message_type, {"pvPw": 20})
    receive(state_runtime, 106, {"pvPw": 30})

    coordinator = state_runtime.coordinator
    assert coordinator._data_cache["pvPw"] == 20
    assert coordinator._power_live_seen == {"pvPw": (message_type, 1002.0)}
    assert coordinator._power_106_samples == {"pvPw": (30, 1003.0)}


def test_live_preference_expires_by_receipt_time(state_runtime):
    receive(state_runtime, 2, {"pvPw": 20})
    receive(state_runtime, 106, {"pvPw": 30})
    assert state_runtime.coordinator._data_cache["pvPw"] == 20

    state_runtime.clock.now += OFFLINE_TIMEOUT
    receive(state_runtime, 106, {"pvPw": 40})

    coordinator = state_runtime.coordinator
    assert coordinator._data_cache["pvPw"] == 40
    assert coordinator._power_live_seen == {}
    assert coordinator._power_106_samples == {"pvPw": (40, 1063.0)}


def test_source_metadata_tracks_child_freshness(state_runtime):
    receive(
        state_runtime,
        101,
        {"cts": [{"deviceSn": "METER", "devType": 3, "tPhasePw": 800}]},
    )
    coordinator = state_runtime.coordinator
    assert coordinator._energy_sources["grid"] == {
        "source": "cts",
        "activity_age": 0.0,
        "skipped_stale": 0,
        "skipped_missing": 0,
        "reason": "first usable meter",
    }

    state_runtime.clock.now += OFFLINE_TIMEOUT + 1
    coordinator._calculate_energy_flow(coordinator._data_cache)
    assert coordinator._energy_sources["grid"]["source"] == "unavailable"
    assert coordinator._energy_sources["grid"]["skipped_stale"] == 1


def test_host_offline_transition_and_message_recovery(state_runtime):
    coordinator = state_runtime.coordinator
    entity = RecordingEntity()
    coordinator.register_sensor("main", entity)
    receive(state_runtime, 2, {"batSoc": 42})
    assert entity.available

    state_runtime.clock.now += OFFLINE_TIMEOUT + 1
    assert state_runtime.clock.now - coordinator._last_update_time > OFFLINE_TIMEOUT
    coordinator._mark_all_offline()
    assert not entity.available

    receive(state_runtime, 2, {"batSoc": 43})
    assert entity.available
    assert coordinator._data_cache["batSoc"] == 43


def test_new_coordinator_resets_ephemeral_runtime_state(state_runtime):
    original = state_runtime.coordinator
    receive(
        state_runtime,
        101,
        {"cts": [{"deviceSn": "METER", "devType": 3, "tPhasePw": 10}]},
    )
    receive(state_runtime, 106, {"pvPw": 20})
    original._reauth_started = True
    original._http_sm_sensors_created = True

    state_runtime.clock.now = 2000.0
    replacement = JackeryDataCoordinator(
        None,
        "hb",
        "synthetic-token",
        "localhost",
        "HOST",
    )

    assert replacement._data_cache == {}
    assert replacement._power_live_seen == {}
    assert replacement._power_106_samples == {}
    assert replacement._energy_sources == {}
    assert replacement._subdevice_last_seen == {}
    assert replacement._last_update_time == replacement._start_time == 2000.0
    assert not replacement._ever_received
    assert not replacement._reauth_started
    assert not replacement._http_sm_sensors_created
    assert replacement._data_cache is not original._data_cache
    assert replacement._data_cache is replacement._runtime_state.data_cache
    assert (
        replacement._subdevice_last_seen
        is replacement._runtime_state.subdevice_last_seen
    )
    assert replacement._power_live_seen is replacement._runtime_state.power_live_seen
    assert (
        replacement._power_106_samples
        is replacement._runtime_state.power_106_samples
    )
    assert replacement._energy_sources is replacement._runtime_state.energy_sources
