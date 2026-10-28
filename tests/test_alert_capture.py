"""Opaque MQTT alert capture storage and export contracts."""

from __future__ import annotations

import asyncio
import base64
import json
from datetime import UTC, datetime

from homeassistant.helpers.storage import Store
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.jackery import DOMAIN, async_remove_entry
from custom_components.jackery import alert_capture as alert_capture_module
from custom_components.jackery.alert_capture import (
    ALERT_CAPTURE_VERSION,
    MAX_ALERT_EVENTS,
    MAX_ALERT_EXPORT_BYTES,
    MAX_ALERT_PAYLOAD_BYTES,
    MAX_ALERT_STORAGE_BYTES,
    MAX_TOTAL_DIAGNOSTICS_BYTES,
    AlertCapture,
    _compact_size,
    async_delete_alert_capture,
    build_alert_capture_export,
    build_alert_topic,
)

TOPIC = "hb/device/HOST_A/alert"
NOW = datetime(2026, 10, 28, 8, 10, tzinfo=UTC)


def _new_capture(
    hass,
    entry_id: str = "entry-a",
    topic: str | None = TOPIC,
    host: str | None = "HOST_A",
) -> AlertCapture:
    return AlertCapture(hass, entry_id, topic, host)


def test_build_alert_topic_is_literal_and_fails_closed() -> None:
    assert build_alert_topic("root/solar", "HOST_A") == "root/solar/device/HOST_A/alert"
    assert build_alert_topic("root/+", "HOST_A") is None
    assert build_alert_topic("root/#", "HOST_A") is None
    assert build_alert_topic("root", "HOST/A") is None
    assert build_alert_topic("root", None) is None
    assert build_alert_topic("", "HOST_A") is None


async def test_payload_is_opaque_byte_preserved_and_metadata_is_bounded(hass) -> None:
    capture = _new_capture(hass)
    await capture.async_load()
    raw = b'{"unknown":[1,2],"bad_utf8":"\xff"}'

    assert capture.observe(
        topic=TOPIC,
        payload=raw,
        qos=1,
        retain=True,
        received_at=NOW,
    )
    assert not capture.observe(topic="hb/device/OTHER/alert", payload=raw)

    snapshot = capture.snapshot()
    assert snapshot["total_received"] == 1
    assert snapshot["stored_count"] == 1
    assert "host_identity" not in snapshot
    event = snapshot["events"][0]
    assert event["received_at"] == "2026-10-28T08:10:00.000Z"
    assert event["topic"] == TOPIC
    assert event["payload_encoding"] == "base64"
    assert base64.b64decode(event["payload_base64"]) == raw
    assert event["payload_size"] == len(raw)
    assert event["payload_truncated"] is False
    assert event["qos"] == 1
    assert event["retain"] is True
    await capture.async_flush()


async def test_empty_invalid_and_non_utf8_payloads_are_recorded_without_parsing(hass) -> None:
    capture = _new_capture(hass)
    await capture.async_load()
    for raw in (b"", b"{invalid json", b"\xff\xfe\x00"):
        assert capture.observe(topic=TOPIC, payload=raw)
    events = capture.snapshot()["events"]
    assert [base64.b64decode(item["payload_base64"]) for item in events] == [
        b"",
        b"{invalid json",
        b"\xff\xfe\x00",
    ]
    await capture.async_flush()


async def test_oversize_payload_is_explicitly_truncated_and_counted(hass) -> None:
    capture = _new_capture(hass)
    await capture.async_load()
    raw = bytes(range(256)) * ((MAX_ALERT_PAYLOAD_BYTES // 256) + 1)

    capture.observe(topic=TOPIC, payload=raw)

    event = capture.snapshot()["events"][0]
    assert event["payload_size"] == len(raw)
    assert event["payload_truncated"] is True
    assert len(base64.b64decode(event["payload_base64"])) == MAX_ALERT_PAYLOAD_BYTES
    assert capture.snapshot()["truncated_count"] == 1
    await capture.async_flush()


async def test_ring_buffer_rotates_oldest_and_tracks_overflow(hass) -> None:
    capture = _new_capture(hass)
    await capture.async_load()
    for index in range(MAX_ALERT_EVENTS + 1):
        capture.observe(topic=TOPIC, payload=str(index).encode(), received_at=NOW)

    snapshot = capture.snapshot()
    assert snapshot["stored_count"] == MAX_ALERT_EVENTS
    assert snapshot["total_received"] == MAX_ALERT_EVENTS + 1
    assert snapshot["dropped_count"] == 1
    assert snapshot["overflow_count"] == 1
    assert base64.b64decode(snapshot["events"][0]["payload_base64"]) == b"1"
    await capture.async_flush()


async def test_storage_budget_is_enforced_even_before_event_limit(hass) -> None:
    capture = _new_capture(hass)
    await capture.async_load()
    for _ in range(80):
        capture.observe(topic=TOPIC, payload=b"x" * MAX_ALERT_PAYLOAD_BYTES)

    saved_data = capture._serialize()
    assert len(saved_data["events"]) < MAX_ALERT_EVENTS
    assert _compact_size(saved_data) <= MAX_ALERT_STORAGE_BYTES
    assert capture.snapshot()["overflow_count"] > 0
    await capture.async_flush()


async def test_store_restores_across_capture_instances_and_isolates_entries(hass) -> None:
    first = _new_capture(hass)
    isolated = AlertCapture(hass, "entry-b", TOPIC, "HOST_A")
    await first.async_load()
    await isolated.async_load()
    first.observe(topic=TOPIC, payload=b"persistent")
    await first.async_flush()

    restored = _new_capture(hass)
    await restored.async_load()
    other = isolated.snapshot()
    assert restored.snapshot()["stored_count"] == 1
    assert base64.b64decode(restored.snapshot()["events"][0]["payload_base64"]) == b"persistent"
    assert other["stored_count"] == 0

    await async_delete_alert_capture(hass, "entry-a")
    await async_delete_alert_capture(hass, "entry-b")


async def test_private_store_setting_preserves_key_and_compatible_data(hass, monkeypatch) -> None:
    real_store = alert_capture_module.Store
    created: list[tuple[int, str, bool]] = []

    def recording_store(hass, version: int, key: str, *args, **kwargs):
        created.append((version, key, kwargs.get("private", False)))
        return real_store(hass, version, key, *args, **kwargs)

    monkeypatch.setattr(alert_capture_module, "Store", recording_store)
    key = f"{DOMAIN}.private-entry.experimental_alert_capture"

    previous = AlertCapture(
        hass, "private-entry", TOPIC, "HOST_A"
    )
    previous.observe(topic=TOPIC, payload=b"compatible data")
    await previous.async_flush()
    # Model an existing file written before Store(private=True) was enabled.
    await real_store(hass, ALERT_CAPTURE_VERSION, key, private=False).async_save(
        previous._serialize()
    )

    restored = AlertCapture(hass, "private-entry", TOPIC, "HOST_A")
    await restored.async_load()
    assert restored.snapshot()["stored_count"] == 1
    assert base64.b64decode(restored.snapshot()["events"][0]["payload_base64"]) == b"compatible data"
    assert restored._store.path == real_store(
        hass, ALERT_CAPTURE_VERSION, key, private=False
    ).path

    await async_delete_alert_capture(hass, "private-entry")

    assert created == [
        (ALERT_CAPTURE_VERSION, key, True),
        (ALERT_CAPTURE_VERSION, key, True),
        (ALERT_CAPTURE_VERSION, key, True),
    ]
    assert (await real_store(hass, ALERT_CAPTURE_VERSION, key, private=True).async_load()) is None


async def test_host_binding_survives_reload_and_prefix_change(hass) -> None:
    original = _new_capture(hass)
    await original.async_load()
    original.observe(topic=TOPIC, payload=b"same host")
    await original.async_flush()

    new_topic = "newroot/device/HOST_A/alert"
    after_prefix_change = _new_capture(hass, topic=new_topic)
    await after_prefix_change.async_load()

    assert after_prefix_change.snapshot()["stored_count"] == 1
    assert after_prefix_change.snapshot()["total_received"] == 1
    assert after_prefix_change.snapshot()["events"][0]["topic"] == TOPIC
    await async_delete_alert_capture(hass, "entry-a")


async def test_host_change_discards_previous_devices_capture(hass) -> None:
    previous = _new_capture(hass)
    await previous.async_load()
    previous.observe(topic=TOPIC, payload=b"host A only")
    await previous.async_flush()

    host_b_topic = "hb/device/HOST_B/alert"
    changed_host = _new_capture(hass, topic=host_b_topic, host="HOST_B")
    await changed_host.async_load()

    assert changed_host.snapshot()["stored_count"] == 0
    assert changed_host.snapshot()["total_received"] == 0
    assert changed_host.observe(topic=host_b_topic, payload=b"host B")
    await changed_host.async_flush()

    restored_host_b = _new_capture(hass, topic=host_b_topic, host="HOST_B")
    await restored_host_b.async_load()
    assert restored_host_b.snapshot()["stored_count"] == 1
    assert base64.b64decode(restored_host_b.snapshot()["events"][0]["payload_base64"]) == b"host B"
    await async_delete_alert_capture(hass, "entry-a")


async def test_legacy_unbound_store_is_read_then_purged_fail_closed(hass) -> None:
    key = f"{DOMAIN}.legacy.experimental_alert_capture"
    legacy_store = Store(hass, ALERT_CAPTURE_VERSION, key, private=False)
    await legacy_store.async_save(
        {
            "capture_version": ALERT_CAPTURE_VERSION,
            "total_received": 1,
            "events": [
                {
                    "received_at": "2026-10-28T08:10:00.000Z",
                    "topic": TOPIC,
                    "payload_encoding": "base64",
                    "payload_size": 13,
                    "payload_truncated": False,
                    "payload_base64": base64.b64encode(b"legacy secret").decode(),
                    "qos": None,
                    "retain": None,
                }
            ],
        }
    )
    capture = _new_capture(hass, entry_id="legacy")

    await capture.async_load()

    assert capture.snapshot()["stored_count"] == 0
    assert capture.snapshot()["total_received"] == 0
    assert capture.observe(topic=TOPIC, payload=b"new trusted event")
    await capture.async_flush()
    await async_delete_alert_capture(hass, "legacy")


async def test_missing_host_identity_fails_closed_and_clears_unboundable_data(hass) -> None:
    valid = _new_capture(hass)
    await valid.async_load()
    valid.observe(topic=TOPIC, payload=b"do not assign without identity")
    await valid.async_flush()

    invalid = _new_capture(hass, topic=None, host=None)
    await invalid.async_load()

    assert invalid.topic is None
    assert invalid.snapshot()["stored_count"] == 0
    assert not invalid.observe(topic=TOPIC, payload=b"foreign")
    restored = _new_capture(hass)
    await restored.async_load()
    assert restored.snapshot()["stored_count"] == 0


async def test_delayed_save_cannot_recreate_data_after_disable_clear(hass, monkeypatch) -> None:
    monkeypatch.setattr(alert_capture_module, "ALERT_SAVE_DELAY_SECONDS", 0.02)
    capture = _new_capture(hass)
    await capture.async_load()
    capture.observe(topic=TOPIC, payload=b"pending raw data")

    await capture.async_clear()
    await asyncio.sleep(0.05)

    restored = _new_capture(hass)
    await restored.async_load()
    assert restored.snapshot()["stored_count"] == 0
    assert restored.snapshot()["total_received"] == 0
    assert not capture.observe(topic=TOPIC, payload=b"after clear")


async def test_removing_config_entry_deletes_its_capture_store(hass) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"device_sn": "HOST_A", "token": "synthetic", "topic_prefix": "hb"},
    )
    entry.add_to_hass(hass)
    capture = AlertCapture(hass, entry.entry_id, TOPIC, "HOST_A")
    await capture.async_load()
    capture.observe(topic=TOPIC, payload=b"remove me")
    await capture.async_flush()

    await async_remove_entry(hass, entry)

    restored = AlertCapture(hass, entry.entry_id, None, "HOST_A")
    await restored.async_load()
    assert restored.snapshot()["stored_count"] == 0


async def test_damaged_or_incompatible_store_is_ignored_safely(hass) -> None:
    store = Store(
        hass,
        ALERT_CAPTURE_VERSION,
        f"{DOMAIN}.damaged.experimental_alert_capture",
        private=True,
    )
    await store.async_save(
        {
            "capture_version": ALERT_CAPTURE_VERSION,
            "host_identity_version": 1,
            "host_identity": alert_capture_module._host_identity("HOST_A"),
            "total_received": "invalid",
            "events": [
                {"topic": TOPIC, "payload_base64": "not-base64"},
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
    capture = AlertCapture(hass, "damaged", TOPIC, "HOST_A")

    await capture.async_load()

    assert capture.snapshot()["stored_count"] == 0
    assert capture.snapshot()["total_received"] == 0

    await store.async_remove()


def test_diagnostic_export_aliases_topic_and_stays_within_total_budget() -> None:
    encoded = base64.b64encode(b"payload").decode()
    event = {
        "received_at": "2026-10-28T08:10:00.000Z",
        "topic": TOPIC,
        "payload_encoding": "base64",
        "payload_size": 7,
        "payload_truncated": False,
        "payload_base64": encoded,
        "qos": 1,
        "retain": False,
    }
    capture = {
        "total_received": 2,
        "stored_count": 1,
        "dropped_count": 1,
        "overflow_count": 1,
        "truncated_count": 0,
        "events": [event],
    }
    base = {"integration": {"known": True}}

    exported = build_alert_capture_export(capture, base)

    assert exported["enabled"] is True
    assert exported["capture_version"] == 1
    assert exported["events"][0]["topic"] == "{prefix}/device/{host}/alert"
    assert TOPIC not in json.dumps(exported)
    assert exported["export_omitted_count"] == 0
    assert "may include serial numbers" in exported["privacy_warning"]
    assert exported["sharing_policy"] == "not_public_without_review"
    assert _compact_size(exported) <= MAX_ALERT_EXPORT_BYTES
    assert _compact_size({**base, "experimental_alert_capture": exported}) <= MAX_TOTAL_DIAGNOSTICS_BYTES


def test_export_drops_old_records_first_and_reports_omissions() -> None:
    event_payload = b"x" * MAX_ALERT_PAYLOAD_BYTES
    events = [
        {
            "received_at": f"2026-10-28T08:{index % 60:02d}:00.000Z",
            "topic": TOPIC,
            "payload_encoding": "base64",
            "payload_size": len(event_payload),
            "payload_truncated": False,
            "payload_base64": base64.b64encode(event_payload).decode(),
            "qos": 1,
            "retain": False,
        }
        for index in range(MAX_ALERT_EVENTS)
    ]
    base = {"fixed": "x" * (64 * 1024 - 300)}
    capture = {
        "total_received": MAX_ALERT_EVENTS,
        "stored_count": MAX_ALERT_EVENTS,
        "dropped_count": 0,
        "overflow_count": 0,
        "truncated_count": 0,
        "events": events,
    }

    exported = build_alert_capture_export(capture, base)

    assert exported["export_omitted_count"] > 0
    assert exported["stored_count"] == MAX_ALERT_EVENTS
    assert exported["events"][-1]["received_at"] == events[-1]["received_at"]
    assert len(exported["events"]) < MAX_ALERT_EVENTS
    assert _compact_size({**base, "experimental_alert_capture": exported}) <= MAX_TOTAL_DIAGNOSTICS_BYTES
