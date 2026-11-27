"""Diagnostic sensor for Jackery cloud-reported firmware information."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers.entity import EntityCategory

from .. import DOMAIN
from ..cloud_firmware import CloudFirmwareMonitor, FirmwareObservation, update_state_label
from ..identity import child_device_identifier, child_unique_id
from ..registry_identity import build_device_info


class JackeryCloudFirmwareSensor(SensorEntity):
    """Expose a device's current cloud version and OTA offer/status fields."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _attr_icon = "mdi:cloud-download-outline"
    _attr_translation_key = "cloud_firmware"

    def __init__(
        self,
        *,
        host_serial: str,
        device_serial: str,
        monitor: CloudFirmwareMonitor,
        config_entry: ConfigEntry,
        expansion_battery: bool = False,
    ) -> None:
        self._host_serial = host_serial
        self._device_serial = device_serial
        self._monitor = monitor
        self._observation: FirmwareObservation | None = monitor.get_observation(device_serial)
        if expansion_battery:
            self._attr_unique_id = child_unique_id(
                host_serial,
                device_serial,
                "battery",
                "cloudfirmware",
            )
            self._attr_device_info = build_device_info(
                monitor.hass,
                config_entry.entry_id,
                identifiers={(DOMAIN, child_device_identifier(host_serial, device_serial))},
                parent_identifier=(DOMAIN, host_serial),
                name=f"Jackery Battery {device_serial}",
                manufacturer="Jackery",
                model="Expansion Battery",
            )
        else:
            self._attr_unique_id = f"jackery_{host_serial}_cloud_firmware"
            self._attr_device_info = {
                "identifiers": {(DOMAIN, host_serial)},
                "name": "Jackery",
                "manufacturer": "Jackery",
                "model": "Energy Monitor",
            }

    @property
    def native_value(self) -> str | int | float | None:
        """Return currentVersion as supplied by the Jackery backend."""
        if self._observation is None or not self._observation.available:
            return None
        status = self._observation.status
        return status.current_version if status is not None else None

    @property
    def available(self) -> bool:
        """Do not present a prior successful response as the latest reading."""
        return self._observation is not None and self._observation.available

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        observation = self._observation
        attributes: dict[str, Any] = {
            "source": "Jackery cloud API backend report",
            "device_serial": self._device_serial,
        }
        if observation is None:
            return attributes
        status = observation.status
        attributes.update(
            {
                "target_version": status.target_version if status is not None else None,
                "app_display_target_version": (
                    status.app_display_target_version if status is not None else None
                ),
                "update_status": status.update_status if status is not None else None,
                "update_status_meaning": update_state_label(status),
                "target_version_id": status.target_version_id if status is not None else None,
                "last_checked": observation.checked_at,
                "last_successful_check": observation.last_successful_check,
                "last_query_error": observation.error,
            }
        )
        return attributes

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._remove_listener = self._monitor.async_add_listener(self._handle_monitor_update)
        self._refresh_from_monitor()

    async def async_will_remove_from_hass(self) -> None:
        remove_listener = getattr(self, "_remove_listener", None)
        if remove_listener is not None:
            remove_listener()
        await super().async_will_remove_from_hass()

    @callback
    def _handle_monitor_update(self, serial: str) -> None:
        if serial == self._device_serial:
            self._refresh_from_monitor()

    @callback
    def _refresh_from_monitor(self) -> None:
        self._observation = self._monitor.get_observation(self._device_serial)
        self.async_write_ha_state()
