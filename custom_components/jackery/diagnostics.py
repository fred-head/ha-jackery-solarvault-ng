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
    MAX_ALERT_EXPORT_BYTES,
    MAX_TOTAL_DIAGNOSTICS_BYTES,
    OPTION_ALERT_CAPTURE_ENABLED,
    AlertCapture,
    build_alert_capture_export,
)
from .bmslog_capture import (
    MAX_BMSLOG_EXPORT_BYTES,
    OPTION_BMSLOG_CAPTURE_ENABLED,
    BmslogCapture,
    build_bmslog_capture_export,
)
from .diagnostics_adapter import collect_diagnostics_inputs
from .diagnostics_snapshot import MAX_SNAPSHOT_BYTES, build_diagnostics_snapshot
from .protocol_capture import (
    MAX_PROTOCOL_EXPORT_BYTES,
    ProtocolDiscoveryCapture,
    build_protocol_capture_export,
)
from .protocol_discovery import OPTION_PROTOCOL_DISCOVERY_ENABLED
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
    alert_enabled = entry.options.get(OPTION_ALERT_CAPTURE_ENABLED) is True
    protocol_enabled = entry.options.get(OPTION_PROTOCOL_DISCOVERY_ENABLED) is True
    bmslog_enabled = entry.options.get(OPTION_BMSLOG_CAPTURE_ENABLED) is True
    enabled_capture_count = sum((alert_enabled, protocol_enabled, bmslog_enabled))
    shared_capture_budget = (
        (MAX_TOTAL_DIAGNOSTICS_BYTES - MAX_SNAPSHOT_BYTES) // enabled_capture_count
        if enabled_capture_count
        else MAX_ALERT_EXPORT_BYTES
    )
    per_capture_export_limit = min(
        MAX_ALERT_EXPORT_BYTES,
        MAX_PROTOCOL_EXPORT_BYTES,
        MAX_BMSLOG_EXPORT_BYTES,
        shared_capture_budget,
    )

    alert_capture_data: dict[str, Any] | None = None
    if alert_enabled:
        capture = getattr(coordinator, "_alert_capture", None)
        if capture is None:
            # Diagnostics remain readable for an enabled but currently unloaded
            # entry; this loads the existing store without starting a listener.
            capture = AlertCapture(hass, entry.entry_id, None, entry.data.get("device_sn"))
            await capture.async_load()
        alert_capture_data = capture.snapshot()

    protocol_capture_data: dict[str, Any] | None = None
    if protocol_enabled:
        capture = getattr(coordinator, "_protocol_discovery_capture", None)
        if capture is None:
            capture = ProtocolDiscoveryCapture(
                hass,
                entry.entry_id,
                entry.data.get("topic_prefix", "hb"),
                entry.data.get("device_sn"),
            )
            await capture.async_load()
        protocol_capture_data = capture.raw_snapshot()

    bmslog_capture_data: dict[str, Any] | None = None
    if bmslog_enabled:
        capture = getattr(coordinator, "_bmslog_capture", None)
        if capture is None:
            capture = BmslogCapture(
                hass,
                entry.entry_id,
                None,
                entry.data.get("device_sn"),
            )
            await capture.async_load()
        bmslog_capture_data = capture.snapshot()

    if alert_capture_data is not None:
        redacted_snapshot["experimental_alert_capture"] = build_alert_capture_export(
            alert_capture_data,
            redacted_snapshot,
            max_export_bytes=per_capture_export_limit,
        )

    if protocol_capture_data is not None:
        redacted_snapshot["experimental_protocol_capture"] = build_protocol_capture_export(
            protocol_capture_data,
            redacted_snapshot,
            max_export_bytes=per_capture_export_limit,
        )

    if bmslog_capture_data is not None:
        redacted_snapshot["experimental_bmslog_capture"] = build_bmslog_capture_export(
            bmslog_capture_data,
            redacted_snapshot,
            max_export_bytes=per_capture_export_limit,
        )
    return redacted_snapshot


__all__ = ["async_get_config_entry_diagnostics"]
