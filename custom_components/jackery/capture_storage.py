"""Small shared primitives for private, host-bound MQTT capture stores."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_HOST_IDENTITY_VERSION = 1
_MAX_COUNTER = 2_147_483_647


def host_fingerprint(device_sn: object, namespace: str) -> str | None:
    """Return a stable host fingerprint without retaining the serial itself."""
    if (
        not isinstance(device_sn, str)
        or not device_sn
        or device_sn != device_sn.strip()
        or any(character in "/+#\x00" or ord(character) < 32 or ord(character) == 127 for character in device_sn)
    ):
        return None
    try:
        encoded = device_sn.encode("utf-8")
    except UnicodeEncodeError:
        return None
    return hashlib.sha256(namespace.encode("ascii") + b"\0" + encoded).hexdigest()


def build_host_topic(
    topic_prefix: object,
    device_sn: object,
    leaf: str,
    *,
    max_topic_bytes: int,
) -> str | None:
    """Build a literal host MQTT topic, rejecting wildcard-capable inputs."""
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
    if not leaf or "/" in leaf or any(character in "+#\x00" for character in leaf):
        return None
    topic = f"{topic_prefix}/device/{device_sn}/{leaf}"
    try:
        if len(topic.encode("utf-8")) > max_topic_bytes:
            return None
    except UnicodeEncodeError:
        return None
    return topic


def private_entry_store(
    hass: HomeAssistant,
    *,
    version: int,
    key: str,
) -> Store[dict[str, Any]]:
    """Create an HA Store with the private-storage behavior used by captures."""
    return Store(hass, version, key, private=True)


def compact_size(value: Any) -> int:
    """Return deterministic compact UTF-8 JSON size for bounded storage."""
    return len(
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )


def bounded_counter(value: object) -> int:
    """Return a normalized persisted counter value."""
    if type(value) is not int:
        return 0
    return min(_MAX_COUNTER, max(0, value))


def validate_capture_event(
    value: object,
    *,
    max_payload_bytes: int,
    max_topic_bytes: int,
) -> dict[str, Any] | None:
    """Validate one opaque MQTT record loaded from private storage."""
    if not isinstance(value, Mapping):
        return None
    topic = value.get("topic")
    received_at = value.get("received_at")
    encoded = value.get("payload_base64")
    payload_size = value.get("payload_size")
    truncated = value.get("payload_truncated")
    try:
        topic_size = len(topic.encode("utf-8")) if isinstance(topic, str) else max_topic_bytes + 1
    except UnicodeEncodeError:
        return None
    if (
        not isinstance(topic, str)
        or topic_size > max_topic_bytes
        or not isinstance(received_at, str)
        or len(received_at) > 40
        or not isinstance(encoded, str)
        or len(encoded) > 4 * ((max_payload_bytes + 2) // 3)
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
    if len(payload) > max_payload_bytes:
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


class PersistentMqttCapture:
    """Shared bounded storage for one exact-topic opaque MQTT capture."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        version: int,
        store_key: str,
        host_identity: str | None,
        expected_topic: str | None,
        topic_identity_suffix: str | None,
        max_topic_bytes: int,
        max_events: int,
        max_payload_bytes: int,
        max_storage_bytes: int,
        save_delay: float,
        store_factory: Any = Store,
    ) -> None:
        self._store: Store[dict[str, Any]] = store_factory(
            hass, version, store_key, private=True
        )
        self._version = version
        self._host_identity = host_identity
        self._topic_identity_suffix = topic_identity_suffix
        self._max_topic_bytes = max_topic_bytes
        self._max_events = max_events
        self._max_payload_bytes = max_payload_bytes
        self._max_storage_bytes = max_storage_bytes
        self._save_delay = save_delay
        self._expected_topic = None
        if (
            host_identity is not None
            and isinstance(expected_topic, str)
            and isinstance(topic_identity_suffix, str)
            and expected_topic.endswith(topic_identity_suffix)
            and len(expected_topic) > len(topic_identity_suffix)
            and not any(
                character in "+#\x00" or ord(character) < 32 or ord(character) == 127
                for character in expected_topic
            )
        ):
            try:
                if len(expected_topic.encode("utf-8")) <= max_topic_bytes:
                    self._expected_topic = expected_topic
            except UnicodeEncodeError:
                pass
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
            or type(data.get("capture_version")) is not int
            or data.get("capture_version") != self._version
            or type(data.get("host_identity_version")) is not int
            or data.get("host_identity_version") != _HOST_IDENTITY_VERSION
            or data.get("host_identity") != self._host_identity
        ):
            # Data written for another or unknown host cannot be safely assigned.
            await self.async_clear()
            self._cleared = False
            return

        restored: list[dict[str, Any]] = []
        raw_events = data.get("events")
        if isinstance(raw_events, list):
            for raw_event in raw_events[-self._max_events :]:
                event = validate_capture_event(
                    raw_event,
                    max_payload_bytes=self._max_payload_bytes,
                    max_topic_bytes=self._max_topic_bytes,
                )
                if (
                    event is not None
                    and self._topic_identity_suffix is not None
                    and event["topic"].endswith(self._topic_identity_suffix)
                ):
                    restored.append(event)
        self._events = restored
        self._total_received = bounded_counter(data.get("total_received"))
        self._dropped_count = bounded_counter(data.get("dropped_count"))
        self._overflow_count = bounded_counter(data.get("overflow_count"))
        self._truncated_count = bounded_counter(data.get("truncated_count"))
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
        """Record an exact-topic delivery without decoding its payload."""
        if self._cleared or self._host_identity is None or topic != self._expected_topic:
            return False

        self._total_received = min(_MAX_COUNTER, self._total_received + 1)
        if isinstance(payload, bytes):
            raw_payload = payload
        elif isinstance(payload, (bytearray, memoryview)):
            raw_payload = bytes(payload)
        elif isinstance(payload, str):
            # HA's MQTT callback supplies bytes; support text test fakes exactly.
            raw_payload = payload.encode("utf-8", errors="surrogatepass")
        else:
            self._dropped_count = min(_MAX_COUNTER, self._dropped_count + 1)
            self._schedule_save()
            return True

        payload_size = len(raw_payload)
        truncated = payload_size > self._max_payload_bytes
        stored_payload = raw_payload[: self._max_payload_bytes]
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
            "capture_version": self._version,
            "total_received": self._total_received,
            "stored_count": len(self._events),
            "dropped_count": self._dropped_count,
            "overflow_count": self._overflow_count,
            "truncated_count": self._truncated_count,
            "events": [dict(event) for event in self._events],
        }

    async def async_flush(self) -> None:
        """Finish a pending debounced save before coordinator unload."""
        if not self._cleared and self._host_identity is not None:
            await self._store.async_save(self._serialize())

    async def async_clear(self) -> None:
        """Delete pending writes and persisted raw data without a save race."""
        self._cleared = True
        self._events.clear()
        self._total_received = 0
        self._dropped_count = 0
        self._overflow_count = 0
        self._truncated_count = 0
        await async_remove_store_without_save_race(self._store, self._serialize())

    def _schedule_save(self) -> None:
        if not self._cleared and self._host_identity is not None:
            self._store.async_delay_save(self._serialize, delay=self._save_delay)

    def _serialize(self) -> dict[str, Any]:
        return {
            "capture_version": self._version,
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
            len(self._events) > self._max_events
            or compact_size(self._serialize()) > self._max_storage_bytes
        ):
            self._events.pop(0)
            self._dropped_count = min(_MAX_COUNTER, self._dropped_count + 1)
            self._overflow_count = min(_MAX_COUNTER, self._overflow_count + 1)


def build_bounded_capture_export(
    capture: Mapping[str, Any],
    base_snapshot: Mapping[str, Any],
    *,
    section_key: str,
    topic_alias: str,
    max_export_bytes: int,
    max_total_bytes: int,
    validate_event: Any,
    metadata_factory: Any,
) -> dict[str, Any]:
    """Build a raw-data section while respecting its own and the shared export budget."""
    raw_events = capture.get("events")
    events = [
        event
        for raw_event in (raw_events if isinstance(raw_events, list) else [])
        if (event := validate_event(raw_event)) is not None
    ]
    exported: list[dict[str, Any]] = []
    for event in reversed(events):
        candidate_event = {
            "received_at": event["received_at"],
            "topic": topic_alias,
            "payload_encoding": "base64",
            "payload_size": event["payload_size"],
            "payload_truncated": event["payload_truncated"],
            "payload_base64": event["payload_base64"],
            "qos": event["qos"],
            "retain": event["retain"],
        }
        candidate = metadata_factory(capture, len(events) - len(exported) - 1)
        candidate["events"] = [*reversed(exported), candidate_event]
        combined = dict(base_snapshot)
        combined[section_key] = candidate
        if compact_size(candidate) <= max_export_bytes and compact_size(combined) <= max_total_bytes:
            exported.append(candidate_event)

    while True:
        result = metadata_factory(capture, len(events) - len(exported))
        result["events"] = list(reversed(exported))
        combined = dict(base_snapshot)
        combined[section_key] = result
        if compact_size(result) <= max_export_bytes and compact_size(combined) <= max_total_bytes:
            return result
        if not exported:
            result = metadata_factory(capture, len(events))
            result["events"] = []
            return result
        exported.pop()


async def async_remove_store_without_save_race(
    store: Store[dict[str, Any]],
    empty_data: Mapping[str, Any],
) -> None:
    """Drain a delayed save, then remove the store so it cannot be recreated."""
    await store.async_save(dict(empty_data))
    await store.async_remove()
