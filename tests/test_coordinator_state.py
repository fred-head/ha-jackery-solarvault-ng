"""Direct tests for the Home Assistant independent coordinator runtime state."""

from __future__ import annotations

import pytest

from custom_components.jackery.coordinator_state import CoordinatorRuntimeState

LIVE_FIELDS = frozenset({"pvPw", "batInPw"})


@pytest.fixture
def state() -> CoordinatorRuntimeState:
    return CoordinatorRuntimeState(last_update_time=100.0, start_time=90.0)


def test_runtime_state_defaults_are_independent():
    first = CoordinatorRuntimeState(last_update_time=1.0, start_time=1.0)
    second = CoordinatorRuntimeState(last_update_time=2.0, start_time=2.0)

    first.data_cache["value"] = 1
    first.subdevice_last_seen["CHILD"] = 1.0

    assert second.data_cache == {}
    assert second.subdevice_last_seen == {}
    assert not first.ever_received and not second.ever_received


def test_record_host_and_child_activity(state):
    state.record_host_activity(120.0)
    state.record_child_activity("CHILD", 121.0)

    assert state.last_update_time == 120.0
    assert state.ever_received
    assert state.subdevice_last_seen == {"CHILD": 121.0}


def test_main_merge_records_only_valid_live_fields(state):
    state.record_host_activity(120.0)
    state.power_live_seen["batInPw"] = (2, 110.0)
    state.merge_main_payload(
        {"pvPw": 0, "batInPw": None, "other": 1},
        observed_keys=("pvPw", "batInPw", "other"),
        message_type=107,
        live_preferred=LIVE_FIELDS,
        valid_live_fields=frozenset({"pvPw"}),
    )

    assert state.data_cache == {"pvPw": 0, "batInPw": None, "other": 1}
    assert state.power_live_seen == {"pvPw": (107, 120.0)}


def test_generic_main_merge_clears_observed_live_evidence(state):
    state.power_live_seen["pvPw"] = (2, 99.0)
    state.merge_main_payload(
        {"pvPw": 8},
        observed_keys=("pvPw",),
        message_type=None,
        live_preferred=LIVE_FIELDS,
        valid_live_fields=frozenset(),
    )

    assert state.data_cache["pvPw"] == 8
    assert state.power_live_seen == {}


def test_type106_records_suppressed_snapshot_at_live_timeout_boundary(state):
    state.data_cache["pvPw"] = 20
    state.power_live_seen["pvPw"] = (2, 100.0)
    state.last_update_time = 160.0

    state.merge_type106_snapshot(
        {"pvPw": 30, "other": 1},
        live_preferred=LIVE_FIELDS,
        live_timeout=60.0,
    )

    assert state.data_cache == {"pvPw": 20, "other": 1}
    assert state.power_live_seen == {"pvPw": (2, 100.0)}
    assert state.power_106_samples == {"pvPw": (30, 160.0)}


@pytest.mark.parametrize("value", [0, None])
def test_type106_applies_zero_and_null_after_live_preference_expires(state, value):
    state.data_cache["pvPw"] = 20
    state.power_live_seen["pvPw"] = (107, 100.0)
    state.last_update_time = 161.0

    state.merge_type106_snapshot(
        {"pvPw": value},
        live_preferred=LIVE_FIELDS,
        live_timeout=60.0,
    )

    assert state.data_cache["pvPw"] is value
    assert state.power_live_seen == {}
    assert state.power_106_samples == {"pvPw": (value, 161.0)}


@pytest.mark.parametrize(
    ("last_seen", "now", "retain", "expected"),
    [
        (0, 149.0, False, True),
        (0, 150.0, False, False),
        (100.0, 160.0, False, True),
        (100.0, 160.001, False, False),
        (100.0, 1000.0, True, True),
        (0, 1000.0, True, False),
    ],
)
def test_child_availability_contract(state, last_seen, now, retain, expected):
    if last_seen:
        state.subdevice_last_seen["CHILD"] = last_seen

    assert state.child_is_available(
        "CHILD",
        now,
        timeout=60.0,
        retain_after_first_seen=retain,
    ) is expected


def test_host_stale_boundary(state):
    assert not state.host_is_stale(160.0, 60.0)
    assert state.host_is_stale(160.001, 60.0)


def test_energy_source_metadata_is_copied(state):
    metadata = {"source": "cts", "activity_age": 0.0}
    state.record_energy_source("grid", metadata)
    metadata["source"] = "changed"

    assert state.energy_sources == {
        "grid": {"source": "cts", "activity_age": 0.0}
    }
