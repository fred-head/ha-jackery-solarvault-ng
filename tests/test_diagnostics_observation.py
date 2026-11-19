"""Direct and coordinator-path tests for passive runtime observations."""

from __future__ import annotations

import ast
import json
import math
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from custom_components.jackery import sensor as sensor_module
from custom_components.jackery.diagnostics_observation import (
    MAX_OBSERVATION_COUNT,
    DiagnosticsObservationState,
    HttpOutcome,
    ProtocolErrorBucket,
    ProtocolRouteBucket,
)
from custom_components.jackery.sensor import JackeryDataCoordinator

from .conftest import FakeMqttMsg


def test_new_observation_state_is_neutral_and_immutable() -> None:
    state = DiagnosticsObservationState()

    snapshot = state.snapshot()

    assert snapshot.http.last_attempt_at is None
    assert snapshot.http.last_success_at is None
    assert snapshot.http.consecutive_failures == 0
    assert snapshot.http.last_outcome == "unknown"
    assert snapshot.http.target_identifier is None
    assert snapshot.http.replacement_state == "unknown"
    assert snapshot.http.health == "unknown"
    assert snapshot.protocol.route_counters == ()
    assert snapshot.protocol.error_counters == ()
    assert snapshot.protocol.unknown_message_count == 0
    with pytest.raises(AttributeError):
        snapshot.http.health = "healthy"  # type: ignore[misc]


def test_protocol_counters_are_fixed_copied_and_saturating() -> None:
    state = DiagnosticsObservationState()
    state.record_protocol_route(ProtocolRouteBucket.GENERIC_KNOWN)
    state.record_protocol_route(
        ProtocolRouteBucket.GENERIC_UNKNOWN,
        unknown_message_type=True,
    )
    state.record_protocol_error(ProtocolErrorBucket.INVALID_JSON)
    first = state.snapshot()

    state.record_protocol_route(ProtocolRouteBucket.TYPE_101)
    state._route_counters[ProtocolRouteBucket.TYPE_101.value] = MAX_OBSERVATION_COUNT
    state.record_protocol_route(ProtocolRouteBucket.TYPE_101)
    second = state.snapshot()

    assert first.protocol.route_counters == (
        ("generic_known", 1),
        ("generic_unknown", 1),
    )
    assert first.protocol.error_counters == (("invalid_json", 1),)
    assert first.protocol.unknown_message_count == 1
    assert dict(second.protocol.route_counters)["type_101"] == MAX_OBSERVATION_COUNT
    assert first.protocol.route_counters != second.protocol.route_counters


def test_http_observation_mirrors_failure_recovery_and_replacement() -> None:
    state = DiagnosticsObservationState()

    state.observe_http_target("METER-A")
    state.record_http_attempt(100.0)
    state.record_http_outcome(
        HttpOutcome.SUCCESS,
        now=101.0,
        consecutive_failures=0,
        failure_threshold=3,
    )
    success = state.snapshot().http
    assert success.target_identifier == "METER-A"
    assert success.replacement_state == "initial"
    assert success.last_attempt_at == 100.0
    assert success.last_success_at == 101.0
    assert success.health == "healthy"

    state.observe_http_target("METER-A")
    assert state.snapshot().http.replacement_state == "unchanged"

    state.record_http_outcome(
        HttpOutcome.TIMEOUT,
        now=102.0,
        consecutive_failures=1,
        failure_threshold=3,
    )
    assert state.snapshot().http.health == "degraded"
    state.record_http_outcome(
        HttpOutcome.TIMEOUT,
        now=103.0,
        consecutive_failures=3,
        failure_threshold=3,
    )
    failed = state.snapshot().http
    assert failed.health == "unavailable"
    assert failed.last_success_at == 101.0

    state.observe_http_target("METER-B")
    state.record_http_outcome(
        HttpOutcome.SUCCESS,
        now=104.0,
        consecutive_failures=0,
        failure_threshold=3,
    )
    recovered = state.snapshot().http
    assert recovered.target_identifier == "METER-B"
    assert recovered.replacement_state == "replaced"
    assert recovered.health == "healthy"
    assert recovered.consecutive_failures == 0
    assert recovered.last_success_at == 104.0


def test_http_no_target_and_invalid_clock_remain_bounded() -> None:
    state = DiagnosticsObservationState()
    state.observe_http_target("")
    state.observe_http_target("S" * 257)
    state.record_http_attempt("bad")  # type: ignore[arg-type]
    state.record_http_attempt(math.nan)
    state.record_http_outcome(
        HttpOutcome.NO_TARGET,
        now=math.inf,
        consecutive_failures=-1,
        failure_threshold=0,
    )

    snapshot = state.snapshot().http
    assert snapshot.target_identifier is None
    assert snapshot.last_attempt_at is None
    assert snapshot.last_success_at is None
    assert snapshot.consecutive_failures == 0
    assert snapshot.last_outcome == "no_target"
    assert snapshot.health == "unknown"


def test_observation_lifetime_is_per_coordinator_instance(hass) -> None:
    first = JackeryDataCoordinator(hass, "hb", "token", "localhost", "HOST-A")
    second = JackeryDataCoordinator(hass, "hb", "token", "localhost", "HOST-B")

    first._diagnostics_observation.record_protocol_route(
        ProtocolRouteBucket.TYPE_106
    )

    assert first.diagnostics_observation().protocol.route_counters == (
        ("type_106", 1),
    )
    assert second.diagnostics_observation().protocol.route_counters == ()
    assert first._diagnostics_observation is not second._diagnostics_observation


def _receive(
    coordinator: JackeryDataCoordinator,
    message_type,
    body,
    *,
    host: str = "HOST",
) -> None:
    coordinator._handle_message(
        FakeMqttMsg(
            f"hb/device/{host}/status",
            json.dumps({"type": message_type, "body": body}),
        )
    )


def test_protocol_observation_uses_real_pipeline_boundaries(hass, monkeypatch) -> None:
    clock = SimpleNamespace(now=1_000.0)
    monkeypatch.setattr(sensor_module.time, "time", lambda: clock.now)
    coordinator = JackeryDataCoordinator(
        hass,
        "hb",
        "token",
        "localhost",
        "HOST",
    )
    listener = SimpleNamespace(_update_from_coordinator=Mock())
    coordinator.register_sensor("listener", listener)

    _receive(coordinator, 2, {"batSoc": 40})
    _receive(
        coordinator,
        101,
        {"plugs": [{"sn": "PLUG", "devType": 6, "outPw": 5}]},
    )
    _receive(coordinator, 999, {"future": 1})
    coordinator._handle_message(FakeMqttMsg("hb/device/HOST/status", "{"))
    coordinator._handle_message(
        FakeMqttMsg("hb/device/HOST/status", '{"type":2,"body":[]}')
    )
    _receive(coordinator, 2, {"batSoc": 99}, host="FOREIGN")
    coordinator._handle_message(FakeMqttMsg("other/topic", "{}"))

    snapshot = coordinator.diagnostics_observation().protocol
    assert dict(snapshot.route_counters) == {
        "generic_known": 1,
        "generic_unknown": 1,
        "type_101": 1,
    }
    assert dict(snapshot.error_counters) == {
        "foreign_host": 1,
        "invalid_envelope": 1,
        "invalid_json": 1,
        "invalid_topic": 1,
    }
    assert snapshot.unknown_message_count == 1
    assert coordinator._data_cache["batSoc"] == 40
    assert coordinator._data_cache["future"] == 1
    assert coordinator._subdevice_last_seen["PLUG"] == 1_000.0
    assert listener._update_from_coordinator.call_count == 3


def test_pipeline_failure_is_not_counted_as_an_accepted_route(hass, monkeypatch) -> None:
    coordinator = JackeryDataCoordinator(
        hass,
        "hb",
        "token",
        "localhost",
        "HOST",
    )
    monkeypatch.setattr(
        coordinator,
        "_calculate_energy_flow",
        Mock(side_effect=RuntimeError("PRIVATE_EXCEPTION_CANARY")),
    )

    _receive(coordinator, 2, {"batSoc": 40})

    snapshot = coordinator.diagnostics_observation().protocol
    assert snapshot.route_counters == ()
    assert snapshot.error_counters == (("handler_error", 1),)
    assert "PRIVATE_EXCEPTION_CANARY" not in repr(snapshot)


async def test_stop_does_not_create_observation_events(hass) -> None:
    coordinator = JackeryDataCoordinator(
        hass,
        "hb",
        "token",
        "localhost",
        "HOST",
    )
    before = coordinator.diagnostics_observation()

    await coordinator.async_stop()

    assert coordinator.diagnostics_observation() == before


def test_observation_module_is_standard_library_only() -> None:
    root = Path(__file__).parents[1]
    module = root / "custom_components/jackery/diagnostics_observation.py"
    tree = ast.parse(module.read_text(encoding="utf-8"))
    imported_roots = {
        node.names[0].name.split(".")[0]
        for node in tree.body
        if isinstance(node, ast.Import)
    } | {
        (node.module or "").split(".")[0]
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
    }

    assert imported_roots <= {
        "__future__",
        "dataclasses",
        "enum",
        "math",
    }
