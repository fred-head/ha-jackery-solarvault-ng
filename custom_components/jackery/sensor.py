"""Jackery Sensor Platform."""
import asyncio
import json
import logging
import random
import time
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DOMAIN
from .calculations.energy_flow import (
    SourceFreshness,
    _power_sample,
    calculate_energy_flow,
    select_grid_source,
)
from .coordinator_state import CoordinatorRuntimeState
from .devices.classification import (
    CT_SUBTYPE_MAP,
    ClassificationContext,
    DeviceFamily,
    DeviceModel,
    classify_device,
)
from .devices.classification import should_create_plug_switch as should_create_plug_switch
from .diagnostics_observation import (
    DiagnosticsObservationSnapshot,
    DiagnosticsObservationState,
    HttpOutcome,
    ProtocolErrorBucket,
    ProtocolRouteBucket,
)
from .discovery import ChildDiscoveryState, child_entity_spec
from .entities.sensor_definitions import CT_STATUS_MAP as CT_STATUS_MAP
from .entities.sensor_definitions import DEVICE_STATUS_MAP as DEVICE_STATUS_MAP
from .entities.sensor_definitions import (
    FUNC_ENABLE_BITS,
    SENSORS,
    SMARTMETER_HTTP_SENSOR_CONFIGS,
    SUBDEVICE_SENSORS,
    ChildSensorConfig,
)
from .entities.sensor_definitions import GRID_METER_LINK_MAP as GRID_METER_LINK_MAP
from .entities.sensor_definitions import ONGRID_STATUS_MAP as ONGRID_STATUS_MAP
from .entities.transforms import COMM_MODE_CLOUD as COMM_MODE_CLOUD
from .entities.transforms import COMM_MODE_LABELS as COMM_MODE_LABELS
from .entities.transforms import COMM_MODE_LOCAL as COMM_MODE_LOCAL
from .entities.transforms import plug_comm_mode as plug_comm_mode
from .entities.transforms import plug_mqtt_control_allowed as plug_mqtt_control_allowed
from .identity import child_device_identifier, child_unique_id, http_unique_id
from .protocol.commands import (
    action_topic,
    build_full_state_request,
    build_main_control,
    build_settings_request,
    build_status_request,
    build_subdevice_request,
    build_subdevice_switch,
)
from .protocol.normalization import normalize_payload_fields
from .protocol.routing import (
    MessageRoute,
    RoutingDecision,
    is_host_message_body,
    parse_envelope,
    parse_topic,
)
from .protocol.routing import (
    subdevice_serial as _subdevice_sn,
)
from .protocol_discovery import ProtocolDiscoverySnapshot, ProtocolDiscoveryState
from .transport.mqtt import JackeryMqttTransport
from .transport.smartmeter_http import (
    SmartMeterHttpRequestError,
    SmartMeterHttpTransport,
)

if TYPE_CHECKING:
    from .child_migration import ChildMigrationResult

_LOGGER = logging.getLogger(__name__)

REQUEST_INTERVAL = 10  # seconds; intentionally 10 s (upstream uses 5 s — too much MQTT traffic for homelab)
OFFLINE_TIMEOUT = 60  # seconds without any message → mark entities unavailable
# If the device never answers within this window after setup the token is most likely rejected
# (the device stays silent on a bad token instead of replying with an error).
REAUTH_HINT_TIMEOUT = 120
HTTP_FAILURE_THRESHOLD = 3

# Device model lookup from deviceType field in MQTT payload
DEVICE_TYPE_MODEL_MAP: dict[int, str] = {
    3: "DIY3",   # SolarVault 3 Pro Max
}
DEFAULT_MODEL = "Energy Monitor"

# Real-time power fields shared between type-2 (~11 s) and type-106 (~30 s).
# Preserve live readings for OFFLINE_TIMEOUT, not forever based on key presence.
# See docs/energy-source-policy.md and the snapshot race in commit 8043585.
_TYPE106_LIVE_PREFERRED: frozenset[str] = frozenset({
    "batInPw", "batOutPw",
    "pvPw", "pv1", "pv2", "pv3", "pv4",
    "swEpsInPw", "swEpsOutPw",
    "stackInPw", "stackOutPw",
})


def _protocol_observation_bucket(
    decision: RoutingDecision,
) -> tuple[ProtocolRouteBucket, bool]:
    """Map an accepted route to one fixed diagnostics bucket."""
    if decision.route is MessageRoute.TYPE_23:
        return ProtocolRouteBucket.TYPE_23, False
    if decision.route is MessageRoute.TYPE_101:
        return ProtocolRouteBucket.TYPE_101, False
    if decision.route is MessageRoute.TYPE_102:
        return ProtocolRouteBucket.TYPE_102, False
    if decision.route is MessageRoute.TYPE_106:
        return ProtocolRouteBucket.TYPE_106, False
    if decision.route is MessageRoute.TYPE_107:
        return ProtocolRouteBucket.TYPE_107, False
    if decision.route is MessageRoute.TYPE_123:
        return ProtocolRouteBucket.TYPE_123, False
    if decision.message_type in (2, 25):
        return ProtocolRouteBucket.GENERIC_KNOWN, False
    return ProtocolRouteBucket.GENERIC_UNKNOWN, True


def _merge_subdevice_list(
    existing: list[dict] | None,
    new_items: list[dict],
) -> list[dict]:
    """Merge sub-device entries by deviceSn/sn, preserving fields not present in new_items.

    Instead of replacing the whole list on every message, each device is identified by its
    serial number and new fields are merged on top of the existing entry.  Fields that are
    present in the cache but absent from the current message are kept intact.
    """
    merged: dict[str, dict] = {}
    for item in (existing or []) + new_items:
        if not isinstance(item, dict):
            continue
        sn = _subdevice_sn(item)
        if not sn:
            continue
        merged[sn] = {**merged.get(sn, {}), **item}
    return list(merged.values())


class JackeryDataCoordinator:
    """协调器：管理MQTT订阅和数据获取，供所有传感器实体共享使用."""

    def __init__(
        self,
        hass: HomeAssistant,
        topic_prefix: str,
        token: str | None,
        mqtt_host: str | None,
        device_sn: str | None,
        *,
        protocol_discovery_enabled: bool = False,
    ) -> None:
        self.hass = hass
        self._topic_prefix = topic_prefix
        self._token = token
        self._mqtt_host = mqtt_host
        self._device_sn = device_sn
        self._topic_root = topic_prefix

        self._sensors: dict[str, Any] = {}
        self._data_task: asyncio.Task[None] | None = None
        self._subscribed = False
        self._mqtt_transport = JackeryMqttTransport(hass)
        self._lifecycle_lock = asyncio.Lock()
        self._runtime_state = CoordinatorRuntimeState(
            last_update_time=time.time(),
            start_time=time.time(),
        )
        self._diagnostics_observation = DiagnosticsObservationState()
        self._protocol_discovery = (
            ProtocolDiscoveryState() if protocol_discovery_enabled else None
        )

        self._child_discovery_state = ChildDiscoveryState()
        # Compatibility aliases retained for existing coordinator consumers.
        self._known_plugs = self._child_discovery_state.known_children
        self._subdevice_missing_since = self._child_discovery_state.missing_since
        self._expansion_battery_sns = self._child_discovery_state.expansion_batteries
        self._poll_105_counter: int = 2  # starts at threshold-1 so type-105 fires on first cycle
        self.add_entities_callback: Any = None
        self.add_switch_entities_callback: Any = None
        # Device meta — populated from first MQTT message, used to update device registry (Ü2/Ü3)
        self._device_type: int | None = None
        self._soft_ver: str | None = None

        # Re-Auth guard — prevents multiple simultaneous re-auth flows
        self._reauth_started: bool = False
        # True as soon as one valid message for this device SN was received (re-auth heuristic)
        self.config_entry_id: str = ""  # set by async_setup_entry
        self._child_migration: ChildMigrationResult | None = None

        # SmartMeter HTTP polling (optional feature, controlled via options flow)
        self._smartmeter_http_task: asyncio.Task[None] | None = None
        self._http_sm_sensor_sns_created: set[str] = set()

        # Relayed child reports also arrive on the host's status/event topics.
        topic_sn = device_sn or "+"
        self._topic_status = f"{self._topic_root}/device/{topic_sn}/status"
        self._topic_event = f"{self._topic_root}/device/{topic_sn}/event"

    @property
    def _data_cache(self) -> dict[str, Any]:
        return self._runtime_state.data_cache

    @property
    def _power_live_seen(self) -> dict[str, tuple[int, float]]:
        return self._runtime_state.power_live_seen

    @property
    def _power_106_samples(self) -> dict[str, tuple[Any, float]]:
        return self._runtime_state.power_106_samples

    @property
    def _energy_sources(self) -> dict[str, Any]:
        return self._runtime_state.energy_sources

    @property
    def _subdevice_last_seen(self) -> dict[str, float]:
        return self._runtime_state.subdevice_last_seen

    @property
    def _last_update_time(self) -> float:
        return self._runtime_state.last_update_time

    @property
    def _start_time(self) -> float:
        return self._runtime_state.start_time

    @property
    def _ever_received(self) -> bool:
        return self._runtime_state.ever_received

    @property
    def _mqtt_unsubscribers(self) -> list[CALLBACK_TYPE]:
        """Compatibility view of transport-owned subscription handles."""
        return self._mqtt_transport.unsubscribers

    def diagnostics_observation(self) -> DiagnosticsObservationSnapshot:
        """Return an immutable copy of passive per-coordinator observations."""
        return self._diagnostics_observation.snapshot()

    def protocol_discovery_snapshot(self) -> ProtocolDiscoverySnapshot | None:
        """Return a detached discovery snapshot when the opt-in mode is active."""
        state = self._protocol_discovery
        return state.snapshot() if state is not None else None

    def register_sensor(self, sensor_id: str, entity: Any) -> None:
        """Register an HA entity for its supported MQTT or HTTP update path."""
        self._sensors[sensor_id] = entity

    def unregister_sensor(self, sensor_id: str) -> None:
        """注销传感器实体."""
        if sensor_id in self._sensors:
            del self._sensors[sensor_id]

    async def async_start(self) -> None:
        """Own every subscription as soon as it is created; unwind failed starts."""
        async with self._lifecycle_lock:
            if self._subscribed:
                return
            try:
                @callback
                def message_received(msg):
                    self._handle_message(msg)

                await self._mqtt_transport.async_subscribe(
                    (self._topic_status, self._topic_event),
                    message_received,
                )
                _LOGGER.debug("MQTT subscriptions created for entry %s", self.config_entry_id)

                self._data_task = asyncio.create_task(self._periodic_data_request())
                # HTTP retains its existing independent polling/health policy.
                entry = self.hass.config_entries.async_get_entry(self.config_entry_id)
                if entry and entry.options.get("smartmeter_http_poll", False):
                    self._smartmeter_http_task = asyncio.create_task(self._smartmeter_http_poll_loop())
                    _LOGGER.info("SmartMeter HTTP polling enabled (interval=%ds)", entry.options.get("smartmeter_poll_interval", 10))
                self._subscribed = True
            except (Exception, asyncio.CancelledError):
                await self._async_release_resources()
                raise

    async def async_stop(self) -> None:
        """Release only this coordinator's resources, once, even after a partial start."""
        async with self._lifecycle_lock:
            await self._async_release_resources()
        _LOGGER.debug("Coordinator stopped for entry %s", self.config_entry_id)

    async def _async_release_resources(self) -> None:
        """Attempt all cleanup before reporting errors; caller holds lifecycle lock."""
        self._subscribed = False
        errors: list[Exception] = []
        had_subscriptions = self._mqtt_transport.unsubscribe_count > 0
        try:
            await self._mqtt_transport.async_stop()
        except ExceptionGroup as error:
            errors.extend(error.exceptions)
        if had_subscriptions:
            _LOGGER.debug("MQTT subscription cleanup attempted for entry %s", self.config_entry_id)

        tasks = [task for task in (self._data_task, self._smartmeter_http_task) if task and not task.done()]
        for task in tasks:
            task.cancel()
        # Child-task cancellation is expected. Cancellation of the caller must
        # still propagate; gather distinguishes it from the collected results.
        results = await asyncio.gather(*tasks, return_exceptions=True)
        errors.extend(result for result in results if isinstance(result, Exception))
        if errors:
            raise ExceptionGroup("Coordinator resource cleanup failed", errors)

    def _handle_message(self, msg) -> None:
        """处理接收到的 MQTT 消息."""
        try:
            topic = msg.topic
            topic_info = parse_topic(self._topic_root, topic)
            if topic_info is None:
                self._diagnostics_observation.record_protocol_error(
                    ProtocolErrorBucket.INVALID_TOPIC
                )
                return
            sn = topic_info.device_sn
            if self._device_sn and self._device_sn != sn:
                self._diagnostics_observation.record_protocol_error(
                    ProtocolErrorBucket.FOREIGN_HOST
                )
                _LOGGER.debug(f"Ignoring data from another device: {sn}")
                return

            try:
                parsed = parse_envelope(msg.payload)
            except json.JSONDecodeError:
                self._diagnostics_observation.record_protocol_error(
                    ProtocolErrorBucket.INVALID_JSON
                )
                _LOGGER.warning(f"Invalid JSON payload on {topic}")
                return
            if parsed is None:
                self._diagnostics_observation.record_protocol_error(
                    ProtocolErrorBucket.INVALID_ENVELOPE
                )
                return

            if not self._device_sn:
                self._device_sn = sn
                _LOGGER.info(f"Discovered device SN: {self._device_sn}")
            # The topic identifies the host; payload SNs may identify its children.
            # Invalid or foreign traffic must not postpone offline/reauth checks.
            received_at = time.time()
            self._runtime_state.record_host_activity(received_at)

            # Discovery observes only host-owned, parsed and structurally accepted
            # envelopes.  It cannot affect routing or any operational state.
            protocol_discovery = self._protocol_discovery
            if protocol_discovery is not None:
                protocol_discovery.observe(
                    parsed.raw_data,
                    parsed.body,
                    message_type=parsed.decision.message_type,
                    now=received_at,
                )

            decision = parsed.decision
            if decision.captures_host_metadata and is_host_message_body(
                parsed.body,
                self._device_sn,
            ):
                self._capture_device_meta(parsed.raw_data, parsed.body)

            self._apply_message_route(decision, parsed.body)
            if decision.refreshes_generic_children:
                self._refresh_generic_child_activity(parsed.body)

            # Enrich data with calculations using merged cache
            # operate on copy or direct? Direct is fine.
            self._calculate_energy_flow(self._data_cache)

            # Check for new plugs
            self._check_for_new_plugs(self._data_cache)

            self._distribute_data(self._data_cache)

            route_bucket, unknown_message_type = _protocol_observation_bucket(
                decision
            )
            self._diagnostics_observation.record_protocol_route(
                route_bucket,
                unknown_message_type=unknown_message_type,
            )

        except Exception as e:
            self._diagnostics_observation.record_protocol_error(
                ProtocolErrorBucket.HANDLER_ERROR
            )
            _LOGGER.error(f"Error handling message: {e}")

    def _apply_message_route(
        self,
        decision: RoutingDecision,
        body: dict[str, Any],
    ) -> None:
        """Apply one pure routing decision to coordinator-owned state."""
        if decision.route is MessageRoute.TYPE_23:
            self._handle_type23(body)
        elif decision.route is MessageRoute.TYPE_101:
            self._merge_subdevice_arrays(body)
        elif decision.route is MessageRoute.TYPE_102:
            if not self._merge_subdevice_arrays(body):
                self._merge_subdevice_point_update(body)
        elif decision.route is MessageRoute.TYPE_106:
            self._handle_type106(body)
        elif decision.route is MessageRoute.TYPE_107:
            self._merge_normalized_cache(body, decision.message_type)
            _LOGGER.debug("Received type-107 incremental update: %s", body)
        elif decision.route is MessageRoute.TYPE_123:
            if body.get("errorCode") == 401:
                self._trigger_reauth("device reported token mismatch (type-123/401)")
        else:
            self._merge_normalized_cache(body, decision.message_type)

    def _handle_type23(self, body: dict[str, Any]) -> None:
        """Apply statistical host or child data to coordinator-owned state."""
        device_sn_in_body = body.get("deviceSn")
        child_sn = _subdevice_sn(body)
        is_expansion_battery = (
            classify_device(body, ClassificationContext.TYPE23_CHILD).family
            is DeviceFamily.EXPANSION_BATTERY
        )
        is_sn_only_expansion = (
            device_sn_in_body is None
            and child_sn is not None
            and is_expansion_battery
        )
        if is_host_message_body(body, self._device_sn) and not is_sn_only_expansion:
            self._merge_normalized_cache(body, 23)
        elif is_expansion_battery and child_sn is not None:
            # Expansion battery (e.g. BP2500) — not in type-101.
            exp_bats = self._data_cache.setdefault("expansion_batteries", {})
            if child_sn not in exp_bats:
                exp_bats[child_sn] = {}
            # Null energy reports must not erase the last real long-cadence value.
            for key, value in body.items():
                if value is not None:
                    exp_bats[child_sn][key] = value
            self._runtime_state.record_child_activity(
                child_sn,
                time.time(),
            )
            self._check_for_new_expansion_batteries()
        else:
            # Existing type-23 search intentionally excludes collectors.
            for data_key in ("plugs", "plug", "cts"):
                items = self._data_cache.get(data_key)
                if isinstance(items, list):
                    for item in items:
                        if (
                            item.get("sn") == device_sn_in_body
                            or item.get("deviceSn") == device_sn_in_body
                        ):
                            item.update(body)
                            self._runtime_state.record_child_activity(
                                device_sn_in_body,
                                time.time(),
                            )
                            break

    def _handle_type106(self, body: dict[str, Any]) -> None:
        """Apply a full-system snapshot with coordinator-owned live preference."""
        normalized = normalize_payload_fields(body)
        self._runtime_state.merge_type106_snapshot(
            normalized,
            live_preferred=_TYPE106_LIVE_PREFERRED,
            live_timeout=OFFLINE_TIMEOUT,
        )
        _LOGGER.debug("Received type-106 system state (%d fields)", len(body))

    def _refresh_generic_child_activity(self, body: dict[str, Any]) -> None:
        """Refresh reported child activity for established generic routes."""
        for key in ("plugs", "plug", "cts", "collectors"):
            items = body.get(key)
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict) and (child_sn := _subdevice_sn(item)):
                        self._runtime_state.record_child_activity(
                            child_sn,
                            self._last_update_time,
                        )

    def _merge_normalized_cache(self, payload: dict, msg_code: Any = None) -> None:
        """Normalize field aliases and merge a main-device payload into the cache."""
        normalized = normalize_payload_fields(payload)
        live_type = msg_code if msg_code in (2, 23, 25, 107) else None
        valid_live_fields = {
            key
            for key in _TYPE106_LIVE_PREFERRED.intersection(payload)
            if live_type is not None and _power_sample(payload[key]) is not None
        }
        self._runtime_state.merge_main_payload(
            normalized,
            observed_keys=payload,
            message_type=live_type,
            live_preferred=_TYPE106_LIVE_PREFERRED,
            valid_live_fields=valid_live_fields,
        )
        plug_items = normalized.get("plug")
        if not isinstance(plug_items, list):
            plug_items = normalized.get("plugs")
        if isinstance(plug_items, list):
            # Both aliases are one canonical cache view, including generic routes.
            self._data_cache["plugs"] = plug_items
            self._data_cache["plug"] = self._data_cache["plugs"]

    def _merge_subdevice_arrays(self, body: dict) -> bool:
        """Merge plugs/cts/collectors arrays from a body into the cache.

        Each section is merged independently by deviceSn so that:
        - A plug poll response (no "cts" key) never wipes the CT cache (issue #16)
        - Partial updates preserve fields not present in the current message

        Returns True if at least one array was merged.
        """
        raw_plugs = (
            body.get("plug") or body.get("plugs")
            or body.get("socket") or body.get("sockets")
        )
        raw_cts = body.get("ct") or body.get("cts")
        raw_collectors = body.get("collectors")

        now_ts = time.time()
        updated = False

        if isinstance(raw_plugs, list) and raw_plugs:
            new_plugs = []
            for item in raw_plugs:
                if not isinstance(item, dict):
                    continue
                classification = classify_device(item, ClassificationContext.PLUG_ARRAY)
                if item.get("devType") is None:
                    item = {**item, "devType": classification.dev_type}
                new_plugs.append(item)
                sn = _subdevice_sn(item)
                if sn:
                    self._runtime_state.record_child_activity(sn, now_ts)
            self._data_cache["plugs"] = _merge_subdevice_list(
                self._data_cache.get("plugs"), new_plugs
            )
            self._data_cache["plug"] = self._data_cache["plugs"]
            updated = True

        if isinstance(raw_cts, list) and raw_cts:
            new_cts = []
            for item in raw_cts:
                if not isinstance(item, dict):
                    continue
                classification = classify_device(item, ClassificationContext.CT_ARRAY)
                if item.get("devType") is None:
                    item = {**item, "devType": classification.dev_type}
                new_cts.append(item)
                sn = _subdevice_sn(item)
                if sn:
                    self._runtime_state.record_child_activity(sn, now_ts)
            self._data_cache["cts"] = _merge_subdevice_list(
                self._data_cache.get("cts"), new_cts
            )
            updated = True

        # Meter Collectors (HTO910A, devType=4, subType=7): appear under "collectors"
        # key in type-101 devType=2 responses, not under "cts".
        if isinstance(raw_collectors, list) and raw_collectors:
            new_collectors = []
            for item in raw_collectors:
                if not isinstance(item, dict):
                    continue
                new_collectors.append(item)
                sn = _subdevice_sn(item)
                if sn:
                    self._runtime_state.record_child_activity(sn, now_ts)
            self._data_cache["collectors"] = _merge_subdevice_list(
                self._data_cache.get("collectors"), new_collectors
            )
            updated = True

        return updated

    def _merge_subdevice_point_update(self, body: dict) -> bool:
        """Merge a single sub-device point update (type-102) into the cache.

        The body describes one sub-device directly (no wrapping array).  If the SN is
        already cached the entry is patched in place, otherwise the device is classified
        by devType and appended to the matching section.
        """
        sn = _subdevice_sn(body)
        if not sn or sn == self._device_sn or sn == "system":
            return False

        self._runtime_state.record_child_activity(sn, time.time())

        # 1. Known device → patch in place (skip null values, they carry no information)
        for key in ("plugs", "plug", "cts", "collectors"):
            items = self._data_cache.get(key)
            if not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, dict) and _subdevice_sn(item) == sn:
                    item.update({k: v for k, v in body.items() if v is not None})
                    return True

        # 2. New device → classify by devType, inferring it from the fields if absent
        entry = dict(body)
        classification = classify_device(entry, ClassificationContext.POINT_UPDATE)
        dev_type = classification.dev_type
        if entry.get("devType") is None and dev_type is not None:
            entry["devType"] = dev_type

        if classification.family is DeviceFamily.UNKNOWN:
            return False

        if classification.family is DeviceFamily.PLUG:
            self._data_cache["plugs"] = _merge_subdevice_list(
                self._data_cache.get("plugs"), [entry]
            )
            self._data_cache["plug"] = self._data_cache["plugs"]
            return True
        if classification.family in (DeviceFamily.CT, DeviceFamily.SMARTMETER, DeviceFamily.COLLECTOR):
            key = (
                "collectors"
                if classification.family is DeviceFamily.COLLECTOR
                else "cts"
            )
            self._data_cache[key] = _merge_subdevice_list(
                self._data_cache.get(key), [entry]
            )
            return True
        return False

    def _capture_device_meta(self, raw_data: dict, body: dict) -> None:
        """Extract deviceType and firmware version from MQTT payload to update HA device registry (Ü2)."""
        changed = False
        device_type = raw_data.get("deviceType")
        if device_type is not None and self._device_type is None:
            try:
                self._device_type = int(device_type)
            except (TypeError, ValueError, OverflowError):
                _LOGGER.debug("Ignoring invalid host deviceType")
            else:
                changed = True
        soft_ver = body.get("softver")
        if soft_ver is not None and soft_ver != self._soft_ver:
            self._soft_ver = str(soft_ver)
            changed = True
        if changed:
            asyncio.create_task(self._update_device_registry())

    async def _update_device_registry(self) -> None:
        """Update HA device registry with model name and firmware version (Ü3)."""
        from homeassistant.helpers import device_registry as dr
        registry = dr.async_get(self.hass)
        model = DEVICE_TYPE_MODEL_MAP.get(self._device_type or 0, DEFAULT_MODEL)
        identifier = self._device_sn or self.config_entry_id
        device = registry.async_get_device(identifiers={(DOMAIN, identifier)})
        if device and device.config_entries != {self.config_entry_id}:
            _LOGGER.warning("Skipping device metadata update: config-entry ownership is ambiguous")
            return
        if device:
            registry.async_update_device(device.id, model=model, sw_version=self._soft_ver)
            _LOGGER.debug("Device registry updated: model=%s sw_version=%s", model, self._soft_ver)

    def _trigger_reauth(self, reason: str) -> None:
        """Initiate a re-authentication flow in HA (Re-Auth feature)."""
        if self._reauth_started:
            return
        self._reauth_started = True
        _LOGGER.warning("Triggering re-authentication: %s", reason)
        from homeassistant.config_entries import SOURCE_REAUTH
        self.hass.async_create_task(
            self.hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": SOURCE_REAUTH, "entry_id": self.config_entry_id},
                data={},
            )
        )

    def _entity_keys_for_subdevice(self, sn: str) -> list[str]:
        """Return all registered entity keys (unique_ids) belonging to a sub-device SN."""
        return [
            sensor_id
            for sensor_id, entity in self._sensors.items()
            if getattr(entity, "_plug_sn", None) == sn or getattr(entity, "_sm_sn", None) == sn
        ]

    def child_identity_allowed(self, sn: str) -> bool:
        """Do not recreate children whose persisted identity could not migrate."""
        migration = getattr(self, "_child_migration", None)
        return migration is None or migration.allows(sn)

    def _child_membership(self) -> ChildDiscoveryState:
        """Return discovery state, adapting minimal test coordinators if needed."""
        state = getattr(self, "_child_discovery_state", None)
        if (
            state is None
            or state.known_children is not self._known_plugs
            or state.expansion_batteries is not self._expansion_battery_sns
            or state.missing_since is not self._subdevice_missing_since
        ):
            state = ChildDiscoveryState(
                known_children=self._known_plugs,
                expansion_batteries=self._expansion_battery_sns,
                missing_since=self._subdevice_missing_since,
            )
            self._child_discovery_state = state
        return state

    def _remove_subdevice_from_ha(self, sn: str) -> None:
        """Remove an unbound sub-device and all its entities from Home Assistant.

        Removing the *device* from the registry removes all of its entities in one go
        and also drops the (now orphaned) device card — cleaner than calling
        `async_remove(force_remove=True)` on every entity individually, which left the
        empty device behind.
        """
        if not self.child_identity_allowed(sn):
            return
        try:
            from homeassistant.helpers import device_registry as dr
            dev_reg = dr.async_get(self.hass)
            # Identifier must match JackerySubDeviceSensor._attr_device_info
            host = self._device_sn or self.config_entry_id
            device = dev_reg.async_get_device(identifiers={(DOMAIN, child_device_identifier(host, sn))})
            if device is not None and device.config_entries != {self.config_entry_id}:
                _LOGGER.warning("Skipping child device removal: config-entry ownership is ambiguous")
                return
            if device is not None:
                dev_reg.async_remove_device(device.id)
                _LOGGER.info("Sub-device %s unbound — removed from HA device registry.", sn)
        except Exception as err:  # registry not available (e.g. during teardown/tests)
            _LOGGER.warning("Could not remove sub-device %s from device registry: %s", sn, err)

        # Drop all in-memory references so the device can be re-discovered cleanly
        self._child_membership().remove(sn)
        self._subdevice_last_seen.pop(sn, None)
        for sensor_id in self._entity_keys_for_subdevice(sn):
            self.unregister_sensor(sensor_id)

    def _check_for_new_plugs(self, data: dict) -> None:
        """Check and sync plugs/CTs/collectors (add new, remove old)."""
        self._update_subdevice_availability()
        all_devices = []
        for key in ("plugs", "plug", "cts", "collectors"):
            items = data.get(key)
            if isinstance(items, list):
                all_devices.extend(items)

        if not all_devices:
            return

        current_sns = set()
        for plug in all_devices:
            sn = plug.get("deviceSn") or plug.get("sn")
            if sn:
                current_sns.add(sn)

        changes = self._child_membership().reconcile(
            current_sns,
            now=time.time(),
            deletion_timeout=OFFLINE_TIMEOUT,
        )
        for sn in changes.reappeared:
            _LOGGER.info("Sub-device %s reappeared, cancelling deletion.", sn)
        for sn in changes.newly_missing:
            _LOGGER.info(
                "Sub-device %s missing, starting %ss deletion timer...",
                sn,
                OFFLINE_TIMEOUT,
            )
        for sn in changes.due_for_removal:
            _LOGGER.info(
                "Sub-device %s missing for >%ss. Removing.", sn, OFFLINE_TIMEOUT
            )
            self._remove_subdevice_from_ha(sn)

        # 3. Add newly discovered devices
        new_entities = []
        new_switch_entities = []
        for plug in all_devices:
            sn = plug.get("deviceSn") or plug.get("sn")
            classification = classify_device(plug)
            dev_type = classification.dev_type
            sub_type = plug.get("subType")

            # Match the supported point-update/static-switch types. Unknown
            # metadata remains cached but must not invent writable plug entities.
            entity_spec = child_entity_spec(classification)
            if entity_spec is None:
                continue

            if sn and sn not in self._known_plugs and self.child_identity_allowed(sn):
                _LOGGER.info(f"Discovered new sub-device: {sn} (devType={dev_type}, subType={sub_type})")
                self._child_membership().register(sn)

                if hasattr(self, "config_entry_id"):
                    sensor_group = entity_spec.sensor_group
                    data_key = entity_spec.data_key
                    assert data_key is not None

                    group_config = SUBDEVICE_SENSORS.get(sensor_group, {})
                    for sensor_key, sensor_cfg in group_config.items():
                        entity = JackerySubDeviceSensor(
                            plug_sn=sn,
                            dev_type=dev_type,
                            sensor_key=sensor_key,
                            sensor_config=sensor_cfg,
                            coordinator=self,
                            config_entry_id=self.config_entry_id,
                            data_key=data_key,
                            sensor_group=sensor_group,
                        )
                        new_entities.append(entity)

                    if entity_spec.create_plug_switch:
                        from .switch import JackeryPlugSwitch
                        switch_entity = JackeryPlugSwitch(
                            plug_sn=sn,
                            dev_type=dev_type,
                            coordinator=self,
                            config_entry_id=self.config_entry_id
                        )
                        new_switch_entities.append(switch_entity)

        if new_entities and self.add_entities_callback:
            self.add_entities_callback(new_entities)
        if new_switch_entities and self.add_switch_entities_callback:
            self.add_switch_entities_callback(new_switch_entities)

    def _check_for_new_expansion_batteries(self) -> None:
        """Create sensors for expansion batteries discovered via type-23 messages."""
        exp_bats = self._data_cache.get("expansion_batteries")
        if not exp_bats or not hasattr(self, "config_entry_id"):
            return
        new_entities = []
        for sn in exp_bats:
            if sn not in self._known_plugs and self.child_identity_allowed(sn):
                self._child_membership().register(sn, expansion_battery=True)
                _LOGGER.info(f"Discovered expansion battery: {sn}")
                group_config = SUBDEVICE_SENSORS.get("expansion_battery", {})
                exp_data = exp_bats.get(sn, {})
                for sensor_key, sensor_cfg in group_config.items():
                    entity = JackerySubDeviceSensor(
                        plug_sn=sn,
                        dev_type=1,
                        sensor_key=sensor_key,
                        sensor_config=sensor_cfg,
                        coordinator=self,
                        config_entry_id=self.config_entry_id,
                        use_expansion=True,
                        sensor_group="expansion_battery",
                    )
                    # Pre-initialize value so the entity shows the correct reading immediately
                    # when added to HA rather than briefly showing "unknown" (null in charts).
                    pre_val = exp_data.get(sensor_cfg.get("key"))
                    if pre_val is not None:
                        try:
                            entity._attr_native_value = float(pre_val) * sensor_cfg.get("scale", 1)
                        except (TypeError, ValueError):
                            entity._attr_available = False
                    else:
                        entity._attr_available = False
                    new_entities.append(entity)
        if new_entities and self.add_entities_callback:
            self.add_entities_callback(new_entities)

    def get_subdevices(self) -> list[dict[str, Any]]:
        """Return latest sub-device list from cache."""
        plugs = self._data_cache.get("plugs") or self._data_cache.get("plug")
        if isinstance(plugs, list):
            return [p for p in plugs if isinstance(p, dict)]
        cts = self._data_cache.get("cts")
        if isinstance(cts, list):
            return [p for p in cts if isinstance(p, dict)]
        return []

    def get_plug_item(self, plug_sn: str) -> dict[str, Any] | None:
        """Return cached plug item by SN, or None if not found."""
        plugs = self._data_cache.get("plugs") or self._data_cache.get("plug")
        if not isinstance(plugs, list):
            return None
        return next(
            (
                p for p in plugs
                if isinstance(p, dict) and (p.get("deviceSn") == plug_sn or p.get("sn") == plug_sn)
            ),
            None,
        )

    async def async_control_subdevice_switch(self, plug_sn: str, dev_type: int, is_on: bool) -> None:
        """Control sub-device switch via type 103."""
        if not self._device_sn:
            _LOGGER.warning("Cannot control sub-device: device SN not discovered")
            return

        topic = action_topic(self._topic_root, self._device_sn)
        ts = int(time.time())
        payload = build_subdevice_switch(
            message_id=random.randint(1000, 9999),
            timestamp=ts,
            token=self._token,
            device_serial=plug_sn,
            device_type=dev_type,
            is_on=is_on,
        )

        await self._mqtt_transport.async_publish(topic, payload)

    async def async_control_main_device(self, params: dict[str, Any]) -> None:
        """Control main device via type 1, cmd 5."""
        if not self._device_sn:
            _LOGGER.warning("Cannot control main device: device SN not discovered")
            return

        topic = action_topic(self._topic_root, self._device_sn)
        ts = int(time.time())
        payload = build_main_control(
            message_id=random.randint(1000, 9999),
            timestamp=ts,
            token=self._token,
            params=params,
        )

        await self._mqtt_transport.async_publish(topic, payload)

    def _calculate_energy_flow(self, data: dict) -> dict:
        """Normalize/cache runtime inputs, then delegate pure energy calculation."""
        try:
            data.update(normalize_payload_fields(data))
            freshness: dict[str, SourceFreshness] | None = None
            if self is not None:
                now = time.time()
                freshness = {}
                for array in ("cts", "collectors"):
                    items = data.get(array)
                    if not isinstance(items, list):
                        continue
                    for item in items:
                        if not isinstance(item, dict) or (sn := _subdevice_sn(item)) is None:
                            continue
                        seen = self._subdevice_last_seen.get(sn)
                        freshness[sn] = SourceFreshness(
                            available=self._subdevice_is_available(sn, now),
                            activity_age=now - seen if seen is not None else None,
                        )
            selected = select_grid_source(data, freshness)
            calculate_energy_flow(data, selected)
            if self is not None:
                self._runtime_state.record_energy_source("grid", selected.metadata())

        except Exception as e:
            _LOGGER.error(f"Error calculating energy flow: {e}")

        return data

    def _subdevice_is_available(self, sn: str, now: float) -> bool:
        """Apply the existing per-child timeout and cumulative-energy exception."""
        return self._runtime_state.child_is_available(
            sn,
            now,
            timeout=OFFLINE_TIMEOUT,
            retain_after_first_seen=sn in self._expansion_battery_sns,
        )

    def _update_subdevice_availability(self) -> None:
        """Check child MQTT health independently of discovery and incoming traffic."""
        now = time.time()
        for sn in list(self._known_plugs):
            last_seen = self._subdevice_last_seen.get(sn, 0)
            if last_seen == 0 and (now - self._start_time) < OFFLINE_TIMEOUT:
                continue
            is_available = self._subdevice_is_available(sn, now)
            for sensor_id in self._entity_keys_for_subdevice(sn):
                # HTTP registration keys share the child SN, but health is HTTP-owned.
                if sensor_id.startswith("http_"):
                    continue
                entity = self._sensors.get(sensor_id)
                if entity is None or entity.available == is_available:
                    continue
                entity._attr_available = is_available
                entity.async_write_ha_state()
                if not is_available:
                    _LOGGER.debug("Sub-device %s offline (last seen %.0fs ago)", sn, now - last_seen)

    def _distribute_data(self, data: dict) -> None:
        """Distribute MQTT data only to entities supporting that callback."""
        # HTTP-only sensors share this registry; callbacks may unregister entities.
        for entity in list(self._sensors.values()):
            update = getattr(entity, "_update_from_coordinator", None)
            if callable(update):
                sn = getattr(entity, "_plug_sn", None)
                if sn is not None and not self._subdevice_is_available(sn, time.time()):
                    # Cached values must not undo a child's timeout during fan-out.
                    if entity.available:
                        entity._attr_available = False
                        entity.async_write_ha_state()
                    continue
                update(data)

    def _mark_all_offline(self) -> None:
        """Mark MQTT entities offline, preserving independent HTTP and energy counters."""
        for entity in list(self._sensors.values()):
            if not callable(getattr(entity, "_update_from_coordinator", None)):
                continue
            if getattr(entity, "_plug_sn", None) in self._expansion_battery_sns:
                continue
            if entity.available:
                entity._attr_available = False
                entity.async_write_ha_state()

    async def _periodic_data_request(self) -> None:
        """Send periodic poll requests (type-25, type-105, type-100)."""
        _LOGGER.info("Starting periodic data polling for %s...", self._device_sn)

        # Ü8: Send initial poll immediately so sensors populate before the first sleep.
        # Small delay lets subscriptions settle first.
        await asyncio.sleep(2)
        if self._device_sn:
            await self._send_poll_requests()

        while True:
            try:
                self._update_subdevice_availability()
                if self._runtime_state.host_is_stale(time.time(), OFFLINE_TIMEOUT):
                    self._mark_all_offline()
                elif self._data_cache:
                    # Child expiry can change the energy source between messages.
                    # Reuse this timer; update only changed derived grid/home entities.
                    previous = {key: self._data_cache.get(key) for key in ("calc_grid_net_power", "calc_home_power")}
                    self._calculate_energy_flow(self._data_cache)
                    changed = {key for key, value in previous.items() if self._data_cache.get(key) != value}
                    for sensor_id, key in (("grid_net_power", "calc_grid_net_power"), ("home_power", "calc_home_power")):
                        entity = self._sensors.get(sensor_id)
                        if key in changed and isinstance(entity, JackerySensor):
                            entity._update_from_coordinator(self._data_cache)

                # Re-auth heuristic: the device stays completely silent when it rejects
                # the token (it does not answer with an error). If we have been polling
                # for REAUTH_HINT_TIMEOUT seconds without a single reply, the token
                # (or the configured SN) is most likely wrong.
                if (
                    not self._ever_received
                    and self._device_sn
                    and time.time() - self._start_time > REAUTH_HINT_TIMEOUT
                ):
                    self._trigger_reauth(
                        f"no device response within {REAUTH_HINT_TIMEOUT}s after setup"
                    )

                if not self._device_sn:
                    _LOGGER.debug("Waiting for device SN discovery...")
                    await asyncio.sleep(5)
                    continue

                await self._send_poll_requests()
                await asyncio.sleep(REQUEST_INTERVAL)

            except asyncio.CancelledError:
                break
            except Exception as e:
                _LOGGER.error("Error in polling task: %s", e)
                await asyncio.sleep(REQUEST_INTERVAL)

    async def _send_poll_requests(self) -> None:
        """Send type-25, throttled type-105, and type-100 poll requests."""
        if not self._device_sn:
            return
        topic = action_topic(self._topic_root, self._device_sn)
        ts = int(time.time())

        # 1. Poll device status (type-25)
        try:
            payload_25 = build_status_request(
                message_id=random.randint(1000, 9999), timestamp=ts, token=self._token
            )
            await self._mqtt_transport.async_publish(topic, payload_25)
        except Exception as e:
            _LOGGER.warning("Error polling device status (type-25): %s", e)

        # 1b. Read-all-settings request (type-2). Some firmware answers this with a
        # settings block that type-25 does not contain; harmless when unsupported.
        try:
            payload_2 = build_settings_request(
                message_id=random.randint(1000, 9999), timestamp=ts, token=self._token
            )
            await self._mqtt_transport.async_publish(topic, payload_2)
        except Exception as e:
            _LOGGER.debug("Error sending read-all-settings request (type-2): %s", e)

        # 2. Poll full system state (type-105) every 3 cycles ≈ 30 s
        self._poll_105_counter += 1
        if self._poll_105_counter >= 3:
            self._poll_105_counter = 0
            try:
                payload_105 = build_full_state_request(
                    message_id=random.randint(1000, 9999), timestamp=ts, token=self._token
                )
                await self._mqtt_transport.async_publish(topic, payload_105)
                _LOGGER.debug("Sent type-105 poll (full system state)")
            except Exception as e:
                _LOGGER.warning("Error polling full system state (type-105): %s", e)

        # 3. Poll sub-devices (type-100): CTs (2), SmartMeter 3P (3), Plugs (6)
        try:
            for dev_type in [2, 3, 6]:
                payload_100 = build_subdevice_request(
                    message_id=random.randint(1000, 9999),
                    timestamp=ts,
                    token=self._token,
                    device_type=dev_type,
                )
                await self._mqtt_transport.async_publish(topic, payload_100)
                await asyncio.sleep(0.5)
        except Exception as e:
            _LOGGER.warning("Error polling sub-devices (type-100): %s", e)

        _LOGGER.debug("Sent poll requests to %s", topic)

    def _find_smartmeter_ip_and_sn(self) -> tuple[str | None, str | None]:
        """Find SmartMeter HTO907A IP and SN from MQTT cache (cts list, devType=3, subType=5)."""
        cts = self._data_cache.get("cts") or []
        for item in cts:
            if (
                isinstance(item, dict)
                and classify_device(item).model is DeviceModel.HTO907A
            ):
                ip = item.get("wip")
                sn = item.get("deviceSn") or item.get("sn")
                if ip and sn:
                    return str(ip), str(sn)
        return None, None

    async def _smartmeter_http_poll_loop(self) -> None:
        """Poll SmartMeter HTO907A HTTP API for additional sensor data (voltage, current, etc.)."""
        entry = self.hass.config_entries.async_get_entry(self.config_entry_id)
        poll_interval: int = entry.options.get("smartmeter_poll_interval", 10) if entry else 10
        transport = SmartMeterHttpTransport(async_get_clientsession(self.hass))
        measurement_keys = tuple(
            config["key"] for config in SMARTMETER_HTTP_SENSOR_CONFIGS.values()
        )
        consecutive_failures = 0
        last_sm_sn: str | None = None

        _LOGGER.info("SmartMeter HTTP poll loop started (interval=%ds)", poll_interval)

        while True:
            try:
                ip, sm_sn = self._find_smartmeter_ip_and_sn()
                self._diagnostics_observation.observe_http_target(sm_sn)
                success = False
                outcome = HttpOutcome.NO_TARGET
                if ip and sm_sn:
                    if last_sm_sn and last_sm_sn != sm_sn:
                        self._mark_http_sensors_unavailable(last_sm_sn)
                        consecutive_failures = 0
                    last_sm_sn = sm_sn
                    try:
                        self._diagnostics_observation.record_http_attempt(
                            time.time()
                        )
                        result = await transport.fetch_measurement(ip, measurement_keys)
                        data = result.data
                        outcome = result.outcome
                        success = data is not None
                        if data is not None:
                            if sm_sn not in self._http_sm_sensor_sns_created:
                                await self._create_http_sensors(sm_sn)
                                self._http_sm_sensor_sns_created.add(sm_sn)
                            self._distribute_http_data(sm_sn, data)
                        elif result.status != 200:
                            _LOGGER.debug(
                                "SmartMeter HTTP %d from %s",
                                result.status,
                                result.url,
                            )
                    except SmartMeterHttpRequestError as e:
                        outcome = e.outcome
                        _LOGGER.debug("SmartMeter HTTP poll failed (%s): %s", ip, e)

                if success:
                    consecutive_failures = 0
                elif last_sm_sn:
                    consecutive_failures += 1
                    if consecutive_failures == HTTP_FAILURE_THRESHOLD:
                        _LOGGER.warning(
                            "SmartMeter HTTP unreachable for %d polls — marking sensors unavailable",
                            HTTP_FAILURE_THRESHOLD,
                        )
                        self._mark_http_sensors_unavailable(last_sm_sn)

                self._diagnostics_observation.record_http_outcome(
                    outcome,
                    now=time.time(),
                    consecutive_failures=consecutive_failures,
                    failure_threshold=HTTP_FAILURE_THRESHOLD,
                )

                await asyncio.sleep(poll_interval if ip and sm_sn else 30)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._diagnostics_observation.record_http_outcome(
                    HttpOutcome.UNEXPECTED_ERROR,
                    now=time.time(),
                    consecutive_failures=consecutive_failures,
                    failure_threshold=HTTP_FAILURE_THRESHOLD,
                )
                _LOGGER.error("SmartMeter HTTP poll loop error: %s", e)
                try:
                    await asyncio.sleep(poll_interval)
                except asyncio.CancelledError:
                    break

        if last_sm_sn:
            self._mark_http_sensors_unavailable(last_sm_sn)
        _LOGGER.info("SmartMeter HTTP poll loop stopped")

    async def _create_http_sensors(self, sm_sn: str) -> None:
        """Create JackerySmartMeterHttpSensor entities for the given SmartMeter SN."""
        if not self.add_entities_callback or not self.child_identity_allowed(sm_sn):
            return
        new_entities = [
            JackerySmartMeterHttpSensor(
                sm_sn=sm_sn,
                sensor_key=sensor_key,
                sensor_config=sensor_config,
                coordinator=self,
                config_entry_id=self.config_entry_id,
            )
            for sensor_key, sensor_config in SMARTMETER_HTTP_SENSOR_CONFIGS.items()
        ]
        self.add_entities_callback(new_entities)
        _LOGGER.info("Created %d SmartMeter HTTP sensor entities for SN %s", len(new_entities), sm_sn)

    def _distribute_http_data(self, sm_sn: str, data: dict) -> None:
        """Push HTTP measurement data to registered SmartMeter HTTP sensor entities."""
        for sensor_key in SMARTMETER_HTTP_SENSOR_CONFIGS:
            entity_id = f"http_{sm_sn}_{sensor_key}"
            entity = self._sensors.get(entity_id)
            if entity is not None and hasattr(entity, "_update_from_http"):
                entity._update_from_http(data)

    def _mark_http_sensors_unavailable(self, sm_sn: str) -> None:
        """Mark all HTTP SmartMeter sensors as unavailable (e.g. after connection loss)."""
        for sensor_key in SMARTMETER_HTTP_SENSOR_CONFIGS:
            entity = self._sensors.get(f"http_{sm_sn}_{sensor_key}")
            if entity is not None and hasattr(entity, "mark_http_unavailable"):
                entity.mark_http_unavailable()


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Jackery sensors."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]

    # Register callback for dynamic entities
    def add_entities_callback(new_entities):
        async_add_entities(new_entities)
    coordinator.add_entities_callback = add_entities_callback

    entities = []
    for sensor_id, sensor_config in SENSORS.items():
        if sensor_config.get("json_key") is None:
            continue

        entity = JackerySensor(
            sensor_id=sensor_id,
            coordinator=coordinator,
            config_entry_id=config_entry.entry_id,
        )
        entities.append(entity)

    async_add_entities(entities)


class JackerySensor(SensorEntity):
    """Jackery Sensor."""
    # These entities expose numeric measurements and textual/enum states.
    _attr_native_value: float | str | None
    # ... (Existing JackerySensor Code) ...
    def __init__(
        self,
        sensor_id: str,
        coordinator: JackeryDataCoordinator,
        config_entry_id: str,
    ) -> None:
        """Initialize."""
        self._sensor_id = sensor_id
        self._coordinator = coordinator
        self._config = SENSORS[sensor_id]

        self._attr_translation_key = sensor_id
        self._attr_native_unit_of_measurement = self._config["unit"]
        self._attr_icon = self._config["icon"]
        self._attr_device_class = self._config["device_class"]
        self._attr_state_class = self._config["state_class"]
        # Multi-instance unique ID: includes device_sn so two SolarVaults on the same HA don't clash
        device_sn = coordinator._device_sn or config_entry_id
        self._attr_unique_id = f"jackery_{device_sn}_{sensor_id}"
        self._attr_has_entity_name = True
        if self._config.get("options"):
            self._attr_options = self._config["options"]

        self._attr_device_info = {
            "identifiers": {(DOMAIN, device_sn)},
            "name": "Jackery",
            "manufacturer": "Jackery",
            "model": DEFAULT_MODEL,
        }

    @property
    def should_poll(self) -> bool:
        return False

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._coordinator.register_sensor(self._sensor_id, self)

    async def async_will_remove_from_hass(self) -> None:
        self._coordinator.unregister_sensor(self._sensor_id)
        await super().async_will_remove_from_hass()

    def _update_from_coordinator(self, data: dict) -> None:
        """Receive data from coordinator."""
        # Special handling for EPS Output Power (Bidirectional)
        if self._sensor_id == "eps_output_power":
            out_p = _power_sample(data.get("swEpsOutPw", 0))
            in_p = _power_sample(data.get("swEpsInPw", 0))
            self._attr_available = out_p is not None and in_p is not None
            self._attr_native_value = out_p - in_p if out_p is not None and in_p is not None else None
            self.async_write_ha_state()
            return

        json_key = self._config.get("json_key")
        if not json_key or json_key not in data:
            return

        value = data[json_key]

        if self._sensor_id == "grid_net_power" and value is None:
            # Keep the last value for recovery, but do not present it as current.
            if self.available:
                self._attr_available = False
                self.async_write_ha_state()
            return

        # Process specific conversions
        if self._sensor_id == "battery_temperature":
            # cellTemp is 0.1 C
            try:
                self._attr_native_value = float(value) * 0.1
            except (TypeError, ValueError):
                pass
        elif self._sensor_id == "battery_soc":
             self._attr_native_value = value
        elif self._sensor_id.startswith("solar_power_pv") and isinstance(value, dict):
            # Handle dictionary for PV if it occurs
            if "pvPw" in value:
                self._attr_native_value = value["pvPw"]
            elif "w" in value:
                self._attr_native_value = value["w"]
            elif "power" in value:
                self._attr_native_value = value["power"]
            else:
                self._attr_native_value = str(value)
        else:
            value_map = self._config.get("value_map")
            if value_map is not None:
                # ENUM sensor: translate integer MQTT value to option string (Ü5)
                try:
                    self._attr_native_value = value_map.get(int(value), str(value))
                except (TypeError, ValueError):
                    self._attr_native_value = str(value)
            else:
                scale = self._config.get("scale", 1)
                try:
                    raw = float(value) * scale
                    if self._config.get("unit") is None and scale == 1:
                        self._attr_native_value = int(raw) if raw == int(raw) else raw
                    else:
                        self._attr_native_value = raw
                except (TypeError, ValueError):
                    self._attr_native_value = value

        self._attr_available = True
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {
            "device_sn": self._coordinator._device_sn,
            "raw_key": self._config.get("json_key"),
        }
        # Decode the funcEnable bitmask into named flags for troubleshooting.
        if self._sensor_id == "func_enable":
            raw_bits: Any = self._coordinator._data_cache.get("funcEnable")
            try:
                bits = int(raw_bits)
            except (TypeError, ValueError):
                return attrs
            attrs["func_enable_raw"] = bits
            attrs["func_enable_flags"] = {
                name: bool(bits & (1 << bit)) for bit, name in FUNC_ENABLE_BITS.items()
            }
        return attrs


class JackerySubDeviceSensor(SensorEntity):
    """Jackery Smart Plug / CT Sub-device Sensor."""

    _attr_native_value: float | str | None
    # Every constructor path assigns the string returned by child_unique_id.
    _attr_unique_id: str

    def __init__(
        self,
        plug_sn: str,
        dev_type: int,
        sensor_key: str,
        sensor_config: ChildSensorConfig,
        coordinator: JackeryDataCoordinator,
        config_entry_id: str,
        data_key: str = "plugs",
        use_cts: bool = False,       # legacy — prefer data_key
        use_expansion: bool = False,
        sensor_group: str = "",
    ) -> None:
        """Initialize."""
        self._plug_sn = plug_sn
        self._dev_type = dev_type
        self._sensor_key = sensor_key
        self._sensor_config = sensor_config
        self._coordinator = coordinator
        self._use_expansion = use_expansion
        # data_key determines which cache entry to read sub-device data from.
        # Explicit data_key takes precedence; fall back to use_cts for backward compat.
        if data_key != "plugs":
            self._data_key = data_key
        elif use_cts:
            self._data_key = "cts"
        else:
            self._data_key = "plugs"

        if self._use_expansion:
            device_name = "Battery"
        elif self._data_key == "collectors":
            device_name = "Collector"
        elif self._data_key == "cts":
            device_name = "SmartMeter" if dev_type == 3 else "CT"
        else:
            device_name = "Plug"

        translation_key = f"{sensor_group}_{sensor_key}" if sensor_group else sensor_key
        self._attr_translation_key = translation_key

        self._attr_native_unit_of_measurement = self._sensor_config.get("unit")
        self._attr_icon = self._sensor_config.get("icon")
        self._attr_device_class = self._sensor_config.get("device_class")
        self._attr_state_class = self._sensor_config.get("state_class")
        if self._sensor_config.get("options"):
            self._attr_options = self._sensor_config["options"]

        main_device_id = coordinator._device_sn or config_entry_id
        safe_key = self._sensor_key.replace("_", "") # e.g. energy_import -> energyimport
        self._attr_unique_id = child_unique_id(main_device_id, plug_sn, device_name.lower(), safe_key)
        self._attr_has_entity_name = True

        self._attr_device_info = {
            "identifiers": {(DOMAIN, child_device_identifier(main_device_id, plug_sn))},
            "via_device": (DOMAIN, main_device_id),
            "name": f"Jackery {device_name} {plug_sn}",
            "manufacturer": "Jackery",
            "model": f"Sub-device Type {dev_type}",
        }

    @property
    def should_poll(self) -> bool:
        return False

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Register with coordinator using a unique ID format
        self._coordinator.register_sensor(self._attr_unique_id, self)

    async def async_will_remove_from_hass(self) -> None:
        self._coordinator.unregister_sensor(self._attr_unique_id)
        await super().async_will_remove_from_hass()

    def _update_from_coordinator(self, data: dict) -> None:
        """Receive data from coordinator."""
        if self._use_expansion:
            exp_data = (data.get("expansion_batteries") or {}).get(self._plug_sn)
            if not exp_data:
                return
            val = exp_data.get(self._sensor_config.get("key"))
            if val is None:
                return
            try:
                scale = self._sensor_config.get("scale", 1)
                self._attr_native_value = float(val) * scale
                self._attr_available = True
                self.async_write_ha_state()
            except (TypeError, ValueError):
                pass
            return

        source = data.get(self._data_key)
        if self._data_key == "plugs":
            source = source or data.get("plug")
        if not source or not isinstance(source, list):
            return

        my_plug = next((p for p in source if (p.get("sn") == self._plug_sn or p.get("deviceSn") == self._plug_sn)), None)
        if not my_plug:
            return

        self._raw_data = dict(my_plug)

        target_key = self._sensor_config.get("key")

        # Direct field access: ct_3phase (HTO907A, cts, devType=3) and
        # collector (HTO910A, collectors, devType=4) — no subType phase mapping.
        is_direct_access = (
            (self._data_key == "cts" and self._dev_type == 3)
            or self._data_key == "collectors"
        )
        if is_direct_access:
            val = my_plug.get(target_key)
            if val is None:
                return
            options = self._sensor_config.get("options")
            if options is not None:
                # ENUM sensor: map integer value to option key.
                # options_offset shifts 1-based MQTT values (e.g. commMode: 1=LAN, 2=Cloud)
                # to 0-based list indices. Default offset=0 for 0-based values (commState).
                try:
                    offset = self._sensor_config.get("options_offset", 0)
                    idx = int(float(val)) - offset
                    self._attr_native_value = options[idx] if 0 <= idx < len(options) else str(val)
                except (TypeError, ValueError, IndexError):
                    self._attr_native_value = str(val)
            else:
                scale = self._sensor_config.get("scale", 1)
                try:
                    raw = float(val) * scale
                    if self._sensor_config.get("unit") is None and scale == 1:
                        self._attr_native_value = int(raw) if raw == int(raw) else raw
                    else:
                        self._attr_native_value = raw
                except (TypeError, ValueError):
                    self._attr_native_value = val
            self._attr_available = True
            self.async_write_ha_state()
            return

        val = my_plug.get(target_key)

        # CT phase mapping by subType (1=A, 2=B, 3=C, 4=Total, 5=Net dual-circuit)
        if self._data_key == "cts" and target_key in {"phasePw", "phaseEgy"}:
            sub_type = my_plug.get("subType")
            if target_key == "phasePw":
                if sub_type == 1:
                    val = my_plug.get("AphasePw") or my_plug.get("aPhasePw")
                elif sub_type == 2:
                    val = my_plug.get("BphasePw") or my_plug.get("bPhasePw")
                elif sub_type == 3:
                    # C 相（单相：A+B 路）
                    val = my_plug.get("CphasePw") or my_plug.get("cPhasePw")
                    if not val:
                        a_pw = my_plug.get("AphasePw") or my_plug.get("aPhasePw") or 0
                        b_pw = my_plug.get("BphasePw") or my_plug.get("bPhasePw") or 0
                        if any(v is not None for v in [a_pw, b_pw]):
                            try:
                                val = float(a_pw) + float(b_pw)
                            except (TypeError, ValueError, OverflowError):
                                return
                else:
                    val = my_plug.get("TphasePw") or my_plug.get("tPhasePw")
            else:
                if sub_type == 1:
                    val = my_plug.get("AphaseEgy") or my_plug.get("aPhaseEgy")
                elif sub_type == 2:
                    val = my_plug.get("BphaseEgy") or my_plug.get("bPhaseEgy")
                elif sub_type == 3:
                    # C 相（单相：A+B 路）
                    val = my_plug.get("CphaseEgy") or my_plug.get("cPhaseEgy")
                    if not val:
                        a_egy = my_plug.get("AphaseEgy") or my_plug.get("aPhaseEgy") or 0
                        b_egy = my_plug.get("BphaseEgy") or my_plug.get("bPhaseEgy") or 0
                        if any(v is not None for v in [a_egy, b_egy]):
                            try:
                                val = float(a_egy) + float(b_egy)
                            except (TypeError, ValueError, OverflowError):
                                return
                else:
                    val = my_plug.get("TphaseEgy") or my_plug.get("tPhaseEgy")
                # If subtype energy is zero/None but total is non-zero, fall back to the single non-zero phase
                if not val:
                    total_egy = my_plug.get("TphaseEgy") or my_plug.get("tPhaseEgy")
                    if total_egy:
                        a_egy = my_plug.get("AphaseEgy") or my_plug.get("aPhaseEgy") or 0
                        b_egy = my_plug.get("BphaseEgy") or my_plug.get("bPhaseEgy") or 0
                        c_egy = my_plug.get("CphaseEgy") or my_plug.get("cPhaseEgy") or 0
                        non_zero = [v for v in [a_egy, b_egy, c_egy] if v]
                        if len(non_zero) == 1:
                            val = non_zero[0]

        # Fallback logic for specific keys if needed (like Power)
        if val is None:
             if target_key == "outPw":
                 val = my_plug.get("power")
             elif target_key == "TphasePw":
                 # Accept alternate key casing and sum phase powers if needed
                 val = my_plug.get("tPhasePw")
                 if val is None:
                     a_pw = my_plug.get("AphasePw") or my_plug.get("aPhasePw") or 0
                     b_pw = my_plug.get("BphasePw") or my_plug.get("bPhasePw") or 0
                     c_pw = my_plug.get("CphasePw") or my_plug.get("cPhasePw") or 0
                     if any(v is not None for v in [a_pw, b_pw, c_pw]):
                         val = float(a_pw) + float(b_pw) + float(c_pw)
             elif target_key == "TphaseEgy":
                 # Total forward active energy
                 val = my_plug.get("tPhaseEgy")
                 if val is None:
                     a_egy = my_plug.get("AphaseEgy") or my_plug.get("aPhaseEgy") or 0
                     b_egy = my_plug.get("BphaseEgy") or my_plug.get("bPhaseEgy") or 0
                     c_egy = my_plug.get("CphaseEgy") or my_plug.get("cPhaseEgy") or 0
                     if any(v is not None for v in [a_egy, b_egy, c_egy]):
                         val = float(a_egy) + float(b_egy) + float(c_egy)
             elif target_key == "TnphaseEgy":
                 # Total reverse active energy
                 val = my_plug.get("tnPhaseEgy")
                 if val is None:
                     an_egy = my_plug.get("AnphaseEgy") or my_plug.get("anPhaseEgy") or 0
                     bn_egy = my_plug.get("BnphaseEgy") or my_plug.get("bnPhaseEgy") or 0
                     cn_egy = my_plug.get("CnphaseEgy") or my_plug.get("cnPhaseEgy") or 0
                     if any(v is not None for v in [an_egy, bn_egy, cn_egy]):
                         val = float(an_egy) + float(bn_egy) + float(cn_egy)

        if val is not None:
            try:
                scale = self._sensor_config.get("scale", 1)
                raw = float(val) * scale
                if self._sensor_config.get("unit") is None and scale == 1:
                    self._attr_native_value = int(raw) if raw == int(raw) else raw
                else:
                    self._attr_native_value = raw
                self._attr_available = True
                self.async_write_ha_state()
            except (TypeError, ValueError):
                pass

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        raw = getattr(self, "_raw_data", None) or {}
        attrs: dict[str, Any] = {
            "device_sn": self._plug_sn,
            "dev_type": self._dev_type,
            "sub_type": raw.get("subType"),
            "sensor_key": self._sensor_key,
            "comm_state": raw.get("commState"),
            "name": raw.get("name") or raw.get("scanName"),
        }
        if self._data_key in ("cts", "collectors"):
            # Human readable meter hardware name (diagnostic only)
            sub_type: Any = raw.get("subType")
            attrs["sub_type_label"] = CT_SUBTYPE_MAP.get(sub_type)
        if self._data_key == "cts" and self._dev_type == 3:
            # SmartMeter 3P (HTO907A)
            attrs.update({
                "import_l1_w": raw.get("aPhasePw"),
                "import_l2_w": raw.get("bPhasePw"),
                "import_l3_w": raw.get("cPhasePw"),
                "import_total_w": raw.get("tPhasePw"),
                "export_l1_w": raw.get("anPhasePw"),
                "export_l2_w": raw.get("bnPhasePw"),
                "export_l3_w": raw.get("cnPhasePw"),
                "export_total_w": raw.get("tnPhasePw"),
                "sche_phase": raw.get("schePhase"),
                "fun_form": raw.get("funForm"),
            })
        elif self._data_key == "cts":
            attrs.update({
                "tPhasePw": raw.get("tPhasePw"),
                "tPhaseEgy": raw.get("tPhaseEgy"),
                "tnPhaseEgy": raw.get("tnPhaseEgy"),
            })
        elif self._data_key == "collectors":
            # Meter Collector (HTO910A)
            attrs.update({
                "scan_name": raw.get("scanName"),
                "in_pw": raw.get("inPw"),
                "out_pw": raw.get("outPw"),
            })
        else:
            attrs.update({
                "inPw": raw.get("inPw"),
                "outPw": raw.get("outPw"),
                "sysSwitch": raw.get("sysSwitch") if raw.get("sysSwitch") is not None else raw.get("switchSta"),
                "totalEgy": raw.get("totalEgy"),
            })
        return attrs


class JackerySmartMeterHttpSensor(SensorEntity):
    """Sensor populated via HTTP polling of the SmartMeter HTO907A API."""

    def __init__(
        self,
        sm_sn: str,
        sensor_key: str,
        sensor_config: ChildSensorConfig,
        coordinator: JackeryDataCoordinator,
        config_entry_id: str,
    ) -> None:
        self._sm_sn = sm_sn
        self._sensor_key = sensor_key
        self._sensor_config = sensor_config
        self._coordinator = coordinator

        self._attr_translation_key = f"http_sm_{sensor_key}"
        self._attr_has_entity_name = True
        self._attr_native_unit_of_measurement = sensor_config.get("unit")
        self._attr_device_class = sensor_config.get("device_class")
        self._attr_state_class = sensor_config.get("state_class")
        self._attr_icon = sensor_config.get("icon")
        self._attr_available = False

        main_device_id = coordinator._device_sn or config_entry_id
        self._attr_unique_id = http_unique_id(main_device_id, sm_sn, sensor_key)
        self._attr_device_info = {
            "identifiers": {(DOMAIN, child_device_identifier(main_device_id, sm_sn))},
            "via_device": (DOMAIN, main_device_id),
            "name": f"Jackery SmartMeter {sm_sn}",
            "manufacturer": "Jackery",
            "model": "SmartMeter HTO907A",
        }

    @property
    def should_poll(self) -> bool:
        return False

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._coordinator.register_sensor(f"http_{self._sm_sn}_{self._sensor_key}", self)

    async def async_will_remove_from_hass(self) -> None:
        self._coordinator.unregister_sensor(f"http_{self._sm_sn}_{self._sensor_key}")
        await super().async_will_remove_from_hass()

    def _update_from_http(self, data: dict) -> None:
        field_key = self._sensor_config.get("key")
        val = data.get(field_key)
        if val is None:
            return
        scale = self._sensor_config.get("scale", 1)
        try:
            self._attr_native_value = float(val) * scale
            self._attr_available = True
            self.async_write_ha_state()
        except (TypeError, ValueError):
            pass

    def mark_http_unavailable(self) -> None:
        """Mark sensor unavailable (called after repeated HTTP failures)."""
        if self._attr_available:
            self._attr_available = False
            self.async_write_ha_state()
