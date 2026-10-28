"""Persistent, sampled raw examples for opt-in protocol discovery."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Final

from homeassistant.core import HomeAssistant

from . import DOMAIN
from .alert_capture import MAX_TOTAL_DIAGNOSTICS_BYTES
from .capture_storage import (
    async_remove_store_without_save_race,
    compact_size,
    host_fingerprint,
    private_entry_store,
)
from .protocol_discovery import (
    DISCOVERY_VERSION,
    MAX_COUNTER,
    DiscoverySignal,
    ProtocolDiscoverySnapshot,
    ProtocolDiscoveryState,
)

PROTOCOL_CAPTURE_VERSION: Final = 1
MAX_PROTOCOL_EVENTS: Final = 100
MAX_PROTOCOL_PAYLOAD_BYTES: Final = 4 * 1024
MAX_PROTOCOL_RAW_STORAGE_BYTES: Final = 256 * 1024
MAX_PROTOCOL_STRUCTURE_STORAGE_BYTES: Final = 32 * 1024
MAX_PROTOCOL_SAMPLING_STORAGE_BYTES: Final = 32 * 1024
MAX_PROTOCOL_STORE_BYTES: Final = 320 * 1024
MAX_PROTOCOL_TOPIC_BYTES: Final = 512
MAX_PROTOCOL_EXPORT_BYTES: Final = 24 * 1024
MAX_SAMPLING_BUCKETS: Final = 128
MAX_SAMPLE_DIGESTS: Final = 4
MAX_INITIAL_SAMPLES: Final = 4
SAMPLE_INTERVAL_SECONDS: Final = 60 * 60
PROTOCOL_SAVE_DELAY_SECONDS: Final = 1.0
DISCOVERY_REASONS: Final = frozenset(
    {
        "invalid_envelope",
        "unknown_device_type",
        "unknown_message_type",
        "unknown_structure",
    }
)
_HOST_IDENTITY_VERSION: Final = 1
_PRIVACY_WARNING: Final = (
    "Contains experimental raw MQTT payloads encoded as Base64. Payloads may "
    "include sensitive information; review carefully before sharing publicly."
)
_EMPTY_PAYLOAD: Final = b""


def _counter(value: object) -> int:
    if type(value) is not int:
        return 0
    return min(MAX_COUNTER, max(0, value))


def _timestamp(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        return None
    return float(value)


def _payload_bytes(value: object) -> bytes | None:
    if isinstance(value, bytes):
        return value
    if isinstance(value, (bytearray, memoryview)):
        return bytes(value)
    if isinstance(value, str):
        # HA supplies bytes. Text is supported for simple transport fakes only.
        return value.encode("utf-8", errors="surrogatepass")
    return None


def _validated_event(value: object) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    received_at = value.get("received_at")
    topic = value.get("topic")
    reason = value.get("discovery_reason")
    encoded = value.get("payload_base64")
    payload_size = value.get("payload_size")
    truncated = value.get("payload_truncated")
    if (
        not isinstance(received_at, str)
        or len(received_at) > 40
        or not isinstance(topic, str)
        or len(topic.encode("utf-8", errors="replace")) > MAX_PROTOCOL_TOPIC_BYTES
        or not (topic.endswith("/status") or topic.endswith("/event"))
        or not isinstance(reason, str)
        or reason not in DISCOVERY_REASONS
        or not isinstance(encoded, str)
        or len(encoded) > 4 * ((MAX_PROTOCOL_PAYLOAD_BYTES + 2) // 3)
        or type(payload_size) is not int
        or not 0 <= payload_size <= MAX_COUNTER
        or type(truncated) is not bool
    ):
        return None
    try:
        datetime.fromisoformat(received_at.replace("Z", "+00:00"))
        payload = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        return None
    if len(payload) > MAX_PROTOCOL_PAYLOAD_BYTES:
        return None
    if (truncated and payload_size <= len(payload)) or (not truncated and payload_size != len(payload)):
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
        "discovery_reason": reason,
    }


class ProtocolDiscoveryCapture:
    """Own one entry's persistent structural state and sampled raw examples."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        topic_prefix: object,
        device_sn: object,
    ) -> None:
        self._store = private_entry_store(
            hass,
            version=PROTOCOL_CAPTURE_VERSION,
            key=f"{DOMAIN}.{entry_id}.experimental_protocol_discovery",
        )
        self._host_identity = host_fingerprint(
            device_sn,
            "jackery-protocol-discovery-host-v1",
        )
        self._expected_topics = self._build_topics(topic_prefix, device_sn)
        self._cleared = False
        self._state = ProtocolDiscoveryState()
        self._events: list[dict[str, Any]] = []
        self._sampling: dict[str, dict[str, Any]] = {}
        self._total_observed = 0
        self._total_captured = 0
        self._sampled_out_count = 0
        self._dropped_count = 0
        self._overflow_count = 0
        self._truncated_count = 0
        self._sampling_overflow_count = 0

    @staticmethod
    def _build_topics(topic_prefix: object, device_sn: object) -> frozenset[str]:
        if (
            not isinstance(topic_prefix, str)
            or not topic_prefix
            or not isinstance(device_sn, str)
            or not device_sn
            or device_sn != device_sn.strip()
        ):
            return frozenset()
        if any(
            character in "+#\x00" or ord(character) < 32 or ord(character) == 127 for character in topic_prefix
        ) or any(character in "/+#\x00" or ord(character) < 32 or ord(character) == 127 for character in device_sn):
            return frozenset()
        topics = {
            f"{topic_prefix}/device/{device_sn}/status",
            f"{topic_prefix}/device/{device_sn}/event",
        }
        try:
            if any(len(topic.encode("utf-8")) > MAX_PROTOCOL_TOPIC_BYTES for topic in topics):
                return frozenset()
        except UnicodeEncodeError:
            return frozenset()
        return frozenset(topics)

    @property
    def enabled(self) -> bool:
        """Whether this owner has both a safe host binding and exact topics."""
        return self._host_identity is not None and bool(self._expected_topics)

    def snapshot(self) -> ProtocolDiscoverySnapshot:
        """Return the detached value-free structural snapshot."""
        return self._state.snapshot()

    @property
    def state(self) -> ProtocolDiscoveryState:
        """Expose the pure structural owner for existing coordinator consumers."""
        return self._state

    async def async_load(self) -> None:
        """Restore versioned data only when the configured host still matches."""
        data = await self._store.async_load()
        if data is None:
            return
        if (
            self._host_identity is None
            or not isinstance(data, Mapping)
            or data.get("capture_version") != PROTOCOL_CAPTURE_VERSION
            or data.get("host_identity_version") != _HOST_IDENTITY_VERSION
            or data.get("host_identity") != self._host_identity
        ):
            await self.async_clear()
            self._cleared = False
            return

        state = ProtocolDiscoveryState.from_storage(data.get("discovery_state"))
        raw = data.get("raw_capture")
        if state is None or not isinstance(raw, Mapping) or raw.get("capture_version") != PROTOCOL_CAPTURE_VERSION:
            await self.async_clear()
            self._cleared = False
            return
        state.enforce_storage_budget(MAX_PROTOCOL_STRUCTURE_STORAGE_BYTES)
        self._state = state
        raw_events = raw.get("events")
        if not isinstance(raw_events, list):
            await self.async_clear()
            self._cleared = False
            return
        self._events = [
            event
            for raw_event in raw_events[-MAX_PROTOCOL_EVENTS:]
            if (event := _validated_event(raw_event)) is not None
        ]
        self._total_observed = _counter(raw.get("total_observed"))
        self._total_captured = _counter(raw.get("total_captured"))
        self._sampled_out_count = _counter(raw.get("sampled_out_count"))
        self._dropped_count = _counter(raw.get("dropped_count"))
        self._overflow_count = _counter(raw.get("overflow_count"))
        self._truncated_count = _counter(raw.get("truncated_count"))
        self._sampling_overflow_count = _counter(raw.get("sampling_overflow_count"))
        raw_sampling = raw.get("sampling_buckets")
        if not isinstance(raw_sampling, list) or len(raw_sampling) > MAX_SAMPLING_BUCKETS:
            await self.async_clear()
            self._cleared = False
            return
        for item in raw_sampling:
            bucket = _validated_sampling_bucket(item)
            if bucket is None or bucket[0] in self._sampling:
                await self.async_clear()
                self._cleared = False
                return
            identity, restored_bucket = bucket
            self._sampling[identity] = restored_bucket
        self._enforce_limits()

    def observe(
        self,
        *,
        topic: object,
        payload: object,
        raw_envelope: Mapping[str, Any],
        body: Mapping[str, Any],
        message_type: Any,
        now: float,
        qos: object = None,
        retain: object = None,
    ) -> bool:
        """Observe structure and sample at most one relevant original payload."""
        if not isinstance(topic, str) or not self._accepts_topic(topic):
            return False
        before = self._state.snapshot()
        findings = self._state.observe(
            raw_envelope,
            body,
            message_type=message_type,
            now=now,
        )
        self._state.enforce_storage_budget(MAX_PROTOCOL_STRUCTURE_STORAGE_BYTES)
        changed = self._state.snapshot() != before
        captured = False
        if findings:
            captured = self._consider_payload(
                topic=topic,
                payload=payload,
                findings=findings,
                now=now,
                qos=qos,
                retain=retain,
            )
        if changed or findings:
            self._schedule_save()
        return captured

    def observe_invalid(
        self,
        *,
        topic: object,
        payload: object,
        now: float,
        qos: object = None,
        retain: object = None,
    ) -> bool:
        """Sample malformed bytes only after exact configured-host topic match."""
        if not isinstance(topic, str) or not self._accepts_topic(topic):
            return False
        return self._consider_payload(
            topic=topic,
            payload=payload,
            findings=(DiscoverySignal("invalid_envelope", "invalid_envelope"),),
            now=now,
            qos=qos,
            retain=retain,
        )

    def _accepts_topic(self, topic: object) -> bool:
        return (
            not self._cleared
            and self._host_identity is not None
            and isinstance(topic, str)
            and topic in self._expected_topics
        )

    def _consider_payload(
        self,
        *,
        topic: str,
        payload: object,
        findings: tuple[DiscoverySignal, ...],
        now: float,
        qos: object,
        retain: object,
    ) -> bool:
        self._total_observed = min(MAX_COUNTER, self._total_observed + 1)
        raw_payload = _payload_bytes(payload)
        if raw_payload is None:
            self._dropped_count = min(MAX_COUNTER, self._dropped_count + 1)
            self._schedule_save()
            return False

        reason = findings[0].reason
        identity_material = json.dumps(
            [[finding.reason, finding.signature] for finding in findings],
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("ascii")
        bucket_id = hashlib.sha256(identity_material).hexdigest()
        digest = hashlib.sha256(raw_payload).hexdigest()
        bucket = self._sampling.get(bucket_id)
        if bucket is None:
            if len(self._sampling) >= MAX_SAMPLING_BUCKETS:
                self._sampling.pop(next(iter(self._sampling)))
                self._sampling_overflow_count = min(
                    MAX_COUNTER,
                    self._sampling_overflow_count + 1,
                )
            bucket = {"sample_count": 0, "last_sample_at": 0.0, "digests": []}
            self._sampling[bucket_id] = bucket

        if digest in bucket["digests"] or (
            bucket["sample_count"] >= MAX_INITIAL_SAMPLES and now - bucket["last_sample_at"] < SAMPLE_INTERVAL_SECONDS
        ):
            self._sampled_out_count = min(MAX_COUNTER, self._sampled_out_count + 1)
            self._schedule_save()
            return False

        bucket["sample_count"] = min(MAX_COUNTER, bucket["sample_count"] + 1)
        bucket["last_sample_at"] = now
        bucket["digests"] = [*bucket["digests"], digest][-MAX_SAMPLE_DIGESTS:]
        payload_size = len(raw_payload)
        truncated = payload_size > MAX_PROTOCOL_PAYLOAD_BYTES
        if truncated:
            self._truncated_count = min(MAX_COUNTER, self._truncated_count + 1)
        timestamp = datetime.fromtimestamp(now, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        self._events.append(
            {
                "received_at": timestamp,
                "topic": topic,
                "payload_encoding": "base64",
                "payload_size": payload_size,
                "payload_truncated": truncated,
                "payload_base64": base64.b64encode(raw_payload[:MAX_PROTOCOL_PAYLOAD_BYTES]).decode("ascii"),
                "qos": qos if type(qos) is int and qos in (0, 1, 2) else None,
                "retain": retain if type(retain) is bool else None,
                "discovery_reason": reason,
            }
        )
        self._total_captured = min(MAX_COUNTER, self._total_captured + 1)
        self._enforce_limits()
        self._schedule_save()
        return True

    def raw_snapshot(self) -> dict[str, Any]:
        """Return a detached raw-data view for the separate diagnostics area."""
        return {
            "capture_version": PROTOCOL_CAPTURE_VERSION,
            "total_observed": self._total_observed,
            "total_captured": self._total_captured,
            "stored_count": len(self._events),
            "sampled_out_count": self._sampled_out_count,
            "dropped_count": self._dropped_count,
            "overflow_count": self._overflow_count,
            "truncated_count": self._truncated_count,
            "sampling_overflow_count": self._sampling_overflow_count,
            "events": [dict(event) for event in self._events],
        }

    async def async_flush(self) -> None:
        """Flush pending delayed writes before coordinator unload."""
        if not self._cleared and self._host_identity is not None:
            await self._store.async_save(self._serialize())

    async def async_clear(self) -> None:
        """Delete pending writes and this feature's data without a save race."""
        self._cleared = True
        self._state = ProtocolDiscoveryState()
        self._events.clear()
        self._sampling.clear()
        self._total_observed = 0
        self._total_captured = 0
        self._sampled_out_count = 0
        self._dropped_count = 0
        self._overflow_count = 0
        self._truncated_count = 0
        self._sampling_overflow_count = 0
        await async_remove_store_without_save_race(self._store, self._serialize())

    def _schedule_save(self) -> None:
        if not self._cleared and self._host_identity is not None:
            self._store.async_delay_save(
                self._serialize,
                delay=PROTOCOL_SAVE_DELAY_SECONDS,
            )

    def _raw_storage(self) -> dict[str, Any]:
        return {
            **self.raw_snapshot(),
            "sampling_buckets": [
                {
                    "identity": identity,
                    "sample_count": bucket["sample_count"],
                    "last_sample_at": bucket["last_sample_at"],
                    "digests": list(bucket["digests"]),
                }
                for identity, bucket in self._sampling.items()
            ],
        }

    def _serialize(self) -> dict[str, Any]:
        return {
            "capture_version": PROTOCOL_CAPTURE_VERSION,
            "host_identity_version": _HOST_IDENTITY_VERSION,
            "host_identity": self._host_identity,
            "discovery_state": self._state.to_storage(),
            "raw_capture": self._raw_storage(),
        }

    def _enforce_limits(self) -> None:
        self._state.enforce_storage_budget(MAX_PROTOCOL_STRUCTURE_STORAGE_BYTES)
        while (
            self._sampling
            and compact_size({"sampling_buckets": self._raw_storage()["sampling_buckets"]})
            > MAX_PROTOCOL_SAMPLING_STORAGE_BYTES
        ):
            self._sampling.pop(next(iter(self._sampling)))
            self._sampling_overflow_count = min(
                MAX_COUNTER,
                self._sampling_overflow_count + 1,
            )
        while self._events and (
            len(self._events) > MAX_PROTOCOL_EVENTS
            or compact_size(self._raw_storage()) > MAX_PROTOCOL_RAW_STORAGE_BYTES
            or compact_size(self._serialize()) > MAX_PROTOCOL_STORE_BYTES
        ):
            self._events.pop(0)
            self._dropped_count = min(MAX_COUNTER, self._dropped_count + 1)
            self._overflow_count = min(MAX_COUNTER, self._overflow_count + 1)


def _validated_sampling_bucket(value: object) -> tuple[str, dict[str, Any]] | None:
    if not isinstance(value, Mapping):
        return None
    identity = value.get("identity")
    sample_count = value.get("sample_count")
    last_sample_at = _timestamp(value.get("last_sample_at"))
    digests = value.get("digests")
    if (
        not isinstance(identity, str)
        or len(identity) != 64
        or any(character not in "0123456789abcdef" for character in identity)
        or type(sample_count) is not int
        or not 0 <= sample_count <= MAX_COUNTER
        or last_sample_at is None
        or not isinstance(digests, list)
        or len(digests) > MAX_SAMPLE_DIGESTS
        or sample_count < len(digests)
    ):
        return None
    validated_digests: list[str] = []
    for digest in digests:
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            return None
        validated_digests.append(digest)
    return identity, {
        "sample_count": sample_count,
        "last_sample_at": last_sample_at,
        "digests": validated_digests,
    }


async def async_delete_protocol_capture(hass: HomeAssistant, entry_id: str) -> None:
    """Remove this entry's discovery store when disabled or removed."""
    store = private_entry_store(
        hass,
        version=PROTOCOL_CAPTURE_VERSION,
        key=f"{DOMAIN}.{entry_id}.experimental_protocol_discovery",
    )
    await store.async_remove()


def _export_metadata(capture: Mapping[str, Any], omitted: int) -> dict[str, Any]:
    return {
        "enabled": True,
        "capture_version": PROTOCOL_CAPTURE_VERSION,
        "discovery_version": DISCOVERY_VERSION,
        "total_observed": _counter(capture.get("total_observed")),
        "total_captured": _counter(capture.get("total_captured")),
        "stored_count": _counter(capture.get("stored_count")),
        "sampled_out_count": _counter(capture.get("sampled_out_count")),
        "dropped_count": _counter(capture.get("dropped_count")),
        "overflow_count": _counter(capture.get("overflow_count")),
        "truncated_count": _counter(capture.get("truncated_count")),
        "export_omitted_count": max(0, omitted),
        "privacy_warning": _PRIVACY_WARNING,
        "sharing_policy": "not_public_without_review",
        "limits": {
            "max_events": MAX_PROTOCOL_EVENTS,
            "max_payload_bytes": MAX_PROTOCOL_PAYLOAD_BYTES,
            "raw_storage_bytes": MAX_PROTOCOL_RAW_STORAGE_BYTES,
            "structure_storage_bytes": MAX_PROTOCOL_STRUCTURE_STORAGE_BYTES,
            "sampling_policy": "first 4 unique examples, then at most 1 per hour",
        },
        "events": [],
    }


def _topic_alias(topic: str) -> str:
    channel = "status" if topic.endswith("/status") else "event"
    return f"{{prefix}}/device/{{host}}/{channel}"


def build_protocol_capture_export(
    capture: Mapping[str, Any],
    base_snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a versioned raw extension inside both documented export budgets."""
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
            "topic": _topic_alias(event["topic"]),
            "payload_encoding": "base64",
            "payload_size": event["payload_size"],
            "payload_truncated": event["payload_truncated"],
            "payload_base64": event["payload_base64"],
            "qos": event["qos"],
            "retain": event["retain"],
            "discovery_reason": event["discovery_reason"],
        }
        candidate = _export_metadata(capture, len(events) - len(exported) - 1)
        candidate["events"] = [*reversed(exported), candidate_event]
        combined = dict(base_snapshot)
        combined["experimental_protocol_capture"] = candidate
        if (
            compact_size(candidate) <= MAX_PROTOCOL_EXPORT_BYTES
            and compact_size(combined) <= MAX_TOTAL_DIAGNOSTICS_BYTES
        ):
            exported.append(candidate_event)

    while True:
        result = _export_metadata(capture, len(events) - len(exported))
        result["events"] = list(reversed(exported))
        combined = dict(base_snapshot)
        combined["experimental_protocol_capture"] = result
        if compact_size(result) <= MAX_PROTOCOL_EXPORT_BYTES and compact_size(combined) <= MAX_TOTAL_DIAGNOSTICS_BYTES:
            return result
        if not exported:
            result = _export_metadata(capture, len(events))
            return result
        exported.pop()


__all__ = [
    "DISCOVERY_REASONS",
    "MAX_PROTOCOL_EVENTS",
    "MAX_PROTOCOL_EXPORT_BYTES",
    "MAX_PROTOCOL_PAYLOAD_BYTES",
    "MAX_PROTOCOL_RAW_STORAGE_BYTES",
    "MAX_PROTOCOL_STORE_BYTES",
    "MAX_PROTOCOL_STRUCTURE_STORAGE_BYTES",
    "PROTOCOL_CAPTURE_VERSION",
    "ProtocolDiscoveryCapture",
    "async_delete_protocol_capture",
    "build_protocol_capture_export",
]
