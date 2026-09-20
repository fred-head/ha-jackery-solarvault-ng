"""Read-only Home Assistant owner aggregation for Jackery diagnostics."""

from __future__ import annotations

import asyncio
import math
import platform
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from . import DOMAIN
from .devices.classification import (
    ClassificationContext,
    DeviceFamily,
    classify_device,
)
from .diagnostics_snapshot import (
    ChildDiagnosticsInput,
    ChildFreshnessDiagnosticsInput,
    DiagnosticsSnapshotInput,
    DiscoveryDeviceTypeInput,
    DiscoveryMessageTypeInput,
    DiscoveryObservationInput,
    DiscoveryStructureInput,
    EnergySourceDiagnosticsInput,
    EntityDiagnosticsInput,
    FreshnessDiagnosticsInput,
    HealthDiagnosticsInput,
    HostDiagnosticsInput,
    IntegrationDiagnosticsInput,
    ProtocolDiagnosticsInput,
    ProtocolDiscoveryDiagnosticsInput,
    SmartMeterDiagnosticsInput,
    TransportDiagnosticsInput,
    Type106EvidenceInput,
)
from .entities.sensor_definitions import SENSORS
from .identity import parse_child_device_identifier
from .protocol.routing import subdevice_serial
from .protocol_discovery import OPTION_PROTOCOL_DISCOVERY_ENABLED
from .sensor import (
    HTTP_FAILURE_THRESHOLD,
    OFFLINE_TIMEOUT,
    REQUEST_INTERVAL,
    JackeryDataCoordinator,
)

_HTTP_REQUEST_TIMEOUT_SECONDS = 5
_DEFAULT_HTTP_POLL_INTERVAL = 10
_DEFAULT_TOPIC_PREFIX = "hb"

_CHILD_CONTAINERS: tuple[
    tuple[str, ClassificationContext], ...
] = (
    ("plugs", ClassificationContext.PLUG_ARRAY),
    ("cts", ClassificationContext.CT_ARRAY),
    ("collectors", ClassificationContext.COLLECTOR_ARRAY),
)

_SEMANTIC_CACHE_FIELDS = {
    "battery_net_power": "calc_batt_net_power",
    "eps_input_power": "swEpsInPw",
    "eps_output_power": "swEpsOutPw",
    "grid_export_power": "gridOutPw",
    "grid_import_power": "gridInPw",
    "grid_net_power": "calc_grid_net_power",
    "home_power": "calc_home_power",
    "main_battery_charge_power": "batInPw",
    "main_battery_discharge_power": "batOutPw",
    "solar_power": "pvPw",
}

_TYPE106_FIELDS = {
    "batInPw": "main_battery_charge_power",
    "batOutPw": "main_battery_discharge_power",
    "pvPw": "solar_power",
    "pv1": "solar_input_1_power",
    "pv2": "solar_input_2_power",
    "pv3": "solar_input_3_power",
    "pv4": "solar_input_4_power",
    "stackInPw": "stack_input_power",
    "stackOutPw": "stack_output_power",
    "swEpsInPw": "eps_input_power",
    "swEpsOutPw": "eps_output_power",
}

_POWER_FIELDS = frozenset(
    {
        "AphasePw",
        "BphasePw",
        "CphasePw",
        "TphasePw",
        "aPhasePw",
        "anPhasePw",
        "bPhasePw",
        "bnPhasePw",
        "cPhasePw",
        "cnPhasePw",
        "inPw",
        "outPw",
        "phasePw",
        "power",
        "tPhasePw",
        "tnPhasePw",
    }
)
_ENERGY_FIELDS = frozenset(
    {
        "aPhaseEgy",
        "anPhaseEgy",
        "bPhaseEgy",
        "bnPhaseEgy",
        "cPhaseEgy",
        "cnPhaseEgy",
        "inEgy",
        "outEgy",
        "phaseEgy",
        "tPhaseEgy",
        "tnPhaseEgy",
        "totalEgy",
    }
)
_CHILD_DIAGNOSTIC_FIELDS = frozenset(
    {
        "commMode",
        "commState",
        "devType",
        "subType",
        *_POWER_FIELDS,
        *_ENERGY_FIELDS,
    }
)

_KNOWN_CACHE_FIELDS = frozenset(
    {
        *(config["json_key"] for config in SENSORS.values() if config["json_key"]),
        "autoStandby",
        "collectors",
        "cts",
        "defaultPw",
        "deviceSn",
        "deviceType",
        "grid_available",
        "isAutoStandby",
        "isFollowMeterPw",
        "maxSocChg",
        "maxSocDischg",
        "minSocChg",
        "minSocDischg",
        "offGridDown",
        "plug",
        "plugs",
        "socForceChg",
        "softver",
        "swEps",
        "workMode",
        "workModel",
        "expansion_batteries",
    }
)


@dataclass(slots=True)
class _ChildAggregate:
    """Temporary allowlisted child view retained only during one collection."""

    identifier: str
    family: str = "unknown"
    model: str = "unknown"
    device_type: int | None = None
    sub_type: int | None = None
    cache_containers: set[str] = field(default_factory=set)
    communication_mode: int | None = None
    communication_state: int | None = None
    has_payload: bool = False
    has_power_measurement: bool = False
    has_energy_measurement: bool = False


def _configured_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


def _safe_int(value: Any) -> int | None:
    return value if type(value) is int else None


def _is_finite_number(value: Any) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(float(value))
    except OverflowError:
        return False


def _task_state(task: asyncio.Task[Any] | None) -> str:
    """Normalize task lifecycle without inspecting coroutine or exception data."""
    if task is None:
        return "absent"
    if task.cancelled():
        return "cancelled"
    if task.done():
        return "done"
    return "running"


def _application_state(
    entry_state: ConfigEntryState,
    coordinator: JackeryDataCoordinator | None,
) -> str:
    if entry_state is ConfigEntryState.SETUP_IN_PROGRESS:
        return "starting"
    if entry_state is ConfigEntryState.UNLOAD_IN_PROGRESS:
        return "stopping"
    if entry_state in (
        ConfigEntryState.SETUP_ERROR,
        ConfigEntryState.SETUP_RETRY,
        ConfigEntryState.MIGRATION_ERROR,
        ConfigEntryState.FAILED_UNLOAD,
    ):
        return "failed"
    if coordinator is None or entry_state is ConfigEntryState.NOT_LOADED:
        return "stopped"
    return "running" if coordinator._subscribed else "stopped"


def _host_model(device_type: Any) -> str:
    if type(device_type) is not int:
        return "unknown"
    return "diy3" if device_type == 3 else "energy_monitor"


def _add_child_payload(
    children: dict[str, _ChildAggregate],
    payload: Mapping[str, Any],
    *,
    container: str,
    context: ClassificationContext,
) -> None:
    payload = dict.copy(payload) if isinstance(payload, dict) else dict(payload)
    identifier = subdevice_serial(payload)
    if identifier is None:
        return
    payload_view = {
        key: payload.get(key)
        for key in _CHILD_DIAGNOSTIC_FIELDS
        if key in payload
    }
    child = children.setdefault(identifier, _ChildAggregate(identifier))
    child.cache_containers.add(container)
    child.has_payload = True

    classification = classify_device(payload_view, context)
    if child.family == "unknown" or classification.family is not DeviceFamily.UNKNOWN:
        child.family = classification.family.value
        child.model = (
            classification.model.value
            if classification.model is not None
            else "unknown"
        )
        child.device_type = _safe_int(classification.dev_type)
    sub_type = _safe_int(payload_view.get("subType"))
    if sub_type is not None:
        child.sub_type = sub_type
    communication_mode = _safe_int(payload_view.get("commMode"))
    if communication_mode is not None:
        child.communication_mode = communication_mode
    communication_state = _safe_int(payload_view.get("commState"))
    if communication_state is not None:
        child.communication_state = communication_state
    child.has_power_measurement |= any(
        key in payload_view and payload_view.get(key) is not None
        for key in _POWER_FIELDS
    )
    child.has_energy_measurement |= any(
        key in payload_view and payload_view.get(key) is not None
        for key in _ENERGY_FIELDS
    )


def _collect_children(
    cache: Mapping[str, Any],
    known_children: set[str],
    expansion_batteries: set[str],
    freshness_identifiers: set[str],
) -> tuple[tuple[ChildDiagnosticsInput, ...], tuple[str, ...]]:
    children: dict[str, _ChildAggregate] = {}
    for container, context in _CHILD_CONTAINERS:
        items = cache.get(container)
        if not isinstance(items, list):
            continue
        for item in tuple(list.copy(items)):
            if isinstance(item, Mapping):
                _add_child_payload(
                    children,
                    item,
                    container=container,
                    context=context,
                )

    expansion_items = cache.get("expansion_batteries")
    if isinstance(expansion_items, Mapping):
        expansion_snapshot = (
            dict.copy(expansion_items)
            if isinstance(expansion_items, dict)
            else dict(expansion_items)
        )
        for identifier, raw_payload in tuple(expansion_snapshot.items()):
            if not isinstance(identifier, str) or not identifier:
                continue
            payload = raw_payload if isinstance(raw_payload, Mapping) else {}
            payload_with_identity = {
                key: payload.get(key)
                for key in _CHILD_DIAGNOSTIC_FIELDS
                if key in payload
            }
            payload_with_identity["deviceSn"] = identifier
            _add_child_payload(
                children,
                payload_with_identity,
                container="expansion_batteries",
                context=ClassificationContext.TYPE23_CHILD,
            )

    all_identifiers = (
        set(children)
        | known_children
        | expansion_batteries
        | freshness_identifiers
    )
    for identifier in all_identifiers:
        child = children.setdefault(identifier, _ChildAggregate(identifier))
        if identifier in expansion_batteries:
            child.family = DeviceFamily.EXPANSION_BATTERY.value

    inputs = tuple(
        ChildDiagnosticsInput(
            identifier=identifier,
            family=child.family,
            model=child.model,
            device_type=child.device_type,
            sub_type=child.sub_type,
            cache_containers=tuple(sorted(child.cache_containers)),
            known=identifier in known_children,
            expansion_battery=identifier in expansion_batteries,
            communication_mode=child.communication_mode,
            communication_state=child.communication_state,
            has_power_measurement=(
                child.has_power_measurement if child.has_payload else None
            ),
            has_energy_measurement=(
                child.has_energy_measurement if child.has_payload else None
            ),
        )
        for identifier, child in sorted(children.items())
    )
    smartmeters = tuple(
        child.identifier
        for child in inputs
        if child.family == DeviceFamily.SMARTMETER.value
    )
    return inputs, smartmeters


def _child_available(
    identifier: str,
    *,
    now: float,
    runtime_started_at: float,
    last_seen: Mapping[str, float],
    expansion_batteries: set[str],
) -> bool:
    activity_at = last_seen.get(identifier, 0)
    if activity_at == 0 and (now - runtime_started_at) < OFFLINE_TIMEOUT:
        return True
    if identifier in expansion_batteries:
        return activity_at > 0
    return activity_at > 0 and (now - activity_at) <= OFFLINE_TIMEOUT


def _freshness_inputs(
    coordinator: JackeryDataCoordinator,
    *,
    now: float,
    identifiers: set[str],
    last_seen: Mapping[str, float],
    missing_since: Mapping[str, float],
    expansion_batteries: set[str],
) -> FreshnessDiagnosticsInput:
    state = coordinator._runtime_state
    return FreshnessDiagnosticsInput(
        runtime_started_at=state.start_time,
        host_activity_at=state.last_update_time if state.ever_received else None,
        host_ever_received=state.ever_received,
        host_stale=state.host_is_stale(now, OFFLINE_TIMEOUT),
        children=tuple(
            ChildFreshnessDiagnosticsInput(
                identifier=identifier,
                activity_at=last_seen.get(identifier),
                available=_child_available(
                    identifier,
                    now=now,
                    runtime_started_at=state.start_time,
                    last_seen=last_seen,
                    expansion_batteries=expansion_batteries,
                ),
                missing_since=missing_since.get(identifier),
                retention_policy=(
                    "retain_after_first_seen"
                    if identifier in expansion_batteries
                    else "timeout"
                ),
            )
            for identifier in sorted(identifiers)
        ),
    )


def _protocol_inputs(
    coordinator: JackeryDataCoordinator,
    cache: Mapping[str, Any],
    observation_routes: Mapping[str, int],
    observation_errors: Mapping[str, int],
    unknown_message_count: int,
) -> ProtocolDiagnosticsInput:
    semantic_measurements = {
        semantic: cache.get(cache_key)
        for semantic, cache_key in _SEMANTIC_CACHE_FIELDS.items()
        if cache_key in cache
    }
    invalid_value_count = sum(
        not _is_finite_number(cache.get(cache_key))
        for cache_key in _SEMANTIC_CACHE_FIELDS.values()
        if cache_key in cache
    )
    cache_keys = tuple(cache)
    known_field_count = sum(
        isinstance(key, str) and key in _KNOWN_CACHE_FIELDS for key in cache_keys
    )
    child_container_counts: dict[str, int | None] = {}
    for container, _context in _CHILD_CONTAINERS:
        value = cache.get(container)
        child_container_counts[container] = len(value) if isinstance(value, list) else None
        if container in cache and not isinstance(value, list):
            invalid_value_count += 1
    expansion_items = cache.get("expansion_batteries")
    child_container_counts["expansion_batteries"] = (
        len(expansion_items) if isinstance(expansion_items, Mapping) else None
    )
    if "expansion_batteries" in cache and not isinstance(
        expansion_items, Mapping
    ):
        invalid_value_count += 1

    runtime = coordinator._runtime_state
    live_seen = dict.copy(runtime.power_live_seen)
    snapshot_seen = dict.copy(runtime.power_106_samples)
    type106_evidence = tuple(
        Type106EvidenceInput(
            field=semantic,
            live_message_type=(
                _safe_int(live_seen[wire][0]) if wire in live_seen else None
            ),
            live_seen_at=live_seen[wire][1] if wire in live_seen else None,
            snapshot_seen_at=(
                snapshot_seen[wire][1] if wire in snapshot_seen else None
            ),
        )
        for wire, semantic in sorted(_TYPE106_FIELDS.items())
        if wire in live_seen or wire in snapshot_seen
    )

    energy_sources = dict.copy(runtime.energy_sources)
    raw_grid_source = energy_sources.get("grid")
    grid_source = None
    if isinstance(raw_grid_source, Mapping):
        grid_source_snapshot = (
            dict.copy(raw_grid_source)
            if isinstance(raw_grid_source, dict)
            else dict(raw_grid_source)
        )
        grid_source = EnergySourceDiagnosticsInput(
            source=grid_source_snapshot.get("source", "unknown"),
            activity_age_seconds=grid_source_snapshot.get("activity_age"),
            skipped_stale=grid_source_snapshot.get("skipped_stale"),
            skipped_missing=grid_source_snapshot.get("skipped_missing"),
            reason=grid_source_snapshot.get("reason", "unknown"),
        )

    discovery_snapshot = coordinator.protocol_discovery_snapshot()
    discovery = None
    if discovery_snapshot is not None:
        discovery = ProtocolDiscoveryDiagnosticsInput(
            version=discovery_snapshot.version,
            unknown_message_types=tuple(
                DiscoveryMessageTypeInput(
                    kind=item.key.kind,
                    value=item.key.value,
                    observation=DiscoveryObservationInput(
                        count=item.observation.count,
                        first_seen_at=item.observation.first_seen_at,
                        last_seen_at=item.observation.last_seen_at,
                    ),
                )
                for item in discovery_snapshot.unknown_message_types
            ),
            unknown_device_types=tuple(
                DiscoveryDeviceTypeInput(
                    dev_type=item.key.dev_type,
                    sub_type=item.key.sub_type,
                    observation=DiscoveryObservationInput(
                        count=item.observation.count,
                        first_seen_at=item.observation.first_seen_at,
                        last_seen_at=item.observation.last_seen_at,
                    ),
                )
                for item in discovery_snapshot.unknown_device_types
            ),
            structures=tuple(
                DiscoveryStructureInput(
                    path=item.key.path,
                    unknown_field_count=item.key.unknown_field_count,
                    unknown_value_types=dict(item.key.unknown_value_types),
                    nested_shapes=item.key.nested_shapes,
                    type_mismatches=item.key.type_mismatches,
                    observation=DiscoveryObservationInput(
                        count=item.observation.count,
                        first_seen_at=item.observation.first_seen_at,
                        last_seen_at=item.observation.last_seen_at,
                    ),
                )
                for item in discovery_snapshot.structures
            ),
            message_type_overflow=discovery_snapshot.message_type_overflow,
            device_type_overflow=discovery_snapshot.device_type_overflow,
            structural_overflow=discovery_snapshot.structural_overflow,
            traversal_dropped=discovery_snapshot.traversal_dropped,
        )

    return ProtocolDiagnosticsInput(
        semantic_measurements=semantic_measurements,
        known_field_count=known_field_count,
        unknown_field_count=len(cache_keys) - known_field_count,
        invalid_value_count=invalid_value_count,
        child_container_counts=child_container_counts,
        type106_evidence=type106_evidence,
        grid_source=grid_source,
        route_counters=dict(observation_routes),
        error_counters=dict(observation_errors),
        unknown_message_count=unknown_message_count,
        discovery_enabled=discovery_snapshot is not None,
        discovery=discovery,
    )


def _registry_inputs(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: JackeryDataCoordinator | None,
) -> EntityDiagnosticsInput:
    entity_registry = er.async_get(hass)
    entries = tuple(
        registry_entry
        for registry_entry in er.async_entries_for_config_entry(
            entity_registry, entry.entry_id
        )
        if registry_entry.platform == DOMAIN
    )
    by_platform = Counter(
        registry_entry.domain
        for registry_entry in entries
        if registry_entry.domain in {"button", "number", "select", "sensor", "switch"}
    )
    state_counts: Counter[str] = Counter()
    for registry_entry in entries:
        state = hass.states.get(registry_entry.entity_id)
        if state is None or state.state == STATE_UNKNOWN:
            state_counts["unknown"] += 1
        elif state.state == STATE_UNAVAILABLE:
            state_counts["unavailable"] += 1
        else:
            state_counts["available"] += 1

    device_registry = dr.async_get(hass)
    device_counts: Counter[str] = Counter()
    for device in tuple(
        dr.async_entries_for_config_entry(device_registry, entry.entry_id)
    ):
        is_child = any(
            domain == DOMAIN
            and parse_child_device_identifier(identifier) is not None
            for domain, identifier in device.identifiers
        )
        device_counts["child" if is_child else "host"] += 1

    listeners: tuple[Any, ...] = ()
    if coordinator is not None:
        listeners = tuple(dict.copy(coordinator._sensors).values())
    mqtt_listeners = sum(
        callable(getattr(listener, "_update_from_coordinator", None))
        for listener in listeners
    )
    http_listeners = sum(
        callable(getattr(listener, "_update_from_http", None))
        for listener in listeners
    )
    enabled_registry_sensors = sum(
        registry_entry.domain == "sensor" and registry_entry.disabled_by is None
        for registry_entry in entries
    )
    runtime_sensor_count = sum(
        callable(getattr(listener, "_update_from_coordinator", None))
        or callable(getattr(listener, "_update_from_http", None))
        for listener in listeners
    )

    return EntityDiagnosticsInput(
        registry_total=len(entries),
        by_platform=dict(by_platform),
        disabled_count=sum(entry.disabled_by is not None for entry in entries),
        state_counts=dict(state_counts),
        device_counts=dict(device_counts),
        runtime_listener_counts={"mqtt": mqtt_listeners, "http": http_listeners},
        mismatch_count=abs(enabled_registry_sensors - runtime_sensor_count),
    )


def _health_inputs(
    coordinator: JackeryDataCoordinator | None,
) -> HealthDiagnosticsInput:
    if coordinator is None:
        return HealthDiagnosticsInput(runtime_available=False)
    migration = coordinator._child_migration
    if migration is None:
        return HealthDiagnosticsInput(
            runtime_available=True,
            reauth_requested=coordinator._reauth_started,
        )
    reported_conflicts = set.copy(migration._reported_conflicts)
    blocked_children = set.copy(migration.blocked_children)
    categories = Counter(
        category for _identifier, category in reported_conflicts
    )
    return HealthDiagnosticsInput(
        runtime_available=True,
        reauth_requested=coordinator._reauth_started,
        migration_block_all=migration.block_all,
        migration_blocked_child_count=len(blocked_children),
        migration_conflict_categories=dict(categories),
    )


def collect_diagnostics_inputs(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: JackeryDataCoordinator | None,
    *,
    manifest_version: str | None,
    now: float,
) -> DiagnosticsSnapshotInput:
    data = entry.data
    options = entry.options
    http_enabled = options.get("smartmeter_http_poll") is True
    protocol_discovery_enabled = (
        options.get(OPTION_PROTOCOL_DISCOVERY_ENABLED) is True
    )
    http_poll_interval = options.get(
        "smartmeter_poll_interval", _DEFAULT_HTTP_POLL_INTERVAL
    )
    integration = IntegrationDiagnosticsInput(
        manifest_version=manifest_version,
        home_assistant_version=HA_VERSION,
        python_version=platform.python_version(),
        entry_state=entry.state.value,
        host_configured=_configured_string(data.get("device_sn")),
        token_configured=_configured_string(data.get("token")),
        custom_topic_configured=(
            _configured_string(data.get("topic_prefix"))
            and data.get("topic_prefix") != _DEFAULT_TOPIC_PREFIX
        ),
        legacy_mqtt_host_configured=_configured_string(data.get("mqtt_host")),
        http_enabled=http_enabled,
        http_poll_interval_seconds=_safe_int(http_poll_interval),
    )
    entities = _registry_inputs(hass, entry, coordinator)
    health = _health_inputs(coordinator)
    if coordinator is None:
        return DiagnosticsSnapshotInput(
            integration=integration,
            transport=TransportDiagnosticsInput(
                mqtt_application_state=_application_state(entry.state, None),
                mqtt_owned_subscriptions=0,
                mqtt_poll_task_state="absent",
                http_task_state="absent",
                poll_interval_seconds=REQUEST_INTERVAL,
                http_request_timeout_seconds=_HTTP_REQUEST_TIMEOUT_SECONDS,
            ),
            smartmeter=SmartMeterDiagnosticsInput(
                http_enabled=http_enabled,
                poll_interval_seconds=_safe_int(http_poll_interval),
                request_timeout_seconds=_HTTP_REQUEST_TIMEOUT_SECONDS,
                failure_threshold=HTTP_FAILURE_THRESHOLD,
            ),
            protocol=ProtocolDiagnosticsInput(
                discovery_enabled=protocol_discovery_enabled
            ),
            entities=entities,
            health=health,
        )

    runtime = coordinator._runtime_state
    cache = dict.copy(runtime.data_cache)
    known_children = set.copy(coordinator._child_discovery_state.known_children)
    expansion_batteries = set.copy(
        coordinator._child_discovery_state.expansion_batteries
    )
    missing_since = dict.copy(coordinator._child_discovery_state.missing_since)
    last_seen = dict.copy(runtime.subdevice_last_seen)
    created_http_identifiers = set.copy(coordinator._http_sm_sensor_sns_created)
    observation = coordinator.diagnostics_observation()
    target_identifier = observation.http.target_identifier
    freshness_identifiers = (
        known_children
        | expansion_batteries
        | set(missing_since)
        | set(last_seen)
        | created_http_identifiers
    )
    if target_identifier is not None:
        freshness_identifiers.add(target_identifier)

    children, smartmeter_identifiers = _collect_children(
        cache,
        known_children,
        expansion_batteries,
        freshness_identifiers,
    )
    freshness = _freshness_inputs(
        coordinator,
        now=now,
        identifiers=freshness_identifiers | {child.identifier for child in children},
        last_seen=last_seen,
        missing_since=missing_since,
        expansion_batteries=expansion_batteries,
    )

    return DiagnosticsSnapshotInput(
        integration=integration,
        host=HostDiagnosticsInput(
            identifier=coordinator._device_sn,
            device_type=_safe_int(coordinator._device_type),
            model=_host_model(coordinator._device_type),
            firmware=coordinator._soft_ver,
            cache_initialized=bool(cache),
        ),
        transport=TransportDiagnosticsInput(
            mqtt_application_state=_application_state(entry.state, coordinator),
            mqtt_owned_subscriptions=coordinator._mqtt_transport.unsubscribe_count,
            mqtt_poll_task_state=_task_state(coordinator._data_task),
            http_task_state=_task_state(coordinator._smartmeter_http_task),
            poll_interval_seconds=REQUEST_INTERVAL,
            http_request_timeout_seconds=_HTTP_REQUEST_TIMEOUT_SECONDS,
        ),
        protocol=_protocol_inputs(
            coordinator,
            cache,
            dict(observation.protocol.route_counters),
            dict(observation.protocol.error_counters),
            observation.protocol.unknown_message_count,
        ),
        freshness=freshness,
        children=children,
        smartmeter=SmartMeterDiagnosticsInput(
            mqtt_identifiers=smartmeter_identifiers,
            http_enabled=http_enabled,
            target_identifier=target_identifier,
            created_http_identifiers=tuple(sorted(created_http_identifiers)),
            poll_interval_seconds=_safe_int(http_poll_interval),
            request_timeout_seconds=_HTTP_REQUEST_TIMEOUT_SECONDS,
            failure_threshold=HTTP_FAILURE_THRESHOLD,
            last_attempt_at=observation.http.last_attempt_at,
            last_success_at=observation.http.last_success_at,
            consecutive_failures=observation.http.consecutive_failures,
            last_outcome=observation.http.last_outcome,
            source_replacement_state=observation.http.replacement_state,
            health=observation.http.health,
        ),
        entities=entities,
        health=health,
    )


__all__ = ["collect_diagnostics_inputs"]
