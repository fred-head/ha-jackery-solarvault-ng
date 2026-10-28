"""Home Assistant adapter tests for config-entry diagnostics."""

from __future__ import annotations

import asyncio
import base64
import inspect
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.jackery import DOMAIN
from custom_components.jackery import diagnostics as diagnostics_module
from custom_components.jackery.alert_capture import (
    MAX_TOTAL_DIAGNOSTICS_BYTES,
    AlertCapture,
    _compact_size,
)
from custom_components.jackery.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.jackery.diagnostics_observation import (
    HttpOutcome,
    ProtocolErrorBucket,
    ProtocolRouteBucket,
)
from custom_components.jackery.diagnostics_snapshot import TOP_LEVEL_SECTIONS
from custom_components.jackery.identity import child_device_identifier
from custom_components.jackery.protocol_capture import (
    MAX_PROTOCOL_EXPORT_BYTES,
    ProtocolDiscoveryCapture,
)
from custom_components.jackery.sensor import JackeryDataCoordinator

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

NOW = 2_000.0
CANARIES = (
    "SUPER_SECRET_TOKEN_123",
    "192.0.2.123",
    "PRIVATE_SSID_CANARY",
    "SERIAL_SECRET_CANARY",
    "mqtt/private/topic",
    "https://secret.example/private?token=abc",
    "ENTITY_SECRET_CANARY",
    "DEVICE_SECRET_CANARY",
    "CONFIG_ENTRY_SECRET_CANARY",
    "USER_NAME_SECRET_CANARY",
    "ENTITY_STATE_SECRET_CANARY",
    "RAW_DATA_SECRET_CANARY",
)


def _entry(
    hass,
    *,
    host: str,
    entry_id: str,
    http_enabled: bool = True,
) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id=entry_id,
        unique_id=host,
        title="USER_NAME_SECRET_CANARY",
        data={
            "device_sn": host,
            "token": "SUPER_SECRET_TOKEN_123",
            "topic_prefix": "mqtt/private/topic",
            "mqtt_host": "192.0.2.123",
            "PRIVATE_SSID_CANARY": "https://secret.example/private?token=abc",
        },
        options={
            "smartmeter_http_poll": http_enabled,
            "smartmeter_poll_interval": 30,
        },
    )
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.LOADED)
    return entry


def _coordinator(hass, entry: MockConfigEntry, *, host: str) -> JackeryDataCoordinator:
    coordinator = JackeryDataCoordinator(
        hass,
        "mqtt/private/topic",
        "SUPER_SECRET_TOKEN_123",
        "192.0.2.123",
        host,
    )
    coordinator.config_entry_id = entry.entry_id
    coordinator._subscribed = True
    coordinator._mqtt_transport._unsubscribers.extend((Mock(), Mock()))
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "config": entry.data,
        "coordinator": coordinator,
    }
    return coordinator


def _populate_runtime(coordinator: JackeryDataCoordinator) -> None:
    meter = "SERIAL_SECRET_CANARY"
    coordinator._device_type = 3
    coordinator._soft_ver = "v1.2.3"
    coordinator._runtime_state.start_time = NOW - 100
    coordinator._runtime_state.last_update_time = NOW - 5
    coordinator._runtime_state.ever_received = True
    coordinator._runtime_state.data_cache.update(
        {
            "pvPw": 120,
            "batInPw": 10,
            "batOutPw": 0,
            "calc_batt_net_power": 10,
            "calc_grid_net_power": -20,
            "calc_home_power": 40,
            "cts": [
                {
                    "deviceSn": meter,
                    "devType": 3,
                    "subType": 5,
                    "commMode": 1,
                    "commState": 1,
                    "tPhasePw": 20,
                    "tPhaseEgy": 200,
                    "wip": "192.0.2.123",
                    "wname": "PRIVATE_SSID_CANARY",
                }
            ],
            "PRIVATE_SSID_CANARY": "https://secret.example/private?token=abc",
            "raw_data": {"topic": "mqtt/private/topic"},
        }
    )
    coordinator._runtime_state.subdevice_last_seen[meter] = NOW - 2
    coordinator._runtime_state.power_live_seen["pvPw"] = (2, NOW - 5)
    coordinator._runtime_state.power_106_samples["pvPw"] = (110, NOW - 15)
    coordinator._runtime_state.energy_sources["grid"] = {
        "source": "cts",
        "activity_age": 2,
        "skipped_stale": 0,
        "skipped_missing": 0,
        "reason": "first usable meter",
        "private": "https://secret.example/private?token=abc",
    }
    coordinator._child_discovery_state.register(meter)
    coordinator._http_sm_sensor_sns_created.add(meter)
    coordinator._diagnostics_observation.observe_http_target(meter)
    coordinator._diagnostics_observation.record_http_attempt(NOW - 3)
    coordinator._diagnostics_observation.record_http_outcome(
        HttpOutcome.SUCCESS,
        now=NOW - 2,
        consecutive_failures=0,
        failure_threshold=3,
    )
    coordinator._diagnostics_observation.record_protocol_route(
        ProtocolRouteBucket.TYPE_101
    )
    coordinator._diagnostics_observation.record_protocol_error(
        ProtocolErrorBucket.INVALID_JSON
    )
    coordinator._sensors = {
        "mqtt-listener": SimpleNamespace(
            _update_from_coordinator=Mock(),
            async_write_ha_state=Mock(),
        ),
        "http-listener": SimpleNamespace(
            _update_from_http=Mock(),
            async_write_ha_state=Mock(),
        ),
    }


def _populate_registries(hass, entry: MockConfigEntry, *, host: str) -> None:
    devices = dr.async_get(hass)
    host_device = devices.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, host)},
        name="DEVICE_SECRET_CANARY",
        serial_number="SERIAL_SECRET_CANARY",
        configuration_url="https://secret.example/private?token=abc",
    )
    child_device = devices.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, child_device_identifier(host, "SERIAL_SECRET_CANARY"))},
        name="USER_NAME_SECRET_CANARY",
        via_device=(DOMAIN, host),
    )
    entities = er.async_get(hass)
    sensor = entities.async_get_or_create(
        "sensor",
        DOMAIN,
        "ENTITY_SECRET_CANARY",
        config_entry=entry,
        device_id=child_device.id,
        original_name="USER_NAME_SECRET_CANARY",
        suggested_object_id="ENTITY_SECRET_CANARY",
    )
    entities.async_get_or_create(
        "switch",
        DOMAIN,
        "CONFIG_ENTRY_SECRET_CANARY",
        config_entry=entry,
        device_id=host_device.id,
        disabled_by=er.RegistryEntryDisabler.USER,
    )
    hass.states.async_set(
        sensor.entity_id,
        "ENTITY_STATE_SECRET_CANARY",
        {
            "raw_data": "RAW_DATA_SECRET_CANARY",
            "url": "https://secret.example/private?token=abc",
        },
    )


def _serialized(snapshot) -> str:
    return json.dumps(
        snapshot,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


async def test_config_entry_diagnostics_happy_path_aliases_and_privacy(
    hass,
    monkeypatch,
) -> None:
    entry = _entry(
        hass,
        host="HOST_SERIAL_SECRET",
        entry_id="CONFIG_ENTRY_SECRET_CANARY",
    )
    coordinator = _coordinator(hass, entry, host="HOST_SERIAL_SECRET")
    _populate_runtime(coordinator)
    _populate_registries(hass, entry, host="HOST_SERIAL_SECRET")
    monkeypatch.setattr(diagnostics_module.time, "time", lambda: NOW)

    with patch.object(
        diagnostics_module,
        "build_diagnostics_snapshot",
        wraps=diagnostics_module.build_diagnostics_snapshot,
    ) as builder:
        snapshot = await async_get_config_entry_diagnostics(hass, entry)

    assert builder.call_count == 1
    assert tuple(snapshot) == TOP_LEVEL_SECTIONS
    assert json.loads(_serialized(snapshot)) == snapshot
    assert snapshot["integration"]["manifest_version"] == "2.4.0"
    assert snapshot["host"]["alias"] == "host"
    child_alias = snapshot["children"]["items"][0]["alias"]
    assert child_alias == "child_001"
    assert snapshot["freshness"]["children"][0]["alias"] == child_alias
    assert snapshot["smartmeter"]["mqtt"]["aliases"] == [child_alias]
    assert snapshot["smartmeter"]["http"]["target_alias"] == child_alias
    assert snapshot["smartmeter"]["http"]["created_aliases"] == [child_alias]
    assert snapshot["protocol"]["observation"] == {
        "route_counters": {"type_101": 1},
        "error_counters": {"invalid_json": 1},
        "unknown_message_count": 0,
    }
    assert snapshot["entities"] == {
        "registry_total": 2,
        "by_platform": {
            "button": None,
            "number": None,
            "select": None,
            "sensor": 1,
            "switch": 1,
        },
        "disabled_count": 1,
        "state_counts": {
            "available": 1,
            "unavailable": None,
            "unknown": 1,
        },
        "device_counts": {"child": 1, "host": 1},
        "runtime_listener_counts": {"http": 1, "mqtt": 1},
        "mismatch_count": 1,
    }
    serialized = _serialized(snapshot)
    assert "HOST_SERIAL_SECRET" not in serialized
    for canary in CANARIES:
        assert canary not in serialized


async def test_snapshot_is_private_before_ha_key_redaction(hass) -> None:
    host = "HOST_SERIAL_SECRET"
    entry = _entry(
        hass,
        host=host,
        entry_id="CONFIG_ENTRY_SECRET_CANARY",
    )
    coordinator = _coordinator(hass, entry, host=host)
    _populate_runtime(coordinator)
    _populate_registries(hass, entry, host=host)

    inputs = diagnostics_module.collect_diagnostics_inputs(
        hass,
        entry,
        coordinator,
        manifest_version="2.4.0",
        now=NOW,
    )
    snapshot = diagnostics_module.build_diagnostics_snapshot(inputs, now=NOW)
    serialized = _serialized(snapshot)

    child_alias = snapshot["children"]["items"][0]["alias"]
    assert snapshot["host"]["alias"] == "host"
    assert child_alias == "child_001"
    assert snapshot["freshness"]["children"][0]["alias"] == child_alias
    assert snapshot["smartmeter"]["mqtt"]["aliases"] == [child_alias]
    assert snapshot["smartmeter"]["http"]["target_alias"] == child_alias
    assert snapshot["smartmeter"]["http"]["created_aliases"] == [child_alias]

    entity_ids = {
        registry_entry.entity_id
        for registry_entry in er.async_entries_for_config_entry(
            er.async_get(hass), entry.entry_id
        )
    }
    device_ids = {
        registry_entry.id
        for registry_entry in dr.async_entries_for_config_entry(
            dr.async_get(hass), entry.entry_id
        )
    }
    assert host not in serialized
    for raw_identifier in ("SERIAL_SECRET_CANARY", *entity_ids, *device_ids):
        assert raw_identifier not in serialized
    for canary in CANARIES:
        assert canary not in serialized


async def test_missing_and_neutral_runtime_return_safe_unknowns(hass) -> None:
    missing = _entry(
        hass,
        host="MISSING_HOST_SECRET",
        entry_id="missing-entry",
        http_enabled=False,
    )
    missing.mock_state(hass, ConfigEntryState.NOT_LOADED)

    snapshot = await async_get_config_entry_diagnostics(hass, missing)

    assert tuple(snapshot) == TOP_LEVEL_SECTIONS
    assert snapshot["health"]["status"] == "unavailable"
    assert snapshot["health"]["reasons"] == ["runtime_unavailable"]
    assert snapshot["transport"]["mqtt"]["application_state"] == "stopped"
    assert snapshot["transport"]["mqtt"]["broker_connectivity"] == "unknown"
    assert snapshot["transport"]["mqtt"]["poll_task"] == "absent"
    assert snapshot["smartmeter"]["http"]["health"] == "disabled"
    assert snapshot["children"]["total"] == 0
    assert snapshot["entities"]["registry_total"] == 0
    assert "MISSING_HOST_SECRET" not in _serialized(snapshot)

    partial = _entry(
        hass,
        host="PARTIAL_HOST_SECRET",
        entry_id="partial-entry",
    )
    _coordinator(hass, partial, host="PARTIAL_HOST_SECRET")

    partial_snapshot = await async_get_config_entry_diagnostics(hass, partial)

    assert partial_snapshot["freshness"]["host"]["ever_received"] is False
    assert partial_snapshot["freshness"]["host"]["activity_age_seconds"] is None
    assert partial_snapshot["protocol"]["observation"] == {
        "route_counters": {},
        "error_counters": {},
        "unknown_message_count": 0,
    }
    assert partial_snapshot["smartmeter"]["http"]["last_outcome"] == "unknown"
    assert partial_snapshot["smartmeter"]["http"]["last_attempt_age_seconds"] is None
    assert partial_snapshot["transport"]["mqtt"]["broker_connectivity"] == "unknown"


async def test_unexpected_adapter_error_is_not_runtime_unavailable(hass) -> None:
    entry = _entry(hass, host="HOST", entry_id="programming-error-entry")

    with (
        patch.object(
            diagnostics_module,
            "collect_diagnostics_inputs",
            side_effect=RuntimeError("intentional adapter failure"),
        ),
        pytest.raises(RuntimeError, match="intentional adapter failure"),
    ):
        await async_get_config_entry_diagnostics(hass, entry)


async def test_multi_entry_diagnostics_are_isolated(hass, monkeypatch) -> None:
    monkeypatch.setattr(diagnostics_module.time, "time", lambda: NOW)
    snapshots = []
    raw_identifiers = []
    for index in range(2):
        host = f"HOST_SECRET_{index}"
        child = f"CHILD_SECRET_{index}"
        raw_identifiers.extend((host, child))
        entry = _entry(hass, host=host, entry_id=f"entry-{index}")
        coordinator = _coordinator(hass, entry, host=host)
        coordinator._runtime_state.start_time = NOW - 10
        coordinator._runtime_state.last_update_time = NOW - index
        coordinator._runtime_state.ever_received = True
        coordinator._runtime_state.data_cache["cts"] = [
            {"deviceSn": child, "devType": 3, "subType": 5, "tPhasePw": index}
        ]
        coordinator._runtime_state.subdevice_last_seen[child] = NOW - index
        coordinator._child_discovery_state.register(child)
        for _ in range(index + 1):
            coordinator._diagnostics_observation.record_protocol_route(
                ProtocolRouteBucket.TYPE_106
            )
        er.async_get(hass).async_get_or_create(
            "sensor",
            DOMAIN,
            f"private-{index}",
            config_entry=entry,
        )
        snapshots.append(await async_get_config_entry_diagnostics(hass, entry))

    assert snapshots[0]["protocol"]["observation"]["route_counters"] == {
        "type_106": 1
    }
    assert snapshots[1]["protocol"]["observation"]["route_counters"] == {
        "type_106": 2
    }
    assert snapshots[0]["entities"]["registry_total"] == 1
    assert snapshots[1]["entities"]["registry_total"] == 1
    assert snapshots[0]["children"]["items"][0]["alias"] == "child_001"
    assert snapshots[1]["children"]["items"][0]["alias"] == "child_001"
    first_serialized = _serialized(snapshots[0])
    second_serialized = _serialized(snapshots[1])
    for identifier in raw_identifiers:
        assert identifier not in first_serialized
        assert identifier not in second_serialized


async def test_diagnostics_collection_has_no_runtime_or_registry_side_effects(
    hass,
    monkeypatch,
) -> None:
    entry = _entry(hass, host="HOST", entry_id="side-effect-entry")
    coordinator = _coordinator(hass, entry, host="HOST")
    _populate_runtime(coordinator)
    _populate_registries(hass, entry, host="HOST")
    monkeypatch.setattr(diagnostics_module.time, "time", lambda: NOW)

    cache_before = deepcopy(coordinator._runtime_state.data_cache)
    freshness_before = dict(coordinator._runtime_state.subdevice_last_seen)
    discovery_before = (
        set(coordinator._child_discovery_state.known_children),
        set(coordinator._child_discovery_state.expansion_batteries),
        dict(coordinator._child_discovery_state.missing_since),
    )
    observation_before = coordinator.diagnostics_observation()
    listeners_before = dict(coordinator._sensors)
    tasks_before = asyncio.all_tasks()

    publish = AsyncMock()
    monkeypatch.setattr(coordinator._mqtt_transport, "async_publish", publish)
    send_poll = AsyncMock()
    monkeypatch.setattr(coordinator, "_send_poll_requests", send_poll)
    discover = Mock()
    monkeypatch.setattr(coordinator, "_check_for_new_plugs", discover)
    fan_out = Mock()
    monkeypatch.setattr(coordinator, "_distribute_data", fan_out)
    registry_update = AsyncMock()
    monkeypatch.setattr(coordinator, "_update_device_registry", registry_update)
    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)
    update_entity = Mock(wraps=entity_registry.async_update_entity)
    update_device = Mock(wraps=device_registry.async_update_device)
    monkeypatch.setattr(entity_registry, "async_update_entity", update_entity)
    monkeypatch.setattr(device_registry, "async_update_device", update_device)

    await async_get_config_entry_diagnostics(hass, entry)

    publish.assert_not_awaited()
    send_poll.assert_not_awaited()
    discover.assert_not_called()
    fan_out.assert_not_called()
    registry_update.assert_not_awaited()
    update_entity.assert_not_called()
    update_device.assert_not_called()
    for listener in coordinator._sensors.values():
        listener.async_write_ha_state.assert_not_called()
    assert coordinator._runtime_state.data_cache == cache_before
    assert coordinator._runtime_state.subdevice_last_seen == freshness_before
    assert (
        set(coordinator._child_discovery_state.known_children),
        set(coordinator._child_discovery_state.expansion_batteries),
        dict(coordinator._child_discovery_state.missing_since),
    ) == discovery_before
    assert coordinator.diagnostics_observation() == observation_before
    assert coordinator._sensors == listeners_before
    assert asyncio.all_tasks() == tasks_before


async def test_alert_capture_is_a_separate_opt_in_diagnostics_extension(
    hass,
    monkeypatch,
    caplog,
) -> None:
    entry = _entry(hass, host="HOST_SERIAL_CANARY", entry_id="alert-export-entry")
    coordinator = _coordinator(hass, entry, host="HOST_SERIAL_CANARY")
    monkeypatch.setattr(diagnostics_module.time, "time", lambda: NOW)
    normal_snapshot = await async_get_config_entry_diagnostics(hass, entry)
    assert tuple(normal_snapshot) == TOP_LEVEL_SECTIONS

    hass.config_entries.async_update_entry(
        entry,
        options={**entry.options, "alert_capture_enabled": True},
    )
    topic = "mqtt/private/topic/device/HOST_SERIAL_CANARY/alert"
    capture = AlertCapture(hass, entry.entry_id, topic, "HOST_SERIAL_CANARY")
    await capture.async_load()
    raw_payload = b'{"deviceSn":"SERIAL_RAW_CANARY","unknown":true}'
    capture.observe(
        topic=topic,
        payload=raw_payload,
        qos=1,
        retain=False,
    )
    coordinator._alert_capture = capture

    active_snapshot = await async_get_config_entry_diagnostics(hass, entry)

    assert tuple(active_snapshot) == (*TOP_LEVEL_SECTIONS, "experimental_alert_capture")
    assert {
        key: value for key, value in active_snapshot.items() if key in TOP_LEVEL_SECTIONS
    } == normal_snapshot
    alert_section = active_snapshot["experimental_alert_capture"]
    assert alert_section["enabled"] is True
    assert alert_section["stored_count"] == 1
    event = alert_section["events"][0]
    assert event["topic"] == "{prefix}/device/{host}/alert"
    assert event["payload_encoding"] == "base64"
    assert base64.b64decode(event["payload_base64"]) == raw_payload
    assert "SERIAL_RAW_CANARY" not in _serialized(active_snapshot)
    assert "HOST_SERIAL_CANARY" not in _serialized(active_snapshot)
    assert "mqtt/private/topic" not in _serialized(active_snapshot)
    assert "SERIAL_RAW_CANARY" not in caplog.text
    assert _compact_size(active_snapshot) <= MAX_TOTAL_DIAGNOSTICS_BYTES


async def test_both_raw_capture_extensions_are_bounded_and_separately_versioned(
    hass,
    monkeypatch,
) -> None:
    entry = _entry(hass, host="HOST_SERIAL_CANARY", entry_id="both-captures-entry")
    hass.config_entries.async_update_entry(
        entry,
        options={
            **entry.options,
            "alert_capture_enabled": True,
            "protocol_discovery_enabled": True,
        },
    )
    coordinator = _coordinator(hass, entry, host="HOST_SERIAL_CANARY")
    monkeypatch.setattr(diagnostics_module.time, "time", lambda: NOW)

    protocol_topic = "mqtt/private/topic/device/HOST_SERIAL_CANARY/status"
    protocol = ProtocolDiscoveryCapture(
        hass,
        entry.entry_id,
        "mqtt/private/topic",
        "HOST_SERIAL_CANARY",
    )
    await protocol.async_load()
    for index in range(8):
        assert protocol.observe_invalid(
            topic=protocol_topic,
            payload=f"protocol-{index}-".encode() + b"p" * 4_000,
            now=NOW + index * 3600,
            qos=1,
            retain=False,
        )
    await protocol.async_flush()

    alert_topic = "mqtt/private/topic/device/HOST_SERIAL_CANARY/alert"
    alert = AlertCapture(hass, entry.entry_id, alert_topic, "HOST_SERIAL_CANARY")
    await alert.async_load()
    for index in range(5):
        assert alert.observe(
            topic=alert_topic,
            payload=f"alert-{index}-".encode() + b"a" * 4_000,
            qos=1,
            retain=False,
        )
    await alert.async_flush()

    coordinator._protocol_discovery_capture = protocol
    coordinator._protocol_discovery = protocol.state
    coordinator._alert_capture = alert
    snapshot = await async_get_config_entry_diagnostics(hass, entry)

    assert tuple(snapshot) == (
        *TOP_LEVEL_SECTIONS,
        "experimental_alert_capture",
        "experimental_protocol_capture",
    )
    assert tuple(key for key in snapshot if key in TOP_LEVEL_SECTIONS) == TOP_LEVEL_SECTIONS
    alert_export = snapshot["experimental_alert_capture"]
    protocol_export = snapshot["experimental_protocol_capture"]
    assert alert_export["capture_version"] == 1
    assert protocol_export["capture_version"] == 1
    assert protocol_export["discovery_version"] == 1
    assert alert_export["privacy_warning"]
    assert protocol_export["privacy_warning"]
    assert alert_export["events"][0]["topic"] == "{prefix}/device/{host}/alert"
    assert protocol_export["events"][0]["topic"] == "{prefix}/device/{host}/status"
    assert protocol_export["events"][0]["discovery_reason"] == "invalid_envelope"
    assert base64.b64decode(protocol_export["events"][0]["payload_base64"]).startswith(
        b"protocol-"
    )
    assert _compact_size(alert_export) <= 24 * 1024
    assert _compact_size(protocol_export) <= MAX_PROTOCOL_EXPORT_BYTES
    assert _compact_size(snapshot) <= MAX_TOTAL_DIAGNOSTICS_BYTES
    assert protocol_export["export_omitted_count"] > 0
    assert "HOST_SERIAL_CANARY" not in _serialized(snapshot)
    assert "mqtt/private/topic" not in _serialized(snapshot)


async def test_task_lifecycle_is_normalized_without_task_details(
    hass,
    monkeypatch,
) -> None:
    entry = _entry(hass, host="HOST", entry_id="task-entry")
    coordinator = _coordinator(hass, entry, host="HOST")
    monkeypatch.setattr(diagnostics_module.time, "time", lambda: NOW)

    blocker = asyncio.Event()
    running = asyncio.create_task(blocker.wait())
    cancelled = asyncio.create_task(asyncio.sleep(60))
    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled
    coordinator._data_task = running
    coordinator._smartmeter_http_task = cancelled
    try:
        snapshot = await async_get_config_entry_diagnostics(hass, entry)
    finally:
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running

    assert snapshot["transport"]["mqtt"]["poll_task"] == "running"
    assert snapshot["transport"]["http"]["task"] == "cancelled"
    serialized = _serialized(snapshot)
    assert "Event.wait" not in serialized
    assert "Task" not in serialized
    assert "0x" not in serialized


def test_diagnostics_entrypoint_has_current_ha_signature() -> None:
    signature = inspect.signature(async_get_config_entry_diagnostics)

    assert inspect.iscoroutinefunction(async_get_config_entry_diagnostics)
    assert tuple(signature.parameters) == ("hass", "entry")
