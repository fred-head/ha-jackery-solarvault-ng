"""Opt-in, bounded and persistent observation of the host MQTT alert topic.

Alert payloads are intentionally treated as opaque bytes. This module does not
parse or classify them and exports raw data only through its separate,
explicitly experimental diagnostics section.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Final

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from . import DOMAIN
from .capture_storage import async_remove_store_without_save_race, host_fingerprint
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
_MAX_COUNTER: Final = 2_147_483_647
_PRIVACY_WARNING: Final = (
    "Contains experimental raw MQTT data that may include serial numbers or "
    "other sensitive information. Review before sharing publicly."
)
_HOST_IDENTITY_VERSION: Final = 1


def build_alert_topic(topic_prefix: object, device_sn: object) -> str | None:
    """Build a literal host topic, rejecting values that could form wildcards."""
    if not isinstance(topic_prefix, str) or not topic_prefix:
        return None
    if not isinstance(device_sn, str) or not device_sn or device_sn != device_sn.strip():
        return None
    if any(
        character in "+#\x00" or ord(character) < 32 or ord(character) == 127
        for character in topic_prefix
    ):
        return None
    if any(
        character in "/+#\x00" or ord(character) < 32 or ord(character) == 127
        for character in device_sn
    ):
        return None
    topic = f"{topic_prefix}/device/{device_sn}/alert"
    try:
        if len(topic.encode("utf-8")) > MAX_ALERT_TOPIC_BYTES:
            return None
    except UnicodeEncodeError:
        return None
    return topic


def _host_identity(device_sn: object) -> str | None:
    """Return a stable SHA-256 fingerprint for a valid configured host."""
    return host_fingerprint(device_sn, "jackery-alert-host-v1")


def _counter(value: object) -> int:
    if type(value) is not int:
        return 0
    return min(_MAX_COUNTER, max(0, value))


def _validated_event(value: object) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    topic = value.get("topic")
    received_at = value.get("received_at")
    encoded = value.get("payload_base64")
    payload_size = value.get("payload_size")
    truncated = value.get("payload_truncated")
    if (
        not isinstance(topic, str)
        or len(topic.encode("utf-8", errors="replace")) > MAX_ALERT_TOPIC_BYTES
        or not isinstance(received_at, str)
        or len(received_at) > 40
        or not isinstance(encoded, str)
        or len(encoded) > 4 * ((MAX_ALERT_PAYLOAD_BYTES + 2) // 3)
        or type(payload_size) is not int
        or payload_size < 0
        or payload_size > _MAX_COUNTER
        or type(truncated) is not bool
    ):
        return None
    try:
        payload = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        return None
    if len(payload) > MAX_ALERT_PAYLOAD_BYTES:
        return None
    if (truncated and payload_size <= len(payload)) or (
        not truncated and payload_size != len(payload)
    ):
        return None
    qos = value.get("qos")
    retain = value.get("retain")
    if qos is not None and (type(qos) is not int or qos not in (0, 1, 2)):
        return None
    if retain is not None and type(retain) is not bool:
        return None
    return {
        "received_at": received_at,
        "topic": topic,
        "payload_encoding": "base64",
        "payload_size": payload_size,
        "payload_truncated": truncated,
        "payload_base64": encoded,
        "qos": qos,
        "retain": retain,
    }


class AlertCapture:
    """Own one config-entry's persistent alert capture buffer."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        expected_topic: str | None,
        device_sn: object,
    ) -> None:
        self._store: Store[dict[str, Any]] = Store(
            hass,
            ALERT_CAPTURE_VERSION,
            f"{DOMAIN}.{entry_id}.experimental_alert_capture",
            private=True,
        )
        self._host_identity = _host_identity(device_sn)
        topic_suffix = f"/device/{device_sn}/alert" if self._host_identity is not None else None
        self._expected_topic = (
            expected_topic
            if isinstance(expected_topic, str)
            and topic_suffix is not None
            and expected_topic.endswith(topic_suffix)
            and len(expected_topic) > len(topic_suffix)
            else None
        )
        self._cleared = False
        self._events: list[dict[str, Any]] = []
        self._total_received = 0
        self._dropped_count = 0
        self._overflow_count = 0
        self._truncated_count = 0

    @property
    def topic(self) -> str | None:
        """Return the validated exact topic this capture may observe."""
        return self._expected_topic

    async def async_load(self) -> None:
        """Restore only records bound to this configured host identity."""
        data = await self._store.async_load()
        if data is None:
            return
        if (
            self._host_identity is None
            or not isinstance(data, Mapping)
            or data.get("capture_version") != ALERT_CAPTURE_VERSION
            or data.get("host_identity_version") != _HOST_IDENTITY_VERSION
            or data.get("host_identity") != self._host_identity
        ):
            # Version-1 stores written before host binding (or stores from a
            # different host) cannot safely be attributed to this device.
            await self.async_clear()
            self._cleared = False
            return

        restored: list[dict[str, Any]] = []
        raw_events = data.get("events")
        if isinstance(raw_events, list):
            for raw_event in raw_events[-MAX_ALERT_EVENTS:]:
                event = _validated_event(raw_event)
                if event is not None:
                    restored.append(event)
        self._events = restored
        self._total_received = _counter(data.get("total_received"))
        self._dropped_count = _counter(data.get("dropped_count"))
        self._overflow_count = _counter(data.get("overflow_count"))
        self._truncated_count = _counter(data.get("truncated_count"))
        self._enforce_limits()

    def observe(
        self,
        *,
        topic: object,
        payload: object,
        qos: object = None,
        retain: object = None,
        received_at: datetime | None = None,
    ) -> bool:
        """Record a matching MQTT delivery without decoding its payload."""
        if self._cleared or self._host_identity is None or topic != self._expected_topic:
            return False

        self._total_received = min(_MAX_COUNTER, self._total_received + 1)
        if isinstance(payload, bytes):
            raw_payload = payload
        elif isinstance(payload, (bytearray, memoryview)):
            raw_payload = bytes(payload)
        elif isinstance(payload, str):
            # HA's MQTT callback supplies bytes; support text fakes as exact UTF-8.
            raw_payload = payload.encode("utf-8", errors="surrogatepass")
        else:
            self._dropped_count = min(_MAX_COUNTER, self._dropped_count + 1)
            self._schedule_save()
            return True

        payload_size = len(raw_payload)
        truncated = payload_size > MAX_ALERT_PAYLOAD_BYTES
        stored_payload = raw_payload[:MAX_ALERT_PAYLOAD_BYTES]
        if truncated:
            self._truncated_count = min(_MAX_COUNTER, self._truncated_count + 1)

        timestamp = received_at or datetime.now(UTC)
        event = {
            "received_at": timestamp.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "topic": topic,
            "payload_encoding": "base64",
            "payload_size": payload_size,
            "payload_truncated": truncated,
            "payload_base64": base64.b64encode(stored_payload).decode("ascii"),
            "qos": qos if type(qos) is int and qos in (0, 1, 2) else None,
            "retain": retain if type(retain) is bool else None,
        }
        self._events.append(event)
        self._enforce_limits()
        self._schedule_save()
        return True

    def snapshot(self) -> dict[str, Any]:
        """Return a detached JSON-compatible view for diagnostics assembly."""
        return {
            "capture_version": ALERT_CAPTURE_VERSION,
            "total_received": self._total_received,
            "stored_count": len(self._events),
            "dropped_count": self._dropped_count,
            "overflow_count": self._overflow_count,
            "truncated_count": self._truncated_count,
            "events": [dict(event) for event in self._events],
        }

    async def async_flush(self) -> None:
        """Finish a pending debounced save before coordinator unload."""
        await self._store.async_save(self._serialize())

    async def async_clear(self) -> None:
        """Delete pending writes and persisted raw capture data without a save race."""
        self._cleared = True
        self._events.clear()
        self._total_received = 0
        self._dropped_count = 0
        self._overflow_count = 0
        self._truncated_count = 0
        # Saving the empty state first waits for an already-running delayed
        # write and cancels its timer. The subsequent remove is then final.
        await async_remove_store_without_save_race(self._store, self._serialize())

    def _schedule_save(self) -> None:
        self._store.async_delay_save(self._serialize, delay=ALERT_SAVE_DELAY_SECONDS)

    def _serialize(self) -> dict[str, Any]:
        return {
            "capture_version": ALERT_CAPTURE_VERSION,
            "host_identity_version": _HOST_IDENTITY_VERSION,
            "host_identity": self._host_identity,
            "total_received": self._total_received,
            "dropped_count": self._dropped_count,
            "overflow_count": self._overflow_count,
            "truncated_count": self._truncated_count,
            "events": [dict(event) for event in self._events],
        }

    def _enforce_limits(self) -> None:
        while self._events and (
            len(self._events) > MAX_ALERT_EVENTS
            or _compact_size(self._serialize()) > MAX_ALERT_STORAGE_BYTES
        ):
            self._events.pop(0)
            self._dropped_count = min(_MAX_COUNTER, self._dropped_count + 1)
            self._overflow_count = min(_MAX_COUNTER, self._overflow_count + 1)


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
            _compact_size(candidate) <= MAX_ALERT_EXPORT_BYTES
            and _compact_size(combined) <= MAX_TOTAL_DIAGNOSTICS_BYTES
        ):
            exported.append(candidate_event)

    while True:
        result = _alert_export_metadata(capture, len(events) - len(exported))
        result["events"] = list(reversed(exported))
        combined = dict(base_snapshot)
        combined["experimental_alert_capture"] = result
        if (
            _compact_size(result) <= MAX_ALERT_EXPORT_BYTES
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
