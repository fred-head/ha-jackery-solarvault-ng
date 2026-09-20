"""Phase 3.5 protocol-discovery state, integration and privacy tests."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import asdict, replace
from unittest.mock import Mock

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.jackery import DOMAIN
from custom_components.jackery import diagnostics as diagnostics_module
from custom_components.jackery import diagnostics_snapshot as snapshot_module
from custom_components.jackery.diagnostics import async_get_config_entry_diagnostics
from custom_components.jackery.diagnostics_snapshot import (
    DIAGNOSTICS_SCHEMA_VERSION,
    MAX_SNAPSHOT_BYTES,
    DiagnosticsSnapshotInput,
    DiscoveryDeviceTypeInput,
    DiscoveryMessageTypeInput,
    DiscoveryObservationInput,
    DiscoveryStructureInput,
    ProtocolDiagnosticsInput,
    ProtocolDiscoveryDiagnosticsInput,
    build_diagnostics_snapshot,
)
from custom_components.jackery.protocol_discovery import (
    DISCOVERY_DETAIL_BUDGET_BYTES,
    MAX_DEVICE_TYPE_BUCKETS,
    MAX_MAPPING_ENTRIES,
    MAX_MESSAGE_TYPE_BUCKETS,
    MAX_STRUCTURAL_SIGNATURES,
    OPTION_PROTOCOL_DISCOVERY_ENABLED,
    ProtocolDiscoveryState,
)
from custom_components.jackery.sensor import JackeryDataCoordinator

from .conftest import FakeMqttMsg

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

NOW = 10_000.0
CANARIES = (
    "SUPER_SECRET_TOKEN_123",
    "192.0.2.123",
    "PRIVATE_SSID_CANARY",
    "SERIAL_SECRET_CANARY",
    "UNKNOWN_FIELD_NAME_SECRET_CANARY",
    "UNKNOWN_STRING_VALUE_SECRET_CANARY",
    "mqtt/private/topic",
    "https://secret.example/private?token=abc",
    "RAW_PAYLOAD_SECRET_CANARY",
    "EXCEPTION_SECRET_CANARY",
)


def _observe(
    state: ProtocolDiscoveryState,
    message_type=147,
    body=None,
    *,
    now: float = NOW,
    **envelope,
) -> None:
    payload = body if body is not None else {}
    state.observe(
        {"type": message_type, "body": payload, **envelope},
        payload,
        message_type=message_type,
        now=now,
    )


def _serialized(value) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def test_state_records_only_safe_unknown_type_and_occurrence_metadata() -> None:
    state = ProtocolDiscoveryState()
    _observe(state, 147, {"batSoc": 5}, now=NOW - 4)
    _observe(state, 147, {"batSoc": 6}, now=NOW - 1)
    _observe(state, "UNKNOWN_STRING_VALUE_SECRET_CANARY", {}, now=NOW)

    snapshot = state.snapshot()
    assert [(item.key.kind, item.key.value) for item in snapshot.unknown_message_types] == [
        ("integer", 147),
        ("string", None),
    ]
    numeric = snapshot.unknown_message_types[0].observation
    assert (numeric.count, numeric.first_seen_at, numeric.last_seen_at) == (
        2,
        NOW - 4,
        NOW - 1,
    )
    assert "UNKNOWN_STRING_VALUE_SECRET_CANARY" not in repr(snapshot)


@pytest.mark.parametrize(
    ("message_type", "kind"),
    [
        ("secret", "string"),
        ({"secret": 1}, "object"),
        (["secret"], "array"),
        (True, "bool"),
        (None, "null"),
        (1.5, "number"),
    ],
)
def test_non_integer_message_types_are_bucketed_only_by_json_type(
    message_type,
    kind,
) -> None:
    state = ProtocolDiscoveryState()
    _observe(state, message_type)
    item = state.snapshot().unknown_message_types[0]
    assert item.key.kind == kind
    assert item.key.value is None
    assert "secret" not in repr(item)


def test_known_message_type_is_not_added_to_unknown_buckets() -> None:
    state = ProtocolDiscoveryState()
    _observe(state, 101, {"plugs": []})
    assert state.snapshot().unknown_message_types == ()


def test_unknown_device_pairs_are_numeric_bounded_and_not_device_specific() -> None:
    state = ProtocolDiscoveryState()
    body = {
        "plugs": [
            {
                "deviceSn": "SERIAL_SECRET_CANARY",
                "devType": 4003,
                "subType": 7,
            },
            {"deviceSn": "OTHER", "devType": 4003, "subType": 7},
            {"devType": "4003", "subType": {"secret": 7}},
        ]
    }
    _observe(state, 101, body)
    snapshot = state.snapshot()
    assert len(snapshot.unknown_device_types) == 1
    item = snapshot.unknown_device_types[0]
    assert (item.key.dev_type, item.key.sub_type, item.observation.count) == (
        4003,
        7,
        2,
    )
    assert "SERIAL_SECRET_CANARY" not in repr(snapshot)


def test_unknown_names_and_scalar_values_collapse_to_same_structural_signature() -> None:
    first = ProtocolDiscoveryState()
    second = ProtocolDiscoveryState()
    _observe(
        first,
        147,
        {
            "UNKNOWN_FIELD_NAME_SECRET_CANARY": "UNKNOWN_STRING_VALUE_SECRET_CANARY",
            "alpha": 123456,
            "nested": {"SUPER_SECRET_TOKEN_123": [1, "secret"]},
        },
    )
    _observe(
        second,
        147,
        {
            "completelyDifferent": "PRIVATE_SSID_CANARY",
            "beta": -99,
            "other": {"mqtt/private/topic": [7, "different"]},
        },
    )
    first_keys = tuple(item.key for item in first.snapshot().structures)
    second_keys = tuple(item.key for item in second.snapshot().structures)
    assert first_keys == second_keys
    serialized = repr(first.snapshot())
    assert not any(canary in serialized for canary in CANARIES)


def test_nested_traversal_and_all_bucket_collections_are_bounded() -> None:
    state = ProtocolDiscoveryState()
    for message_type in range(1_000, 1_000 + MAX_MESSAGE_TYPE_BUCKETS + 5):
        _observe(state, message_type)
    for index in range(MAX_DEVICE_TYPE_BUCKETS + 5):
        _observe(
            state,
            101,
            {"plugs": [{"devType": 1_000 + index, "subType": index}]},
        )
    for index in range(MAX_STRUCTURAL_SIGNATURES + 5):
        _observe(
            state,
            147,
            {f"unknown_{index}_{offset}": offset for offset in range(index + 1)},
        )
    _observe(
        state,
        147,
        {f"field_{index}": [index] * 100 for index in range(MAX_MAPPING_ENTRIES + 10)},
    )

    snapshot = state.snapshot()
    assert len(snapshot.unknown_message_types) == MAX_MESSAGE_TYPE_BUCKETS
    assert len(snapshot.unknown_device_types) == MAX_DEVICE_TYPE_BUCKETS
    assert len(snapshot.structures) <= MAX_STRUCTURAL_SIGNATURES
    assert snapshot.message_type_overflow > 0
    assert snapshot.device_type_overflow > 0
    assert snapshot.structural_overflow > 0
    assert snapshot.traversal_dropped > 0


def test_snapshot_is_detached_deterministic_and_state_is_instance_local() -> None:
    first = ProtocolDiscoveryState()
    second = ProtocolDiscoveryState()
    _observe(first, 147, {"secret": [1, 2]}, now=NOW)
    before = first.snapshot()
    assert before == first.snapshot()
    _observe(first, 148, {"other": True}, now=NOW + 1)
    assert before != first.snapshot()
    assert second.snapshot().unknown_message_types == ()


def _discovery_input(size: int = 1) -> ProtocolDiscoveryDiagnosticsInput:
    observation = DiscoveryObservationInput(3, NOW - 10, NOW - 2)
    return ProtocolDiscoveryDiagnosticsInput(
        unknown_message_types=tuple(
            DiscoveryMessageTypeInput("integer", 1_000 + index, observation)
            for index in range(size)
        ),
        unknown_device_types=tuple(
            DiscoveryDeviceTypeInput(2_000 + index, index, observation)
            for index in range(size)
        ),
        structures=tuple(
            DiscoveryStructureInput(
                path="payload",
                unknown_field_count=index + 1,
                unknown_value_types={"string": index + 1, "object": 1},
                nested_shapes=("object(array:1,string:1)",),
                type_mismatches=(("type", "string"),),
                observation=observation,
            )
            for index in range(size)
        ),
    )


def test_p31_discovery_export_is_explicit_aged_json_safe_and_versioned() -> None:
    snapshot = build_diagnostics_snapshot(
        DiagnosticsSnapshotInput(
            protocol=ProtocolDiagnosticsInput(
                discovery_enabled=True,
                discovery=_discovery_input(),
            )
        ),
        now=NOW,
    )
    discovery = snapshot["protocol"]["discovery"]
    assert snapshot["integration"]["schema_version"] == DIAGNOSTICS_SCHEMA_VERSION == 2
    assert snapshot["protocol"]["discovery_enabled"] is True
    assert discovery["version"] == 1
    assert discovery["limits"] == {
        "detail_budget_bytes": DISCOVERY_DETAIL_BUDGET_BYTES,
        "message_type_buckets": MAX_MESSAGE_TYPE_BUCKETS,
        "device_type_buckets": MAX_DEVICE_TYPE_BUCKETS,
        "structural_signatures": MAX_STRUCTURAL_SIGNATURES,
        "mapping_entries": MAX_MAPPING_ENTRIES,
        "array_items": 16,
        "structural_depth": 3,
    }
    assert discovery["unknown_message_types"]["items"][0][
        "first_seen_age_seconds"
    ] == 10
    assert discovery["unknown_message_types"]["items"][0][
        "last_seen_age_seconds"
    ] == 2
    assert json.loads(_serialized(snapshot)) == snapshot


def test_disabled_p31_output_has_no_discovery_detail_object() -> None:
    snapshot = build_diagnostics_snapshot(DiagnosticsSnapshotInput(), now=NOW)
    assert snapshot["protocol"]["discovery_enabled"] is False
    assert "discovery" not in snapshot["protocol"]


def test_discovery_detail_and_complete_snapshot_budgets_are_deterministic() -> None:
    inputs = DiagnosticsSnapshotInput(
        protocol=ProtocolDiagnosticsInput(
            discovery_enabled=True,
            discovery=_discovery_input(100),
        )
    )
    first = build_diagnostics_snapshot(inputs, now=NOW)
    second = build_diagnostics_snapshot(inputs, now=NOW)
    assert _serialized(first) == _serialized(second)
    assert len(_serialized(first).encode()) <= MAX_SNAPSHOT_BYTES
    assert len(_serialized(first["protocol"]["discovery"]).encode()) <= (
        DISCOVERY_DETAIL_BUDGET_BYTES
    )
    assert first["protocol"]["discovery"]["omitted_records"] > 0
    assert set(first) == {
        "integration", "host", "transport", "protocol", "freshness",
        "children", "smartmeter", "entities", "health",
    }


def test_discovery_detail_is_sacrificed_before_standard_diagnostics_core() -> None:
    from .test_diagnostics_hardening import _maximal_input

    base = _maximal_input()
    inputs = replace(
        base,
        protocol=replace(
            base.protocol,
            discovery_enabled=True,
            discovery=_discovery_input(100),
        ),
    )
    snapshot = build_diagnostics_snapshot(inputs, now=NOW)
    serialized_size = len(_serialized(snapshot).encode())

    assert serialized_size <= MAX_SNAPSHOT_BYTES
    assert snapshot["children"]["included"] == 100
    assert snapshot["host"]["alias"] == "host"
    assert snapshot["transport"]["mqtt"]["broker_connectivity"] == "unknown"
    assert snapshot["health"]["status"] in {
        "ok", "degraded", "unavailable", "unknown"
    }
    assert snapshot["protocol"]["discovery"]["omitted_records"] > 0
    assert snapshot["integration"]["truncation"][
        "protocol_observations_omitted"
    ] == snapshot["protocol"]["discovery"]["omitted_records"]


def test_utf8_byte_budget_is_exact_at_and_below_the_boundary(monkeypatch) -> None:
    """Use the production serializer for ASCII, multibyte and truncation edges."""
    def compact(value) -> bytes:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")

    ascii_sample = {"value": "ascii"}
    unicode_sample = {"value": "€漢字"}
    assert snapshot_module._serialized_size(ascii_sample) == len(
        compact(ascii_sample)
    )
    assert snapshot_module._serialized_size(unicode_sample) == len(
        compact(unicode_sample)
    )
    assert snapshot_module._serialized_size(unicode_sample) > len(
        compact(unicode_sample).decode("utf-8")
    )

    from .test_diagnostics_hardening import _maximal_input

    base = _maximal_input()
    inputs = replace(
        base,
        protocol=replace(
            base.protocol,
            discovery_enabled=True,
            discovery=_discovery_input(100),
        ),
    )
    baseline = build_diagnostics_snapshot(inputs, now=NOW)
    exact_size = len(compact(baseline))
    assert exact_size == 65_519

    monkeypatch.setattr(snapshot_module, "MAX_SNAPSHOT_BYTES", exact_size)
    exact = build_diagnostics_snapshot(inputs, now=NOW)
    assert len(compact(exact)) == exact_size

    monkeypatch.setattr(snapshot_module, "MAX_SNAPSHOT_BYTES", exact_size - 1)
    below = build_diagnostics_snapshot(inputs, now=NOW)
    assert len(compact(below)) <= exact_size - 1
    assert below["protocol"]["discovery"]["omitted_records"] > exact[
        "protocol"
    ]["discovery"]["omitted_records"]


def _coordinator(hass, *, enabled: bool) -> JackeryDataCoordinator:
    coordinator = JackeryDataCoordinator(
        hass,
        "hb",
        "SUPER_SECRET_TOKEN_123",
        "192.0.2.123",
        "HOST",
        protocol_discovery_enabled=enabled,
    )
    coordinator.config_entry_id = "entry"
    coordinator.add_entities_callback = Mock()
    coordinator.add_switch_entities_callback = Mock()
    coordinator.register_sensor("listener", Mock())
    return coordinator


def _receive(coordinator: JackeryDataCoordinator, message_type, body, *, host="HOST"):
    coordinator._handle_message(
        FakeMqttMsg(
            f"hb/device/{host}/status",
            json.dumps({"type": message_type, "body": body}),
        )
    )


def test_disabled_hot_path_has_no_state_and_enabled_mode_preserves_runtime(
    hass,
    monkeypatch,
) -> None:
    from custom_components.jackery import sensor as sensor_module

    monkeypatch.setattr(sensor_module.time, "time", lambda: NOW)
    disabled = _coordinator(hass, enabled=False)
    enabled = _coordinator(hass, enabled=True)
    stream = [
        (101, {"plugs": [{"sn": "PLUG", "devType": 6, "outPw": 10}]}),
        (147, {"batSoc": 50, "unknown": "secret"}),
        (2, {"pvPw": 20}),
    ]
    for message_type, body in stream:
        _receive(disabled, message_type, deepcopy(body))
        _receive(enabled, message_type, deepcopy(body))

    assert disabled._protocol_discovery is None
    assert disabled.protocol_discovery_snapshot() is None
    assert enabled.protocol_discovery_snapshot() is not None
    assert disabled._data_cache == enabled._data_cache
    assert disabled._runtime_state.last_update_time == enabled._runtime_state.last_update_time
    assert disabled._subdevice_last_seen == enabled._subdevice_last_seen
    assert disabled._known_plugs == enabled._known_plugs
    assert disabled._energy_sources == enabled._energy_sources
    assert disabled.diagnostics_observation() == enabled.diagnostics_observation()


def test_disabled_mode_never_calls_structural_summarizer(hass, monkeypatch) -> None:
    observe = Mock(side_effect=AssertionError("summarizer must remain cold"))
    monkeypatch.setattr(ProtocolDiscoveryState, "observe", observe)
    coordinator = JackeryDataCoordinator(
        hass,
        "hb",
        "token",
        None,
        "HOST",
    )
    coordinator.config_entry_id = "entry"
    coordinator.add_entities_callback = Mock()
    coordinator.add_switch_entities_callback = Mock()

    _receive(coordinator, 2, {"batSoc": 50})
    _receive(coordinator, 147, {"unknown": {"nested": [1, 2, 3]}})

    observe.assert_not_called()
    assert coordinator._protocol_discovery is None
    assert coordinator.protocol_discovery_snapshot() is None
    assert coordinator._data_cache["batSoc"] == 50
    assert coordinator._data_cache["unknown"] == {"nested": [1, 2, 3]}


def test_reload_reset_and_multi_entry_isolation(hass) -> None:
    first = _coordinator(hass, enabled=True)
    second = JackeryDataCoordinator(
        hass,
        "hb",
        "token",
        None,
        "OTHER",
        protocol_discovery_enabled=True,
    )
    _receive(first, 147, {"secret": "one"})
    assert first.protocol_discovery_snapshot().unknown_message_types
    assert second.protocol_discovery_snapshot().unknown_message_types == ()

    reloaded = _coordinator(hass, enabled=True)
    disabled_after_reload = _coordinator(hass, enabled=False)
    assert reloaded.protocol_discovery_snapshot().unknown_message_types == ()
    assert disabled_after_reload.protocol_discovery_snapshot() is None


def test_observation_point_rejects_foreign_invalid_json_and_invalid_envelope(hass) -> None:
    coordinator = _coordinator(hass, enabled=True)
    coordinator._handle_message(
        FakeMqttMsg("hb/device/FOREIGN/status", '{"type":147,"body":{"secret":1}}')
    )
    coordinator._handle_message(FakeMqttMsg("hb/device/HOST/status", "{"))
    coordinator._handle_message(FakeMqttMsg("hb/device/HOST/status", "[]"))
    snapshot = coordinator.protocol_discovery_snapshot()
    assert snapshot is not None
    assert snapshot.unknown_message_types == ()
    assert snapshot.structures == ()


def test_programming_errors_in_discovery_are_not_swallowed(hass, monkeypatch) -> None:
    coordinator = _coordinator(hass, enabled=True)
    state = coordinator._protocol_discovery
    assert state is not None
    monkeypatch.setattr(state, "observe", Mock(side_effect=RuntimeError("bug")))
    _receive(coordinator, 147, {})
    assert coordinator.diagnostics_observation().protocol.error_counters == (
        ("handler_error", 1),
    )


async def test_option_defaults_false_and_can_be_enabled_and_disabled(hass) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"device_sn": "HOST", "token": "token", "topic_prefix": "hb"},
        options={},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    schema = result["data_schema"]
    defaults = schema({})
    assert defaults[OPTION_PROTOCOL_DISCOVERY_ENABLED] is False

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            "token": "token",
            "topic_prefix": "hb",
            "smartmeter_http_poll": False,
            "smartmeter_poll_interval": 10,
            OPTION_PROTOCOL_DISCOVERY_ENABLED: True,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[OPTION_PROTOCOL_DISCOVERY_ENABLED] is True

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            "token": "token",
            "topic_prefix": "hb",
            "smartmeter_http_poll": False,
            "smartmeter_poll_interval": 10,
            OPTION_PROTOCOL_DISCOVERY_ENABLED: False,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[OPTION_PROTOCOL_DISCOVERY_ENABLED] is False


async def test_final_ha_export_and_internal_snapshot_exclude_all_canaries(
    hass,
    monkeypatch,
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="CONFIG_ENTRY_SECRET_CANARY",
        unique_id="HOST",
        title="PRIVATE_SSID_CANARY",
        data={
            "device_sn": "HOST",
            "token": "SUPER_SECRET_TOKEN_123",
            "topic_prefix": "mqtt/private/topic",
        },
        options={OPTION_PROTOCOL_DISCOVERY_ENABLED: True},
    )
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.LOADED)
    coordinator = _coordinator(hass, enabled=True)
    coordinator.config_entry_id = entry.entry_id
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "config": entry.data,
        "coordinator": coordinator,
    }
    body = {
        "SERIAL_SECRET_CANARY": "UNKNOWN_STRING_VALUE_SECRET_CANARY",
        "nested": {
            "UNKNOWN_FIELD_NAME_SECRET_CANARY": [
                "192.0.2.123",
                "https://secret.example/private?token=abc",
            ]
        },
        "plugs": [
            {
                "sn": "SERIAL_SECRET_CANARY",
                "devType": 4003,
                "subType": 7,
                "RAW_PAYLOAD_SECRET_CANARY": "EXCEPTION_SECRET_CANARY",
            }
        ],
    }
    _receive(coordinator, "SUPER_SECRET_TOKEN_123", body)
    internal = repr(coordinator.protocol_discovery_snapshot())
    discovery_before_diagnostics = coordinator.protocol_discovery_snapshot()
    assert not any(canary in internal for canary in CANARIES)

    pre_redaction: dict[str, object] = {}
    real_builder = diagnostics_module.build_diagnostics_snapshot

    def capture_pre_redaction(inputs, *, now):
        snapshot = real_builder(inputs, now=now)
        pre_redaction["snapshot"] = deepcopy(snapshot)
        return snapshot

    monkeypatch.setattr(diagnostics_module.time, "time", lambda: NOW)
    monkeypatch.setattr(
        diagnostics_module,
        "build_diagnostics_snapshot",
        capture_pre_redaction,
    )
    final = await async_get_config_entry_diagnostics(hass, entry)
    assert coordinator.protocol_discovery_snapshot() == discovery_before_diagnostics
    pre_serialized = _serialized(pre_redaction["snapshot"])
    serialized = _serialized(final)
    assert not any(canary in pre_serialized for canary in CANARIES)
    assert not any(canary in serialized for canary in CANARIES)
    assert "UNKNOWN_FIELD_NAME" not in internal + pre_serialized + serialized
    assert final["protocol"]["discovery_enabled"] is True
    assert final["protocol"]["discovery"]["unknown_message_types"]["items"] == [
        {
            "kind": "string",
            "value": None,
            "count": 1,
            "first_seen_age_seconds": 0.0,
            "last_seen_age_seconds": 0.0,
        }
    ]


def test_diagnostics_snapshot_read_is_side_effect_free(hass) -> None:
    coordinator = _coordinator(hass, enabled=True)
    _receive(coordinator, 147, {"secret": [1, 2, 3]})
    before = coordinator.protocol_discovery_snapshot()
    assert before is not None
    detached = asdict(before)
    assert coordinator.protocol_discovery_snapshot() == before
    detached["message_type_overflow"] = 99
    assert coordinator.protocol_discovery_snapshot() == before
