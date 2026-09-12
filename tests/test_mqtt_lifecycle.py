"""Subscription ownership through real coordinator and HA entry lifecycles.

Foundation 3006414 discards both unsubscribe callbacks, never resets
_subscribed, and swallows startup errors. The fake MQTT boundary retains actual
registered callbacks so leaked subscriptions remain observable through delivery.
"""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.jackery import DOMAIN, PLATFORMS
from custom_components.jackery.sensor import JackeryDataCoordinator

from .conftest import FakeMqttMsg


class Subscriptions:
    """Model HA's synchronous cleanup API and independent listener handles."""

    def __init__(self):
        self.records = []
        self.fail_at = None
        self.pause_at = None
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.attempts = 0

    async def subscribe(self, hass, topic, callback, qos):
        self.attempts += 1
        if self.attempts == self.pause_at:
            self.entered.set()
            await self.release.wait()
        if self.attempts == self.fail_at:
            raise HomeAssistantError("synthetic subscribe failure")
        record = SimpleNamespace(topic=topic, callback=callback, qos=qos, active=True, error=None)

        def remove():
            assert record.active, "unsubscribe invoked twice"
            if record.error:
                raise record.error
            record.active = False

        record.remove = Mock(side_effect=remove)
        self.records.append(record)
        return record.remove

    @property
    def active(self):
        return [record for record in self.records if record.active]

    def send(self, host, channel="status", prefix="hb", value=42):
        topic = f"{prefix}/device/{host}/{channel}"
        msg = FakeMqttMsg(topic, json.dumps({"type": 2, "body": {"batSoc": value}}))
        deliveries = 0
        for record in list(self.active):
            if all(a == b or a == "+" for a, b in zip(record.topic.split("/"), topic.split("/"), strict=True)):
                record.callback(msg)
                deliveries += 1
        return deliveries


async def idle():
    await asyncio.Future()


@pytest.fixture
async def runtime(hass, monkeypatch):
    broker = Subscriptions()
    monkeypatch.setattr("homeassistant.components.mqtt.async_subscribe", broker.subscribe)
    c = JackeryDataCoordinator(hass, "hb", "synthetic", "localhost", "HOST_A")
    monkeypatch.setattr(c, "_periodic_data_request", idle)
    yield c, broker
    # Baseline failures must not leave real asyncio tasks alive in the harness.
    for task in (c._data_task, c._smartmeter_http_task):
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def test_stop_releases_every_subscription_once_and_allows_restart(runtime):
    c, broker = runtime
    await c.async_stop()  # zero subscriptions
    await c.async_start()
    await c.async_start()
    assert len(broker.records) == 2
    assert all(record.qos == 1 for record in broker.records)
    assert broker.send("HOST_A") == 1
    assert c._data_cache["batSoc"] == 42
    await c.async_stop()
    await c.async_stop()
    assert not broker.active
    assert all(record.remove.call_count == 1 for record in broker.records)
    assert not c._subscribed
    assert not c._mqtt_unsubscribers
    assert broker.send("HOST_A", value=99) == 0
    assert c._data_cache["batSoc"] == 42
    await c.async_start()
    assert len(broker.records) == 4 and len(broker.active) == 2
    await c.async_stop()
    assert not broker.active


@pytest.mark.parametrize("failed_subscription", [1, 2])
async def test_partial_subscribe_failure_releases_handles_and_propagates(runtime, failed_subscription):
    c, broker = runtime
    broker.fail_at = failed_subscription
    with pytest.raises(HomeAssistantError, match="subscribe failure"):
        await c.async_start()
    assert not broker.active
    assert not c._subscribed and not c._mqtt_unsubscribers
    assert c._data_task is None
    assert all(record.remove.call_count == 1 for record in broker.records)
    broker.fail_at = None
    await c.async_start()
    assert len(broker.active) == 2
    await c.async_stop()


async def test_later_startup_error_releases_subscriptions_and_poll_task(runtime, monkeypatch):
    c, broker = runtime
    with monkeypatch.context() as patcher:
        patcher.setattr(c.hass.config_entries, "async_get_entry", Mock(side_effect=RuntimeError("later startup failure")))
        with pytest.raises(RuntimeError, match="later startup failure"):
            await c.async_start()
    assert not broker.active
    assert c._data_task.done()
    assert not c._subscribed
    await c.async_stop()
    assert all(record.remove.call_count == 1 for record in broker.records)


async def test_cancelled_partial_start_releases_owned_subscription(runtime):
    c, broker = runtime
    broker.pause_at = 2
    start = asyncio.create_task(c.async_start())
    await broker.entered.wait()
    start.cancel()
    with pytest.raises(asyncio.CancelledError):
        await start
    assert not broker.active
    assert broker.records[0].remove.call_count == 1
    assert not c._subscribed


@pytest.mark.parametrize("failure_count", [1, 2])
async def test_cleanup_attempts_all_callbacks_and_reports_errors(runtime, failure_count):
    c, broker = runtime
    await c.async_start()
    for record in broker.records[:failure_count]:
        record.error = RuntimeError("synthetic unsubscribe failure")
    with pytest.raises(ExceptionGroup) as error:
        await c.async_stop()
    assert len(error.value.exceptions) == failure_count
    assert all(record.remove.call_count == 1 for record in broker.records)
    assert len(broker.active) == failure_count  # Failure cannot guarantee removal.
    assert c._data_task.done()
    assert not c._mqtt_unsubscribers and not c._subscribed
    await c.async_stop()
    assert all(record.remove.call_count == 1 for record in broker.records)


async def test_concurrent_start_is_serialized(runtime):
    c, broker = runtime
    broker.pause_at = 1
    first = asyncio.create_task(c.async_start())
    await broker.entered.wait()
    second = asyncio.create_task(c.async_start())
    await asyncio.sleep(0)
    broker.release.set()
    await asyncio.gather(first, second)
    assert len(broker.records) == 2
    await c.async_stop()
    assert not broker.active


async def test_stop_during_start_cleans_completed_start(runtime):
    c, broker = runtime
    broker.pause_at = 2
    start = asyncio.create_task(c.async_start())
    await broker.entered.wait()
    stop = asyncio.create_task(c.async_stop())
    await asyncio.sleep(0)
    broker.release.set()
    await asyncio.gather(start, stop)
    assert not broker.active
    assert not c._subscribed and c._data_task.done()


async def test_cancelled_stop_preserves_cancellation_after_unsubscribe(runtime):
    c, broker = runtime
    entered = asyncio.Event()

    async def slow_task_cleanup():
        try:
            await idle()
        finally:
            entered.set()
            await idle()

    await c.async_start()
    c._smartmeter_http_task = asyncio.create_task(slow_task_cleanup())
    await asyncio.sleep(0)
    stop = asyncio.create_task(c.async_stop())
    await entered.wait()
    stop.cancel()
    with pytest.raises(asyncio.CancelledError):
        await stop
    assert not broker.active
    assert c._data_task.done() and c._smartmeter_http_task.done()
    await c.async_stop()
    assert all(record.remove.call_count == 1 for record in broker.records)


async def test_task_cleanup_failure_does_not_skip_other_task(runtime):
    c, broker = runtime

    async def broken_task():
        try:
            await idle()
        finally:
            raise RuntimeError("synthetic task cleanup failure")

    await c.async_start()
    c._data_task.cancel()
    await asyncio.gather(c._data_task, return_exceptions=True)
    c._data_task = asyncio.create_task(broken_task())
    c._smartmeter_http_task = asyncio.create_task(idle())
    await asyncio.sleep(0)
    with pytest.raises(ExceptionGroup) as error:
        await c.async_stop()
    assert str(error.value.exceptions[0]) == "synthetic task cleanup failure"
    assert c._smartmeter_http_task.done() and c._data_task.done()
    assert not broker.active


@pytest.fixture
async def entries(hass, monkeypatch, enable_custom_integrations):
    broker = Subscriptions()
    monkeypatch.setattr("homeassistant.components.mqtt.async_wait_for_mqtt_client", AsyncMock(return_value=True))
    monkeypatch.setattr("homeassistant.components.mqtt.async_subscribe", broker.subscribe)

    async def idle_poll(self):
        await idle()

    monkeypatch.setattr(JackeryDataCoordinator, "_periodic_data_request", idle_poll)
    monkeypatch.setattr(JackeryDataCoordinator, "_smartmeter_http_poll_loop", idle_poll)
    configs = [MockConfigEntry(domain=DOMAIN, data={"device_sn": host, "token": "synthetic", "topic_prefix": "hb"},
                               unique_id=host, options={"smartmeter_http_poll": True}) for host in ("HOST_A", "HOST_B")]
    yield configs, broker
    for entry in configs:
        if entry.state is ConfigEntryState.LOADED:
            await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.parametrize("order", [(0, 1), (1, 0)])
async def test_real_entries_repeated_reload_delivery_and_http_isolation(hass, entries, order):
    configs, broker = entries
    coordinators = {}
    for index in order:
        entry = configs[index]
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        c = hass.data[DOMAIN][entry.entry_id]["coordinator"]
        c._handle_message = Mock(wraps=c._handle_message)
        coordinators[index] = c
    assert len(broker.active) == 4
    assert {r.topic for r in broker.active} == {f"hb/device/{e.data['device_sn']}/{channel}" for e in configs for channel in ("status", "event")}
    for cycle in range(3):
        for index in order:
            entry, other_entry = configs[index], configs[1 - index]
            old, other = coordinators[index], coordinators[1 - index]
            other_http = other._smartmeter_http_task
            other_calls = other._handle_message.call_count
            other_listeners = dict(other._sensors)
            assert broker.send(entry.data["device_sn"], "event", value=40 + cycle) == 1
            before = old._handle_message.call_count
            assert await hass.config_entries.async_unload(entry.entry_id)
            assert not old._sensors and old._data_task.done() and old._smartmeter_http_task.done()
            assert len(broker.active) == 2
            assert other._smartmeter_http_task is other_http and not other_http.done()
            assert other._sensors == other_listeners
            assert other._handle_message.call_count == other_calls
            assert broker.send(entry.data["device_sn"]) == 0
            assert broker.send(other_entry.data["device_sn"]) == 1
            assert old._handle_message.call_count == before
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()
            current = hass.data[DOMAIN][entry.entry_id]["coordinator"]
            assert current is not old
            current._handle_message = Mock(wraps=current._handle_message)
            coordinators[index] = current
            assert broker.send(entry.data["device_sn"], value=80 + cycle) == 1
            assert current._handle_message.call_count == 1
            assert current._data_cache["batSoc"] == 80 + cycle
            assert old._handle_message.call_count == before
            assert len(broker.active) == 4
    for index in order[::-1]:
        assert await hass.config_entries.async_unload(configs[index].entry_id)
    assert not broker.active
    assert all(record.remove.call_count == 1 for record in broker.records)


async def test_entry_start_failure_unloads_forwarded_platforms_and_can_retry(hass, entries):
    configs, broker = entries
    entry = configs[0]
    entry.add_to_hass(hass)
    broker.fail_at = 2
    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert not broker.active
    assert entry.entry_id not in hass.data[DOMAIN]
    broker.fail_at = None
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    c = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    assert c._sensors
    assert len(broker.active) == 2
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert not c._sensors and not broker.active


async def test_platform_forward_failure_cleans_runtime(hass, entries, monkeypatch):
    configs, broker = entries
    entry = configs[0]
    entry.add_to_hass(hass)
    forward = hass.config_entries.async_forward_entry_setups

    async def partial_forward(config, platforms):
        await forward(config, [PLATFORMS[0]])
        raise RuntimeError("synthetic platform failure")

    with monkeypatch.context() as patcher:
        patcher.setattr(hass.config_entries, "async_forward_entry_setups", partial_forward)
        assert not await hass.config_entries.async_setup(entry.entry_id)
    assert not broker.active
    assert entry.entry_id not in hass.data[DOMAIN]
    assert await hass.config_entries.async_reload(entry.entry_id)
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_unload_error_still_releases_platforms_and_reports_failed_unload(hass, entries, caplog):
    configs, broker = entries
    entry = configs[0]
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    c = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    remove = broker.records[0].remove.side_effect

    def broken_remove():
        remove()
        raise RuntimeError("synthetic error after unsubscribe")

    broker.records[0].remove.side_effect = broken_remove
    assert not await hass.config_entries.async_unload(entry.entry_id)
    assert "Coordinator resource cleanup failed" in caplog.text
    assert not broker.active
    assert not c._sensors
    assert c._data_task.done() and c._smartmeter_http_task.done()
    # HA treats an exception from unload as non-recoverable until restart.
    assert entry.state is ConfigEntryState.FAILED_UNLOAD
    assert entry.entry_id in hass.data[DOMAIN]
    await c.async_stop()  # Coordinator cleanup itself remains idempotent.
    assert all(record.remove.call_count == 1 for record in broker.records)


async def test_actual_ha_reload_replaces_only_its_own_subscriptions(hass, entries):
    configs, broker = entries
    for entry in configs:
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
    other = hass.data[DOMAIN][configs[1].entry_id]["coordinator"]
    other_handles = list(broker.active[2:])
    other_http = other._smartmeter_http_task
    for _ in range(3):
        old = hass.data[DOMAIN][configs[0].entry_id]["coordinator"]
        calls = Mock(wraps=old._handle_message)
        old._handle_message = calls
        assert await hass.config_entries.async_reload(configs[0].entry_id)
        assert len(broker.active) == 4
        assert other._smartmeter_http_task is other_http and not other_http.done()
        assert all(r.active and r.remove.call_count == 0 for r in other_handles)
        assert broker.send("HOST_A") == 1
        assert calls.call_count == 0


async def test_startup_and_cleanup_errors_are_both_observable(runtime, monkeypatch):
    c, broker = runtime

    def fail_after_subscribing(_entry_id):
        broker.records[0].error = RuntimeError("synthetic cleanup failure")
        raise ValueError("synthetic startup failure")

    monkeypatch.setattr(c.hass.config_entries, "async_get_entry", fail_after_subscribing)
    with pytest.raises(ExceptionGroup) as error:
        await c.async_start()
    assert isinstance(error.value.__context__, ValueError)
    assert str(error.value.__context__) == "synthetic startup failure"
    assert len(error.value.exceptions) == 1
    assert all(r.remove.call_count == 1 for r in broker.records)
    assert c._data_task.done()
