"""Opt-in, bounded observation of the host MQTT BMS log topic.

BMS log payloads stay opaque bytes and are exposed only in their own explicitly
experimental diagnostics section.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from . import DOMAIN
from .alert_capture import MAX_TOTAL_DIAGNOSTICS_BYTES
from .capture_storage import (
    PersistentMqttCapture,
    bounded_counter,
    build_bounded_capture_export,
    build_host_topic,
    host_fingerprint,
    validate_capture_event,
)

OPTION_BMSLOG_CAPTURE_ENABLED: Final = "bmslog_capture_enabled"
BMSLOG_CAPTURE_VERSION: Final = 1
MAX_BMSLOG_EVENTS: Final = 100
MAX_BMSLOG_PAYLOAD_BYTES: Final = 4 * 1024
MAX_BMSLOG_STORAGE_BYTES: Final = 256 * 1024
MAX_BMSLOG_TOPIC_BYTES: Final = 512
MAX_BMSLOG_EXPORT_BYTES: Final = 24 * 1024
BMSLOG_SAVE_DELAY_SECONDS: Final = 1.0
BMSLOG_TOPIC_ALIAS: Final = "{prefix}/device/{host}/bmslog"
_PRIVACY_WARNING: Final = (
    "Contains experimental raw MQTT data that may include serial numbers or "
    "other sensitive information. Review before sharing publicly."
)


def build_bmslog_topic(topic_prefix: object, device_sn: object) -> str | None:
    """Build the exact host BMS log topic without permitting wildcards."""
    return build_host_topic(
        topic_prefix,
        device_sn,
        "bmslog",
        max_topic_bytes=MAX_BMSLOG_TOPIC_BYTES,
    )


def _host_identity(device_sn: object) -> str | None:
    """Return a stable BMS-capture-specific host fingerprint."""
    return host_fingerprint(device_sn, "jackery-bmslog-host-v1")


def _validated_event(value: object) -> dict[str, Any] | None:
    return validate_capture_event(
        value,
        max_payload_bytes=MAX_BMSLOG_PAYLOAD_BYTES,
        max_topic_bytes=MAX_BMSLOG_TOPIC_BYTES,
    )


class BmslogCapture(PersistentMqttCapture):
    """Own one config-entry's persistent BMS log ring buffer."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        expected_topic: str | None,
        device_sn: object,
    ) -> None:
        identity = _host_identity(device_sn)
        topic_suffix = f"/device/{device_sn}/bmslog" if identity is not None else None
        super().__init__(
            hass,
            version=BMSLOG_CAPTURE_VERSION,
            store_key=f"{DOMAIN}.{entry_id}.experimental_bmslog_capture",
            host_identity=identity,
            expected_topic=expected_topic,
            topic_identity_suffix=topic_suffix,
            max_topic_bytes=MAX_BMSLOG_TOPIC_BYTES,
            max_events=MAX_BMSLOG_EVENTS,
            max_payload_bytes=MAX_BMSLOG_PAYLOAD_BYTES,
            max_storage_bytes=MAX_BMSLOG_STORAGE_BYTES,
            save_delay=BMSLOG_SAVE_DELAY_SECONDS,
            store_factory=Store,
        )


async def async_delete_bmslog_capture(hass: HomeAssistant, entry_id: str) -> None:
    """Remove this entry's private BMS log capture store."""
    store: Store[dict[str, Any]] = Store(
        hass,
        BMSLOG_CAPTURE_VERSION,
        f"{DOMAIN}.{entry_id}.experimental_bmslog_capture",
        private=True,
    )
    await store.async_remove()


def _export_metadata(capture: Mapping[str, Any], omitted: int) -> dict[str, Any]:
    return {
        "enabled": True,
        "capture_version": BMSLOG_CAPTURE_VERSION,
        "total_received": _counter(capture.get("total_received")),
        "stored_count": _counter(capture.get("stored_count")),
        "dropped_count": _counter(capture.get("dropped_count")),
        "overflow_count": _counter(capture.get("overflow_count")),
        "truncated_count": _counter(capture.get("truncated_count")),
        "export_omitted_count": max(0, omitted),
        "privacy_warning": _PRIVACY_WARNING,
        "sharing_policy": "not_public_without_review",
        "limits": {
            "max_events": MAX_BMSLOG_EVENTS,
            "max_payload_bytes": MAX_BMSLOG_PAYLOAD_BYTES,
            "max_storage_bytes": MAX_BMSLOG_STORAGE_BYTES,
        },
        "events": [],
    }


def _counter(value: object) -> int:
    return bounded_counter(value)


def build_bmslog_capture_export(
    capture: Mapping[str, Any],
    base_snapshot: Mapping[str, Any],
    *,
    max_export_bytes: int = MAX_BMSLOG_EXPORT_BYTES,
) -> dict[str, Any]:
    """Build the aliased, bounded BMS log extension under the shared budget."""
    return build_bounded_capture_export(
        capture,
        base_snapshot,
        section_key="experimental_bmslog_capture",
        topic_alias=BMSLOG_TOPIC_ALIAS,
        max_export_bytes=max_export_bytes,
        max_total_bytes=MAX_TOTAL_DIAGNOSTICS_BYTES,
        validate_event=_validated_event,
        metadata_factory=_export_metadata,
    )


__all__ = [
    "BMSLOG_CAPTURE_VERSION",
    "BMSLOG_TOPIC_ALIAS",
    "MAX_BMSLOG_EVENTS",
    "MAX_BMSLOG_EXPORT_BYTES",
    "MAX_BMSLOG_PAYLOAD_BYTES",
    "MAX_BMSLOG_STORAGE_BYTES",
    "OPTION_BMSLOG_CAPTURE_ENABLED",
    "BmslogCapture",
    "async_delete_bmslog_capture",
    "build_bmslog_capture_export",
    "build_bmslog_topic",
]
