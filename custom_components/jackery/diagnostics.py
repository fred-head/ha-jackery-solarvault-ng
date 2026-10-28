"""Home Assistant config-entry diagnostics for Jackery."""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from . import DOMAIN
from .alert_capture import (
    OPTION_ALERT_CAPTURE_ENABLED,
    AlertCapture,
    build_alert_capture_export,
)
from .diagnostics_adapter import collect_diagnostics_inputs
from .diagnostics_snapshot import build_diagnostics_snapshot
from .sensor import JackeryDataCoordinator

_FINAL_REDACTION_KEYS = {
    "api_key",
    "authorization",
    "config_entry_id",
    "credentials",
    "device_id",
    "entity_id",
    "password",
    "raw_data",
    "ssid",
    "token",
    "unique_id",
    "url",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return one bounded, read-only diagnostics snapshot for a config entry."""
    integration = await async_get_integration(hass, DOMAIN)
    raw_version = integration.manifest.get("version")
    manifest_version = raw_version if isinstance(raw_version, str) else None

    runtime_entry = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    coordinator = None
    if isinstance(runtime_entry, Mapping):
        candidate = runtime_entry.get("coordinator")
        if isinstance(candidate, JackeryDataCoordinator):
            coordinator = candidate

    # Runtime receipt timestamps use time.time(); use one value on the same basis
    # for every copied owner and for the pure P3.1 age conversion.
    now = time.time()
    inputs = collect_diagnostics_inputs(
        hass,
        entry,
        coordinator,
        manifest_version=manifest_version,
        now=now,
    )
    snapshot = build_diagnostics_snapshot(inputs, now=now)
    redacted_snapshot = async_redact_data(snapshot, _FINAL_REDACTION_KEYS)
    if entry.options.get(OPTION_ALERT_CAPTURE_ENABLED) is True:
        capture = getattr(coordinator, "_alert_capture", None)
        if capture is None:
            # Diagnostics remain readable for an enabled but currently unloaded
            # entry; this loads the existing store without starting a listener.
            capture = AlertCapture(hass, entry.entry_id, None)
            await capture.async_load()
        redacted_snapshot["experimental_alert_capture"] = (
            build_alert_capture_export(capture.snapshot(), redacted_snapshot)
        )
    return redacted_snapshot


__all__ = ["async_get_config_entry_diagnostics"]
