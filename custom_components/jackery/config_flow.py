"""Config flow for Jackery SolarVault integration."""
from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components import mqtt
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType

from . import DOMAIN
from .alert_capture import OPTION_ALERT_CAPTURE_ENABLED
from .bmslog_capture import OPTION_BMSLOG_CAPTURE_ENABLED
from .cloud_firmware import (
    CLOUD_FIRMWARE_ACCOUNT,
    CLOUD_FIRMWARE_ENABLED,
    CLOUD_FIRMWARE_PASSWORD,
    CLOUD_FIRMWARE_REGION,
)
from .protocol_discovery import OPTION_PROTOCOL_DISCOVERY_ENABLED

_LOGGER = logging.getLogger(__name__)

DATA_SCHEMA = vol.Schema(
    {
        vol.Required("device_sn"): str,
        vol.Required("token"): str,
        vol.Optional("topic_prefix", default="hb"): str,
    }
)

REAUTH_SCHEMA = vol.Schema({vol.Required("token"): str})

DEFAULT_SMARTMETER_POLL_INTERVAL = 10


class JackeryConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):  # type: ignore[call-arg]
    """Handle a config flow for Jackery."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize state carried between setup steps."""
        self._pending_user_input: dict[str, str] = {}
        self._reauth_device_sn = ""

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> JackeryOptionsFlowHandler:
        """Return the options flow handler."""
        return JackeryOptionsFlowHandler(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            device_sn = user_input.get("device_sn", "").strip()
            self._pending_user_input = {
                "device_sn": device_sn,
                "token": user_input.get("token", ""),
                "topic_prefix": user_input.get("topic_prefix", "hb"),
            }

            if not device_sn:
                errors["device_sn"] = "invalid_sn"
            elif device_sn != device_sn.upper():
                # Jackery MQTT topics use the uppercase host serial number.
                # Confirm it before creating an entry with a topic that will not match.
                return await self.async_step_confirm_sn()
            else:
                result = await self._async_finish_setup(device_sn, errors)
                if result is not None:
                    return result

        return self.async_show_form(
            step_id="user",
            data_schema=DATA_SCHEMA,
            errors=errors,
            description_placeholders={
                "topic_prefix": "Protocol root topic (default: hb)",
            },
        )

    async def _async_finish_setup(
        self, device_sn: str, errors: dict[str, str]
    ) -> config_entries.ConfigFlowResult | None:
        """Create the entry once the final serial number has been confirmed."""
        if not device_sn:
            errors["device_sn"] = "invalid_sn"
            return None

        await self.async_set_unique_id(device_sn)
        self._abort_if_unique_id_configured()

        if not await mqtt.async_wait_for_mqtt_client(self.hass):
            errors["base"] = "mqtt_not_configured"
            return None

        topic_prefix = self._pending_user_input.get("topic_prefix", "hb")
        _LOGGER.info(
            "Creating Jackery config entry for device_sn=%s topic_prefix=%s",
            device_sn,
            topic_prefix,
        )
        return self.async_create_entry(
            title=f"Jackery {device_sn}",
            data={
                "device_sn": device_sn,
                "token": self._pending_user_input.get("token", ""),
                "topic_prefix": topic_prefix,
            },
        )

    async def async_step_confirm_sn(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Confirm the uppercase serial number suggested for MQTT topic matching."""
        errors: dict[str, str] = {}
        original_sn = self._pending_user_input.get("device_sn", "")
        if user_input is not None:
            device_sn = user_input.get("device_sn", "").strip().upper()
            result = await self._async_finish_setup(device_sn, errors)
            if result is not None:
                return result
            suggested_sn = device_sn
        else:
            suggested_sn = original_sn.upper()

        return self.async_show_form(
            step_id="confirm_sn",
            data_schema=vol.Schema(
                {vol.Required("device_sn", default=suggested_sn): str}
            ),
            errors=errors,
            description_placeholders={"original_sn": original_sn},
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> config_entries.ConfigFlowResult:
        """Handle re-authentication when runtime communication cannot authenticate."""
        self._reauth_device_sn = entry_data.get("device_sn", "")
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Let the user enter a new token."""
        errors: dict[str, str] = {}

        if user_input is not None:
            return self.async_update_reload_and_abort(
                self._get_reauth_entry(),
                data_updates={"token": user_input["token"].strip()},
            )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=REAUTH_SCHEMA,
            errors=errors,
            description_placeholders={"device_sn": self._reauth_device_sn},
        )


class JackeryOptionsFlowHandler(config_entries.OptionsFlowWithReload):
    """Handle Jackery options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Manage options."""
        current_data = self._config_entry.data
        current_options = self._config_entry.options

        if user_input is not None:
            errors: dict[str, str] = {}
            cloud_enabled = user_input.get(CLOUD_FIRMWARE_ENABLED, False) is True
            clear_cloud_credentials = user_input.get(
                "clear_cloud_firmware_credentials", False
            ) is True
            cloud_account = user_input.get(
                CLOUD_FIRMWARE_ACCOUNT,
                current_data.get(CLOUD_FIRMWARE_ACCOUNT, ""),
            )
            if not isinstance(cloud_account, str):
                cloud_account = ""
            cloud_account = cloud_account.strip()
            cloud_password_input = user_input.get(CLOUD_FIRMWARE_PASSWORD, "")
            if not isinstance(cloud_password_input, str):
                cloud_password_input = ""
            stored_cloud_password = current_data.get(CLOUD_FIRMWARE_PASSWORD, "")
            if not isinstance(stored_cloud_password, str):
                stored_cloud_password = ""
            cloud_password = cloud_password_input or stored_cloud_password
            cloud_region = user_input.get(
                CLOUD_FIRMWARE_REGION,
                current_data.get(CLOUD_FIRMWARE_REGION, "DE"),
            )
            if not isinstance(cloud_region, str):
                cloud_region = ""
            cloud_region = cloud_region.strip().upper()

            if clear_cloud_credentials and cloud_enabled:
                errors["base"] = "cloud_credentials_required"
            elif cloud_enabled:
                if not cloud_account:
                    errors[CLOUD_FIRMWARE_ACCOUNT] = "invalid_cloud_account"
                if not cloud_password:
                    errors[CLOUD_FIRMWARE_PASSWORD] = "invalid_cloud_password"
            if cloud_enabled and not re.fullmatch(r"[A-Z]{2}", cloud_region):
                errors[CLOUD_FIRMWARE_REGION] = "invalid_cloud_region"
            elif cloud_region and not re.fullmatch(r"[A-Z]{2}", cloud_region):
                errors[CLOUD_FIRMWARE_REGION] = "invalid_cloud_region"

            if errors:
                return self.async_show_form(
                    step_id="init",
                    data_schema=self._options_schema(current_data, current_options),
                    errors=errors,
                )

            new_options = {
                "smartmeter_http_poll": user_input["smartmeter_http_poll"],
                "smartmeter_poll_interval": user_input["smartmeter_poll_interval"],
                CLOUD_FIRMWARE_ENABLED: cloud_enabled,
                OPTION_PROTOCOL_DISCOVERY_ENABLED: user_input[
                    OPTION_PROTOCOL_DISCOVERY_ENABLED
                ],
                OPTION_ALERT_CAPTURE_ENABLED: user_input[
                    OPTION_ALERT_CAPTURE_ENABLED
                ],
                OPTION_BMSLOG_CAPTURE_ENABLED: user_input[
                    OPTION_BMSLOG_CAPTURE_ENABLED
                ],
            }
            options_changed = any(
                new_options[key] != current_options.get(key, default)
                for key, default in (
                    ("smartmeter_http_poll", False),
                    ("smartmeter_poll_interval", DEFAULT_SMARTMETER_POLL_INTERVAL),
                    (CLOUD_FIRMWARE_ENABLED, False),
                    (OPTION_PROTOCOL_DISCOVERY_ENABLED, False),
                    (OPTION_ALERT_CAPTURE_ENABLED, False),
                    (OPTION_BMSLOG_CAPTURE_ENABLED, False),
                )
            )
            data_updates: dict[str, Any] = {}
            if user_input["token"] != current_data.get("token"):
                data_updates["token"] = user_input["token"]
            if user_input["topic_prefix"] != current_data.get("topic_prefix", "hb"):
                data_updates["topic_prefix"] = user_input["topic_prefix"]
            if clear_cloud_credentials:
                data_updates[CLOUD_FIRMWARE_ACCOUNT] = None
                data_updates[CLOUD_FIRMWARE_PASSWORD] = None
            else:
                if cloud_account and cloud_account != current_data.get(CLOUD_FIRMWARE_ACCOUNT):
                    data_updates[CLOUD_FIRMWARE_ACCOUNT] = cloud_account
                if cloud_password_input:
                    data_updates[CLOUD_FIRMWARE_PASSWORD] = cloud_password_input
                if (
                    cloud_enabled
                    and cloud_region
                    and cloud_region != current_data.get(CLOUD_FIRMWARE_REGION)
                ):
                    data_updates[CLOUD_FIRMWARE_REGION] = cloud_region
            if data_updates:
                updated_data = dict(current_data)
                for key, value in data_updates.items():
                    if value is None:
                        updated_data.pop(key, None)
                    else:
                        updated_data[key] = value
                self.hass.config_entries.async_update_entry(
                    self._config_entry, data=updated_data
                )
                # HA reloads changed options after this flow completes. A data-only
                # change needs the same reload without a config-entry listener.
                if not options_changed:
                    self.hass.config_entries.async_schedule_reload(
                        self._config_entry.entry_id
                    )
            return self.async_create_entry(
                title="",
                data=new_options if options_changed else dict(current_options),
            )

        return self.async_show_form(
            step_id="init",
            data_schema=self._options_schema(current_data, current_options),
        )

    @staticmethod
    def _options_schema(
        current_data: Mapping[str, Any], current_options: Mapping[str, Any]
    ) -> vol.Schema:
        """Build options while never prefilling the stored cloud password."""
        schema = vol.Schema(
            {
                vol.Required("token", default=current_data.get("token", "")): str,
                vol.Required("topic_prefix", default=current_data.get("topic_prefix", "hb")): str,
                vol.Required(
                    "smartmeter_http_poll",
                    default=current_options.get("smartmeter_http_poll", False),
                ): bool,
                vol.Required(
                    "smartmeter_poll_interval",
                    default=current_options.get("smartmeter_poll_interval", DEFAULT_SMARTMETER_POLL_INTERVAL),
                ): vol.All(int, vol.Range(min=2, max=60)),
                vol.Required(
                    CLOUD_FIRMWARE_ENABLED,
                    default=current_options.get(CLOUD_FIRMWARE_ENABLED, False),
                ): bool,
                vol.Required(
                    CLOUD_FIRMWARE_ACCOUNT,
                    default=current_data.get(CLOUD_FIRMWARE_ACCOUNT, ""),
                ): str,
                vol.Optional(CLOUD_FIRMWARE_PASSWORD): TextSelector(
                    TextSelectorConfig(
                        type=TextSelectorType.PASSWORD,
                        autocomplete="current-password",
                    )
                ),
                vol.Required(
                    CLOUD_FIRMWARE_REGION,
                    default=current_data.get(CLOUD_FIRMWARE_REGION, "DE"),
                ): str,
                vol.Required("clear_cloud_firmware_credentials", default=False): bool,
                vol.Required(
                    OPTION_PROTOCOL_DISCOVERY_ENABLED,
                    default=current_options.get(
                        OPTION_PROTOCOL_DISCOVERY_ENABLED, False
                    ),
                ): bool,
                vol.Required(
                    OPTION_ALERT_CAPTURE_ENABLED,
                    default=current_options.get(OPTION_ALERT_CAPTURE_ENABLED, False),
                ): bool,
                vol.Required(
                    OPTION_BMSLOG_CAPTURE_ENABLED,
                    default=current_options.get(OPTION_BMSLOG_CAPTURE_ENABLED, False),
                ): bool,
            }
        )
        return schema
