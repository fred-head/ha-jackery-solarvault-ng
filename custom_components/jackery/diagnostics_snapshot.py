"""Pure, allowlisted diagnostics contract and snapshot builder.

The caller owns runtime-state collection. This module accepts explicit copied
inputs and returns a bounded JSON-compatible snapshot without importing Home
Assistant or retaining mutable input references.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, NotRequired, TypedDict

DIAGNOSTICS_SCHEMA_VERSION: Final = 2
MAX_CHILDREN: Final = 100
MAX_SNAPSHOT_BYTES: Final = 64 * 1024
MAX_VERSION_LENGTH: Final = 32
DISCOVERY_DETAIL_BUDGET_BYTES: Final = 8 * 1024
MAX_DISCOVERY_MESSAGE_TYPES: Final = 32
MAX_DISCOVERY_DEVICE_TYPES: Final = 64
MAX_DISCOVERY_STRUCTURES: Final = 64
MAX_DISCOVERY_MAPPING_ENTRIES: Final = 64
MAX_DISCOVERY_ARRAY_ITEMS: Final = 16
MAX_DISCOVERY_DEPTH: Final = 3
MAX_SAFE_PROTOCOL_INTEGER: Final = 65_535

TOP_LEVEL_SECTIONS: Final = (
    "integration",
    "host",
    "transport",
    "protocol",
    "freshness",
    "children",
    "smartmeter",
    "entities",
    "health",
)

_VERSION_TOKEN = re.compile(
    rf"(?=.{{1,{MAX_VERSION_LENGTH}}}\Z)(?=.*\d)(?=.*[.+-])[A-Za-z0-9][A-Za-z0-9.+-]*"
)

_ENTRY_STATES: Final = frozenset(
    {
        "failed_unload",
        "loaded",
        "migration_error",
        "not_loaded",
        "setup_error",
        "setup_in_progress",
        "setup_retry",
        "unload_in_progress",
        "unknown",
    }
)
_APPLICATION_STATES: Final = frozenset(
    {"failed", "running", "starting", "stopped", "stopping", "unknown"}
)
_TASK_STATES: Final = frozenset(
    {"absent", "cancelled", "done", "failed", "pending", "running", "unknown"}
)
_HOST_MODELS: Final = frozenset({"diy3", "energy_monitor", "unknown"})
_CHILD_FAMILIES: Final = frozenset(
    {"collector", "ct", "expansion_battery", "plug", "smartmeter", "unknown"}
)
_CHILD_MODELS: Final = frozenset(
    {"hto907a", "hto910a", "shelly_pro_3em", "unknown"}
)
_CACHE_CONTAINERS: Final = frozenset(
    {"collectors", "cts", "expansion_batteries", "plugs"}
)
_RETENTION_POLICIES: Final = frozenset(
    {"retain_after_first_seen", "timeout", "unknown"}
)
_SEMANTIC_MEASUREMENTS: Final = frozenset(
    {
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
    }
)
_TYPE106_FIELDS: Final = frozenset(
    {
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
    }
)
_CHILD_CONTAINER_COUNTS: Final = (
    "collectors",
    "cts",
    "expansion_batteries",
    "plugs",
)
_GRID_SOURCES: Final = frozenset(
    {"collectors", "cts", "system", "unavailable", "unknown"}
)
_SOURCE_REASONS: Final = {
    "first usable meter": "first_usable_meter",
    "first_usable_meter": "first_usable_meter",
    "no usable meter": "no_usable_meter",
    "no_usable_meter": "no_usable_meter",
    "unknown": "unknown",
}
_PLATFORMS: Final = ("button", "number", "select", "sensor", "switch")
_ENTITY_STATES: Final = ("available", "unavailable", "unknown")
_DEVICE_ROLES: Final = ("child", "host")
_LISTENER_KINDS: Final = ("http", "mqtt")
_MIGRATION_CATEGORIES: Final = frozenset(
    {
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
    }
)
_PROTOCOL_ROUTE_COUNTERS: Final = (
    "generic_known",
    "generic_unknown",
    "type_23",
    "type_101",
    "type_102",
    "type_106",
    "type_107",
    "type_123",
)
_PROTOCOL_ERROR_COUNTERS: Final = (
    "foreign_host",
    "handler_error",
    "invalid_envelope",
    "invalid_json",
    "invalid_topic",
)
_HTTP_OUTCOMES: Final = frozenset(
    {
        "client_error",
        "http_status_error",
        "invalid_json",
        "invalid_payload",
        "no_target",
        "success",
        "timeout",
        "unexpected_error",
        "unknown",
    }
)
_HTTP_REPLACEMENT_STATES: Final = frozenset(
    {"initial", "replaced", "unchanged", "unknown"}
)
_HTTP_HEALTH_STATES: Final = frozenset(
    {"degraded", "healthy", "unavailable", "unknown"}
)
_DISCOVERY_TYPES: Final = frozenset(
    {"array", "bool", "integer", "null", "number", "object", "string"}
)
_DISCOVERY_PATHS: Final = frozenset(
    {"child_item", "envelope", "expansion_item", "payload"}
)
_DISCOVERY_FIELDS: Final = frozenset(
    {"body", "deviceSn", "devType", "sn", "subType", "type"}
)
_DISCOVERY_SHAPE = re.compile(
    r"(?=.{1,256}\Z)[a-z]+(?:\([a-z0-9:,_()]*\))?"
)


@dataclass(frozen=True, slots=True)
class IntegrationDiagnosticsInput:
    """Allowlisted integration and configuration facts."""

    manifest_version: str | None = None
    home_assistant_version: str | None = None
    python_version: str | None = None
    entry_state: str = "unknown"
    host_configured: bool = False
    token_configured: bool = False
    custom_topic_configured: bool = False
    legacy_mqtt_host_configured: bool = False
    http_enabled: bool = False
    http_poll_interval_seconds: int | None = None


@dataclass(frozen=True, slots=True)
class HostDiagnosticsInput:
    """Allowlisted host facts; identifier is used only for local aliasing."""

    identifier: str | None = None
    device_type: int | None = None
    model: str = "unknown"
    firmware: str | None = None
    cache_initialized: bool = False


@dataclass(frozen=True, slots=True)
class TransportDiagnosticsInput:
    """Application lifecycle facts, never broker connectivity."""

    mqtt_application_state: str = "unknown"
    mqtt_owned_subscriptions: int | None = None
    mqtt_poll_task_state: str = "unknown"
    http_task_state: str = "unknown"
    poll_interval_seconds: int | None = None
    http_request_timeout_seconds: int | None = None


@dataclass(frozen=True, slots=True)
class Type106EvidenceInput:
    """Allowlisted Type-106 arbitration evidence for one semantic field."""

    field: str
    live_message_type: int | None = None
    live_seen_at: float | None = None
    snapshot_seen_at: float | None = None


@dataclass(frozen=True, slots=True)
class EnergySourceDiagnosticsInput:
    """Allowlisted current grid-source decision."""

    source: str = "unknown"
    activity_age_seconds: float | None = None
    skipped_stale: int | None = None
    skipped_missing: int | None = None
    reason: str = "unknown"


@dataclass(frozen=True, slots=True)
class DiscoveryObservationInput:
    """Occurrence metadata for one safe discovery record."""

    count: int
    first_seen_at: float
    last_seen_at: float


@dataclass(frozen=True, slots=True)
class DiscoveryMessageTypeInput:
    """One unknown message-type category."""

    kind: str
    value: int | None
    observation: DiscoveryObservationInput


@dataclass(frozen=True, slots=True)
class DiscoveryDeviceTypeInput:
    """One unknown safe numeric devType/subType pair."""

    dev_type: int
    sub_type: int
    observation: DiscoveryObservationInput


@dataclass(frozen=True, slots=True)
class DiscoveryStructureInput:
    """One value-free structural signature at a fixed path."""

    path: str
    unknown_field_count: int
    unknown_value_types: Mapping[str, Any]
    nested_shapes: Sequence[str]
    type_mismatches: Sequence[tuple[str, str]]
    observation: DiscoveryObservationInput


@dataclass(frozen=True, slots=True)
class ProtocolDiscoveryDiagnosticsInput:
    """Explicit P3.1 input for the optional discovery contract."""

    version: int = 1
    unknown_message_types: Sequence[DiscoveryMessageTypeInput] = ()
    unknown_device_types: Sequence[DiscoveryDeviceTypeInput] = ()
    structures: Sequence[DiscoveryStructureInput] = ()
    message_type_overflow: int = 0
    device_type_overflow: int = 0
    structural_overflow: int = 0
    traversal_dropped: int = 0


@dataclass(frozen=True, slots=True)
class ProtocolDiagnosticsInput:
    """Explicit semantic protocol facts, not a raw protocol cache."""

    semantic_measurements: Mapping[str, Any] = field(default_factory=dict)
    known_field_count: int | None = None
    unknown_field_count: int | None = None
    invalid_value_count: int | None = None
    child_container_counts: Mapping[str, Any] = field(default_factory=dict)
    type106_evidence: Sequence[Type106EvidenceInput] = ()
    grid_source: EnergySourceDiagnosticsInput | None = None
    route_counters: Mapping[str, Any] = field(default_factory=dict)
    error_counters: Mapping[str, Any] = field(default_factory=dict)
    unknown_message_count: int | None = None
    discovery_enabled: bool = False
    discovery: ProtocolDiscoveryDiagnosticsInput | None = None


@dataclass(frozen=True, slots=True)
class ChildFreshnessDiagnosticsInput:
    """One child freshness decision supplied by its state owner."""

    identifier: str
    activity_at: float | None = None
    available: bool | None = None
    missing_since: float | None = None
    retention_policy: str = "unknown"


@dataclass(frozen=True, slots=True)
class FreshnessDiagnosticsInput:
    """Host and child communication freshness facts."""

    runtime_started_at: float | None = None
    host_activity_at: float | None = None
    host_ever_received: bool = False
    host_stale: bool | None = None
    children: Sequence[ChildFreshnessDiagnosticsInput] = ()


@dataclass(frozen=True, slots=True)
class ChildDiagnosticsInput:
    """Allowlisted semantic summary for one child identity."""

    identifier: str
    family: str = "unknown"
    model: str = "unknown"
    device_type: int | None = None
    sub_type: int | None = None
    cache_containers: Sequence[str] = ()
    known: bool = False
    expansion_battery: bool = False
    communication_mode: int | None = None
    communication_state: int | None = None
    has_power_measurement: bool | None = None
    has_energy_measurement: bool | None = None


@dataclass(frozen=True, slots=True)
class SmartMeterDiagnosticsInput:
    """SmartMeter membership and configuration facts available before P3.2."""

    mqtt_identifiers: Sequence[str] = ()
    http_enabled: bool = False
    target_identifier: str | None = None
    created_http_identifiers: Sequence[str] = ()
    poll_interval_seconds: int | None = None
    request_timeout_seconds: int | None = None
    failure_threshold: int | None = 3
    last_attempt_at: float | None = None
    last_success_at: float | None = None
    consecutive_failures: int | None = None
    last_outcome: str = "unknown"
    source_replacement_state: str = "unknown"
    health: str = "unknown"


@dataclass(frozen=True, slots=True)
class EntityDiagnosticsInput:
    """Pre-aggregated HA facts for the future thin adapter."""

    registry_total: int | None = None
    by_platform: Mapping[str, Any] = field(default_factory=dict)
    disabled_count: int | None = None
    state_counts: Mapping[str, Any] = field(default_factory=dict)
    device_counts: Mapping[str, Any] = field(default_factory=dict)
    runtime_listener_counts: Mapping[str, Any] = field(default_factory=dict)
    mismatch_count: int | None = None


@dataclass(frozen=True, slots=True)
class HealthDiagnosticsInput:
    """Health facts not derivable from another snapshot section."""

    runtime_available: bool | None = None
    reauth_requested: bool = False
    migration_block_all: bool = False
    migration_blocked_child_count: int | None = None
    migration_conflict_categories: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DiagnosticsSnapshotInput:
    """Complete explicit input to :func:`build_diagnostics_snapshot`."""

    integration: IntegrationDiagnosticsInput = field(
        default_factory=IntegrationDiagnosticsInput
    )
    host: HostDiagnosticsInput = field(default_factory=HostDiagnosticsInput)
    transport: TransportDiagnosticsInput = field(
        default_factory=TransportDiagnosticsInput
    )
    protocol: ProtocolDiagnosticsInput = field(
        default_factory=ProtocolDiagnosticsInput
    )
    freshness: FreshnessDiagnosticsInput = field(
        default_factory=FreshnessDiagnosticsInput
    )
    children: Sequence[ChildDiagnosticsInput] = ()
    smartmeter: SmartMeterDiagnosticsInput = field(
        default_factory=SmartMeterDiagnosticsInput
    )
    entities: EntityDiagnosticsInput = field(
        default_factory=EntityDiagnosticsInput
    )
    health: HealthDiagnosticsInput = field(default_factory=HealthDiagnosticsInput)


class TruncationSection(TypedDict):
    """Deterministic snapshot truncation metadata."""

    size_limit_bytes: int
    children_total: int
    children_included: int
    children_omitted: int
    protocol_observations_omitted: int
    entity_detail_omitted: bool


class IntegrationSection(TypedDict):
    """Integration section of the diagnostics contract."""

    schema_version: int
    manifest_version: str | None
    home_assistant_version: str | None
    python_version: str | None
    entry_state: str
    identity_mode: str
    configuration: dict[str, bool | int | None]
    truncation: TruncationSection


class HostSection(TypedDict):
    """Host section of the diagnostics contract."""

    alias: str
    identity_mode: str
    device_type: int | None
    model: str
    firmware: str | None
    firmware_valid: bool | None
    cache_initialized: bool
    observed_capabilities: list[str]


class TransportSection(TypedDict):
    """Transport section of the diagnostics contract."""

    mqtt: dict[str, str | int | bool | None]
    http: dict[str, str | int | None]
    consistency: dict[str, bool | None]


class ProtocolSection(TypedDict):
    """Protocol section of the diagnostics contract."""

    measurements: dict[str, float]
    cache: dict[str, int | None | dict[str, int | None]]
    type106_evidence: list[dict[str, str | int | float | bool | None]]
    energy_sources: dict[str, dict[str, str | int | float | None]]
    observation: dict[str, dict[str, int] | int | None]
    discovery_enabled: bool
    discovery: NotRequired[dict[str, Any]]


class FreshnessSection(TypedDict):
    """Freshness section of the diagnostics contract."""

    host: dict[str, bool | float | None]
    children: list[dict[str, str | bool | float | None]]


class ChildrenSection(TypedDict):
    """Children section of the diagnostics contract."""

    total: int
    included: int
    omitted: int
    items: list[dict[str, Any]]


class SmartMeterSection(TypedDict):
    """SmartMeter section of the diagnostics contract."""

    mqtt: dict[str, int | list[str]]
    http: dict[str, Any]


class EntitiesSection(TypedDict):
    """Entities section of the diagnostics contract."""

    registry_total: int | None
    by_platform: dict[str, int | None]
    disabled_count: int | None
    state_counts: dict[str, int | None]
    device_counts: dict[str, int | None]
    runtime_listener_counts: dict[str, int | None]
    mismatch_count: int | None


class HealthSection(TypedDict):
    """Health section of the diagnostics contract."""

    status: str
    reasons: list[str]
    reauth_requested: bool
    migration: dict[str, bool | int | None | dict[str, int]]


class DiagnosticsSnapshot(TypedDict):
    """Versioned, JSON-compatible diagnostics snapshot."""

    integration: IntegrationSection
    host: HostSection
    transport: TransportSection
    protocol: ProtocolSection
    freshness: FreshnessSection
    children: ChildrenSection
    smartmeter: SmartMeterSection
    entities: EntitiesSection
    health: HealthSection


def _closed_string(value: Any, allowed: frozenset[str], default: str) -> str:
    return value if isinstance(value, str) and value in allowed else default


def _version_token(value: Any) -> str | None:
    if not isinstance(value, str) or _VERSION_TOKEN.fullmatch(value) is None:
        return None
    return value


def _firmware(value: Any) -> tuple[str | None, bool | None]:
    if value is None:
        return None, None
    token = _version_token(value)
    return (token, True) if token is not None else (None, False)


def _optional_count(value: Any) -> int | None:
    if type(value) is not int or value < 0:  # bool is intentionally rejected
        return None
    return min(value, 2_147_483_647)


def _optional_small_int(value: Any) -> int | None:
    if type(value) is not int or not 0 <= value <= 65_535:
        return None
    return value


def _optional_interval(value: Any) -> int | None:
    if type(value) is not int or not 1 <= value <= 86_400:
        return None
    return value


def _finite_number(value: Any) -> float | None:
    if type(value) not in (int, float):  # bool is intentionally rejected
        return None
    try:
        result = float(value)
    except OverflowError:
        return None
    return result if math.isfinite(result) else None


def _nonnegative_number(value: Any) -> float | None:
    result = _finite_number(value)
    if result is None or result < 0:
        return None
    return round(result, 3)


def _age(now: float, timestamp: Any) -> float | None:
    value = _finite_number(timestamp)
    if value is None:
        return None
    return round(max(0.0, now - value), 3)


def _valid_identifier(value: Any) -> str | None:
    if not isinstance(value, str) or not value or len(value) > 256:
        return None
    return value


def _identity_mode(inputs: DiagnosticsSnapshotInput) -> str:
    if inputs.integration.host_configured:
        return "configured"
    if _valid_identifier(inputs.host.identifier) is not None:
        return "adopted"
    return "unknown"


def _alias_map(inputs: DiagnosticsSnapshotInput) -> dict[str, str]:
    identities: set[str] = set()
    host_identifier = _valid_identifier(inputs.host.identifier)

    for child_summary in inputs.children:
        if (identifier := _valid_identifier(child_summary.identifier)) is not None:
            identities.add(identifier)
    for child_freshness in inputs.freshness.children:
        if (identifier := _valid_identifier(child_freshness.identifier)) is not None:
            identities.add(identifier)
    for raw_identifier in inputs.smartmeter.mqtt_identifiers:
        if (identifier := _valid_identifier(raw_identifier)) is not None:
            identities.add(identifier)
    for raw_identifier in inputs.smartmeter.created_http_identifiers:
        if (identifier := _valid_identifier(raw_identifier)) is not None:
            identities.add(identifier)
    if (
        identifier := _valid_identifier(inputs.smartmeter.target_identifier)
    ) is not None:
        identities.add(identifier)

    if host_identifier is not None:
        identities.discard(host_identifier)
    return {
        identifier: f"child_{index:03d}"
        for index, identifier in enumerate(sorted(identities), start=1)
    }


def _integration_section(
    inputs: DiagnosticsSnapshotInput,
    *,
    identity_mode: str,
    child_total: int,
    child_included: int,
    entity_detail_omitted: bool,
    protocol_observations_omitted: int = 0,
) -> IntegrationSection:
    source = inputs.integration
    return {
        "schema_version": DIAGNOSTICS_SCHEMA_VERSION,
        "manifest_version": _version_token(source.manifest_version),
        "home_assistant_version": _version_token(source.home_assistant_version),
        "python_version": _version_token(source.python_version),
        "entry_state": _closed_string(source.entry_state, _ENTRY_STATES, "unknown"),
        "identity_mode": identity_mode,
        "configuration": {
            "host_configured": source.host_configured is True,
            "token_configured": source.token_configured is True,
            "custom_topic_configured": source.custom_topic_configured is True,
            "legacy_mqtt_host_configured": (
                source.legacy_mqtt_host_configured is True
            ),
            "http_enabled": source.http_enabled is True,
            "http_poll_interval_seconds": _optional_interval(
                source.http_poll_interval_seconds
            ),
        },
        "truncation": {
            "size_limit_bytes": MAX_SNAPSHOT_BYTES,
            "children_total": child_total,
            "children_included": child_included,
            "children_omitted": child_total - child_included,
            "protocol_observations_omitted": protocol_observations_omitted,
            "entity_detail_omitted": entity_detail_omitted,
        },
    }


def _semantic_measurements(source: Mapping[str, Any]) -> dict[str, float]:
    result: dict[str, float] = {}
    for key in sorted(_SEMANTIC_MEASUREMENTS):
        if (value := _finite_number(source.get(key))) is not None:
            result[key] = value
    return result


def _observed_capabilities(measurements: Mapping[str, float]) -> list[str]:
    capabilities: set[str] = set()
    if "solar_power" in measurements:
        capabilities.add("solar_power")
    if any(
        key in measurements
        for key in (
            "battery_net_power",
            "main_battery_charge_power",
            "main_battery_discharge_power",
        )
    ):
        capabilities.add("battery_power")
    if any(key.startswith("grid_") for key in measurements):
        capabilities.add("grid_power")
    if "eps_input_power" in measurements or "eps_output_power" in measurements:
        capabilities.add("eps_power")
    return sorted(capabilities)


def _host_section(
    inputs: DiagnosticsSnapshotInput,
    *,
    identity_mode: str,
    measurements: Mapping[str, float],
) -> HostSection:
    source = inputs.host
    firmware, firmware_valid = _firmware(source.firmware)
    return {
        "alias": "host",
        "identity_mode": identity_mode,
        "device_type": _optional_small_int(source.device_type),
        "model": _closed_string(source.model, _HOST_MODELS, "unknown"),
        "firmware": firmware,
        "firmware_valid": firmware_valid,
        "cache_initialized": source.cache_initialized is True,
        "observed_capabilities": _observed_capabilities(measurements),
    }


def _transport_section(inputs: DiagnosticsSnapshotInput) -> TransportSection:
    source = inputs.transport
    lifecycle = _closed_string(
        source.mqtt_application_state, _APPLICATION_STATES, "unknown"
    )
    subscriptions = _optional_count(source.mqtt_owned_subscriptions)
    inconsistent = (
        lifecycle == "running" and subscriptions == 0
        if subscriptions is not None
        else None
    )
    return {
        "mqtt": {
            "application_state": lifecycle,
            "broker_connectivity": "unknown",
            "owned_subscriptions": subscriptions,
            "poll_task": _closed_string(
                source.mqtt_poll_task_state, _TASK_STATES, "unknown"
            ),
            "subscription_qos": 1,
            "publish_qos": 0,
            "publish_retain": False,
            "topic_shape": "{prefix}/device/{host}/status|event",
            "poll_interval_seconds": _optional_interval(
                source.poll_interval_seconds
            ),
        },
        "http": {
            "task": _closed_string(
                source.http_task_state, _TASK_STATES, "unknown"
            ),
            "request_timeout_seconds": _optional_interval(
                source.http_request_timeout_seconds
            ),
        },
        "consistency": {
            "running_without_owned_subscriptions": inconsistent,
        },
    }


def _type106_evidence(
    entries: Sequence[Type106EvidenceInput], now: float
) -> list[dict[str, str | int | float | bool | None]]:
    candidates: list[dict[str, str | int | float | bool | None]] = []
    for entry in entries:
        if entry.field not in _TYPE106_FIELDS:
            continue
        live_age = _age(now, entry.live_seen_at)
        snapshot_age = _age(now, entry.snapshot_seen_at)
        candidates.append(
            {
                "field": entry.field,
                "live_present": live_age is not None,
                "live_message_type": _optional_small_int(entry.live_message_type),
                "live_age_seconds": live_age,
                "snapshot_present": snapshot_age is not None,
                "snapshot_age_seconds": snapshot_age,
            }
        )

    candidates.sort(key=lambda item: json.dumps(item, sort_keys=True))
    by_field: dict[str, dict[str, str | int | float | bool | None]] = {}
    for item in candidates:
        by_field.setdefault(str(item["field"]), item)
    return [by_field[key] for key in sorted(by_field)]


def _energy_source(
    source: EnergySourceDiagnosticsInput | None,
) -> dict[str, str | int | float | None]:
    if source is None:
        return {
            "source": "unknown",
            "activity_age_seconds": None,
            "skipped_stale": None,
            "skipped_missing": None,
            "reason": "unknown",
        }
    return {
        "source": _closed_string(source.source, _GRID_SOURCES, "unknown"),
        "activity_age_seconds": _nonnegative_number(source.activity_age_seconds),
        "skipped_stale": _optional_count(source.skipped_stale),
        "skipped_missing": _optional_count(source.skipped_missing),
        "reason": _SOURCE_REASONS.get(source.reason, "unknown"),
    }


def _fixed_count_map(
    source: Mapping[str, Any], keys: Sequence[str]
) -> dict[str, int | None]:
    return {key: _optional_count(source.get(key)) for key in keys}


def _protocol_section(
    inputs: DiagnosticsSnapshotInput,
    *,
    now: float,
    measurements: dict[str, float],
) -> ProtocolSection:
    source = inputs.protocol
    result: ProtocolSection = {
        "measurements": measurements,
        "cache": {
            "known_field_count": _optional_count(source.known_field_count),
            "unknown_field_count": _optional_count(source.unknown_field_count),
            "invalid_value_count": _optional_count(source.invalid_value_count),
            "child_container_counts": _fixed_count_map(
                source.child_container_counts, _CHILD_CONTAINER_COUNTS
            ),
        },
        "type106_evidence": _type106_evidence(source.type106_evidence, now),
        "energy_sources": {"grid": _energy_source(source.grid_source)},
        "observation": {
            "route_counters": {
                key: count
                for key in _PROTOCOL_ROUTE_COUNTERS
                if (count := _optional_count(source.route_counters.get(key)))
                is not None
                and count > 0
            },
            "error_counters": {
                key: count
                for key in _PROTOCOL_ERROR_COUNTERS
                if (count := _optional_count(source.error_counters.get(key)))
                is not None
                and count > 0
            },
            "unknown_message_count": _optional_count(
                source.unknown_message_count
            ),
        },
        "discovery_enabled": source.discovery_enabled is True,
    }
    if source.discovery_enabled is True:
        result["discovery"] = _discovery_section(source.discovery, now=now)
    return result


def _discovery_observation(
    source: DiscoveryObservationInput,
    *,
    now: float,
) -> dict[str, int | float | None]:
    return {
        "count": _optional_count(source.count) or 0,
        "first_seen_age_seconds": _age(now, source.first_seen_at),
        "last_seen_age_seconds": _age(now, source.last_seen_at),
    }


def _discovery_section(
    source: ProtocolDiscoveryDiagnosticsInput | None,
    *,
    now: float,
) -> dict[str, Any]:
    message_types: list[dict[str, Any]] = []
    device_types: list[dict[str, Any]] = []
    structures: list[dict[str, Any]] = []

    if source is not None:
        for message_item in source.unknown_message_types:
            kind = _closed_string(message_item.kind, _DISCOVERY_TYPES, "unknown")
            if kind == "unknown":
                continue
            value = (
                message_item.value
                if kind == "integer"
                and isinstance(message_item.value, int)
                and not isinstance(message_item.value, bool)
                and 0 <= message_item.value <= MAX_SAFE_PROTOCOL_INTEGER
                else None
            )
            message_types.append(
                {
                    "kind": kind,
                    "value": value,
                    **_discovery_observation(message_item.observation, now=now),
                }
            )

        for device_item in source.unknown_device_types:
            if not (
                isinstance(device_item.dev_type, int)
                and not isinstance(device_item.dev_type, bool)
                and 0 <= device_item.dev_type <= MAX_SAFE_PROTOCOL_INTEGER
                and isinstance(device_item.sub_type, int)
                and not isinstance(device_item.sub_type, bool)
                and 0 <= device_item.sub_type <= MAX_SAFE_PROTOCOL_INTEGER
            ):
                continue
            device_types.append(
                {
                    "dev_type": device_item.dev_type,
                    "sub_type": device_item.sub_type,
                    **_discovery_observation(device_item.observation, now=now),
                }
            )

        for structure_item in source.structures:
            if structure_item.path not in _DISCOVERY_PATHS:
                continue
            shapes = sorted(
                {
                    shape
                    for shape in structure_item.nested_shapes
                    if isinstance(shape, str) and _DISCOVERY_SHAPE.fullmatch(shape)
                }
            )[:16]
            mismatches = [
                {"field": field, "observed_type": observed}
                for field, observed in sorted(set(structure_item.type_mismatches))
                if field in _DISCOVERY_FIELDS and observed in _DISCOVERY_TYPES
            ]
            structures.append(
                {
                    "path": structure_item.path,
                    "unknown_field_count": _optional_count(
                        structure_item.unknown_field_count
                    )
                    or 0,
                    "unknown_value_types": {
                        kind: count
                        for kind in sorted(_DISCOVERY_TYPES)
                        if (
                            count := _optional_count(
                                structure_item.unknown_value_types.get(kind)
                            )
                        )
                        is not None
                        and count > 0
                    },
                    "nested_shapes": shapes,
                    "type_mismatches": mismatches,
                    **_discovery_observation(structure_item.observation, now=now),
                }
            )

    message_types.sort(key=lambda item: json.dumps(item, sort_keys=True))
    device_types.sort(key=lambda item: json.dumps(item, sort_keys=True))
    structures.sort(key=lambda item: json.dumps(item, sort_keys=True))
    result: dict[str, Any] = {
        "version": 1,
        "limits": {
            "detail_budget_bytes": DISCOVERY_DETAIL_BUDGET_BYTES,
            "message_type_buckets": MAX_DISCOVERY_MESSAGE_TYPES,
            "device_type_buckets": MAX_DISCOVERY_DEVICE_TYPES,
            "structural_signatures": MAX_DISCOVERY_STRUCTURES,
            "mapping_entries": MAX_DISCOVERY_MAPPING_ENTRIES,
            "array_items": MAX_DISCOVERY_ARRAY_ITEMS,
            "structural_depth": MAX_DISCOVERY_DEPTH,
        },
        "unknown_message_types": {
            "items": message_types,
            "overflow_count": _optional_count(
                source.message_type_overflow if source is not None else 0
            )
            or 0,
        },
        "unknown_device_types": {
            "items": device_types,
            "overflow_count": _optional_count(
                source.device_type_overflow if source is not None else 0
            )
            or 0,
        },
        "structures": {
            "items": structures,
            "overflow_count": _optional_count(
                source.structural_overflow if source is not None else 0
            )
            or 0,
            "traversal_dropped": _optional_count(
                source.traversal_dropped if source is not None else 0
            )
            or 0,
        },
        "omitted_records": 0,
    }
    while _serialized_size(result) > DISCOVERY_DETAIL_BUDGET_BYTES:
        if not _remove_discovery_record(result):
            break
    return result


def _remove_discovery_record(discovery: dict[str, Any]) -> bool:
    """Drop the lowest-priority discovery detail deterministically."""
    for section in ("structures", "unknown_device_types", "unknown_message_types"):
        items = discovery[section]["items"]
        if items:
            items.pop()
            discovery["omitted_records"] += 1
            return True
    return False


def _freshness_reason(
    available: bool | None,
    activity_age: float | None,
    retention_policy: str,
) -> str:
    if available is None:
        return "unknown"
    if available:
        return (
            "retained_after_first_seen"
            if retention_policy == "retain_after_first_seen"
            else "fresh"
        )
    return "never_seen" if activity_age is None else "stale"


def _freshness_section(
    inputs: DiagnosticsSnapshotInput,
    *,
    now: float,
    aliases: Mapping[str, str],
    included_aliases: set[str],
) -> FreshnessSection:
    source = inputs.freshness
    candidates: list[dict[str, str | bool | float | None]] = []
    for child in source.children:
        identifier = _valid_identifier(child.identifier)
        alias = aliases.get(identifier) if identifier is not None else None
        if alias is None or alias not in included_aliases:
            continue
        retention = _closed_string(
            child.retention_policy, _RETENTION_POLICIES, "unknown"
        )
        activity_age = _age(now, child.activity_at)
        missing_age = _age(now, child.missing_since)
        available = child.available if isinstance(child.available, bool) else None
        candidates.append(
            {
                "alias": alias,
                "activity_age_seconds": activity_age,
                "available": available,
                "reason": _freshness_reason(available, activity_age, retention),
                "missing": missing_age is not None,
                "missing_age_seconds": missing_age,
                "retention_policy": retention,
            }
        )

    candidates.sort(key=lambda item: json.dumps(item, sort_keys=True))
    by_alias: dict[str, dict[str, str | bool | float | None]] = {}
    for item in candidates:
        by_alias.setdefault(str(item["alias"]), item)
    return {
        "host": {
            "runtime_age_seconds": _age(now, source.runtime_started_at),
            "activity_age_seconds": _age(now, source.host_activity_at),
            "ever_received": source.host_ever_received is True,
            "stale": source.host_stale
            if isinstance(source.host_stale, bool)
            else None,
        },
        "children": [by_alias[key] for key in sorted(by_alias)],
    }


def _child_item(
    child: ChildDiagnosticsInput, alias: str
) -> dict[str, Any]:
    return {
        "alias": alias,
        "family": _closed_string(child.family, _CHILD_FAMILIES, "unknown"),
        "model": _closed_string(child.model, _CHILD_MODELS, "unknown"),
        "device_type": _optional_small_int(child.device_type),
        "sub_type": _optional_small_int(child.sub_type),
        "cache_containers": sorted(
            {
                container
                for container in child.cache_containers
                if isinstance(container, str) and container in _CACHE_CONTAINERS
            }
        ),
        "known": child.known is True,
        "expansion_battery": child.expansion_battery is True,
        "communication_mode": _optional_small_int(child.communication_mode),
        "communication_state": _optional_small_int(child.communication_state),
        "has_power_measurement": child.has_power_measurement
        if isinstance(child.has_power_measurement, bool)
        else None,
        "has_energy_measurement": child.has_energy_measurement
        if isinstance(child.has_energy_measurement, bool)
        else None,
    }


def _children_section(
    inputs: DiagnosticsSnapshotInput,
    *,
    aliases: Mapping[str, str],
    included_aliases: set[str],
) -> ChildrenSection:
    candidates: list[dict[str, Any]] = []
    for child in inputs.children:
        identifier = _valid_identifier(child.identifier)
        alias = aliases.get(identifier) if identifier is not None else None
        if alias is not None and alias in included_aliases:
            candidates.append(_child_item(child, alias))

    candidates.sort(key=lambda item: json.dumps(item, sort_keys=True))
    by_alias: dict[str, dict[str, Any]] = {}
    for item in candidates:
        by_alias.setdefault(str(item["alias"]), item)
    total = len(aliases)
    included = len(included_aliases)
    return {
        "total": total,
        "included": included,
        "omitted": total - included,
        "items": [by_alias[key] for key in sorted(by_alias)],
    }


def _aliases_for(
    identifiers: Sequence[str],
    aliases: Mapping[str, str],
    included_aliases: set[str],
) -> tuple[list[str], int]:
    all_aliases = {
        alias
        for raw_identifier in identifiers
        if (identifier := _valid_identifier(raw_identifier)) is not None
        and (alias := aliases.get(identifier)) is not None
    }
    return sorted(all_aliases.intersection(included_aliases)), len(all_aliases)


def _smartmeter_section(
    inputs: DiagnosticsSnapshotInput,
    *,
    now: float,
    aliases: Mapping[str, str],
    included_aliases: set[str],
) -> SmartMeterSection:
    source = inputs.smartmeter
    mqtt_aliases, mqtt_count = _aliases_for(
        source.mqtt_identifiers, aliases, included_aliases
    )
    created_aliases, created_count = _aliases_for(
        source.created_http_identifiers, aliases, included_aliases
    )
    target_identifier = _valid_identifier(source.target_identifier)
    target_alias = aliases.get(target_identifier) if target_identifier else None
    if target_alias not in included_aliases:
        target_alias = None
    enabled = source.http_enabled is True
    return {
        "mqtt": {
            "count": mqtt_count,
            "aliases": mqtt_aliases,
        },
        "http": {
            "enabled": enabled,
            "task": _closed_string(
                inputs.transport.http_task_state, _TASK_STATES, "unknown"
            ),
            "target_alias": target_alias,
            "target_discovered": target_identifier is not None,
            "created_count": created_count,
            "created_aliases": created_aliases,
            "poll_interval_seconds": _optional_interval(
                source.poll_interval_seconds
            ),
            "request_timeout_seconds": _optional_interval(
                source.request_timeout_seconds
            ),
            "failure_threshold": _optional_count(source.failure_threshold),
            "last_attempt_age_seconds": _age(now, source.last_attempt_at),
            "last_success_age_seconds": _age(now, source.last_success_at),
            "consecutive_failures": _optional_count(
                source.consecutive_failures
            ),
            "last_outcome": _closed_string(
                source.last_outcome,
                _HTTP_OUTCOMES,
                "unknown",
            ),
            "source_replacement_state": _closed_string(
                source.source_replacement_state,
                _HTTP_REPLACEMENT_STATES,
                "unknown",
            ),
            "health": "disabled"
            if not enabled
            else _closed_string(
                source.health,
                _HTTP_HEALTH_STATES,
                "unknown",
            ),
        },
    }


def _entities_section(
    inputs: DiagnosticsSnapshotInput, *, omit_detail: bool
) -> EntitiesSection:
    source = inputs.entities
    return {
        "registry_total": _optional_count(source.registry_total),
        "by_platform": {}
        if omit_detail
        else _fixed_count_map(source.by_platform, _PLATFORMS),
        "disabled_count": _optional_count(source.disabled_count),
        "state_counts": _fixed_count_map(source.state_counts, _ENTITY_STATES),
        "device_counts": _fixed_count_map(source.device_counts, _DEVICE_ROLES),
        "runtime_listener_counts": {}
        if omit_detail
        else _fixed_count_map(source.runtime_listener_counts, _LISTENER_KINDS),
        "mismatch_count": _optional_count(source.mismatch_count),
    }


def _health_section(
    inputs: DiagnosticsSnapshotInput,
    *,
    transport: TransportSection,
    freshness: FreshnessSection,
) -> HealthSection:
    source = inputs.health
    conflict_categories = {
        category: count
        for category in sorted(_MIGRATION_CATEGORIES)
        if (count := _optional_count(source.migration_conflict_categories.get(category)))
        is not None
        and count > 0
    }

    reasons: set[str] = set()
    runtime_available = (
        source.runtime_available
        if isinstance(source.runtime_available, bool)
        else None
    )
    host_stale = freshness["host"]["stale"]
    if runtime_available is False:
        reasons.add("runtime_unavailable")
    if host_stale is True:
        reasons.add("host_stale")
    if source.reauth_requested is True:
        reasons.add("reauth_requested")
    if transport["consistency"]["running_without_owned_subscriptions"] is True:
        reasons.add("mqtt_subscription_inconsistent")
    blocked_count = _optional_count(source.migration_blocked_child_count)
    if source.migration_block_all is True or (blocked_count or 0) > 0:
        reasons.add("identity_migration_blocked")

    if runtime_available is False or host_stale is True:
        status = "unavailable"
    elif reasons:
        status = "degraded"
    elif runtime_available is True and host_stale is False:
        status = "ok"
    else:
        status = "unknown"

    return {
        "status": status,
        "reasons": sorted(reasons),
        "reauth_requested": source.reauth_requested is True,
        "migration": {
            "block_all": source.migration_block_all is True,
            "blocked_child_count": blocked_count,
            "conflict_categories": conflict_categories,
        },
    }


def _serialized_size(snapshot: Any) -> int:
    return len(
        json.dumps(
            snapshot,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )


def _remove_alias(snapshot: DiagnosticsSnapshot, alias: str) -> None:
    snapshot["freshness"]["children"] = [
        item
        for item in snapshot["freshness"]["children"]
        if item["alias"] != alias
    ]
    snapshot["children"]["items"] = [
        item for item in snapshot["children"]["items"] if item["alias"] != alias
    ]
    for key in ("mqtt",):
        aliases = snapshot["smartmeter"][key]["aliases"]
        assert isinstance(aliases, list)
        snapshot["smartmeter"][key]["aliases"] = [
            item for item in aliases if item != alias
        ]
    created_aliases = snapshot["smartmeter"]["http"]["created_aliases"]
    assert isinstance(created_aliases, list)
    snapshot["smartmeter"]["http"]["created_aliases"] = [
        item for item in created_aliases if item != alias
    ]
    if snapshot["smartmeter"]["http"]["target_alias"] == alias:
        snapshot["smartmeter"]["http"]["target_alias"] = None

    snapshot["children"]["included"] -= 1
    snapshot["children"]["omitted"] += 1
    truncation = snapshot["integration"]["truncation"]
    truncation["children_included"] -= 1
    truncation["children_omitted"] += 1


def build_diagnostics_snapshot(
    inputs: DiagnosticsSnapshotInput, *, now: float
) -> DiagnosticsSnapshot:
    """Build a deterministic, bounded diagnostics snapshot without side effects."""
    snapshot_now = _finite_number(now)
    if snapshot_now is None:
        raise ValueError("now must be a finite number")

    aliases = _alias_map(inputs)
    ordered_aliases = [aliases[identifier] for identifier in sorted(aliases)]
    included_alias_list = ordered_aliases[:MAX_CHILDREN]
    included_aliases = set(included_alias_list)
    identity_mode = _identity_mode(inputs)
    measurements = _semantic_measurements(inputs.protocol.semantic_measurements)
    transport = _transport_section(inputs)
    protocol = _protocol_section(
        inputs, now=snapshot_now, measurements=measurements
    )
    discovery = protocol.get("discovery")
    protocol_observations_omitted = (
        discovery["omitted_records"] if discovery is not None else 0
    )
    freshness = _freshness_section(
        inputs,
        now=snapshot_now,
        aliases=aliases,
        included_aliases=included_aliases,
    )

    snapshot: DiagnosticsSnapshot = {
        "integration": _integration_section(
            inputs,
            identity_mode=identity_mode,
            child_total=len(aliases),
            child_included=len(included_aliases),
            entity_detail_omitted=False,
            protocol_observations_omitted=protocol_observations_omitted,
        ),
        "host": _host_section(
            inputs, identity_mode=identity_mode, measurements=measurements
        ),
        "transport": transport,
        "protocol": protocol,
        "freshness": freshness,
        "children": _children_section(
            inputs,
            aliases=aliases,
            included_aliases=included_aliases,
        ),
        "smartmeter": _smartmeter_section(
            inputs,
            now=snapshot_now,
            aliases=aliases,
            included_aliases=included_aliases,
        ),
        "entities": _entities_section(inputs, omit_detail=False),
        "health": _health_section(
            inputs, transport=transport, freshness=freshness
        ),
    }

    while _serialized_size(snapshot) > MAX_SNAPSHOT_BYTES:
        current_discovery = snapshot["protocol"].get("discovery")
        if current_discovery is None or not _remove_discovery_record(
            current_discovery
        ):
            break
        snapshot["integration"]["truncation"][
            "protocol_observations_omitted"
        ] += 1

    while _serialized_size(snapshot) > MAX_SNAPSHOT_BYTES and included_alias_list:
        _remove_alias(snapshot, included_alias_list.pop())

    if _serialized_size(snapshot) > MAX_SNAPSHOT_BYTES:
        snapshot["entities"] = _entities_section(inputs, omit_detail=True)
        snapshot["integration"]["truncation"]["entity_detail_omitted"] = True

    if _serialized_size(snapshot) > MAX_SNAPSHOT_BYTES:
        raise ValueError("diagnostics contract exceeds the fixed size budget")
    return snapshot


__all__ = [
    "DIAGNOSTICS_SCHEMA_VERSION",
    "MAX_CHILDREN",
    "MAX_SNAPSHOT_BYTES",
    "TOP_LEVEL_SECTIONS",
    "ChildDiagnosticsInput",
    "ChildFreshnessDiagnosticsInput",
    "DiagnosticsSnapshot",
    "DiagnosticsSnapshotInput",
    "DiscoveryDeviceTypeInput",
    "DiscoveryMessageTypeInput",
    "DiscoveryObservationInput",
    "DiscoveryStructureInput",
    "EnergySourceDiagnosticsInput",
    "EntityDiagnosticsInput",
    "FreshnessDiagnosticsInput",
    "HealthDiagnosticsInput",
    "HostDiagnosticsInput",
    "IntegrationDiagnosticsInput",
    "ProtocolDiagnosticsInput",
    "ProtocolDiscoveryDiagnosticsInput",
    "SmartMeterDiagnosticsInput",
    "TransportDiagnosticsInput",
    "Type106EvidenceInput",
    "build_diagnostics_snapshot",
]
