"""Opt-in, bounded and persistent observation of the host MQTT alert topic.

Alert payloads are intentionally treated as opaque bytes. This module does not
parse or classify them and exports raw data only through its separate,
explicitly experimental diagnostics section.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from . import DOMAIN
from .capture_storage import (
    PersistentMqttCapture,
    bounded_counter,
    build_host_topic,
    host_fingerprint,
    validate_capture_event,
)
from .capture_storage import compact_size as _compact_size

OPTION_ALERT_CAPTURE_ENABLED: Final = "alert_capture_enabled"
ALERT_CAPTURE_VERSION: Final = 1
MAX_ALERT_EVENTS: Final = 100
MAX_ALERT_PAYLOAD_BYTES: Final = 4 * 1024
MAX_ALERT_STORAGE_BYTES: Final = 256 * 1024
MAX_ALERT_TOPIC_BYTES: Final = 512
MAX_ALERT_EXPORT_BYTES: Final = 24 * 1024
MAX_TOTAL_DIAGNOSTICS_BYTES: Final = 64 * 1024 + 2 * MAX_ALERT_EXPORT_BYTES
ALERT_SAVE_DELAY_SECONDS: Final = 1.0
ALERT_TOPIC_ALIAS: Final = "{prefix}/device/{host}/alert"
_PRIVACY_WARNING: Final = (
    "Contains experimental raw MQTT data that may include serial numbers or "
    "other sensitive information. Review before sharing publicly."
)


def build_alert_topic(topic_prefix: object, device_sn: object) -> str | None:
    """Build a literal host topic, rejecting values that could form wildcards."""
    return build_host_topic(
        topic_prefix,
        device_sn,
        "alert",
        max_topic_bytes=MAX_ALERT_TOPIC_BYTES,
    )


def _host_identity(device_sn: object) -> str | None:
    """Return a stable SHA-256 fingerprint for a valid configured host."""
    return host_fingerprint(device_sn, "jackery-alert-host-v1")


def _counter(value: object) -> int:
    return bounded_counter(value)


def _validated_event(value: object) -> dict[str, Any] | None:
    return validate_capture_event(
        value,
        max_payload_bytes=MAX_ALERT_PAYLOAD_BYTES,
        max_topic_bytes=MAX_ALERT_TOPIC_BYTES,
    )


class AlertCapture(PersistentMqttCapture):
    """Own one config-entry's persistent alert capture buffer."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        expected_topic: str | None,
        device_sn: object,
    ) -> None:
        identity = _host_identity(device_sn)
        topic_suffix = f"/device/{device_sn}/alert" if identity is not None else None
        super().__init__(
            hass,
            version=ALERT_CAPTURE_VERSION,
            store_key=f"{DOMAIN}.{entry_id}.experimental_alert_capture",
            host_identity=identity,
            expected_topic=expected_topic,
            topic_identity_suffix=topic_suffix,
            max_topic_bytes=MAX_ALERT_TOPIC_BYTES,
            max_events=MAX_ALERT_EVENTS,
            max_payload_bytes=MAX_ALERT_PAYLOAD_BYTES,
            max_storage_bytes=MAX_ALERT_STORAGE_BYTES,
            save_delay=ALERT_SAVE_DELAY_SECONDS,
            store_factory=Store,
        )


async def async_delete_alert_capture(hass: HomeAssistant, entry_id: str) -> None:
    """Remove a capture store when the option is disabled or entry is removed."""
    store: Store[dict[str, Any]] = Store(
        hass,
        ALERT_CAPTURE_VERSION,
        f"{DOMAIN}.{entry_id}.experimental_alert_capture",
        private=True,
    )
    await store.async_remove()


def build_alert_capture_export(
    capture: Mapping[str, Any],
    base_snapshot: Mapping[str, Any],
    *,
    max_export_bytes: int = MAX_ALERT_EXPORT_BYTES,
) -> dict[str, Any]:
    """Build the separately versioned raw-data section within total size bounds."""
    raw_events = capture.get("events")
    events = [
        event
        for raw_event in (raw_events if isinstance(raw_events, list) else [])
        if (event := _validated_event(raw_event)) is not None
    ]
    exported: list[dict[str, Any]] = []
    for event in reversed(events):
        candidate_event = {
            "received_at": event["received_at"],
            "topic": ALERT_TOPIC_ALIAS,
            "payload_encoding": "base64",
            "payload_size": event["payload_size"],
            "payload_truncated": event["payload_truncated"],
            "payload_base64": event["payload_base64"],
            "qos": event["qos"],
            "retain": event["retain"],
        }
        candidate = _alert_export_metadata(capture, len(events) - len(exported) - 1)
        candidate["events"] = [*reversed(exported), candidate_event]
        combined = dict(base_snapshot)
        combined["experimental_alert_capture"] = candidate
        if (
            _compact_size(candidate) <= max_export_bytes
            and _compact_size(combined) <= MAX_TOTAL_DIAGNOSTICS_BYTES
        ):
            exported.append(candidate_event)

    while True:
        result = _alert_export_metadata(capture, len(events) - len(exported))
        result["events"] = list(reversed(exported))
        combined = dict(base_snapshot)
        combined["experimental_alert_capture"] = result
        if (
            _compact_size(result) <= max_export_bytes
            and _compact_size(combined) <= MAX_TOTAL_DIAGNOSTICS_BYTES
        ):
            return result
        if not exported:
            # Fixed metadata is far smaller than either budget; this is a
            # defensive fallback if a future schema changes that assumption.
            result = _alert_export_metadata(capture, len(events))
            result["events"] = []
            return result
        exported.pop()  # records were selected newest-first; discard oldest


def _alert_export_metadata(capture: Mapping[str, Any], omitted: int) -> dict[str, Any]:
    return {
        "enabled": True,
        "capture_version": ALERT_CAPTURE_VERSION,
        "total_received": _counter(capture.get("total_received")),
        "stored_count": _counter(capture.get("stored_count")),
        "dropped_count": _counter(capture.get("dropped_count")),
        "overflow_count": _counter(capture.get("overflow_count")),
        "truncated_count": _counter(capture.get("truncated_count")),
        "export_omitted_count": max(0, omitted),
        "privacy_warning": _PRIVACY_WARNING,
        "sharing_policy": "not_public_without_review",
        "limits": {
            "max_events": MAX_ALERT_EVENTS,
            "max_payload_bytes": MAX_ALERT_PAYLOAD_BYTES,
            "max_storage_bytes": MAX_ALERT_STORAGE_BYTES,
        },
        "events": [],
    }


__all__ = [
    "ALERT_CAPTURE_VERSION",
    "ALERT_TOPIC_ALIAS",
    "MAX_ALERT_EVENTS",
    "MAX_ALERT_EXPORT_BYTES",
    "MAX_ALERT_PAYLOAD_BYTES",
    "MAX_ALERT_STORAGE_BYTES",
    "MAX_TOTAL_DIAGNOSTICS_BYTES",
    "OPTION_ALERT_CAPTURE_ENABLED",
    "AlertCapture",
    "async_delete_alert_capture",
    "build_alert_capture_export",
    "build_alert_topic",
]
