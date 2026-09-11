"""HTTP/MQTT coexistence through real coordinator and entity callbacks."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.jackery import sensor as sensor_module
from custom_components.jackery.sensor import (
    SMARTMETER_HTTP_SENSOR_CONFIGS,
    JackeryDataCoordinator,
    JackerySensor,
    JackerySmartMeterHttpSensor,
)

from .conftest import FakeMqttMsg


@pytest.fixture
async def mixed_sensors(monkeypatch):
    """Register an HTTP entity between two ordinary MQTT entities."""
    coordinator = JackeryDataCoordinator(None, "hb", "testtoken", "localhost", "MAIN")
    battery = JackerySensor("battery_soc", coordinator, "ENTRY")
    http = JackerySmartMeterHttpSensor(
        "METER", "frequency", SMARTMETER_HTTP_SENSOR_CONFIGS["frequency"], coordinator, "ENTRY"
    )
    solar = JackerySensor("solar_power", coordinator, "ENTRY")
    entities = (battery, http, solar)
    for entity in entities:
        # Only HA state persistence is replaced; registration and updates are real.
        monkeypatch.setattr(entity, "async_write_ha_state", Mock())
        await entity.async_added_to_hass()
    try:
        yield coordinator, battery, http, solar
    finally:
        for entity in entities:
            await entity.async_will_remove_from_hass()


@pytest.mark.parametrize("http_state", ["new", "healthy", "failed"])
async def test_mqtt_dispatch_preserves_http_state(mixed_sensors, http_state, caplog):
    coordinator, battery, http, solar = mixed_sensors
    if http_state != "new":
        coordinator._distribute_http_data("METER", {"freq": 50})
    if http_state == "failed":
        coordinator._mark_http_sensors_unavailable("METER")
    http_before = (http.native_value, http.available, http.async_write_ha_state.call_count)

    # Direct dispatch exposes the original AttributeError (the MQTT handler logs it).
    coordinator._distribute_data({"batSoc": 42, "pvPw": 123, "freq": 999})
    assert battery.native_value == 42
    assert solar.native_value == 123
    battery.async_write_ha_state.assert_called_once_with()
    solar.async_write_ha_state.assert_called_once_with()

    # Also exercise message decoding, cache merging and the actual fan-out caller.
    coordinator._handle_message(FakeMqttMsg(
        "hb/device/MAIN/status",
        json.dumps({"type": 2, "body": {"batSoc": 43, "pvPw": 124, "freq": 998}}),
    ))
    assert battery.native_value == 43
    assert solar.native_value == 124
    assert battery.async_write_ha_state.call_count == 2
    assert solar.async_write_ha_state.call_count == 2
    assert (http.native_value, http.available, http.async_write_ha_state.call_count) == http_before
    assert coordinator._smartmeter_http_task is None
    assert "Error handling message" not in caplog.text


async def test_mixed_sensor_registration_removal_and_readdition(mixed_sensors):
    coordinator, battery, http, solar = mixed_sensors
    registered = dict(coordinator._sensors)
    assert list(registered.values()) == [battery, http, solar]

    # Registering the same entity/key twice must not duplicate delivery.
    for key, entity in registered.items():
        coordinator.register_sensor(key, entity)
    coordinator._distribute_data({"batSoc": 42, "pvPw": 123})
    coordinator._distribute_http_data("METER", {"freq": 50})
    for entity in registered.values():
        entity.async_write_ha_state.assert_called_once_with()
        await entity.async_will_remove_from_hass()
    assert coordinator._sensors == {}

    coordinator._distribute_data({"batSoc": 0, "pvPw": 0})
    coordinator._distribute_http_data("METER", {"freq": 0})
    coordinator._mark_http_sensors_unavailable("METER")
    for entity in registered.values():
        entity.async_write_ha_state.assert_called_once_with()
        await entity.async_added_to_hass()
    assert coordinator._sensors == registered

    coordinator._distribute_data({"batSoc": 43, "pvPw": 124})
    coordinator._distribute_http_data("METER", {"freq": 51})
    assert (battery.native_value, solar.native_value, http.native_value) == (43, 124, 51)
    for entity in registered.values():
        assert entity.async_write_ha_state.call_count == 2


@pytest.mark.parametrize("listener", [object(), SimpleNamespace(_update_from_coordinator=None)])
def test_dispatch_skips_listeners_without_callable_mqtt_callback(listener):
    coordinator = JackeryDataCoordinator(None, "hb", "testtoken", "localhost", "MAIN")
    update = Mock()
    coordinator.register_sensor("incompatible", listener)
    coordinator.register_sensor("compatible", SimpleNamespace(_update_from_coordinator=update))
    coordinator._distribute_data({"batSoc": 42})
    update.assert_called_once_with({"batSoc": 42})


def test_dispatch_allows_listener_to_unregister_itself():
    coordinator = JackeryDataCoordinator(None, "hb", "testtoken", "localhost", "MAIN")
    remove = Mock(side_effect=lambda data: coordinator.unregister_sensor("removing"))
    update = Mock()
    coordinator.register_sensor("removing", SimpleNamespace(_update_from_coordinator=remove))
    coordinator.register_sensor("remaining", SimpleNamespace(_update_from_coordinator=update))
    coordinator._distribute_data({"batSoc": 42})
    coordinator._distribute_data({"batSoc": 43})
    remove.assert_called_once_with({"batSoc": 42})
    assert update.call_count == 2
    assert list(coordinator._sensors) == ["remaining"]


def test_dispatch_does_not_hide_callback_programming_errors():
    coordinator = JackeryDataCoordinator(None, "hb", "testtoken", "localhost", "MAIN")
    update = Mock(side_effect=AttributeError("error inside callback"))
    coordinator.register_sensor("broken", SimpleNamespace(_update_from_coordinator=update))
    with pytest.raises(AttributeError, match="error inside callback"):
        coordinator._distribute_data({})


async def test_http_poll_health_and_stop_survive_mqtt_updates(mixed_sensors, monkeypatch):
    """MQTT between real HTTP polls must not reset the three-failure threshold."""
    coordinator, battery, http, solar = mixed_sensors
    entry = SimpleNamespace(options={"smartmeter_http_poll": True, "smartmeter_poll_interval": 10})
    coordinator.hass = SimpleNamespace(config_entries=SimpleNamespace(async_get_entry=Mock(return_value=entry)))
    coordinator._data_cache["cts"] = [
        {"deviceSn": "METER", "devType": 3, "subType": 5, "wip": "192.0.2.1"}
    ]
    # Entities have already been added through their actual lifecycle hooks.
    coordinator._http_sm_sensors_created = True
    response = SimpleNamespace(status=200, json=AsyncMock(return_value={"freq": 50}))
    request = AsyncMock()
    request.__aenter__.return_value = response
    session = SimpleNamespace(get=Mock(return_value=request))
    monkeypatch.setattr(sensor_module, "async_get_clientsession", Mock(return_value=session))
    subscribe = AsyncMock()
    monkeypatch.setattr(sensor_module.ha_mqtt, "async_subscribe", subscribe)
    monkeypatch.setattr(coordinator, "_periodic_data_request", AsyncMock())
    create_task = Mock(wraps=asyncio.create_task)
    monkeypatch.setattr(sensor_module.asyncio, "create_task", create_task)

    paused = asyncio.Queue()
    resume = asyncio.Queue()

    async def poll_pause(delay):
        assert delay == 10
        await paused.put(None)
        await resume.get()

    monkeypatch.setattr(sensor_module.asyncio, "sleep", poll_pause)
    await coordinator.async_start()
    http_task = coordinator._smartmeter_http_task
    try:
        # One success, three consecutive failures, then recovery via HTTP alone.
        for index, (available, value) in enumerate([
            (True, 50), (True, 50), (True, 50), (False, 50), (True, 51)
        ]):
            await paused.get()
            assert (http.available, http.native_value) == (available, value)
            writes = http.async_write_ha_state.call_count
            coordinator._handle_message(FakeMqttMsg(
                "hb/device/MAIN/status",
                json.dumps({"type": 2, "body": {"batSoc": 40 + index, "pvPw": 100 + index, "freq": 999}}),
            ))
            assert battery.native_value == 40 + index
            assert solar.native_value == 100 + index
            assert (http.available, http.native_value) == (available, value)
            assert http.async_write_ha_state.call_count == writes
            await coordinator.async_start()
            assert coordinator._smartmeter_http_task is http_task
            assert create_task.call_count == 2  # One MQTT task and one HTTP task.
            assert subscribe.await_count == 2  # Status and event subscriptions.
            response.status = 200 if index == 3 else 503
            response.json.return_value = {"freq": 51}
            if index < 4:
                await resume.put(None)
    finally:
        await coordinator.async_stop()
    assert http_task.done()
    assert not http.available
    assert session.get.call_count == 5
    assert http.async_write_ha_state.call_count == 4  # Success, failure, recovery, stop.
    for entity in (battery, http, solar):
        await entity.async_will_remove_from_hass()
    assert coordinator._sensors == {}


@pytest.fixture
async def http_poll(mixed_sensors, monkeypatch):
    """Run the production HTTP loop one completed attempt at a time."""
    coordinator, _, http, _ = mixed_sensors
    entry = SimpleNamespace(options={"smartmeter_poll_interval": 10})
    coordinator.hass = SimpleNamespace(config_entries=SimpleNamespace(async_get_entry=Mock(return_value=entry)))
    meter = {"deviceSn": "METER", "devType": 3, "subType": 5, "wip": "192.0.2.1"}
    coordinator._data_cache["cts"] = [meter]
    coordinator._http_sm_sensors_created = True
    response = SimpleNamespace(status=200, json=AsyncMock(return_value={"freq": 50}))
    request = AsyncMock()
    request.__aenter__.return_value = response
    session = SimpleNamespace(get=Mock(return_value=request))
    monkeypatch.setattr(sensor_module, "async_get_clientsession", Mock(return_value=session))
    paused, resume = asyncio.Queue(), asyncio.Queue()

    async def sleep(delay):
        await paused.put(delay)
        await resume.get()

    monkeypatch.setattr(sensor_module.asyncio, "sleep", sleep)
    task = asyncio.create_task(coordinator._smartmeter_http_poll_loop())
    coordinator._smartmeter_http_task = task
    assert await paused.get() == 10
    assert http.available and http.native_value == 50

    async def poll():
        await resume.put(None)
        return await paused.get()

    try:
        yield SimpleNamespace(
            coordinator=coordinator, http=http, meter=meter, response=response,
            request=request, session=session, poll=poll, task=task,
        )
    finally:
        await coordinator.async_stop()
        assert task.done()


@pytest.mark.parametrize("failure", ["status", "timeout", "json", "list", "empty", "nonnumeric"])
async def test_http_invalid_polls_use_failure_threshold_and_recover(http_poll, failure):
    p = http_poll
    if failure == "status":
        p.response.status = 503
    elif failure == "timeout":
        p.request.__aenter__.side_effect = TimeoutError()
    elif failure == "json":
        p.response.json.side_effect = ValueError("invalid JSON")
    else:
        p.response.json.return_value = {"list": [], "empty": {}, "nonnumeric": {"freq": "bad"}}[failure]
    for attempt in range(1, 5):
        assert await p.poll() == 10
        assert p.http.available is (attempt < 3)
        assert p.http.native_value == 50
    p.response.status = 200
    p.request.__aenter__.side_effect = None
    p.response.json.side_effect = None
    p.response.json.return_value = {"freq": 0}
    await p.poll()
    assert p.http.available and p.http.native_value == 0
    assert p.session.get.call_args.kwargs["timeout"].total == 5


async def test_http_success_resets_consecutive_failures(http_poll):
    p = http_poll
    for status in [503, 503, 200, 503, 503]:
        p.response.status = status
        await p.poll()
        assert p.http.available
    p.response.status = 503
    await p.poll()
    assert not p.http.available


async def test_http_lost_address_expires_and_recovers_without_new_entities(http_poll):
    p = http_poll
    registered = dict(p.coordinator._sensors)
    p.meter.pop("wip")
    for attempt in range(1, 4):
        assert await p.poll() == 30
        assert p.http.available is (attempt < 3)
    assert p.session.get.call_count == 1
    p.meter["wip"] = "192.0.2.1"
    assert await p.poll() == 10
    assert p.http.available
    assert p.coordinator._sensors == registered


async def test_http_stop_while_request_pending_marks_unavailable(http_poll):
    p = http_poll
    entered = asyncio.Event()

    async def pending_request():
        entered.set()
        await asyncio.Event().wait()

    p.request.__aenter__.side_effect = pending_request
    # poll() waits for a completed iteration, so run it separately for cancellation.
    waiter = asyncio.create_task(p.poll())
    try:
        await entered.wait()
        await p.coordinator.async_stop()
        assert not p.http.available
        assert p.http.native_value == 50
    finally:
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter


async def test_http_stop_during_unexpected_error_backoff_marks_unavailable(http_poll, monkeypatch):
    p = http_poll
    # Unexpected programming errors retain the existing outer error path;
    # cancellation during that path must still execute health cleanup.
    monkeypatch.setattr(p.coordinator, "_distribute_http_data", Mock(side_effect=RuntimeError("callback error")))
    await p.poll()
    await p.coordinator.async_stop()
    assert not p.http.available


async def test_partial_http_measurements_preserve_existing_field_policy(http_poll):
    p = http_poll
    # A valid partial response is successful source activity. There is no existing
    # per-field timeout policy; omitting freq must not silently invent one.
    p.response.json.return_value = {"volt1": 230}
    for _ in range(4):
        await p.poll()
    assert p.http.available and p.http.native_value == 50


async def test_http_meter_identity_change_retires_old_source_and_return_recovers(http_poll):
    p = http_poll
    p.meter["deviceSn"] = "REPLACEMENT"
    await p.poll()
    assert not p.http.available
    assert p.http.native_value == 50
    p.meter["deviceSn"] = "METER"
    p.response.json.return_value = {"freq": 51}
    await p.poll()
    assert p.http.available and p.http.native_value == 51
