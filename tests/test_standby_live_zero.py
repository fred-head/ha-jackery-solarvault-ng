"""Regression coverage for bounded standby/live-zero arbitration."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from custom_components.jackery import sensor as sensor_module
from custom_components.jackery.calculations.energy_flow import (
    OnGridSourceEvidence,
    _effective_ongrid_net,
    _power_sample,
)
from custom_components.jackery.sensor import JackeryDataCoordinator, JackerySensor

from .conftest import FakeMqttMsg


def _receive(coordinator: JackeryDataCoordinator, message_type: int, body: dict) -> None:
    """Route one synthetic host message through the production entry point."""
    coordinator._handle_message(
        FakeMqttMsg(
            f"{coordinator._topic_root}/device/{coordinator._device_sn}/status",
            json.dumps({"type": message_type, "body": body}),
        )
    )


def _effective(
    data: dict,
    *,
    live_seen_at: float | None,
    type106_seen_at: float | None,
    live_observed: bool = True,
    type106_observed: bool = True,
) -> float:
    """Resolve the on-grid semantic value with fixed receipt evidence."""
    def sample(key: str) -> float:
        value = _power_sample(data.get(key))
        return value if value is not None else 0.0

    return _effective_ongrid_net(
        data,
        sample("gridInPw"),
        sample("gridOutPw"),
        sample("inOngridPw"),
        sample("outOngridPw"),
        sample("inGridSidePw"),
        sample("outGridSidePw"),
        OnGridSourceEvidence(
            live_observed=live_observed,
            live_seen_at=live_seen_at,
            type106_observed=type106_observed,
            type106_seen_at=type106_seen_at,
            live_preference_seconds=60,
        ),
    )


def test_newer_live_zero_overrides_older_type106_through_entity_fanout(
    monkeypatch,
) -> None:
    """A current live zero must not lose to an older non-zero snapshot alias."""
    clock = SimpleNamespace(now=1000.0)
    monkeypatch.setattr(
        sensor_module,
        "time",
        SimpleNamespace(time=lambda: clock.now),
    )
    coordinator = JackeryDataCoordinator(
        None,
        "hb",
        "synthetic",
        "localhost",
        "HOST",
    )
    coordinator.add_entities_callback = Mock()

    entities: dict[str, JackerySensor] = {}
    for sensor_id in ("grid_net_power", "home_power", "battery_net_power"):
        entity = JackerySensor(sensor_id, coordinator, "ENTRY")
        entity.async_write_ha_state = Mock()
        coordinator.register_sensor(sensor_id, entity)
        entities[sensor_id] = entity

    _receive(
        coordinator,
        106,
        {"gridInPw": 300, "gridOutPw": 0, "pvPw": 0},
    )
    clock.now = 1011.0
    _receive(
        coordinator,
        2,
        {
            "inOngridPw": 0,
            "outOngridPw": 0,
            "pvPw": 0,
            "cts": [
                {
                    "deviceSn": "METER",
                    "devType": 3,
                    "tPhasePw": 300,
                    "tnPhasePw": 0,
                }
            ],
        },
    )

    assert coordinator._energy_sources["grid"]["source"] == "cts"
    assert coordinator._data_cache["calc_grid_net_power"] == 300
    assert coordinator._data_cache["calc_home_power"] == 300
    assert coordinator._data_cache["calc_batt_net_power"] == 0
    assert entities["grid_net_power"].native_value == 300
    assert entities["home_power"].native_value == 300
    assert entities["battery_net_power"].native_value == 0


@pytest.mark.parametrize(
    ("snapshot_delay", "expected_home"),
    [(59.999, 300), (60.0, 300), (60.001, 0)],
)
def test_routed_snapshot_receipt_uses_inclusive_live_window(
    monkeypatch,
    snapshot_delay,
    expected_home,
) -> None:
    """Real routing feeds the same inclusive receipt-time decision."""
    clock = SimpleNamespace(now=1000.0)
    monkeypatch.setattr(sensor_module, "time", SimpleNamespace(time=lambda: clock.now))
    coordinator = JackeryDataCoordinator(None, "hb", "synthetic", "localhost", "HOST")
    _receive(
        coordinator,
        2,
        {
            "inOngridPw": 0,
            "outOngridPw": 0,
            "cts": [{"deviceSn": "METER", "devType": 3, "tPhasePw": 300}],
        },
    )

    clock.now = 1000 + snapshot_delay
    _receive(coordinator, 106, {"gridInPw": 300, "gridOutPw": 0})

    assert coordinator._data_cache["calc_home_power"] == pytest.approx(
        expected_home
    )


@pytest.mark.parametrize(
    ("snapshot_delay", "expected"),
    [(59.999, 0), (60.0, 0), (60.001, 300)],
)
def test_live_preference_has_an_inclusive_sixty_second_boundary(
    snapshot_delay,
    expected,
) -> None:
    """Only a newly received snapshot after the bounded window may replace live."""
    data = {
        "gridInPw": 300,
        "gridOutPw": 0,
        "inOngridPw": 0,
        "outOngridPw": 0,
    }

    assert _effective(
        data,
        live_seen_at=1000,
        type106_seen_at=1000 + snapshot_delay,
    ) == pytest.approx(expected)


def test_missing_live_and_explicit_live_zero_are_distinct() -> None:
    """Missing live evidence falls back while a valid live zero wins."""
    snapshot_only = {"gridInPw": 300, "gridOutPw": 0}
    with_live_zero = {
        **snapshot_only,
        "inOngridPw": 0,
        "outOngridPw": 0,
    }

    assert _effective(
        snapshot_only,
        live_observed=False,
        live_seen_at=None,
        type106_seen_at=1000,
    ) == 300
    assert _effective(
        with_live_zero,
        live_seen_at=1010,
        type106_seen_at=1000,
    ) == 0


@pytest.mark.parametrize("invalid", [True, "bad", float("nan"), float("inf"), []])
def test_invalid_live_input_does_not_become_zero_or_replace_snapshot(invalid) -> None:
    """Malformed live values are neither samples nor priority evidence."""
    data = {
        "gridInPw": 300,
        "gridOutPw": 0,
        "inOngridPw": invalid,
        "outOngridPw": 0,
    }

    assert _effective(
        data,
        live_seen_at=None,
        type106_seen_at=1000,
    ) == 300


def test_suppressed_snapshot_never_reactivates_without_new_receipt() -> None:
    """Wall-clock passage cannot change a receipt-order decision."""
    data = {
        "gridInPw": 300,
        "gridOutPw": 0,
        "inOngridPw": 0,
        "outOngridPw": 0,
    }
    evidence = {
        "live_seen_at": 1011,
        "type106_seen_at": 1020,
    }

    assert _effective(data, **evidence) == 0
    assert _effective(data, **evidence) == 0


def test_suppressed_routed_snapshot_does_not_reactivate_as_clock_advances(
    monkeypatch,
) -> None:
    """Recalculation alone cannot promote a snapshot suppressed at receipt."""
    clock = SimpleNamespace(now=1000.0)
    monkeypatch.setattr(sensor_module, "time", SimpleNamespace(time=lambda: clock.now))
    coordinator = JackeryDataCoordinator(None, "hb", "synthetic", "localhost", "HOST")
    _receive(coordinator, 106, {"gridInPw": 300, "gridOutPw": 0})
    clock.now = 1011
    _receive(
        coordinator,
        2,
        {
            "inOngridPw": 0,
            "outOngridPw": 0,
            "cts": [{"deviceSn": "METER", "devType": 3, "tPhasePw": 300}],
        },
    )
    clock.now = 1020
    _receive(coordinator, 106, {"gridInPw": 400, "gridOutPw": 0})
    assert coordinator._data_cache["calc_home_power"] == 300

    clock.now = 1120
    coordinator._calculate_energy_flow(coordinator._data_cache)

    assert coordinator._energy_sources["grid"]["source"] == "system"
    assert coordinator._data_cache["calc_home_power"] == 400


@pytest.mark.parametrize(("live_value", "expected_home"), [(None, 0), (0, 300)])
def test_routed_missing_live_and_explicit_zero_diverge(
    monkeypatch,
    live_value,
    expected_home,
) -> None:
    """A null releases live preference while an explicit zero establishes it."""
    clock = SimpleNamespace(now=1000.0)
    monkeypatch.setattr(sensor_module, "time", SimpleNamespace(time=lambda: clock.now))
    coordinator = JackeryDataCoordinator(None, "hb", "synthetic", "localhost", "HOST")
    _receive(coordinator, 106, {"gridInPw": 300, "gridOutPw": 0})
    clock.now = 1011
    _receive(
        coordinator,
        2,
        {
            "inOngridPw": live_value,
            "outOngridPw": live_value,
            "cts": [{"deviceSn": "METER", "devType": 3, "tPhasePw": 300}],
        },
    )

    assert coordinator._data_cache["calc_home_power"] == expected_home


def test_new_snapshot_after_window_and_later_live_update_recover() -> None:
    """A fresh snapshot may replace stale live, and newer live wins immediately."""
    data = {
        "gridInPw": 300,
        "gridOutPw": 0,
        "inOngridPw": 0,
        "outOngridPw": 0,
    }
    assert _effective(
        data,
        live_seen_at=1000,
        type106_seen_at=1061,
    ) == 300

    data["inOngridPw"] = 125
    assert _effective(
        data,
        live_seen_at=1062,
        type106_seen_at=1061,
    ) == 125


def test_receipt_metadata_changes_only_for_valid_or_explicitly_missing_pairs(
    monkeypatch,
) -> None:
    """Invalid input cannot move receipt priority; null releases live evidence."""
    clock = SimpleNamespace(now=1000.0)
    monkeypatch.setattr(sensor_module, "time", SimpleNamespace(time=lambda: clock.now))
    coordinator = JackeryDataCoordinator(None, "hb", "synthetic", "localhost", "HOST")

    _receive(coordinator, 2, {"inOngridPw": 20, "outOngridPw": 0})
    assert coordinator._runtime_state.ongrid_live_seen_at == 1000

    clock.now = 1010
    _receive(coordinator, 2, {"inOngridPw": "bad"})
    assert coordinator._runtime_state.ongrid_live_seen_at == 1000

    clock.now = 1020
    _receive(coordinator, 2, {"inOngridPw": None, "outOngridPw": None})
    assert coordinator._runtime_state.ongrid_live_observed
    assert coordinator._runtime_state.ongrid_live_seen_at is None


def test_type106_startup_and_existing_same_key_priority_remain_unchanged(
    monkeypatch,
) -> None:
    """On-grid evidence does not alter the established same-key PV policy."""
    clock = SimpleNamespace(now=1000.0)
    monkeypatch.setattr(sensor_module, "time", SimpleNamespace(time=lambda: clock.now))
    coordinator = JackeryDataCoordinator(None, "hb", "synthetic", "localhost", "HOST")

    _receive(coordinator, 106, {"gridInPw": 300, "gridOutPw": 0, "pvPw": 90})
    assert coordinator._runtime_state.ongrid_type106_seen_at == 1000
    assert coordinator._data_cache["calc_home_power"] == 0

    clock.now = 1001
    _receive(coordinator, 2, {"pvPw": 0})
    clock.now = 1002
    _receive(coordinator, 106, {"pvPw": 40})
    assert coordinator._data_cache["pvPw"] == 0
    assert coordinator._power_live_seen["pvPw"] == (2, 1001)
