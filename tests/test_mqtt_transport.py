"""Direct contract tests for the per-coordinator MQTT transport boundary."""

import json
from unittest.mock import AsyncMock, Mock, call

import pytest

from custom_components.jackery.transport import mqtt as mqtt_transport_module
from custom_components.jackery.transport.mqtt import JackeryMqttTransport


@pytest.fixture
def transport(hass):
    return JackeryMqttTransport(hass)


async def test_subscribes_to_both_topics_with_qos_one(
    transport, monkeypatch
) -> None:
    unsubscribe_status = Mock()
    unsubscribe_event = Mock()
    subscribe = AsyncMock(side_effect=[unsubscribe_status, unsubscribe_event])
    monkeypatch.setattr(mqtt_transport_module.ha_mqtt, "async_subscribe", subscribe)
    callback = Mock()

    await transport.async_subscribe(
        ("hb/device/HOST/status", "hb/device/HOST/event"), callback
    )

    assert subscribe.await_args_list == [
        call(transport.hass, "hb/device/HOST/status", callback, 1),
        call(transport.hass, "hb/device/HOST/event", callback, 1),
    ]
    assert transport.unsubscribe_count == 2


async def test_registered_callback_receives_raw_message(transport, monkeypatch) -> None:
    callbacks = []

    async def subscribe(hass, topic, callback, qos):
        callbacks.append(callback)
        return Mock()

    monkeypatch.setattr(mqtt_transport_module.ha_mqtt, "async_subscribe", subscribe)
    callback = Mock()
    message = object()

    await transport.async_subscribe(("status", "event"), callback)
    callbacks[0](message)

    callback.assert_called_once_with(message)


async def test_publish_serializes_once_with_existing_mqtt_options(
    transport, monkeypatch
) -> None:
    publish = AsyncMock()
    monkeypatch.setattr(mqtt_transport_module.ha_mqtt, "async_publish", publish)
    payload = {"type": 25, "body": None}

    await transport.async_publish("hb/device/HOST/action", payload)

    publish.assert_awaited_once_with(
        transport.hass,
        "hb/device/HOST/action",
        json.dumps(payload),
        0,
        False,
    )


async def test_publish_error_propagates(transport, monkeypatch) -> None:
    publish = AsyncMock(side_effect=RuntimeError("publish failed"))
    monkeypatch.setattr(mqtt_transport_module.ha_mqtt, "async_publish", publish)

    with pytest.raises(RuntimeError, match="publish failed"):
        await transport.async_publish("action", {"type": 1})


async def test_stop_unsubscribes_once_and_is_idempotent(transport, monkeypatch) -> None:
    unsubscribers = [Mock(), Mock()]
    subscribe = AsyncMock(side_effect=unsubscribers)
    monkeypatch.setattr(mqtt_transport_module.ha_mqtt, "async_subscribe", subscribe)
    await transport.async_subscribe(("status", "event"), Mock())

    await transport.async_stop()
    await transport.async_stop()

    for unsubscribe in unsubscribers:
        unsubscribe.assert_called_once_with()
    assert transport.unsubscribe_count == 0


async def test_partial_subscription_failure_cleans_first_handle(
    transport, monkeypatch
) -> None:
    unsubscribe = Mock()
    subscribe = AsyncMock(side_effect=[unsubscribe, RuntimeError("second failed")])
    monkeypatch.setattr(mqtt_transport_module.ha_mqtt, "async_subscribe", subscribe)

    with pytest.raises(RuntimeError, match="second failed"):
        await transport.async_subscribe(("status", "event"), Mock())

    unsubscribe.assert_called_once_with()
    assert transport.unsubscribe_count == 0


async def test_cleanup_attempts_every_handle_before_raising(
    transport, monkeypatch
) -> None:
    failing = Mock(side_effect=RuntimeError("unsubscribe failed"))
    succeeding = Mock()
    subscribe = AsyncMock(side_effect=[failing, succeeding])
    monkeypatch.setattr(mqtt_transport_module.ha_mqtt, "async_subscribe", subscribe)
    await transport.async_subscribe(("status", "event"), Mock())

    with pytest.raises(ExceptionGroup, match="MQTT subscription cleanup failed"):
        await transport.async_stop()

    failing.assert_called_once_with()
    succeeding.assert_called_once_with()
    assert transport.unsubscribe_count == 0


async def test_transport_instances_are_isolated(hass, monkeypatch) -> None:
    first_unsubscribe = Mock()
    second_unsubscribe = Mock()
    subscribe = AsyncMock(side_effect=[first_unsubscribe, second_unsubscribe])
    monkeypatch.setattr(mqtt_transport_module.ha_mqtt, "async_subscribe", subscribe)
    first = JackeryMqttTransport(hass)
    second = JackeryMqttTransport(hass)

    await first.async_subscribe(("first",), Mock())
    await second.async_subscribe(("second",), Mock())
    await first.async_stop()

    first_unsubscribe.assert_called_once_with()
    second_unsubscribe.assert_not_called()
    assert first.unsubscribe_count == 0
    assert second.unsubscribe_count == 1
    await second.async_stop()
