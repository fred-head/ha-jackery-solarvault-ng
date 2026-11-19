"""Adversarial privacy, size, mutation and determinism diagnostics tests."""

from __future__ import annotations

import asyncio
import json
import math
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import label_registry as lr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.jackery import DOMAIN
from custom_components.jackery import diagnostics as diagnostics_module
from custom_components.jackery.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.jackery.diagnostics_adapter import (
    collect_diagnostics_inputs,
)
from custom_components.jackery.diagnostics_snapshot import (
    MAX_CHILDREN,
    MAX_SNAPSHOT_BYTES,
    MAX_VERSION_LENGTH,
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
from custom_components.jackery.identity import child_device_identifier
from custom_components.jackery.sensor import JackeryDataCoordinator

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

NOW = 20_000.0
MAX_COUNT = 2_147_483_647
CANARIES = (
    "SUPER_SECRET_TOKEN_123",
    "192.0.2.123",
    "PRIVATE_SSID_CANARY",
    "SERIAL_SECRET_CANARY",
    "ENTITY_SECRET_CANARY",
    "DEVICE_SECRET_CANARY",
    "CONFIG_ENTRY_SECRET_CANARY",
    "USER_NAME_SECRET_CANARY",
    "mqtt/private/topic",
    "https://secret.example/private?token=abc",
    "EXCEPTION_SECRET_CANARY",
    "RAW_PAYLOAD_SECRET_CANARY",
    "RAW_DATA_SECRET_CANARY",
    "UNIQUE_ID_SECRET_CANARY",
    "AREA_SECRET_CANARY",
    "LABEL_SECRET_CANARY",
)

ROUTE_KEYS = (
    "generic_known",
    "generic_unknown",
    "type_23",
    "type_101",
    "type_102",
    "type_106",
    "type_107",
    "type_123",
)
ERROR_KEYS = (
    "foreign_host",
    "handler_error",
    "invalid_envelope",
    "invalid_json",
    "invalid_topic",
)
TYPE106_FIELDS = (
    "eps_input_power",
    "eps_output_power",
    "main_battery_charge_power",
    "main_battery_discharge_power",
    "solar_input_1_power",
    "solar_input_2_power",
    "solar_input_3_power",
    "solar_input_4_power",
    "solar_power",
    "stack_input_power",
    "stack_output_power",
)
SEMANTIC_MEASUREMENTS = (
    "battery_net_power",
    "eps_input_power",
    "eps_output_power",
    "grid_export_power",
    "grid_import_power",
    "grid_net_power",
    "home_power",
    "main_battery_charge_power",
    "main_battery_discharge_power",
    "solar_power",
)
MIGRATION_CATEGORIES = (
    "ambiguous-entity-device-link",
    "ambiguous-host-identity",
    "device-target-conflict",
    "duplicate-device-target",
    "entity-target-conflict",
    "foreign-entity-on-device",
    "foreign-entity-target",
    "foreign-http-entity-target",
    "foreign-or-shared-device",
    "host-identifier-mismatch",
    "main-child-namespace-conflict",
    "malformed-device-identity",
    "multiple-child-identifiers",
    "parent-ownership-mismatch",
    "unknown-or-mismatched-entity-id",
    "unrecognized-device-alias",
    "unresolved-entity-identity",
)


def _compact(snapshot: dict[str, Any]) -> str:
    return json.dumps(
        snapshot,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _entry(
    hass,
    *,
    entry_id: str,
    host: str,
    title: str = "USER_NAME_SECRET_CANARY",
) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id=entry_id,
        unique_id=host,
        title=title,
        data={
            "device_sn": host,
            "token": "SUPER_SECRET_TOKEN_123",
            "topic_prefix": "mqtt/private/topic",
            "mqtt_host": "192.0.2.123",
            "ssid": "PRIVATE_SSID_CANARY",
            "url": "https://secret.example/private?token=abc",
            "raw_payload": "RAW_PAYLOAD_SECRET_CANARY",
        },
        options={
            "smartmeter_http_poll": True,
            "smartmeter_poll_interval": 30,
        },
    )
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.LOADED)
    return entry


def _coordinator(
    hass,
    entry: MockConfigEntry,
    *,
    host: str,
) -> JackeryDataCoordinator:
    coordinator = JackeryDataCoordinator(
        hass,
        "mqtt/private/topic",
        "SUPER_SECRET_TOKEN_123",
        "192.0.2.123",
        host,
    )
    coordinator.config_entry_id = entry.entry_id
    coordinator._subscribed = True
    coordinator._runtime_state.start_time = NOW - 100
    coordinator._runtime_state.last_update_time = NOW - 5
    coordinator._runtime_state.ever_received = True
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "config": entry.data,
        "coordinator": coordinator,
    }
    return coordinator


def _seed_adversarial_runtime(coordinator: JackeryDataCoordinator) -> None:
    meter = "SERIAL_SECRET_CANARY"
    coordinator._device_type = 3
    coordinator._soft_ver = "EXCEPTION_SECRET_CANARY"
    coordinator._runtime_state.data_cache.update(
        {
            "pvPw": 0,
            "gridInPw": 25,
            "cts": [
                {
                    "deviceSn": meter,
                    "devType": 3,
                    "subType": 5,
                    "commMode": 1,
                    "commState": 1,
                    "tPhasePw": 25,
                    "scanName": "USER_NAME_SECRET_CANARY",
                    "ip": "192.0.2.123",
                    "ssid": "PRIVATE_SSID_CANARY",
                    "url": "https://secret.example/private?token=abc",
                    "exception": "EXCEPTION_SECRET_CANARY",
                    "payload": "RAW_PAYLOAD_SECRET_CANARY",
                }
            ],
            "raw_data": {"secret": "RAW_DATA_SECRET_CANARY"},
            "UNKNOWN_SECRET_FIELD": {
                "topic": "mqtt/private/topic",
                "unique_id": "UNIQUE_ID_SECRET_CANARY",
            },
        }
    )
    coordinator._runtime_state.subdevice_last_seen[meter] = NOW - 2
    coordinator._runtime_state.power_live_seen["pvPw"] = (2, NOW - 5)
    coordinator._runtime_state.power_106_samples["pvPw"] = (99, NOW - 10)
    coordinator._runtime_state.energy_sources["grid"] = {
        "source": "cts",
        "activity_age": 2,
        "skipped_stale": 0,
        "skipped_missing": 0,
        "reason": "first usable meter",
        "exception": "EXCEPTION_SECRET_CANARY",
    }
    coordinator._child_discovery_state.register(meter)
    coordinator._child_discovery_state.missing_since[meter] = NOW - 1
    coordinator._http_sm_sensor_sns_created.add(meter)
    coordinator._diagnostics_observation.observe_http_target(meter)


def _seed_adversarial_registries(
    hass,
    entry: MockConfigEntry,
    *,
    host: str,
) -> tuple[set[str], set[str]]:
    area = ar.async_get(hass).async_create("AREA_SECRET_CANARY")
    label = lr.async_get(hass).async_create("LABEL_SECRET_CANARY")
    devices = dr.async_get(hass)
    host_device = devices.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, host)},
        name="DEVICE_SECRET_CANARY",
        serial_number="SERIAL_SECRET_CANARY",
        configuration_url="https://secret.example/private?token=abc",
    )
    host_device = devices.async_update_device(
        host_device.id,
        area_id=area.id,
        labels={label.label_id},
        name_by_user="USER_NAME_SECRET_CANARY",
    )
    child_device = devices.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, child_device_identifier(host, "SERIAL_SECRET_CANARY"))},
        name="DEVICE_SECRET_CANARY",
        via_device=(DOMAIN, host),
    )
    entities = er.async_get(hass)
    entity = entities.async_get_or_create(
        "sensor",
        DOMAIN,
        "UNIQUE_ID_SECRET_CANARY",
        config_entry=entry,
        device_id=child_device.id,
        original_name="USER_NAME_SECRET_CANARY",
        suggested_object_id="ENTITY_SECRET_CANARY",
    )
    entity = entities.async_update_entity(
        entity.entity_id,
        area_id=area.id,
        labels={label.label_id},
        name="USER_NAME_SECRET_CANARY",
    )
    hass.states.async_set(
        entity.entity_id,
        "ENTITY_SECRET_CANARY",
        {
            "raw_data": "RAW_DATA_SECRET_CANARY",
            "raw_payload": "RAW_PAYLOAD_SECRET_CANARY",
            "exception": "EXCEPTION_SECRET_CANARY",
        },
    )
    return {entity.entity_id}, {host_device.id, child_device.id}


def _maximal_input() -> DiagnosticsSnapshotInput:
    identifiers = tuple(
        f"{index:04d}-" + "x" * 251 for index in range(2_000)
    )
    children = tuple(
        ChildDiagnosticsInput(
            identifier=identifier,
            family="smartmeter",
            model="shelly_pro_3em",
            device_type=65_535,
            sub_type=65_535,
            cache_containers=(
                "collectors",
                "cts",
                "expansion_batteries",
                "plugs",
            ),
            known=True,
            expansion_battery=True,
            communication_mode=65_535,
            communication_state=65_535,
            has_power_measurement=True,
            has_energy_measurement=True,
        )
        for identifier in identifiers
    )
    freshness = tuple(
        ChildFreshnessDiagnosticsInput(
            identifier=identifier,
            activity_at=1,
            available=True,
            missing_since=2,
            retention_policy="retain_after_first_seen",
        )
        for identifier in identifiers
    )
    version = "v1." + "2" * (MAX_VERSION_LENGTH - 3)
    return DiagnosticsSnapshotInput(
        integration=IntegrationDiagnosticsInput(
            manifest_version=version,
            home_assistant_version=version,
            python_version=version,
            entry_state="loaded",
            host_configured=True,
            token_configured=True,
            custom_topic_configured=True,
            legacy_mqtt_host_configured=True,
            http_enabled=True,
            http_poll_interval_seconds=86_400,
        ),
        host=HostDiagnosticsInput(
            identifier="host",
            device_type=65_535,
            model="energy_monitor",
            firmware=version,
            cache_initialized=True,
        ),
        transport=TransportDiagnosticsInput(
            mqtt_application_state="running",
            mqtt_owned_subscriptions=MAX_COUNT,
            mqtt_poll_task_state="running",
            http_task_state="running",
            poll_interval_seconds=86_400,
            http_request_timeout_seconds=86_400,
        ),
        protocol=ProtocolDiagnosticsInput(
            semantic_measurements={key: 1e308 for key in SEMANTIC_MEASUREMENTS},
            known_field_count=MAX_COUNT,
            unknown_field_count=MAX_COUNT,
            invalid_value_count=MAX_COUNT,
            child_container_counts={
                key: MAX_COUNT
                for key in ("collectors", "cts", "expansion_batteries", "plugs")
            },
            type106_evidence=tuple(
                Type106EvidenceInput(
                    field=field,
                    live_message_type=65_535,
                    live_seen_at=1,
                    snapshot_seen_at=2,
                )
                for field in TYPE106_FIELDS
            ),
            grid_source=EnergySourceDiagnosticsInput(
                source="collectors",
                activity_age_seconds=1e308,
                skipped_stale=MAX_COUNT,
                skipped_missing=MAX_COUNT,
                reason="first_usable_meter",
            ),
            route_counters={key: MAX_COUNT for key in ROUTE_KEYS},
            error_counters={key: MAX_COUNT for key in ERROR_KEYS},
            unknown_message_count=MAX_COUNT,
        ),
        freshness=FreshnessDiagnosticsInput(
            runtime_started_at=1,
            host_activity_at=1,
            host_ever_received=True,
            host_stale=False,
            children=freshness,
        ),
        children=children,
        smartmeter=SmartMeterDiagnosticsInput(
            mqtt_identifiers=identifiers,
            http_enabled=True,
            target_identifier=identifiers[-1],
            created_http_identifiers=identifiers,
            poll_interval_seconds=86_400,
            request_timeout_seconds=86_400,
            failure_threshold=MAX_COUNT,
            last_attempt_at=1,
            last_success_at=1,
            consecutive_failures=MAX_COUNT,
            last_outcome="unexpected_error",
            source_replacement_state="replaced",
            health="unavailable",
        ),
        entities=EntityDiagnosticsInput(
            registry_total=MAX_COUNT,
            by_platform={
                key: MAX_COUNT
                for key in ("button", "number", "select", "sensor", "switch")
            },
            disabled_count=MAX_COUNT,
            state_counts={
                key: MAX_COUNT for key in ("available", "unavailable", "unknown")
            },
            device_counts={key: MAX_COUNT for key in ("child", "host")},
            runtime_listener_counts={key: MAX_COUNT for key in ("http", "mqtt")},
            mismatch_count=MAX_COUNT,
        ),
        health=HealthDiagnosticsInput(
            runtime_available=True,
            reauth_requested=True,
            migration_block_all=True,
            migration_blocked_child_count=MAX_COUNT,
            migration_conflict_categories={
                category: MAX_COUNT for category in MIGRATION_CATEGORIES
            },
        ),
    )


async def test_adversarial_privacy_before_and_after_ha_redaction(
    hass,
    monkeypatch,
) -> None:
    host = "HOST_SERIAL_SECRET_CANARY"
    entry = _entry(
        hass,
        entry_id="CONFIG_ENTRY_SECRET_CANARY",
        host=host,
    )
    coordinator = _coordinator(hass, entry, host=host)
    _seed_adversarial_runtime(coordinator)
    entity_ids, device_ids = _seed_adversarial_registries(
        hass,
        entry,
        host=host,
    )
    monkeypatch.setattr(diagnostics_module.time, "time", lambda: NOW)

    inputs = collect_diagnostics_inputs(
        hass,
        entry,
        coordinator,
        manifest_version="2.4.0",
        now=NOW,
    )
    before_redaction = build_diagnostics_snapshot(inputs, now=NOW)
    final = await async_get_config_entry_diagnostics(hass, entry)

    for snapshot in (before_redaction, final):
        serialized = _compact(snapshot)
        assert snapshot["host"]["alias"] == "host"
        assert snapshot["smartmeter"]["http"]["target_alias"] == "child_001"
        assert snapshot["children"]["items"][0]["alias"] == "child_001"
        for canary in (*CANARIES, host, *entity_ids, *device_ids):
            assert canary not in serialized


def test_maximal_snapshot_respects_budget_relations_and_determinism() -> None:
    inputs = _maximal_input()
    snapshot = build_diagnostics_snapshot(inputs, now=NOW)
    reordered = build_diagnostics_snapshot(
        replace(
            inputs,
            children=tuple(reversed(inputs.children)),
            freshness=replace(
                inputs.freshness,
                children=tuple(reversed(inputs.freshness.children)),
            ),
            protocol=replace(
                inputs.protocol,
                semantic_measurements=dict(
                    reversed(tuple(inputs.protocol.semantic_measurements.items()))
                ),
                child_container_counts=dict(
                    reversed(tuple(inputs.protocol.child_container_counts.items()))
                ),
                route_counters=dict(
                    reversed(tuple(inputs.protocol.route_counters.items()))
                ),
                error_counters=dict(
                    reversed(tuple(inputs.protocol.error_counters.items()))
                ),
            ),
            smartmeter=replace(
                inputs.smartmeter,
                mqtt_identifiers=tuple(reversed(inputs.smartmeter.mqtt_identifiers)),
                created_http_identifiers=tuple(
                    reversed(inputs.smartmeter.created_http_identifiers)
                ),
            ),
            entities=replace(
                inputs.entities,
                by_platform=dict(reversed(tuple(inputs.entities.by_platform.items()))),
                state_counts=dict(
                    reversed(tuple(inputs.entities.state_counts.items()))
                ),
                device_counts=dict(
                    reversed(tuple(inputs.entities.device_counts.items()))
                ),
                runtime_listener_counts=dict(
                    reversed(tuple(inputs.entities.runtime_listener_counts.items()))
                ),
            ),
            health=replace(
                inputs.health,
                migration_conflict_categories=dict(
                    reversed(
                        tuple(inputs.health.migration_conflict_categories.items())
                    )
                ),
            ),
        ),
        now=NOW,
    )
    serialized = _compact(snapshot)
    size = len(serialized.encode("utf-8"))

    assert snapshot == reordered
    assert 55_000 < size <= MAX_SNAPSHOT_BYTES
    assert json.loads(serialized) == snapshot
    assert snapshot["children"]["total"] == 2_000
    assert snapshot["children"]["included"] == MAX_CHILDREN
    assert snapshot["children"]["omitted"] == 2_000 - MAX_CHILDREN
    detail_aliases = {item["alias"] for item in snapshot["children"]["items"]}
    freshness_aliases = {
        item["alias"] for item in snapshot["freshness"]["children"]
    }
    mqtt_aliases = set(snapshot["smartmeter"]["mqtt"]["aliases"])
    created_aliases = set(snapshot["smartmeter"]["http"]["created_aliases"])
    assert detail_aliases == freshness_aliases == mqtt_aliases == created_aliases
    assert snapshot["smartmeter"]["http"]["target_alias"] is None
    assert snapshot["integration"]["truncation"] == {
        "size_limit_bytes": MAX_SNAPSHOT_BYTES,
        "children_total": 2_000,
        "children_included": MAX_CHILDREN,
        "children_omitted": 2_000 - MAX_CHILDREN,
        "protocol_observations_omitted": 0,
        "entity_detail_omitted": False,
    }
    assert snapshot["host"]["alias"] == "host"
    assert snapshot["transport"]["mqtt"]["application_state"] == "running"
    assert snapshot["health"]["status"] == "degraded"


def test_alias_edge_cases_are_bounded_local_and_deterministic() -> None:
    host = "HOST_IDENTIFIER_CANARY"
    identifiers = (
        "SORT_Z_IDENTIFIER_CANARY",
        "SORT_A_IDENTIFIER_CANARY",
        "ÜNICODE_IDENTIFIER_CANARY",
        "SORT_A_IDENTIFIER_CANARY",
        host,
        "",
        "x" * 257,
    )
    children = tuple(
        ChildDiagnosticsInput(identifier=identifier, family="plug")
        for identifier in identifiers
    )
    freshness = tuple(
        ChildFreshnessDiagnosticsInput(identifier=identifier, available=True)
        for identifier in reversed(identifiers)
    )
    inputs = DiagnosticsSnapshotInput(
        host=HostDiagnosticsInput(identifier=host),
        children=children,
        freshness=FreshnessDiagnosticsInput(children=freshness),
        smartmeter=SmartMeterDiagnosticsInput(
            mqtt_identifiers=identifiers,
            target_identifier="SORT_A_IDENTIFIER_CANARY",
            created_http_identifiers=tuple(reversed(identifiers)),
        ),
    )

    first = build_diagnostics_snapshot(inputs, now=NOW)
    second = build_diagnostics_snapshot(
        replace(inputs, children=tuple(reversed(children))),
        now=NOW,
    )
    independent = build_diagnostics_snapshot(
        DiagnosticsSnapshotInput(
            children=(ChildDiagnosticsInput(identifier="ONLY_CHILD_CANARY"),)
        ),
        now=NOW,
    )

    assert first == second
    assert first["children"]["total"] == 3
    assert [item["alias"] for item in first["children"]["items"]] == [
        "child_001",
        "child_002",
        "child_003",
    ]
    assert first["smartmeter"]["http"]["target_alias"] == "child_001"
    assert independent["children"]["items"][0]["alias"] == "child_001"
    serialized = _compact(first)
    for identifier in identifiers:
        if identifier:
            assert identifier not in serialized


def test_unknown_values_counters_and_nonfinite_numbers_are_closed() -> None:
    snapshot = build_diagnostics_snapshot(
        DiagnosticsSnapshotInput(
            protocol=ProtocolDiagnosticsInput(
                semantic_measurements={
                    "solar_power": math.nan,
                    "grid_import_power": math.inf,
                    "grid_export_power": 0,
                    "UNKNOWN_MEASUREMENT_CANARY": 99,
                },
                route_counters={
                    "type_101": MAX_COUNT + 100,
                    "type_102": -1,
                    "UNKNOWN_ROUTE_CANARY": MAX_COUNT,
                },
                error_counters={
                    "invalid_json": MAX_COUNT + 100,
                    "handler_error": -1,
                    "UNKNOWN_ERROR_CANARY": MAX_COUNT,
                },
                unknown_message_count=MAX_COUNT + 100,
            ),
            smartmeter=SmartMeterDiagnosticsInput(
                http_enabled=True,
                last_outcome="UNKNOWN_OUTCOME_CANARY",
                source_replacement_state="UNKNOWN_REPLACEMENT_CANARY",
                health="UNKNOWN_HEALTH_CANARY",
                consecutive_failures=-1,
            ),
            entities=EntityDiagnosticsInput(
                registry_total=MAX_COUNT + 100,
                by_platform={"sensor": MAX_COUNT + 100, "secret": 99},
                state_counts={"available": -1, "secret": 99},
            ),
        ),
        now=NOW,
    )

    assert snapshot["protocol"]["measurements"] == {"grid_export_power": 0.0}
    assert snapshot["protocol"]["observation"] == {
        "route_counters": {"type_101": MAX_COUNT},
        "error_counters": {"invalid_json": MAX_COUNT},
        "unknown_message_count": MAX_COUNT,
    }
    assert snapshot["smartmeter"]["http"]["last_outcome"] == "unknown"
    assert snapshot["smartmeter"]["http"]["source_replacement_state"] == "unknown"
    assert snapshot["smartmeter"]["http"]["health"] == "unknown"
    assert snapshot["smartmeter"]["http"]["consecutive_failures"] is None
    assert snapshot["entities"]["registry_total"] == MAX_COUNT
    assert snapshot["entities"]["by_platform"]["sensor"] == MAX_COUNT
    serialized = _compact(snapshot)
    for canary in (
        "UNKNOWN_MEASUREMENT_CANARY",
        "UNKNOWN_ROUTE_CANARY",
        "UNKNOWN_ERROR_CANARY",
        "UNKNOWN_OUTCOME_CANARY",
        "UNKNOWN_REPLACEMENT_CANARY",
        "UNKNOWN_HEALTH_CANARY",
    ):
        assert canary not in serialized


@pytest.mark.parametrize(
    ("firmware", "expected", "valid"),
    [
        ("v1.2.3-beta+4", "v1.2.3-beta+4", True),
        ("v1." + "2" * (MAX_VERSION_LENGTH - 3), "v1." + "2" * 29, True),
        ("v1." + "2" * (MAX_VERSION_LENGTH - 2), None, False),
        ("", None, False),
        ("mqtt/private/topic", None, False),
        ("https://secret.example/1.2", None, False),
        ("SUPER_SECRET_TOKEN_123", None, False),
        ("SERIAL_SECRET_CANARY", None, False),
        ("版本-1.2", None, False),
        ("v1.2\nsecret", None, False),
        ("v1.2\tsecret", None, False),
        ("v1.2\0secret", None, False),
        ("v" + "1" * 4_096 + ".2", None, False),
        (None, None, None),
    ],
)
def test_firmware_string_boundary_is_closed(
    firmware: str | None,
    expected: str | None,
    valid: bool | None,
) -> None:
    snapshot = build_diagnostics_snapshot(
        DiagnosticsSnapshotInput(host=HostDiagnosticsInput(firmware=firmware)),
        now=NOW,
    )

    assert snapshot["host"]["firmware"] == expected
    assert snapshot["host"]["firmware_valid"] is valid


async def test_large_registry_is_entry_scoped_and_export_size_is_constant(
    hass,
    monkeypatch,
) -> None:
    own = _entry(hass, entry_id="own-entry", host="OWN_HOST")
    foreign = _entry(
        hass,
        entry_id="CONFIG_ENTRY_SECRET_CANARY",
        host="SERIAL_SECRET_CANARY",
    )
    _coordinator(hass, own, host="OWN_HOST")
    entities = er.async_get(hass)
    devices = dr.async_get(hass)
    domains = ("sensor", "switch", "button", "number", "select", "binary_sensor")

    for index in range(300):
        domain = domains[index % len(domains)]
        record = entities.async_get_or_create(
            domain,
            DOMAIN,
            f"own-{index}",
            config_entry=own,
            disabled_by=(
                er.RegistryEntryDisabler.USER if index % 2 == 0 else None
            ),
        )
        if index % 3 == 0:
            hass.states.async_set(record.entity_id, index)
        elif index % 3 == 1:
            hass.states.async_set(record.entity_id, STATE_UNAVAILABLE)
        entities.async_get_or_create(
            domain,
            DOMAIN,
            f"UNIQUE_ID_SECRET_CANARY-{index}",
            config_entry=foreign,
            original_name="USER_NAME_SECRET_CANARY",
        )

    for index in range(100):
        own_identifier = (
            child_device_identifier("OWN_HOST", f"child-{index}")
            if index % 2
            else f"host-{index}"
        )
        devices.async_get_or_create(
            config_entry_id=own.entry_id,
            identifiers={(DOMAIN, own_identifier)},
        )
        devices.async_get_or_create(
            config_entry_id=foreign.entry_id,
            identifiers={(DOMAIN, f"DEVICE_SECRET_CANARY-{index}")},
            name="USER_NAME_SECRET_CANARY",
        )

    monkeypatch.setattr(diagnostics_module.time, "time", lambda: NOW)
    snapshot = await async_get_config_entry_diagnostics(hass, own)
    serialized = _compact(snapshot)

    assert snapshot["entities"]["registry_total"] == 300
    assert snapshot["entities"]["by_platform"] == {
        "button": 50,
        "number": 50,
        "select": 50,
        "sensor": 50,
        "switch": 50,
    }
    assert snapshot["entities"]["disabled_count"] == 150
    assert snapshot["entities"]["state_counts"] == {
        "available": 100,
        "unavailable": 100,
        "unknown": 100,
    }
    assert snapshot["entities"]["device_counts"] == {"child": 50, "host": 50}
    assert len(serialized.encode("utf-8")) < 5_000
    for canary in CANARIES:
        assert canary not in serialized


async def test_large_discovery_and_expansion_membership_is_bounded(
    hass,
    monkeypatch,
) -> None:
    entry = _entry(hass, entry_id="discovery-stress-entry", host="HOST")
    coordinator = _coordinator(hass, entry, host="HOST")
    identifiers = [f"DISCOVERY_SECRET_{index:04d}" for index in range(1_000)]
    coordinator._child_discovery_state.known_children.update(identifiers)
    coordinator._child_discovery_state.expansion_batteries.update(identifiers[:500])
    coordinator._child_discovery_state.missing_since.update(
        {identifier: NOW - 5 for identifier in identifiers[500:]}
    )
    coordinator._runtime_state.subdevice_last_seen.update(
        {identifier: NOW - 1 for identifier in identifiers}
    )
    coordinator._runtime_state.data_cache["expansion_batteries"] = {
        identifier: {"devType": 4, "inPw": index}
        for index, identifier in enumerate(identifiers[:500])
    }
    monkeypatch.setattr(diagnostics_module.time, "time", lambda: NOW)

    snapshot = await async_get_config_entry_diagnostics(hass, entry)
    serialized = _compact(snapshot)

    assert len(serialized.encode("utf-8")) <= MAX_SNAPSHOT_BYTES
    assert snapshot["children"]["total"] == 1_000
    assert snapshot["children"]["included"] == MAX_CHILDREN
    assert snapshot["children"]["omitted"] == 1_000 - MAX_CHILDREN
    assert len(snapshot["children"]["items"]) == MAX_CHILDREN
    assert len(snapshot["freshness"]["children"]) == MAX_CHILDREN
    assert len({item["alias"] for item in snapshot["children"]["items"]}) == (
        MAX_CHILDREN
    )
    for identifier in (identifiers[0], identifiers[99], identifiers[-1]):
        assert identifier not in serialized


class _MutatingDict(dict[str, Any]):
    def __iter__(self):
        iterator = super().__iter__()
        first = next(iterator)
        yield first
        self["MUTATION_SECRET_CANARY"] = "RAW_PAYLOAD_SECRET_CANARY"
        yield from iterator


class _MutatingList(list[dict[str, Any]]):
    def __iter__(self):
        snapshot = list.copy(self)
        self.append(
            {
                "deviceSn": "MUTATION_SECRET_CANARY",
                "devType": 6,
                "outPw": 999,
            }
        )
        return iter(snapshot)


async def test_mutating_runtime_collections_are_copied_before_iteration(
    hass,
    monkeypatch,
) -> None:
    entry = _entry(hass, entry_id="mutation-entry", host="HOST")
    coordinator = _coordinator(hass, entry, host="HOST")
    children = _MutatingList(
        [{"deviceSn": "CHILD", "devType": 6, "outPw": 1}]
    )
    cache = _MutatingDict({"pvPw": 1, "plugs": children})
    coordinator._runtime_state.data_cache = cache
    coordinator._child_discovery_state.register("CHILD")
    coordinator._runtime_state.subdevice_last_seen["CHILD"] = NOW - 1
    cache_before = dict.copy(cache)
    children_before = list.copy(children)
    monkeypatch.setattr(diagnostics_module.time, "time", lambda: NOW)

    snapshot = await async_get_config_entry_diagnostics(hass, entry)

    assert snapshot["children"]["total"] == 1
    assert snapshot["children"]["items"][0]["alias"] == "child_001"
    assert dict.copy(cache) == cache_before
    assert list.copy(children) == children_before
    assert "MUTATION_SECRET_CANARY" not in _compact(snapshot)


async def test_registry_reordering_and_disappearing_state_are_tolerated(
    hass,
    monkeypatch,
) -> None:
    entry = _entry(hass, entry_id="registry-mutation-entry", host="HOST")
    _coordinator(hass, entry, host="HOST")
    registry = er.async_get(hass)
    records = [
        registry.async_get_or_create(
            "sensor",
            DOMAIN,
            f"entity-{index}",
            config_entry=entry,
        )
        for index in range(10)
    ]
    for record in records:
        hass.states.async_set(record.entity_id, "on")

    original_entries = er.async_entries_for_config_entry
    calls = 0

    def reordered_entries(entity_registry, config_entry_id):
        nonlocal calls
        entries = list(
            original_entries(
                entity_registry,
                config_entry_id,
            )
        )
        calls += 1
        return entries if calls % 2 else list(reversed(entries))

    original_get = hass.states.get
    removed = False

    def disappearing_get(entity_id):
        nonlocal removed
        if not removed:
            removed = True
            hass.states.async_remove(entity_id)
            return None
        return original_get(entity_id)

    def patched_get(_state_machine, entity_id):
        return disappearing_get(entity_id)

    monkeypatch.setattr(er, "async_entries_for_config_entry", reordered_entries)
    monkeypatch.setattr(diagnostics_module.time, "time", lambda: NOW)
    with patch.object(type(hass.states), "get", patched_get):
        first = await async_get_config_entry_diagnostics(hass, entry)

        for record in records:
            hass.states.async_set(record.entity_id, "on")
        removed = False
        second = await async_get_config_entry_diagnostics(hass, entry)

    assert first == second
    assert first["entities"]["registry_total"] == 10
    assert first["entities"]["state_counts"] == {
        "available": 9,
        "unavailable": None,
        "unknown": 1,
    }


async def test_adversarial_diagnostics_remains_read_only_and_errors_propagate(
    hass,
    monkeypatch,
) -> None:
    entry = _entry(hass, entry_id="side-effect-entry", host="HOST")
    coordinator = _coordinator(hass, entry, host="HOST")
    _seed_adversarial_runtime(coordinator)
    _seed_adversarial_registries(hass, entry, host="HOST")
    listener = SimpleNamespace(
        _update_from_coordinator=Mock(),
        async_write_ha_state=Mock(),
    )
    coordinator._sensors = {"listener": listener}
    blocker = asyncio.Event()
    task = asyncio.create_task(blocker.wait())
    coordinator._data_task = task
    monkeypatch.setattr(diagnostics_module.time, "time", lambda: NOW)

    runtime_before = (
        deepcopy(coordinator._runtime_state.data_cache),
        dict(coordinator._runtime_state.subdevice_last_seen),
        dict(coordinator._runtime_state.power_live_seen),
        dict(coordinator._runtime_state.power_106_samples),
        deepcopy(coordinator._runtime_state.energy_sources),
    )
    discovery_before = (
        set(coordinator._child_discovery_state.known_children),
        set(coordinator._child_discovery_state.expansion_batteries),
        dict(coordinator._child_discovery_state.missing_since),
    )
    observation_before = coordinator.diagnostics_observation()
    tasks_before = asyncio.all_tasks()

    publish = AsyncMock()
    poll = AsyncMock()
    discover = Mock()
    reauth = Mock()
    registry_write = AsyncMock()
    monkeypatch.setattr(coordinator._mqtt_transport, "async_publish", publish)
    monkeypatch.setattr(coordinator, "_send_poll_requests", poll)
    monkeypatch.setattr(coordinator, "_check_for_new_plugs", discover)
    monkeypatch.setattr(coordinator, "_trigger_reauth", reauth)
    monkeypatch.setattr(coordinator, "_update_device_registry", registry_write)

    try:
        await async_get_config_entry_diagnostics(hass, entry)

        publish.assert_not_awaited()
        poll.assert_not_awaited()
        discover.assert_not_called()
        reauth.assert_not_called()
        registry_write.assert_not_awaited()
        listener.async_write_ha_state.assert_not_called()
        assert not task.done()
        assert asyncio.all_tasks() == tasks_before
        assert runtime_before == (
            deepcopy(coordinator._runtime_state.data_cache),
            dict(coordinator._runtime_state.subdevice_last_seen),
            dict(coordinator._runtime_state.power_live_seen),
            dict(coordinator._runtime_state.power_106_samples),
            deepcopy(coordinator._runtime_state.energy_sources),
        )
        assert discovery_before == (
            set(coordinator._child_discovery_state.known_children),
            set(coordinator._child_discovery_state.expansion_batteries),
            dict(coordinator._child_discovery_state.missing_since),
        )
        assert coordinator.diagnostics_observation() == observation_before

        with (
            patch.object(
                diagnostics_module,
                "collect_diagnostics_inputs",
                side_effect=TypeError("intentional programming failure"),
            ),
            pytest.raises(TypeError, match="intentional programming failure"),
        ):
            await async_get_config_entry_diagnostics(hass, entry)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


def test_partial_relations_are_json_safe_and_output_is_detached() -> None:
    child_identifiers = ["PARTIAL_CHILD_CANARY"]
    counters = {"type_101": 1}
    inputs = DiagnosticsSnapshotInput(
        protocol=ProtocolDiagnosticsInput(route_counters=counters),
        freshness=FreshnessDiagnosticsInput(
            host_ever_received=False,
            children=(
                ChildFreshnessDiagnosticsInput(
                    identifier="PARTIAL_CHILD_CANARY",
                    available=None,
                ),
            ),
        ),
        smartmeter=SmartMeterDiagnosticsInput(
            mqtt_identifiers=child_identifiers,
            http_enabled=True,
            target_identifier="PARTIAL_CHILD_CANARY",
            created_http_identifiers=(),
        ),
    )
    snapshot = build_diagnostics_snapshot(inputs, now=NOW)
    serialized_before = _compact(snapshot)

    child_identifiers.append("LATE_MUTATION_CANARY")
    counters["type_101"] = 999

    assert _compact(snapshot) == serialized_before
    assert json.loads(serialized_before) == snapshot
    assert snapshot["children"]["items"] == []
    assert snapshot["freshness"]["children"][0]["alias"] == "child_001"
    assert snapshot["smartmeter"]["http"]["target_alias"] == "child_001"
    assert "PARTIAL_CHILD_CANARY" not in serialized_before
    assert "LATE_MUTATION_CANARY" not in serialized_before

    def assert_json_types(value: Any) -> None:
        assert not isinstance(value, (bytes, tuple, set))
        if isinstance(value, dict):
            assert all(isinstance(key, str) for key in value)
            for item in value.values():
                assert_json_types(item)
        elif isinstance(value, list):
            for item in value:
                assert_json_types(item)
        else:
            assert value is None or type(value) in (str, int, float, bool)
            if type(value) is float:
                assert math.isfinite(value)

    assert_json_types(snapshot)
