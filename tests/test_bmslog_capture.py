"""Opaque BMS log capture storage, bounds and export contract."""

from __future__ import annotations

import asyncio
import base64
import json
from datetime import UTC, datetime

from homeassistant.helpers.storage import Store
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.jackery import DOMAIN, async_remove_entry
from custom_components.jackery.bmslog_capture import (
    BMSLOG_CAPTURE_VERSION,
    BMSLOG_TOPIC_ALIAS,
    MAX_BMSLOG_EVENTS,
    MAX_BMSLOG_EXPORT_BYTES,
    MAX_BMSLOG_PAYLOAD_BYTES,
    MAX_BMSLOG_STORAGE_BYTES,
    MAX_BMSLOG_TOPIC_BYTES,
    BmslogCapture,
    async_delete_bmslog_capture,
    build_bmslog_capture_export,
    build_bmslog_topic,
)
from custom_components.jackery.capture_storage import compact_size

TOPIC = "hb/device/HOST_A/bmslog"
NOW = datetime(2026, 11, 13, 10, 15, tzinfo=UTC)


def _new_capture(hass, entry_id: str = "entry-a", topic: str | None = TOPIC, host: str = "HOST_A"):
    return BmslogCapture(hass, entry_id, topic, host)


def test_bmslog_topic_is_literal_and_fails_closed() -> None:
    assert build_bmslog_topic("root/solar", "HOST_A") == "root/solar/device/HOST_A/bmslog"
    assert build_bmslog_topic("root/+", "HOST_A") is None
    assert build_bmslog_topic("root/#", "HOST_A") is None
    assert build_bmslog_topic("root", "HOST/A") is None
    assert build_bmslog_topic("root", None) is None
    assert build_bmslog_topic("", "HOST_A") is None
    assert build_bmslog_topic("x" * MAX_BMSLOG_TOPIC_BYTES, "HOST_A") is None


async def test_exact_topic_opaque_bytes_and_metadata_are_preserved(hass) -> None:
    capture = _new_capture(hass)
    await capture.async_load()
    raw = b'{"unknown":[1,2],"bad_utf8":"\xff"}'

    assert capture.observe(
        topic=TOPIC,
        payload=raw,
        qos=2,
        retain=True,
        received_at=NOW,
    )
    assert not capture.observe(topic="hb/device/OTHER/bmslog", payload=raw)
    assert not capture.observe(topic="other/device/HOST_A/bmslog", payload=raw)
    assert not capture.observe(topic="hb/device/HOST_A/status", payload=raw)

    snapshot = capture.snapshot()
    assert snapshot["capture_version"] == BMSLOG_CAPTURE_VERSION
    assert snapshot["total_received"] == 1
    assert snapshot["stored_count"] == 1
    assert "host_identity" not in snapshot
    event = snapshot["events"][0]
    assert event["received_at"] == "2026-11-13T10:15:00.000Z"
    assert event["topic"] == TOPIC
    assert event["payload_encoding"] == "base64"
    assert base64.b64decode(event["payload_base64"]) == raw
    assert event["payload_size"] == len(raw)
    assert event["payload_truncated"] is False
    assert event["qos"] == 2
    assert event["retain"] is True
    await capture.async_flush()


async def test_payload_truncation_event_ring_and_storage_bounds(hass) -> None:
    capture = _new_capture(hass)
    await capture.async_load()
    oversized = bytes(range(256)) * ((MAX_BMSLOG_PAYLOAD_BYTES // 256) + 1)
    capture.observe(topic=TOPIC, payload=oversized)
    event = capture.snapshot()["events"][0]
    assert event["payload_size"] == len(oversized)
    assert event["payload_truncated"] is True
    assert len(base64.b64decode(event["payload_base64"])) == MAX_BMSLOG_PAYLOAD_BYTES
    assert capture.snapshot()["truncated_count"] == 1

    for index in range(MAX_BMSLOG_EVENTS):
        capture.observe(topic=TOPIC, payload=str(index).encode(), received_at=NOW)
    snapshot = capture.snapshot()
    assert snapshot["stored_count"] == MAX_BMSLOG_EVENTS
    assert snapshot["total_received"] == MAX_BMSLOG_EVENTS + 1
    assert snapshot["overflow_count"] == 1
    assert snapshot["dropped_count"] == 1
    assert base64.b64decode(snapshot["events"][0]["payload_base64"]) == b"0"
    await capture.async_flush()

    large = _new_capture(hass, entry_id="large")
    await large.async_load()
    for _ in range(80):
        large.observe(topic=TOPIC, payload=b"x" * MAX_BMSLOG_PAYLOAD_BYTES)
    stored = large._serialize()
    assert len(stored["events"]) < MAX_BMSLOG_EVENTS
    assert compact_size(stored) <= MAX_BMSLOG_STORAGE_BYTES
    assert large.snapshot()["overflow_count"] > 0
    await large.async_flush()


async def test_persistence_entry_isolation_prefix_change_and_host_binding(hass) -> None:
    first = _new_capture(hass)
    other_entry = _new_capture(hass, entry_id="entry-b")
    await first.async_load()
    await other_entry.async_load()
    first.observe(topic=TOPIC, payload=b"persistent bytes")
    await first.async_flush()

    restored = _new_capture(hass)
    await restored.async_load()
    assert restored.snapshot()["stored_count"] == 1
    assert base64.b64decode(restored.snapshot()["events"][0]["payload_base64"]) == b"persistent bytes"
    assert other_entry.snapshot()["stored_count"] == 0

    prefix_changed = _new_capture(
        hass,
        topic="newroot/device/HOST_A/bmslog",
    )
    await prefix_changed.async_load()
    assert prefix_changed.topic == "newroot/device/HOST_A/bmslog"
    assert prefix_changed.snapshot()["stored_count"] == 1

    changed_host = _new_capture(
        hass,
        topic="hb/device/HOST_B/bmslog",
        host="HOST_B",
    )
    await changed_host.async_load()
    assert changed_host.snapshot()["stored_count"] == 0
    assert changed_host.snapshot()["total_received"] == 0
    assert changed_host.observe(topic="hb/device/HOST_B/bmslog", payload=b"host B only")
    await changed_host.async_flush()

    await async_delete_bmslog_capture(hass, "entry-a")
    await async_delete_bmslog_capture(hass, "entry-b")


async def test_delayed_save_cannot_recreate_store_after_clear(hass, monkeypatch) -> None:
    monkeypatch.setattr("custom_components.jackery.bmslog_capture.BMSLOG_SAVE_DELAY_SECONDS", 0.02)
    capture = _new_capture(hass)
    capture._save_delay = 0.02
    await capture.async_load()
    capture.observe(topic=TOPIC, payload=b"pending raw data")

    await capture.async_clear()
    await asyncio.sleep(0.05)

    restored = _new_capture(hass)
    await restored.async_load()
    assert restored.snapshot()["stored_count"] == 0
    assert restored.snapshot()["total_received"] == 0
    assert not capture.observe(topic=TOPIC, payload=b"after clear")
    await capture.async_flush()
    assert await restored._store.async_load() is None


async def test_removing_config_entry_deletes_bmslog_store(hass) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"device_sn": "HOST_A", "token": "synthetic", "topic_prefix": "hb"},
    )
    entry.add_to_hass(hass)
    capture = _new_capture(hass, entry_id=entry.entry_id)
    await capture.async_load()
    capture.observe(topic=TOPIC, payload=b"remove me")
    await capture.async_flush()

    await async_remove_entry(hass, entry)

    restored = BmslogCapture(hass, entry.entry_id, None, "HOST_A")
    await restored.async_load()
    assert restored.snapshot()["stored_count"] == 0


async def test_damaged_or_wrong_host_store_fails_closed(hass) -> None:
    store = Store(
        hass,
        BMSLOG_CAPTURE_VERSION,
        f"{DOMAIN}.damaged.experimental_bmslog_capture",
        private=True,
    )
    await store.async_save(
        {
            "capture_version": BMSLOG_CAPTURE_VERSION,
            "host_identity_version": 1,
            "host_identity": "wrong-host",
            "total_received": "bad",
            "events": [
                {"topic": TOPIC, "payload_base64": "not base64"},
                {
                    "topic": TOPIC,
                    "received_at": NOW.isoformat(),
                    "payload_base64": base64.b64encode(b"mismatch").decode(),
                    "payload_size": 1,
                    "payload_truncated": False,
                },
            ],
        }
    )
    capture = _new_capture(hass, entry_id="damaged")
    await capture.async_load()
    assert capture.snapshot()["stored_count"] == 0
    assert capture.snapshot()["total_received"] == 0
    await store.async_remove()


def test_export_aliases_topic_warns_about_raw_data_and_enforces_bounds() -> None:
    raw = b"PRIVATE_SERIAL_CANARY"
    capture = {
        "total_received": 3,
        "stored_count": 1,
        "dropped_count": 1,
        "overflow_count": 1,
        "truncated_count": 1,
        "events": [
            {
                "received_at": "2026-11-13T10:15:00.000Z",
                "topic": TOPIC,
                "payload_encoding": "base64",
                "payload_size": len(raw),
                "payload_truncated": False,
                "payload_base64": base64.b64encode(raw).decode("ascii"),
                "qos": 1,
                "retain": False,
            }
        ],
    }
    exported = build_bmslog_capture_export(capture, {"integration": {"safe": True}})

    assert exported["enabled"] is True
    assert exported["capture_version"] == BMSLOG_CAPTURE_VERSION
    assert exported["events"][0]["topic"] == BMSLOG_TOPIC_ALIAS
    assert exported["events"][0]["payload_encoding"] == "base64"
    assert base64.b64decode(exported["events"][0]["payload_base64"]) == raw
    assert "PRIVATE_SERIAL_CANARY" not in json.dumps(exported)
    assert TOPIC not in json.dumps(exported)
    assert "sensitive information" in exported["privacy_warning"]
    assert exported["export_omitted_count"] == 0
    assert compact_size(exported) <= MAX_BMSLOG_EXPORT_BYTES


def test_export_drops_oldest_events_when_shared_budget_is_tight() -> None:
    payload = b"x" * MAX_BMSLOG_PAYLOAD_BYTES
    events = [
        {
            "received_at": f"2026-11-13T10:{index % 60:02d}:00.000Z",
            "topic": TOPIC,
            "payload_encoding": "base64",
            "payload_size": len(payload),
            "payload_truncated": False,
            "payload_base64": base64.b64encode(payload).decode("ascii"),
            "qos": 1,
            "retain": False,
        }
        for index in range(MAX_BMSLOG_EVENTS)
    ]
    capture = {
        "total_received": MAX_BMSLOG_EVENTS,
        "stored_count": MAX_BMSLOG_EVENTS,
        "dropped_count": 0,
        "overflow_count": 0,
        "truncated_count": 0,
        "events": events,
    }
    base = {"fixed": "x" * (64 * 1024 + 2 * 24 * 1024 - 7_500)}

    exported = build_bmslog_capture_export(capture, base)

    assert exported["export_omitted_count"] > 0
    assert exported["stored_count"] == MAX_BMSLOG_EVENTS
    assert len(exported["events"]) < MAX_BMSLOG_EVENTS
    assert exported["events"][-1]["received_at"] == events[-1]["received_at"]
    assert compact_size({**base, "experimental_bmslog_capture": exported}) <= 64 * 1024 + 2 * 24 * 1024
