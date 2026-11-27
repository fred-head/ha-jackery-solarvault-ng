"""Integration tests for the Jackery config flow (uses real HA test framework)."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.selector import TextSelector, TextSelectorType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.jackery import DOMAIN

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_USER_INPUT = {
    "device_sn": "TEST001",
    "token": "secret-token",
    "topic_prefix": "hb",
}

_PATCH_MQTT = "homeassistant.components.mqtt.async_wait_for_mqtt_client"


async def _start_flow(hass):
    """Open the config flow and return the FORM result."""
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


# ---------------------------------------------------------------------------
# Initial form
# ---------------------------------------------------------------------------


async def test_shows_user_form(hass):
    """Config flow shows the user input form on first call."""
    result = await _start_flow(hass)

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    assert "flow_id" in result


# ---------------------------------------------------------------------------
# Successful entry creation
# ---------------------------------------------------------------------------


async def test_creates_entry_with_valid_input(hass):
    """Valid user input creates a config entry with the submitted data."""
    result = await _start_flow(hass)

    with patch(_PATCH_MQTT, return_value=True):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input=_VALID_USER_INPUT,
        )
        await hass.async_block_till_done()

    assert result2["type"] == FlowResultType.CREATE_ENTRY
    assert result2["title"] == "Jackery TEST001"
    assert result2["data"]["device_sn"] == "TEST001"
    assert result2["data"]["token"] == "secret-token"
    assert result2["data"]["topic_prefix"] == "hb"


async def test_lowercase_serial_requires_uppercase_confirmation_and_preserves_other_input(
    hass,
):
    """Lowercase serials are reviewed in uppercase before their entry is created."""
    result = await _start_flow(hass)

    with patch(_PATCH_MQTT, return_value=True):
        confirm = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                "device_sn": "  ab12cd  ",
                "token": "token-value",
                "topic_prefix": "custom-root",
            },
        )

    assert confirm["type"] == FlowResultType.FORM
    assert confirm["step_id"] == "confirm_sn"
    assert confirm["data_schema"]({})["device_sn"] == "AB12CD"

    with patch(_PATCH_MQTT, return_value=True):
        created = await hass.config_entries.flow.async_configure(
            confirm["flow_id"],
            user_input={"device_sn": "AB12CD"},
        )

    assert created["type"] == FlowResultType.CREATE_ENTRY
    assert created["data"] == {
        "device_sn": "AB12CD",
        "token": "token-value",
        "topic_prefix": "custom-root",
    }


async def test_empty_serial_is_rejected(hass):
    """An empty serial is shown as a field error without attempting MQTT setup."""
    result = await _start_flow(hass)

    submitted = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={"device_sn": "  ", "token": "token-value", "topic_prefix": "hb"},
    )

    assert submitted["type"] == FlowResultType.FORM
    assert submitted["step_id"] == "user"
    assert submitted["errors"]["device_sn"] == "invalid_sn"


# ---------------------------------------------------------------------------
# Duplicate device_sn is rejected
# ---------------------------------------------------------------------------


async def test_duplicate_sn_aborts_flow(hass):
    """A second setup attempt with the same SN is aborted."""
    with patch(_PATCH_MQTT, return_value=True):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data=_VALID_USER_INPUT,
        )
        await hass.async_block_till_done()

    assert result["type"] == FlowResultType.CREATE_ENTRY

    # Second flow with same SN
    result2 = await _start_flow(hass)
    with patch(_PATCH_MQTT, return_value=True):
        result3 = await hass.config_entries.flow.async_configure(
            result2["flow_id"],
            user_input=_VALID_USER_INPUT,
        )

    assert result3["type"] == FlowResultType.ABORT
    assert result3["reason"] == "already_configured"


# ---------------------------------------------------------------------------
# MQTT not available → shows form with error
# ---------------------------------------------------------------------------


async def test_mqtt_not_available_shows_error(hass):
    """When MQTT is not configured, the form is re-shown with an error."""
    result = await _start_flow(hass)

    with patch(_PATCH_MQTT, return_value=False):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input=_VALID_USER_INPUT,
        )

    assert result2["type"] == FlowResultType.FORM
    assert result2["errors"]["base"] == "mqtt_not_configured"


async def _start_options_flow(hass, *, data=None):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="HOST1234",
        data=data or {"device_sn": "HOST1234", "token": "mqtt-token", "topic_prefix": "hb"},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.FORM
    return entry, result


def _options_input(result):
    """Build form defaults and leave the password blank unless a test sets it."""
    return dict(result["data_schema"]({}))


async def test_cloud_firmware_cannot_be_enabled_without_credentials(hass):
    entry, flow = await _start_options_flow(hass)
    user_input = _options_input(flow)
    user_input["cloud_firmware_enabled"] = True

    result = await hass.config_entries.options.async_configure(
        flow["flow_id"], user_input=user_input
    )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"]["cloud_firmware_account"] == "invalid_cloud_account"
    assert result["errors"]["cloud_firmware_password"] == "invalid_cloud_password"
    assert entry.options.get("cloud_firmware_enabled", False) is False


async def test_cloud_firmware_options_store_credentials_without_prefilling_password(hass):
    entry, flow = await _start_options_flow(hass)
    assert "cloud_firmware_password" not in flow["data_schema"]({})
    password_selector = next(
        selector
        for key, selector in flow["data_schema"].schema.items()
        if getattr(key, "schema", None) == "cloud_firmware_password"
    )
    assert isinstance(password_selector, TextSelector)
    assert password_selector.config["type"] == TextSelectorType.PASSWORD.value
    user_input = _options_input(flow)
    user_input.update(
        {
            "cloud_firmware_enabled": True,
            "cloud_firmware_account": "  user@example.com  ",
            "cloud_firmware_password": "cloud-secret",
            "cloud_firmware_region": "de",
        }
    )

    result = await hass.config_entries.options.async_configure(
        flow["flow_id"], user_input=user_input
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.options["cloud_firmware_enabled"] is True
    assert entry.data["cloud_firmware_account"] == "user@example.com"
    assert entry.data["cloud_firmware_password"] == "cloud-secret"
    assert entry.data["cloud_firmware_region"] == "DE"


async def test_blank_cloud_password_keeps_existing_secret_and_can_be_cleared(hass):
    entry, flow = await _start_options_flow(
        hass,
        data={
            "device_sn": "HOST1234",
            "token": "mqtt-token",
            "topic_prefix": "hb",
            "cloud_firmware_account": "user@example.com",
            "cloud_firmware_password": "saved-secret",
            "cloud_firmware_region": "DE",
        },
    )
    user_input = _options_input(flow)
    user_input.update(
        {
            "cloud_firmware_enabled": True,
            "cloud_firmware_account": "user@example.com",
        }
    )
    enabled = await hass.config_entries.options.async_configure(
        flow["flow_id"], user_input=user_input
    )
    assert enabled["type"] == FlowResultType.CREATE_ENTRY
    assert entry.data["cloud_firmware_password"] == "saved-secret"

    clear_flow = await hass.config_entries.options.async_init(entry.entry_id)
    clear_input = _options_input(clear_flow)
    clear_input.update(
        {
            "cloud_firmware_enabled": False,
            "clear_cloud_firmware_credentials": True,
        }
    )
    cleared = await hass.config_entries.options.async_configure(
        clear_flow["flow_id"], user_input=clear_input
    )

    assert cleared["type"] == FlowResultType.CREATE_ENTRY
    assert "cloud_firmware_account" not in entry.data
    assert "cloud_firmware_password" not in entry.data
