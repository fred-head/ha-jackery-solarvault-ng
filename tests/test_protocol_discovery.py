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
    MAX_DISCOVERY_COMMANDS,
    MAX_SNAPSHOT_BYTES,
    DiagnosticsSnapshotInput,
    DiscoveryCommandInput,
    DiscoveryDeviceTypeInput,
    DiscoveryMessageTypeInput,
    DiscoveryObservationInput,
    DiscoveryStructureInput,
    ProtocolDiagnosticsInput,
    ProtocolDiscoveryDiagnosticsInput,
    build_diagnostics_snapshot,
)
from custom_components.jackery.protocol_capture import ProtocolDiscoveryCapture
from custom_components.jackery.protocol_discovery import (
    DISCOVERY_DETAIL_BUDGET_BYTES,
    MAX_COMMAND_BUCKETS,
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


@pytest.mark.parametrize(
    ("message_type", "expected_key"),
    [
        (-1, ("integer", None)),
        (0, ("integer", 0)),
        (147, ("integer", 147)),
        (65_535, ("integer", 65_535)),
        (65_536, ("integer", None)),
        (70_000, ("integer", None)),
        (2**256, ("integer", None)),
        (True, ("bool", None)),
        ("70000", ("string", None)),
    ],
)
def test_message_type_buckets_round_trip_through_storage(message_type, expected_key) -> None:
    state = ProtocolDiscoveryState()
    _observe(state, message_type, now=NOW - 1)
    _observe(state, message_type, now=NOW)

    stored = state.to_storage()
    restored = ProtocolDiscoveryState.from_storage(stored)

    assert restored is not None
    assert restored.snapshot() == state.snapshot()
    assert [(item.key.kind, item.key.value) for item in restored.snapshot().unknown_message_types] == [
        expected_key
    ]
    observation = restored.snapshot().unknown_message_types[0].observation
    assert (observation.count, observation.first_seen_at, observation.last_seen_at) == (
        2,
        NOW - 1,
        NOW,
    )


@pytest.mark.parametrize("invalid_value", [True, -1, 65_536, "70000", 101])
def test_integer_bucket_storage_rejects_invalid_or_unabstracted_values(invalid_value) -> None:
    state = ProtocolDiscoveryState()
    _observe(state, 70_000)
    stored = state.to_storage()
    stored["unknown_message_types"][0]["value"] = invalid_value

    assert ProtocolDiscoveryState.from_storage(stored) is None


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


@pytest.mark.parametrize(
    ("message_type", "cmd"),
    ((2, 106), (2, 107), (101, 110), (106, 120), (23, 0)),
)
def test_integer_body_cmd_alone_is_not_an_unknown_structure(
    message_type: int,
    cmd: int,
) -> None:
    state = ProtocolDiscoveryState()

    _observe(state, message_type, {"cmd": cmd})

    assert state.snapshot().structures == ()


@pytest.mark.parametrize(
    ("cmd", "expected_type"),
    (("106", "string"), (True, "bool"), (106.0, "number"), (None, "null")),
)
def test_non_integer_cmd_is_reported_as_a_type_mismatch_and_restores(
    cmd: object,
    expected_type: str,
) -> None:
    state = ProtocolDiscoveryState()
    body = {"cmd": cmd}

    signals = state.observe(
        {"type": 2, "body": body},
        body,
        message_type=2,
        now=NOW,
    )

    structures = state.snapshot().structures
    assert len(structures) == 1
    assert structures[0].key.path == "payload"
    assert structures[0].key.unknown_field_count == 0
    assert structures[0].key.type_mismatches == (("cmd", expected_type),)
    assert any(signal.reason == "unknown_structure" for signal in signals)

    restored = ProtocolDiscoveryState.from_storage(state.to_storage())
    assert restored is not None
    assert restored.snapshot().structures == structures


@pytest.mark.parametrize(
    ("message_type", "body"),
    (
        (
            2,
            {
                "cmd": 106, "batSoc": 50, "soc": 50, "batInPw": 0, "batOutPw": 0,
                "cellTemp": 250, "batState": 1, "pvPw": 0,
                "pv1": {"pvPw": 0, "commState": 1}, "socChgLimit": 90,
                "socDischgLimit": 10, "socForceChg": 0, "ethPort": 1,
                "eip": "192.0.2.1", "wsig": -55, "wname": "lan",
                "swEpsState": 1, "stackInPw": 0, "stackOutPw": 0, "workModel": 4,
                "maxCellTemp": 250, "minCellTemp": 100, "maxCellVolt": 3500,
                "minCellVolt": 3000, "stackChgCurLimit": 30,
                "stackDischgCurLimit": 40, "emsChgCurLimit": 30,
                "emsDischgCurLimit": 40, "pcsSetPw": 1500,
            },
        ),
        (2, {"soc": 50, "pvPw": 0}),
        (
            2,
            {
                "cmd": 107, "socChgLimit": 90, "socDischgLimit": 10,
                "maxOutPw": 2500, "maxFeedGrid": 800, "autoStandby": 2,
                "isAutoStandby": 1, "swEps": 1, "socForceChg": 0,
                "reboot": 0, "workModel": 4, "defaultPw": 500,
                "isFollowMeterPw": 0, "offGridDown": 0,
            },
        ),
        (
            106,
            {
                "cmd": 120, "ongridStat": 1, "ctStat": 1, "gridSate": 1,
                "isFollowMeterPw": 0, "energyPlanPw": 0, "workModel": 4,
                "maxFeedGrid": 800, "defaultPw": 500, "offGridDown": 0,
                "offGridTime": 120, "standbyPw": 0, "pvMaxChgPower": 4000,
                "maxSysOutPw": 2500, "maxSysInPw": 2500, "funcEnable": 0,
                "chargePlanPw": 0, "tempUnit": 0,
            },
        ),
        (106, {"gridInPw": 0, "gridOutPw": 0, "energyPlanPw": 0}),
        (
            23,
            {
                "cmd": 0, "deviceSn": "system", "pvEgy": 1, "pv1Egy": 2,
                "pv2Egy": 3, "pv3Egy": 4, "pv4Egy": 5, "batChgEgy": 6,
                "batDisChgEgy": 7, "inOngridEgy": 8, "outOngridEgy": 9,
                "inEpsEgy": 10, "outEpsEgy": 11, "pvOtBatEgy": 12,
                "pvOtAcEgy": 13, "pvOtOngridEgy": 14, "ongridOtAcLoadEgy": 15,
                "batOtAcEgy": 16, "batOtGridEgy": 17, "ongridOtBatEgy": 18,
                "acOtBatEgy": 19, "acOtOngridEgy": 20,
            },
        ),
        (23, {"deviceSn": "BATTERY", "devType": 1, "subType": 0, "inEgy": 100, "outEgy": 80}),
        (
            101,
            {
                "cmd": 110,
                "plugs": [{
                    "deviceSn": "PLUG", "devType": 6, "subType": 0, "commMode": 1,
                    "commState": 1, "switchSta": 1, "sysSwitch": 1, "outPw": 20, "totalEgy": 30,
                }],
                "cts": [{
                    "deviceSn": "METER", "devType": 3, "subType": 5, "commMode": 1,
                    "commState": 1, "tPhasePw": 10, "tnPhasePw": 0, "tPhaseEgy": 40,
                    "tnPhaseEgy": 0, "aPhasePw": 10, "bPhasePw": 0, "cPhasePw": 0,
                    "anPhasePw": 0, "bnPhasePw": 0, "cnPhasePw": 0,
                }],
                "collectors": [{
                    "deviceSn": "COLLECTOR", "devType": 4, "subType": 7,
                    "commState": 1, "inPw": 10, "outPw": 0,
                }],
            },
        ),
    ),
)
def test_known_message_and_device_contexts_do_not_create_findings(
    message_type: int,
    body: dict[str, object],
) -> None:
    state = ProtocolDiscoveryState()
    signals = state.observe(
        {"type": message_type, "body": body}, body, message_type=message_type, now=NOW
    )

    assert signals == ()
    assert state.snapshot().structures == ()
    assert state.snapshot().unknown_commands == ()


@pytest.mark.parametrize(
    ("message_type", "body", "expected_path"),
    (
        (2, {"cmd": 106, "newType2Field": 1}, "payload"),
        (106, {"cmd": 120, "newType106Field": 1}, "payload"),
        (23, {"pvEgy": 1, "newType23HostField": 1}, "payload"),
        (
            23,
            {
                "deviceSn": "synthetic-battery",
                "devType": 1,
                "subType": 0,
                "inEgy": 1,
                "outEgy": 1,
                "newBp2500Field": 1,
            },
            "expansion_item",
        ),
    ),
)
def test_unknown_fields_remain_visible_in_each_discovery_context(
    message_type: int,
    body: dict[str, object],
    expected_path: str,
) -> None:
    state = ProtocolDiscoveryState()

    signals = state.observe(
        {"type": message_type, "body": body},
        body,
        message_type=message_type,
        now=NOW,
    )

    assert any(signal.reason == "unknown_structure" for signal in signals)
    assert any(item.key.path == expected_path for item in state.snapshot().structures)


def test_capture_observed_fields_remain_context_scoped() -> None:
    type2_wrong_context = ProtocolDiscoveryState()
    body = {"cmd": 106, "tempUnit": 0}
    signals = type2_wrong_context.observe(
        {"type": 2, "body": body}, body, message_type=2, now=NOW
    )
    assert any(signal.reason == "unknown_structure" for signal in signals)

    type106_wrong_context = ProtocolDiscoveryState()
    body = {"cmd": 120, "maxCellTemp": 250}
    signals = type106_wrong_context.observe(
        {"type": 106, "body": body}, body, message_type=106, now=NOW
    )
    assert any(signal.reason == "unknown_structure" for signal in signals)

    bp2500_wrong_context = ProtocolDiscoveryState()
    body = {
        "devType": 1,
        "subType": 0,
        "inEgy": 1,
        "outEgy": 1,
        "maxCellTemp": 250,
    }
    signals = bp2500_wrong_context.observe(
        {"type": 23, "body": body}, body, message_type=23, now=NOW
    )
    assert any(signal.reason == "unknown_structure" for signal in signals)
    assert bp2500_wrong_context.snapshot().structures[0].key.unknown_field_count == 1


def test_unknown_command_variants_are_distinct_bounded_and_persisted() -> None:
    state = ProtocolDiscoveryState()
    for offset in range(MAX_COMMAND_BUCKETS + 3):
        body = {"cmd": 1_000 + offset}
        signals = state.observe(
            {"type": 2, "body": body}, body, message_type=2, now=NOW + offset
        )
        assert any(signal.reason == "unknown_command" for signal in signals)

    snapshot = state.snapshot()
    assert len(snapshot.unknown_commands) == MAX_COMMAND_BUCKETS
    assert snapshot.command_overflow == 3
    assert snapshot.unknown_commands[0].key.message_type == 2
    assert snapshot.unknown_commands[0].key.command == 1_000
    restored = ProtocolDiscoveryState.from_storage(state.to_storage())
    assert restored is not None
    assert restored.snapshot().unknown_commands == snapshot.unknown_commands
    assert restored.snapshot().command_overflow == 3


def test_old_discovery_storage_is_migrated_without_reclassifying_signatures() -> None:
    legacy = {
        "version": 1,
        "unknown_message_types": [],
        "unknown_device_types": [],
        "structures": [{
            "path": "payload", "unknown_field_count": 2,
            "unknown_value_types": [["integer", 2]], "nested_shapes": [],
            "type_mismatches": [], "count": 12,
            "first_seen_at": NOW - 20, "last_seen_at": NOW - 2,
        }],
        "message_type_overflow": 0, "device_type_overflow": 0,
        "structural_overflow": 0, "traversal_dropped": 0,
    }

    restored = ProtocolDiscoveryState.from_storage(legacy)

    assert restored is not None
    assert restored.snapshot().version == 2
    assert len(restored.snapshot().structures) == 1
    assert restored.snapshot().structures[0].observation.count == 12
    assert restored.snapshot().unknown_commands == ()


@pytest.mark.parametrize(
    ("message_type", "body", "envelope", "expected_path", "mismatch"),
    (
        (2, {"cmd": 106, "soc": "50"}, None, "payload", ("soc", "string")),
        (2, {"cmd": 106, "maxCellTemp": "250"}, None, "payload", ("maxCellTemp", "string")),
        (106, {"cmd": 120, "tempUnit": "celsius"}, None, "payload", ("tempUnit", "string")),
        (2, {"cmd": 106, "pv1": 50}, None, "payload", ("pv1", "integer")),
        (101, {"plugs": [{"deviceSn": "PLUG", "devType": True, "subType": 0}]}, None, "child_item", ("devType", "bool")),
        (2, {}, {"type": 2, "body": "not an object"}, "envelope", ("body", "string")),
    ),
)
def test_known_fields_with_wrong_types_are_still_reported(
    message_type: int,
    body: dict[str, object],
    envelope: dict[str, object] | None,
    expected_path: str,
    mismatch: tuple[str, str],
) -> None:
    state = ProtocolDiscoveryState()
    raw_envelope = envelope or {"type": message_type, "body": body}

    signals = state.observe(raw_envelope, body, message_type=message_type, now=NOW)

    assert any(signal.reason == "unknown_structure" for signal in signals)
    assert any(
        item.key.path == expected_path and mismatch in item.key.type_mismatches
        for item in state.snapshot().structures
    )


def test_new_nested_and_cross_context_fields_remain_findings() -> None:
    nested = ProtocolDiscoveryState()
    body = {"cmd": 106, "pv1": {"pvPw": 0, "commState": 1, "newNested": {"x": 1}}}
    signals = nested.observe({"type": 2, "body": body}, body, message_type=2, now=NOW)
    assert any(signal.reason == "unknown_structure" for signal in signals)
    assert any(item.key.path == "pv_item" for item in nested.snapshot().structures)

    incremental = ProtocolDiscoveryState()
    body_without_cmd = {"pv1": {"pvPw": 0, "commState": 1, "newNested": {"x": 1}}}
    signals = incremental.observe(
        {"type": 2, "body": body_without_cmd},
        body_without_cmd,
        message_type=2,
        now=NOW,
    )
    assert any(signal.reason == "unknown_structure" for signal in signals)
    assert any(item.key.path == "pv_item" for item in incremental.snapshot().structures)

    cross_context = ProtocolDiscoveryState()
    wrong_family = {"cmd": 0, "pvPw": 1}
    signals = cross_context.observe(
        {"type": 23, "body": wrong_family}, wrong_family, message_type=23, now=NOW
    )
    assert any(signal.reason == "unknown_structure" for signal in signals)
    assert cross_context.snapshot().structures[0].key.unknown_field_count == 1

    misplaced_container = ProtocolDiscoveryState()
    misplaced_body = {
        "cmd": 106,
        "plugs": [{"deviceSn": "PLUG", "devType": 6, "subType": 0, "sysSwitch": 1}],
    }
    signals = misplaced_container.observe(
        {"type": 2, "body": misplaced_body},
        misplaced_body,
        message_type=2,
        now=NOW,
    )
    assert any(signal.reason == "unknown_structure" for signal in signals)
    assert misplaced_container.snapshot().structures[0].key.path == "payload"


def test_command_observation_uses_only_established_namespaces() -> None:
    type101 = ProtocolDiscoveryState()
    body101 = {"cmd": 111, "plugs": []}
    signals101 = type101.observe(
        {"type": 101, "body": body101}, body101, message_type=101, now=NOW
    )
    assert any(signal.reason == "unknown_command" for signal in signals101)

    type23 = ProtocolDiscoveryState()
    body23 = {"cmd": 999, "deviceSn": "system", "pvEgy": 1}
    signals23 = type23.observe(
        {"type": 23, "body": body23}, body23, message_type=23, now=NOW
    )
    assert not any(signal.reason == "unknown_command" for signal in signals23)
    assert type23.snapshot().unknown_commands == ()


def test_generic_known_device_fallback_does_not_hide_unknown_family_fields() -> None:
    state = ProtocolDiscoveryState()
    body = {"cts": [{"deviceSn": "METER", "devType": 3, "subType": 99, "tPhasePw": 25}]}

    signals = state.observe({"type": 101, "body": body}, body, message_type=101, now=NOW)

    assert any(signal.reason == "unknown_structure" for signal in signals)
    assert state.snapshot().unknown_device_types == ()
    assert state.snapshot().structures[0].key.unknown_field_count == 1


def test_unknown_payload_field_remains_reported_alongside_integer_cmd() -> None:
    state = ProtocolDiscoveryState()
    body = {"cmd": 106, "newly_observed_field": "shape only"}

    signals = state.observe(
        {"type": 2, "body": body},
        body,
        message_type=2,
        now=NOW,
    )

    assert any(signal.reason == "unknown_structure" for signal in signals)
    structures = state.snapshot().structures
    assert len(structures) == 1
    assert structures[0].key.unknown_field_count == 1
    assert structures[0].key.unknown_value_types == (("string", 1),)
    assert structures[0].key.type_mismatches == ()


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
        unknown_commands=tuple(
            DiscoveryCommandInput(2, 1_000 + index, observation)
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
    assert snapshot["integration"]["schema_version"] == DIAGNOSTICS_SCHEMA_VERSION == 4
    assert snapshot["protocol"]["discovery_enabled"] is True
    assert discovery["version"] == 2
    assert discovery["limits"] == {
        "detail_budget_bytes": DISCOVERY_DETAIL_BUDGET_BYTES,
        "message_type_buckets": MAX_MESSAGE_TYPE_BUCKETS,
        "command_buckets": MAX_DISCOVERY_COMMANDS,
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
    assert discovery["unknown_commands"]["items"][0]["message_type"] == 2
    assert discovery["unknown_commands"]["items"][0]["command"] == 1_000
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
    assert exact_size == 65_447

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
    raw_observe = Mock(side_effect=AssertionError("raw recorder must remain cold"))
    monkeypatch.setattr(ProtocolDiscoveryState, "observe", observe)
    monkeypatch.setattr(ProtocolDiscoveryCapture, "observe", raw_observe)
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
    raw_observe.assert_not_called()
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
    assert defaults["bmslog_capture_enabled"] is False

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            "token": "token",
            "topic_prefix": "hb",
            "smartmeter_http_poll": False,
            "smartmeter_poll_interval": 10,
            OPTION_PROTOCOL_DISCOVERY_ENABLED: True,
            "bmslog_capture_enabled": False,
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
            "bmslog_capture_enabled": False,
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
