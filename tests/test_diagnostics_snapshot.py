"""Direct contracts for the pure diagnostics snapshot builder."""

from __future__ import annotations

import ast
import json
import math
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from custom_components.jackery import diagnostics_snapshot as diagnostics_module
from custom_components.jackery.diagnostics_snapshot import (
    DIAGNOSTICS_SCHEMA_VERSION,
    MAX_CHILDREN,
    MAX_SNAPSHOT_BYTES,
    TOP_LEVEL_SECTIONS,
    ChildDiagnosticsInput,
    ChildFreshnessDiagnosticsInput,
    DiagnosticsSnapshotInput,
    EnergySourceDiagnosticsInput,
    EntityDiagnosticsInput,
    FreshnessDiagnosticsInput,
    HealthDiagnosticsInput,
    HostDiagnosticsInput,
    IntegrationDiagnosticsInput,
    ProtocolDiagnosticsInput,
    SmartMeterDiagnosticsInput,
    TransportDiagnosticsInput,
    Type106EvidenceInput,
    build_diagnostics_snapshot,
)

NOW = 10_000.0


def _populated_input() -> DiagnosticsSnapshotInput:
    return DiagnosticsSnapshotInput(
        integration=IntegrationDiagnosticsInput(
            manifest_version="2.0.0",
            home_assistant_version="2026.9.1",
            python_version="3.13.7",
            entry_state="loaded",
            host_configured=True,
            token_configured=True,
            custom_topic_configured=True,
            legacy_mqtt_host_configured=False,
            http_enabled=True,
            http_poll_interval_seconds=30,
        ),
        host=HostDiagnosticsInput(
            identifier="HOST-SERIAL-SECRET",
            device_type=3,
            model="diy3",
            firmware="v1.2.3-beta+4",
            cache_initialized=True,
        ),
        transport=TransportDiagnosticsInput(
            mqtt_application_state="running",
            mqtt_owned_subscriptions=2,
            mqtt_poll_task_state="running",
            http_task_state="running",
            poll_interval_seconds=10,
            http_request_timeout_seconds=5,
        ),
        protocol=ProtocolDiagnosticsInput(
            semantic_measurements={
                "solar_power": 0,
                "grid_import_power": 125.5,
                "battery_net_power": -50,
            },
            known_field_count=42,
            unknown_field_count=3,
            invalid_value_count=1,
            child_container_counts={"plugs": 1, "cts": 1},
            type106_evidence=(
                Type106EvidenceInput(
                    field="solar_power",
                    live_message_type=2,
                    live_seen_at=9_995.0,
                    snapshot_seen_at=9_990.0,
                ),
            ),
            grid_source=EnergySourceDiagnosticsInput(
                source="cts",
                activity_age_seconds=5,
                skipped_stale=1,
                skipped_missing=2,
                reason="first usable meter",
            ),
        ),
        freshness=FreshnessDiagnosticsInput(
            runtime_started_at=9_000.0,
            host_activity_at=9_997.0,
            host_ever_received=True,
            host_stale=False,
            children=(
                ChildFreshnessDiagnosticsInput(
                    identifier="METER-Z",
                    activity_at=9_998.0,
                    available=True,
                    retention_policy="timeout",
                ),
                ChildFreshnessDiagnosticsInput(
                    identifier="PLUG-A",
                    activity_at=9_940.0,
                    available=False,
                    missing_since=9_950.0,
                    retention_policy="timeout",
                ),
            ),
        ),
        children=(
            ChildDiagnosticsInput(
                identifier="METER-Z",
                family="smartmeter",
                model="hto907a",
                device_type=3,
                sub_type=5,
                cache_containers=("cts",),
                known=True,
                communication_mode=1,
                communication_state=2,
                has_power_measurement=True,
                has_energy_measurement=True,
            ),
            ChildDiagnosticsInput(
                identifier="PLUG-A",
                family="plug",
                device_type=6,
                cache_containers=("plugs",),
                known=True,
                has_power_measurement=True,
                has_energy_measurement=False,
            ),
        ),
        smartmeter=SmartMeterDiagnosticsInput(
            mqtt_identifiers=("METER-Z",),
            http_enabled=True,
            target_identifier="METER-Z",
            created_http_identifiers=("METER-Z",),
            poll_interval_seconds=30,
            request_timeout_seconds=5,
            failure_threshold=3,
        ),
        entities=EntityDiagnosticsInput(
            registry_total=21,
            by_platform={"sensor": 16, "switch": 2},
            disabled_count=3,
            state_counts={"available": 18, "unavailable": 2, "unknown": 1},
            device_counts={"host": 1, "child": 2},
            runtime_listener_counts={"mqtt": 18, "http": 3},
            mismatch_count=0,
        ),
        health=HealthDiagnosticsInput(
            runtime_available=True,
            migration_blocked_child_count=0,
        ),
    )


def _compact_json(value: Any) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def test_empty_snapshot_has_exact_stable_contract_and_neutral_states() -> None:
    snapshot = build_diagnostics_snapshot(DiagnosticsSnapshotInput(), now=NOW)

    assert tuple(snapshot) == TOP_LEVEL_SECTIONS
    assert snapshot["integration"]["schema_version"] == DIAGNOSTICS_SCHEMA_VERSION
    assert snapshot["integration"]["entry_state"] == "unknown"
    assert snapshot["host"]["alias"] == "host"
    assert snapshot["host"]["firmware_valid"] is None
    assert snapshot["transport"]["mqtt"]["broker_connectivity"] == "unknown"
    assert snapshot["protocol"]["observation"] == {
        "route_counters": {},
        "error_counters": {},
        "unknown_message_count": None,
    }
    assert snapshot["smartmeter"]["http"]["last_attempt_age_seconds"] is None
    assert snapshot["smartmeter"]["http"]["last_success_age_seconds"] is None
    assert snapshot["smartmeter"]["http"]["consecutive_failures"] is None
    assert snapshot["smartmeter"]["http"]["last_outcome"] == "unknown"
    assert snapshot["health"] == {
        "status": "unknown",
        "reasons": [],
        "reauth_requested": False,
        "migration": {
            "block_all": False,
            "blocked_child_count": None,
            "conflict_categories": {},
        },
    }
    assert json.loads(_compact_json(snapshot)) == snapshot


def test_snapshot_uses_one_deterministic_alias_map_everywhere() -> None:
    inputs = _populated_input()

    snapshot = build_diagnostics_snapshot(inputs, now=NOW)

    assert snapshot["host"]["alias"] == "host"
    assert [item["alias"] for item in snapshot["children"]["items"]] == [
        "child_001",
        "child_002",
    ]
    assert [item["alias"] for item in snapshot["freshness"]["children"]] == [
        "child_001",
        "child_002",
    ]
    assert snapshot["smartmeter"]["mqtt"]["aliases"] == ["child_001"]
    assert snapshot["smartmeter"]["http"]["target_alias"] == "child_001"
    assert snapshot["smartmeter"]["http"]["created_aliases"] == ["child_001"]

    serialized = _compact_json(snapshot)
    for raw_identifier in ("HOST-SERIAL-SECRET", "METER-Z", "PLUG-A"):
        assert raw_identifier not in serialized


def test_aliases_are_deterministic_for_reordered_input() -> None:
    inputs = _populated_input()
    reordered = replace(
        inputs,
        children=tuple(reversed(inputs.children)),
        freshness=replace(
            inputs.freshness,
            children=tuple(reversed(inputs.freshness.children)),
        ),
        smartmeter=replace(
            inputs.smartmeter,
            mqtt_identifiers=tuple(reversed(inputs.smartmeter.mqtt_identifiers)),
            created_http_identifiers=tuple(
                reversed(inputs.smartmeter.created_http_identifiers)
            ),
        ),
    )

    assert build_diagnostics_snapshot(inputs, now=NOW) == build_diagnostics_snapshot(
        reordered, now=NOW
    )


def test_different_child_identities_do_not_collide() -> None:
    snapshot = build_diagnostics_snapshot(
        DiagnosticsSnapshotInput(
            children=(
                ChildDiagnosticsInput(identifier="A"),
                ChildDiagnosticsInput(identifier="B"),
                ChildDiagnosticsInput(identifier="A"),
            )
        ),
        now=NOW,
    )

    aliases = [item["alias"] for item in snapshot["children"]["items"]]
    assert aliases == ["child_001", "child_002"]
    assert len(set(aliases)) == 2


def test_builder_does_not_mutate_or_retain_mutable_input_collections() -> None:
    measurements: dict[str, Any] = {"solar_power": 10}
    platforms: dict[str, Any] = {"sensor": 2}
    mqtt_identifiers = ["METER-A"]
    children = [ChildDiagnosticsInput(identifier="METER-A", cache_containers=["cts"])]
    inputs = DiagnosticsSnapshotInput(
        protocol=ProtocolDiagnosticsInput(semantic_measurements=measurements),
        children=children,
        smartmeter=SmartMeterDiagnosticsInput(mqtt_identifiers=mqtt_identifiers),
        entities=EntityDiagnosticsInput(by_platform=platforms),
    )
    before = deepcopy((measurements, platforms, mqtt_identifiers, children))

    snapshot = build_diagnostics_snapshot(inputs, now=NOW)
    assert (measurements, platforms, mqtt_identifiers, children) == before

    measurements["solar_power"] = 999
    platforms["sensor"] = 999
    mqtt_identifiers.append("METER-B")
    children[0].cache_containers.append("plugs")  # type: ignore[union-attr]

    assert snapshot["protocol"]["measurements"]["solar_power"] == 10
    assert snapshot["entities"]["by_platform"]["sensor"] == 2
    assert snapshot["smartmeter"]["mqtt"]["count"] == 1
    assert snapshot["children"]["items"][0]["cache_containers"] == ["cts"]

    snapshot["protocol"]["measurements"]["solar_power"] = -1
    snapshot["children"]["items"][0]["cache_containers"].append("plugs")
    assert measurements["solar_power"] == 999
    assert children[0].cache_containers == ["cts", "plugs"]


def test_allowlist_drops_sensitive_unknown_keys_and_values() -> None:
    canaries = {
        "SUPER_SECRET_TOKEN_123",
        "192.0.2.123",
        "PRIVATE_SSID_CANARY",
        "mqtt/private/device/topic",
        "https://user:pass@example.invalid/private?token=secret",
        '{"raw_payload":"SERIAL_SECRET_CANARY"}',
        "UNREVIEWED_UNKNOWN_VALUE",
    }
    measurements: dict[str, Any] = {
        "solar_power": 12,
        "token": "SUPER_SECRET_TOKEN_123",
        "ip": "192.0.2.123",
        "ssid": "PRIVATE_SSID_CANARY",
        "topic": "mqtt/private/device/topic",
        "url": "https://user:pass@example.invalid/private?token=secret",
        "raw_payload": '{"raw_payload":"SERIAL_SECRET_CANARY"}',
        "unknown_extra_field": "UNREVIEWED_UNKNOWN_VALUE",
    }
    snapshot = build_diagnostics_snapshot(
        DiagnosticsSnapshotInput(
            host=HostDiagnosticsInput(model="PRIVATE_SSID_CANARY"),
            protocol=ProtocolDiagnosticsInput(
                semantic_measurements=measurements,
                child_container_counts={"secret_bucket": 99},
            ),
            children=(
                ChildDiagnosticsInput(
                    identifier="SERIAL_SECRET_CANARY",
                    family="UNREVIEWED_UNKNOWN_VALUE",
                    model="PRIVATE_SSID_CANARY",
                    cache_containers=("cts", "secret_bucket"),
                ),
            ),
            entities=EntityDiagnosticsInput(
                by_platform={"sensor": 1, "SUPER_SECRET_TOKEN_123": 100}
            ),
        ),
        now=NOW,
    )

    serialized = _compact_json(snapshot)
    assert snapshot["protocol"]["measurements"] == {"solar_power": 12.0}
    assert snapshot["host"]["model"] == "unknown"
    assert snapshot["children"]["items"][0]["family"] == "unknown"
    assert snapshot["children"]["items"][0]["model"] == "unknown"
    assert snapshot["children"]["items"][0]["cache_containers"] == ["cts"]
    for canary in canaries:
        assert canary not in serialized


@pytest.mark.parametrize(
    ("firmware", "expected", "valid"),
    [
        ("v1.2.3-beta+4", "v1.2.3-beta+4", True),
        (None, None, None),
        ("SERIAL123456789", None, False),
        ("https://example.invalid/1.2", None, False),
        ("v1." + "2" * 40, None, False),
        ("version one.two", None, False),
    ],
)
def test_firmware_validator_is_conservative(
    firmware: str | None, expected: str | None, valid: bool | None
) -> None:
    snapshot = build_diagnostics_snapshot(
        DiagnosticsSnapshotInput(host=HostDiagnosticsInput(firmware=firmware)),
        now=NOW,
    )

    assert snapshot["host"]["firmware"] == expected
    assert snapshot["host"]["firmware_valid"] is valid


def test_numeric_boundaries_preserve_zero_and_reject_bool_and_nonfinite() -> None:
    snapshot = build_diagnostics_snapshot(
        DiagnosticsSnapshotInput(
            protocol=ProtocolDiagnosticsInput(
                semantic_measurements={
                    "solar_power": 0,
                    "grid_import_power": True,
                    "grid_export_power": math.nan,
                    "battery_net_power": math.inf,
                    "eps_input_power": 10**1000,
                },
                known_field_count=True,
            )
        ),
        now=NOW,
    )

    assert snapshot["protocol"]["measurements"] == {"solar_power": 0.0}
    assert snapshot["protocol"]["cache"]["known_field_count"] is None
    assert "NaN" not in _compact_json(snapshot)
    assert "Infinity" not in _compact_json(snapshot)


def test_adopted_identity_capabilities_and_unknown_freshness_are_bounded() -> None:
    snapshot = build_diagnostics_snapshot(
        DiagnosticsSnapshotInput(
            host=HostDiagnosticsInput(identifier="ADOPTED-HOST"),
            protocol=ProtocolDiagnosticsInput(
                semantic_measurements={"eps_output_power": 3},
                type106_evidence=(
                    Type106EvidenceInput(field="unknown_private_field"),
                ),
                grid_source=EnergySourceDiagnosticsInput(
                    source="private_source",
                    activity_age_seconds=-1,
                    reason="private_reason",
                ),
            ),
            freshness=FreshnessDiagnosticsInput(
                children=(
                    ChildFreshnessDiagnosticsInput(
                        identifier="ORPHAN",
                        available=None,
                    ),
                    ChildFreshnessDiagnosticsInput(identifier=""),
                )
            ),
        ),
        now=NOW,
    )

    assert snapshot["integration"]["identity_mode"] == "adopted"
    assert snapshot["host"]["observed_capabilities"] == ["eps_power"]
    assert snapshot["protocol"]["type106_evidence"] == []
    assert snapshot["protocol"]["energy_sources"]["grid"] == {
        "source": "unknown",
        "activity_age_seconds": None,
        "skipped_stale": None,
        "skipped_missing": None,
        "reason": "unknown",
    }
    assert snapshot["freshness"]["children"][0]["reason"] == "unknown"


def test_children_are_deterministically_bounded_and_output_fits_budget() -> None:
    child_count = MAX_CHILDREN + 25
    children = tuple(
        ChildDiagnosticsInput(
            identifier=f"SERIAL-{index:03d}",
            family="plug",
            device_type=6,
            cache_containers=("plugs",),
            known=True,
        )
        for index in reversed(range(child_count))
    )

    snapshot = build_diagnostics_snapshot(
        DiagnosticsSnapshotInput(children=children), now=NOW
    )
    serialized = _compact_json(snapshot).encode()

    assert snapshot["children"]["total"] == child_count
    assert snapshot["children"]["included"] == MAX_CHILDREN
    assert snapshot["children"]["omitted"] == 25
    assert snapshot["integration"]["truncation"]["children_included"] == MAX_CHILDREN
    assert snapshot["integration"]["truncation"]["children_omitted"] == 25
    assert [item["alias"] for item in snapshot["children"]["items"]] == [
        f"child_{index:03d}" for index in range(1, MAX_CHILDREN + 1)
    ]
    assert len(serialized) <= MAX_SNAPSHOT_BYTES
    assert snapshot == build_diagnostics_snapshot(
        DiagnosticsSnapshotInput(children=tuple(reversed(children))), now=NOW
    )


def test_size_fallback_drops_children_then_entity_detail_deterministically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(diagnostics_module, "MAX_SNAPSHOT_BYTES", 3_200)
    child_limited = build_diagnostics_snapshot(_populated_input(), now=NOW)

    assert child_limited["children"]["included"] == 0
    assert child_limited["integration"]["truncation"]["children_omitted"] > 0
    assert child_limited["smartmeter"]["http"]["target_alias"] is None
    assert len(_compact_json(child_limited).encode()) <= 3_200

    entity_input = DiagnosticsSnapshotInput(
        entities=EntityDiagnosticsInput(
            registry_total=99,
            by_platform={platform: 99 for platform in ("button", "number", "select", "sensor", "switch")},
            state_counts={state: 99 for state in ("available", "unavailable", "unknown")},
            device_counts={"child": 99, "host": 1},
            runtime_listener_counts={"http": 99, "mqtt": 99},
        )
    )
    monkeypatch.setattr(diagnostics_module, "MAX_SNAPSHOT_BYTES", 2_600)
    entity_limited = build_diagnostics_snapshot(entity_input, now=NOW)

    assert entity_limited["entities"]["by_platform"] == {}
    assert entity_limited["entities"]["runtime_listener_counts"] == {}
    assert entity_limited["integration"]["truncation"]["entity_detail_omitted"]
    assert len(_compact_json(entity_limited).encode()) <= 2_600

    monkeypatch.setattr(diagnostics_module, "MAX_SNAPSHOT_BYTES", 2_500)
    with pytest.raises(ValueError, match="exceeds the fixed size budget"):
        build_diagnostics_snapshot(entity_input, now=NOW)


def test_type106_energy_source_and_age_contracts_are_allowlisted() -> None:
    snapshot = build_diagnostics_snapshot(_populated_input(), now=NOW)

    assert snapshot["protocol"]["type106_evidence"] == [
        {
            "field": "solar_power",
            "live_present": True,
            "live_message_type": 2,
            "live_age_seconds": 5.0,
            "snapshot_present": True,
            "snapshot_age_seconds": 10.0,
        }
    ]
    assert snapshot["protocol"]["energy_sources"]["grid"] == {
        "source": "cts",
        "activity_age_seconds": 5.0,
        "skipped_stale": 1,
        "skipped_missing": 2,
        "reason": "first_usable_meter",
    }
    assert snapshot["freshness"]["host"]["runtime_age_seconds"] == 1_000.0
    assert snapshot["freshness"]["host"]["activity_age_seconds"] == 3.0


def test_passive_observation_inputs_use_fixed_allowlists_and_ages() -> None:
    inputs = _populated_input()
    snapshot = build_diagnostics_snapshot(
        replace(
            inputs,
            protocol=replace(
                inputs.protocol,
                route_counters={
                    "type_101": 2,
                    "generic_unknown": 1,
                    "PRIVATE_ROUTE_CANARY": 99,
                },
                error_counters={
                    "invalid_json": 3,
                    "PRIVATE_ERROR_CANARY": 99,
                },
                unknown_message_count=1,
            ),
            smartmeter=replace(
                inputs.smartmeter,
                last_attempt_at=9_998.0,
                last_success_at=9_997.0,
                consecutive_failures=2,
                last_outcome="timeout",
                source_replacement_state="replaced",
                health="degraded",
            ),
        ),
        now=NOW,
    )

    assert snapshot["protocol"]["observation"] == {
        "route_counters": {"generic_unknown": 1, "type_101": 2},
        "error_counters": {"invalid_json": 3},
        "unknown_message_count": 1,
    }
    assert snapshot["smartmeter"]["http"]["last_attempt_age_seconds"] == 2.0
    assert snapshot["smartmeter"]["http"]["last_success_age_seconds"] == 3.0
    assert snapshot["smartmeter"]["http"]["consecutive_failures"] == 2
    assert snapshot["smartmeter"]["http"]["last_outcome"] == "timeout"
    assert snapshot["smartmeter"]["http"]["source_replacement_state"] == "replaced"
    assert snapshot["smartmeter"]["http"]["health"] == "degraded"
    serialized = _compact_json(snapshot)
    assert "PRIVATE_ROUTE_CANARY" not in serialized
    assert "PRIVATE_ERROR_CANARY" not in serialized
    assert "METER-Z" not in serialized


def test_health_uses_fixed_reasons_and_precedence() -> None:
    inputs = _populated_input()
    snapshot = build_diagnostics_snapshot(
        replace(
            inputs,
            transport=replace(inputs.transport, mqtt_owned_subscriptions=0),
            freshness=replace(inputs.freshness, host_stale=True),
            health=HealthDiagnosticsInput(
                runtime_available=False,
                reauth_requested=True,
                migration_block_all=True,
                migration_blocked_child_count=2,
                migration_conflict_categories={
                    "entity-target-conflict": 1,
                    "PRIVATE_ERROR_TEXT": 7,
                },
            ),
        ),
        now=NOW,
    )

    assert snapshot["health"]["status"] == "unavailable"
    assert snapshot["health"]["reasons"] == [
        "host_stale",
        "identity_migration_blocked",
        "mqtt_subscription_inconsistent",
        "reauth_requested",
        "runtime_unavailable",
    ]
    assert snapshot["health"]["migration"]["conflict_categories"] == {
        "entity-target-conflict": 1
    }
    assert "PRIVATE_ERROR_TEXT" not in _compact_json(snapshot)


def test_health_reports_degraded_for_non_availability_warning() -> None:
    snapshot = build_diagnostics_snapshot(
        DiagnosticsSnapshotInput(
            freshness=FreshnessDiagnosticsInput(host_stale=False),
            health=HealthDiagnosticsInput(
                runtime_available=True,
                reauth_requested=True,
            ),
        ),
        now=NOW,
    )

    assert snapshot["health"]["status"] == "degraded"
    assert snapshot["health"]["reasons"] == ["reauth_requested"]


@pytest.mark.parametrize("now", [math.nan, math.inf, -math.inf, True])
def test_builder_rejects_nonfinite_or_boolean_clock(now: float) -> None:
    with pytest.raises(ValueError, match="now must be a finite number"):
        build_diagnostics_snapshot(DiagnosticsSnapshotInput(), now=now)


def test_snapshot_module_has_only_standard_library_dependencies_and_no_back_edges() -> None:
    root = Path(__file__).parents[1]
    module_path = root / "custom_components/jackery/diagnostics_snapshot.py"
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
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
        "collections",
        "dataclasses",
        "json",
        "math",
        "re",
        "typing",
    }

    for path in (root / "custom_components/jackery").rglob("*.py"):
        if path == module_path:
            continue
        source = path.read_text(encoding="utf-8")
        assert "diagnostics_snapshot" not in source, path
