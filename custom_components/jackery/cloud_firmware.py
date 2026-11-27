"""Optional, read-only cloud firmware polling and update notifications."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from .protocol.ota import OtaFirmwareStatus, validate_device_serial
from .transport.jackery_cloud import JackeryCloudError, JackeryCloudFirmwareTransport

_LOGGER = logging.getLogger(__name__)

CLOUD_FIRMWARE_ENABLED = "cloud_firmware_enabled"
CLOUD_FIRMWARE_ACCOUNT = "cloud_firmware_account"
CLOUD_FIRMWARE_PASSWORD = "cloud_firmware_password"
CLOUD_FIRMWARE_REGION = "cloud_firmware_region"
CLOUD_FIRMWARE_POLL_INTERVAL = 24 * 60 * 60
_NOTIFICATION_STORE_VERSION = 1
_NOTIFICATION_VERSION_RE = re.compile(r"[A-Za-z0-9._+-]{1,80}\Z")


@dataclass(frozen=True, slots=True)
class FirmwareObservation:
    """Latest response state and freshness for one configured device."""

    status: OtaFirmwareStatus | None
    checked_at: str
    last_successful_check: str | None
    error: str | None = None

    @property
    def available(self) -> bool:
        """Only expose a version as current when the latest request succeeded."""
        return self.status is not None and self.error is None


class CloudFirmwareMonitor:
    """Poll the host and expansion batteries using one GET per serial number."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        account: str,
        password: str,
        region: str,
        host_serial: str,
        *,
        transport_factory: Callable[[Any], JackeryCloudFirmwareTransport] | None = None,
    ) -> None:
        self.hass = hass
        self._entry_id = entry_id
        self._account = account
        self._password = password
        self._region = region
        self._host_serial = host_serial
        self._targets = {host_serial}
        self._records: dict[str, FirmwareObservation] = {}
        self._listeners: set[Callable[[str], None]] = set()
        self._task: asyncio.Task[None] | None = None
        self._targets_changed = asyncio.Event()
        self._transport_factory = transport_factory or JackeryCloudFirmwareTransport
        self._session = async_get_clientsession(hass)
        self._notification_store: Store[dict[str, str]] = Store(
            hass,
            _NOTIFICATION_STORE_VERSION,
            f"{__package__}.{entry_id}.firmware_notifications",
        )
        self._notified: dict[str, str] = {}

    @property
    def host_serial(self) -> str:
        """Configured SolarVault serial number."""
        return self._host_serial

    def get_observation(self, serial: str) -> FirmwareObservation | None:
        """Return the latest cloud observation for an exact serial."""
        return self._records.get(serial)

    def async_add_listener(self, listener: Callable[[str], None]) -> Callable[[], None]:
        """Subscribe to changes for one or more monitored devices."""
        self._listeners.add(listener)

        def remove_listener() -> None:
            self._listeners.discard(listener)

        return remove_listener

    def set_expansion_serials(self, serials: set[str]) -> None:
        """Update the known battery targets and poll newly discovered devices."""
        targets = {self._host_serial}
        for serial in serials:
            try:
                targets.add(validate_device_serial(serial))
            except ValueError:
                _LOGGER.debug("Ignoring invalid expansion battery serial for cloud firmware polling")
        if targets != self._targets:
            removed = self._targets - targets
            self._targets = targets
            for serial in removed:
                self._records.pop(serial, None)
                self._notify_listeners(serial)
            self._targets_changed.set()

    async def async_start(self) -> None:
        """Load notification deduplication state and start the single poll task."""
        if self._task is not None and not self._task.done():
            return
        try:
            stored = await self._notification_store.async_load()
        except Exception:
            _LOGGER.warning("Could not load Jackery firmware notification deduplication state")
            stored = None
        if isinstance(stored, dict):
            self._notified = {
                key: value
                for key, value in stored.items()
                if isinstance(key, str) and isinstance(value, str)
            }
        self._task = asyncio.create_task(self._poll_loop())

    async def async_stop(self) -> None:
        """Cancel the poll loop during config-entry unload or reload."""
        task = self._task
        self._task = None
        if task is None or task.done():
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def async_poll_once(self) -> None:
        """Perform one login and one sequential list GET for every target."""
        targets = sorted(self._targets)
        if not targets:
            return
        checked_at = datetime.now(UTC).isoformat()
        transport = self._transport_factory(self._session)
        try:
            await transport.async_login(self._account, self._password, self._region)
        except JackeryCloudError as error:
            _LOGGER.warning("Optional Jackery cloud firmware login failed (%s)", error.reason)
            for serial in targets:
                self._record_failure(serial, checked_at, error.reason)
            return
        except Exception as error:  # Defensive isolation from optional cloud failures.
            _LOGGER.warning(
                "Optional Jackery cloud firmware login failed (%s)",
                type(error).__name__,
            )
            for serial in targets:
                self._record_failure(serial, checked_at, "login_error")
            return

        for serial in targets:
            try:
                status = await transport.async_get_firmware(serial)
            except JackeryCloudError as error:
                self._record_failure(serial, checked_at, error.reason)
                _LOGGER.debug("Jackery cloud firmware query failed for a device (%s)", error.reason)
                continue
            except Exception as error:  # A bad child response must not block other serials.
                self._record_failure(serial, checked_at, "query_error")
                _LOGGER.debug(
                    "Jackery cloud firmware query failed for a device (%s)",
                    type(error).__name__,
                )
                continue

            observation = FirmwareObservation(
                status=status,
                checked_at=checked_at,
                last_successful_check=checked_at,
            )
            self._records[serial] = observation
            try:
                await self._update_notification(serial, status)
            except Exception as error:
                _LOGGER.warning(
                    "Could not update Jackery firmware notification (%s)",
                    type(error).__name__,
                )
            self._notify_listeners(serial)

    async def _poll_loop(self) -> None:
        """Poll on startup, on battery discovery, and every 24 hours."""
        while True:
            self._targets_changed.clear()
            try:
                await self.async_poll_once()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                _LOGGER.warning(
                    "Optional Jackery cloud firmware poll failed (%s)",
                    type(error).__name__,
                )
            try:
                await asyncio.wait_for(
                    self._targets_changed.wait(),
                    timeout=CLOUD_FIRMWARE_POLL_INTERVAL,
                )
            except TimeoutError:
                pass

    def _record_failure(self, serial: str, checked_at: str, reason: str) -> None:
        previous = self._records.get(serial)
        self._records[serial] = FirmwareObservation(
            status=previous.status if previous is not None else None,
            checked_at=checked_at,
            last_successful_check=(
                previous.last_successful_check if previous is not None else None
            ),
            error=reason,
        )
        self._notify_listeners(serial)

    async def _update_notification(self, serial: str, status: OtaFirmwareStatus) -> None:
        """Notify once per newly offered status-0 target; preserve unknown codes."""
        if status.update_available:
            fingerprint_data = json.dumps(
                [status.current_version, status.target_version, status.target_version_id],
                ensure_ascii=True,
                separators=(",", ":"),
            )
            fingerprint = hashlib.sha256(fingerprint_data.encode("ascii")).hexdigest()
            device_key = hashlib.sha256(serial.encode("utf-8")).hexdigest()
            if self._notified.get(device_key) == fingerprint:
                return
            current = _safe_version_label(status.current_version)
            target = _safe_version_label(status.target_version)
            message = f"Firmware update available for Jackery device `{serial}`."
            if current:
                message += f"\n\nCurrent cloud version: `{current}`."
            if target:
                message += f" Target version: `{target}`."
            else:
                message += (
                    " The API did not provide `targetVersion`; the Jackery app "
                    "falls back to displaying the current version."
                )
            persistent_notification.async_create(
                self.hass,
                message,
                title="Jackery firmware update available",
                notification_id=self._notification_id(device_key),
            )
            self._notified[device_key] = fingerprint
            try:
                await self._notification_store.async_save(self._notified)
            except Exception:
                _LOGGER.warning("Could not persist Jackery firmware notification deduplication state")
            return

        if type(status.update_status) is int and status.update_status in {1, 2, 6}:
            device_key = hashlib.sha256(serial.encode("utf-8")).hexdigest()
            persistent_notification.async_dismiss(
                self.hass,
                notification_id=self._notification_id(device_key),
            )
        if type(status.update_status) is int and status.update_status == 6:
            device_key = hashlib.sha256(serial.encode("utf-8")).hexdigest()
            if self._notified.pop(device_key, None) is not None:
                try:
                    await self._notification_store.async_save(self._notified)
                except Exception:
                    _LOGGER.warning("Could not persist Jackery firmware notification deduplication state")

    def _notification_id(self, device_key: str) -> str:
        return f"jackery_firmware_{self._entry_id}_{device_key[:16]}"

    def _notify_listeners(self, serial: str) -> None:
        for listener in tuple(self._listeners):
            try:
                listener(serial)
            except Exception:  # Listener failures must not stop cloud polling.
                _LOGGER.debug("Cloud firmware entity listener failed", exc_info=True)


def _safe_version_label(value: str | int | float | None) -> str | None:
    """Keep untrusted API text out of notification markup."""
    if isinstance(value, (int, float)) and type(value) is not bool:
        return str(value)
    if isinstance(value, str) and _NOTIFICATION_VERSION_RE.fullmatch(value):
        return value
    return None


def update_state_label(status: OtaFirmwareStatus | None) -> str:
    """Return the app-supported status label, without guessing unknown codes."""
    if status is None:
        return "unknown"
    return status.update_state
