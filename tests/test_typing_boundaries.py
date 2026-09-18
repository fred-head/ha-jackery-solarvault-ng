"""Restored configuration must be checked before migration or subscriptions."""

from unittest.mock import AsyncMock, Mock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.jackery import DOMAIN, async_setup_entry
from custom_components.jackery.sensor import JackeryDataCoordinator


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("device_sn", None), ("device_sn", 123), ("device_sn", []),
        ("topic_prefix", None), ("topic_prefix", {}),
        ("token", 123), ("token", ["secret"]),
        ("mqtt_host", False), ("mqtt_host", {"secret": "value"}),
    ],
)
async def test_invalid_restored_config_stops_before_effects(hass, monkeypatch, caplog, key, value):
    entry = MockConfigEntry(domain=DOMAIN, data={
        "device_sn": "HOST", "token": "synthetic", key: value,
    })
    wait = AsyncMock(return_value=True)
    migrate = Mock()
    forward = AsyncMock()
    monkeypatch.setattr("homeassistant.components.mqtt.async_wait_for_mqtt_client", wait)
    monkeypatch.setattr("custom_components.jackery.child_migration.migrate_child_identities", migrate)
    monkeypatch.setattr(hass.config_entries, "async_forward_entry_setups", forward)
    monkeypatch.setattr(JackeryDataCoordinator, "async_start", AsyncMock())

    assert await async_setup_entry(hass, entry) is False
    wait.assert_not_awaited()
    migrate.assert_not_called()
    forward.assert_not_awaited()
    assert entry.entry_id not in hass.data.get(DOMAIN, {})
    assert "secret" not in caplog.text


@pytest.mark.parametrize("data", [
    {},
    {"device_sn": "", "token": None, "mqtt_host": None},
    {"device_sn": "HOST_001", "token": "", "topic_prefix": "custom", "mqtt_host": "legacy"},
])
async def test_optional_config_preserves_setup_values(hass, monkeypatch, data):
    entry = MockConfigEntry(domain=DOMAIN, data=data)
    monkeypatch.setattr("homeassistant.components.mqtt.async_wait_for_mqtt_client", AsyncMock(return_value=True))
    monkeypatch.setattr(hass.config_entries, "async_forward_entry_setups", AsyncMock())
    monkeypatch.setattr(JackeryDataCoordinator, "async_start", AsyncMock())

    assert await async_setup_entry(hass, entry)
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    assert coordinator._device_sn == data.get("device_sn")
    assert coordinator._token == data.get("token")
    assert coordinator._mqtt_host == data.get("mqtt_host")
    assert coordinator._topic_root == data.get("topic_prefix", "hb")
    if not coordinator._device_sn:
        assert coordinator._topic_status == "hb/device/+/status"
