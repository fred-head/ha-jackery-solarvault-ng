"""Persistence, sampling, and raw-byte guarantees for Protocol Discovery."""

from __future__ import annotations

import base64
import json
from copy import deepcopy

import pytest

from custom_components.jackery import DOMAIN
from custom_components.jackery import capture_storage as capture_storage_module
from custom_components.jackery.capture_storage import compact_size
from custom_components.jackery.protocol_capture import (
    MAX_INITIAL_SAMPLES,
    MAX_PROTOCOL_EVENTS,
    MAX_PROTOCOL_EXPORT_BYTES,
    MAX_PROTOCOL_PAYLOAD_BYTES,
    MAX_PROTOCOL_RAW_STORAGE_BYTES,
    MAX_PROTOCOL_STRUCTURE_STORAGE_BYTES,
    PROTOCOL_CAPTURE_VERSION,
    ProtocolDiscoveryCapture,
    async_delete_protocol_capture,
    build_protocol_capture_export,
)

pytestmark = [
    pytest.mark.usefixtures("enable_custom_integrations"),
    pytest.mark.parametrize("load_registries", [False]),
]

TOPIC = "hb/device/HOST_A/status"


def _capture(hass, entry_id: str = "protocol-entry", prefix: str = "hb", host: str = "HOST_A"):
    return ProtocolDiscoveryCapture(hass, entry_id, prefix, host)


def _observe(
    capture: ProtocolDiscoveryCapture,
    payload: bytes,
    *,
    message_type: object = 2,
    body: dict | None = None,
    topic: str = TOPIC,
    now: float = 10_000,
) -> bool:
    data = body if body is not None else {"batSoc": 50, "newField": payload.decode("ascii", "replace")}
    return capture.observe(
        topic=topic,
        payload=payload,
        raw_envelope={"type": message_type, "body": data},
        body=data,
        message_type=message_type,
        now=now,
        qos=1,
        retain=False,
    )


async def test_only_findings_are_sampled_and_raw_bytes_are_preserved(hass) -> None:
    capture = _capture(hass)
    await capture.async_load()

    assert not _observe(
        capture,
        b'{"type":101,"body":{"plugs":[]}}',
        message_type=101,
        body={"plugs": []},
    )
    assert _observe(
        capture,
        b'{ "type" : 147, "body" : { "batSoc" : 50 } }',
        message_type=147,
        body={"batSoc": 50},
    )
    raw = b'{"type":2,"body":{"newField":"first","bad_utf8":"\xff"}}'
    assert _observe(capture, raw, message_type=2, body={"newField": "first"})

    snapshot = capture.raw_snapshot()
    assert snapshot["stored_count"] == 2
    assert snapshot["events"][0]["discovery_reason"] == "unknown_message_type"
    event = snapshot["events"][1]
    assert event["discovery_reason"] == "unknown_structure"
    assert base64.b64decode(event["payload_base64"]) == raw
    assert event["payload_size"] == len(raw)
    assert event["payload_truncated"] is False
    assert event["qos"] == 1
    assert event["retain"] is False
    await capture.async_clear()


async def test_unknown_device_classes_and_new_signatures_are_findings(hass) -> None:
    capture = _capture(hass)
    await capture.async_load()

    child_body = {
        "plugs": [{"devType": 4003, "subType": 7, "newChildValue": 1}],
    }
    assert _observe(
        capture,
        b'{"type":101,"body":{"plugs":[{"devType":4003,"subType":7}]}}',
        message_type=101,
        body=child_body,
    )
    assert capture.raw_snapshot()["events"][0]["discovery_reason"] == "unknown_device_type"

    before = len(capture.raw_snapshot()["events"])
    assert _observe(
        capture,
        b'{"type":2,"body":{"batSoc":50,"newField":10}}',
        body={"batSoc": 50, "newField": 10},
    )
    assert _observe(
        capture,
        b'{"type":2,"body":{"batSoc":51,"newField":11}}',
        body={"batSoc": 51, "newField": 11},
        now=10_001,
    )
    events = capture.raw_snapshot()["events"]
    assert len(events) == before + 2
    assert events[-2]["discovery_reason"] == "unknown_structure"
    assert events[-1]["discovery_reason"] == "unknown_structure"
    state = capture.snapshot()
    assert any(item.observation.count == 2 for item in state.structures)
    await capture.async_clear()


async def test_sampling_deduplicates_and_allows_occasional_new_examples(hass) -> None:
    capture = _capture(hass)
    await capture.async_load()
    assert _observe(capture, b"sample-0")
    assert not _observe(capture, b"sample-0", now=10_001)
    for index in range(1, MAX_INITIAL_SAMPLES):
        assert _observe(capture, f"sample-{index}".encode(), now=10_000 + index)
    assert not _observe(capture, b"sample-after-four", now=10_010)
    assert _observe(capture, b"sample-after-hour", now=10_000 + 3 + 3600)

    snapshot = capture.raw_snapshot()
    assert snapshot["stored_count"] == MAX_INITIAL_SAMPLES + 1
    assert snapshot["sampled_out_count"] == 2
    await capture.async_clear()


async def test_invalid_and_non_utf8_payloads_are_captured_only_for_exact_host(hass) -> None:
    capture = _capture(hass)
    await capture.async_load()
    assert not capture.observe_invalid(
        topic="hb/device/OTHER/status",
        payload=b"foreign",
        now=10_000,
    )
    raw = b"\xff\xfe\x00bad json"
    assert capture.observe_invalid(topic=TOPIC, payload=raw, now=10_000)
    event = capture.raw_snapshot()["events"][0]
    assert event["discovery_reason"] == "invalid_envelope"
    assert base64.b64decode(event["payload_base64"]) == raw
    await capture.async_clear()


async def test_truncation_ring_buffer_and_raw_storage_budget(hass) -> None:
    capture = _capture(hass)
    await capture.async_load()
    large = b"a" * (MAX_PROTOCOL_PAYLOAD_BYTES + 1)
    assert capture.observe_invalid(topic=TOPIC, payload=large, now=1)
    event = capture.raw_snapshot()["events"][0]
    assert event["payload_truncated"] is True
    assert len(base64.b64decode(event["payload_base64"])) == MAX_PROTOCOL_PAYLOAD_BYTES

    for index in range(100):
        capture.observe_invalid(
            topic=TOPIC,
            payload=f"event-{index}".encode() + b"x" * 4_000,
            now=2 + (index + 1) * 3600,
        )
    saved = capture._serialize()
    assert len(capture.raw_snapshot()["events"]) <= MAX_PROTOCOL_EVENTS
    assert compact_size(saved["raw_capture"]) <= MAX_PROTOCOL_RAW_STORAGE_BYTES
    assert capture.raw_snapshot()["dropped_count"] > 0
    assert capture.raw_snapshot()["overflow_count"] > 0
    assert capture.raw_snapshot()["truncated_count"] == 1
    await capture.async_clear()


async def test_structure_counters_first_last_seen_and_raw_events_restore(hass) -> None:
    capture = _capture(hass)
    await capture.async_load()
    _observe(capture, b'{"type":147,"body":{"new":1}}', message_type=147, body={"new": 1}, now=100)
    _observe(capture, b'{"type":147,"body":{"new":2}}', message_type=147, body={"new": 2}, now=200)
    await capture.async_flush()

    restored = _capture(hass)
    await restored.async_load()
    type_bucket = restored.snapshot().unknown_message_types[0].observation
    assert (type_bucket.count, type_bucket.first_seen_at, type_bucket.last_seen_at) == (2, 100, 200)
    assert restored.raw_snapshot()["stored_count"] == 2
    assert base64.b64decode(restored.raw_snapshot()["events"][0]["payload_base64"]) == (
        b'{"type":147,"body":{"new":1}}'
    )
    assert compact_size(restored._serialize()["discovery_state"]) <= MAX_PROTOCOL_STRUCTURE_STORAGE_BYTES
    assert not _observe(
        restored,
        b'{"type":147,"body":{"new":1}}',
        message_type=147,
        body={"new": 1},
        now=300,
    )
    assert restored.raw_snapshot()["sampled_out_count"] == 1
    await restored.async_clear()


async def test_overflow_and_traversal_counts_survive_restore(hass) -> None:
    capture = _capture(hass, entry_id="overflow-entry")
    await capture.async_load()
    for message_type in range(2_000, 2_000 + 34):
        body = {"batSoc": 50}
        raw = json.dumps({"type": message_type, "body": body}).encode()
        _observe(
            capture,
            raw,
            message_type=message_type,
            body=body,
            now=10_000 + message_type,
        )
    large_body = {f"field-{index}": index for index in range(70)}
    _observe(
        capture,
        json.dumps({"type": 2, "body": large_body}).encode(),
        message_type=2,
        body=large_body,
        now=20_000,
    )
    before = capture.snapshot()
    assert before.message_type_overflow == 2
    assert before.traversal_dropped == 6
    await capture.async_flush()

    restored = _capture(hass, entry_id="overflow-entry")
    await restored.async_load()
    after = restored.snapshot()
    assert after.message_type_overflow == before.message_type_overflow
    assert after.traversal_dropped == before.traversal_dropped
    assert after.unknown_message_types == before.unknown_message_types
    await restored.async_clear()


async def test_host_binding_prefix_change_entry_isolation_and_host_change(hass) -> None:
    original = _capture(hass)
    await original.async_load()
    _observe(original, b'{"type":147,"body":{"x":1}}', message_type=147, body={"x": 1})
    await original.async_flush()

    isolated = _capture(hass, entry_id="another-entry")
    await isolated.async_load()
    assert isolated.raw_snapshot()["stored_count"] == 0

    prefix_changed = _capture(hass, prefix="newroot")
    await prefix_changed.async_load()
    assert prefix_changed.raw_snapshot()["stored_count"] == 1
    assert prefix_changed.raw_snapshot()["events"][0]["topic"] == TOPIC

    changed_host = _capture(hass, host="HOST_B")
    await changed_host.async_load()
    assert changed_host.raw_snapshot()["stored_count"] == 0
    assert changed_host.snapshot().unknown_message_types == ()
    await async_delete_protocol_capture(hass, "another-entry")
    await async_delete_protocol_capture(hass, "protocol-entry")


async def test_corrupted_state_is_discarded_fail_closed(hass) -> None:
    capture = _capture(hass, entry_id="corrupt-entry")
    await capture.async_load()
    _observe(capture, b'{"type":147,"body":{"x":1}}', message_type=147, body={"x": 1})
    await capture.async_flush()

    stored = await capture._store.async_load()
    assert stored is not None
    corrupted = deepcopy(stored)
    corrupted["discovery_state"]["unknown_message_types"][0]["kind"] = {"bad": "shape"}
    await capture._store.async_save(corrupted)

    restored = _capture(hass, entry_id="corrupt-entry")
    await restored.async_load()
    assert restored.snapshot().unknown_message_types == ()
    assert restored.raw_snapshot()["stored_count"] == 0
    assert await restored._store.async_load() is None


async def test_deactivation_clear_cancels_delayed_saves(hass) -> None:
    capture = _capture(hass, entry_id="clear-entry")
    await capture.async_load()
    assert _observe(capture, b'{"type":147,"body":{"x":1}}', message_type=147, body={"x": 1})
    await capture.async_clear()
    assert await capture._store.async_load() is None
    assert not capture.observe_invalid(topic=TOPIC, payload=b"late", now=20_000)
    assert await capture._store.async_load() is None


async def test_both_capture_extensions_respect_independent_24k_and_112k_budgets(hass) -> None:
    capture = _capture(hass, entry_id="export-entry")
    await capture.async_load()
    for index in range(20):
        _observe(
            capture,
            json.dumps({"type": 147, "body": {"new": index}}).encode(),
            message_type=147,
            body={"new": index},
            now=10_000 + index,
        )
    raw = capture.raw_snapshot()
    base = {
        "normal": "x" * 63_000,
        "experimental_alert_capture": {"events": [{"payload_base64": "a" * 20_000}]},
    }
    exported = build_protocol_capture_export(raw, base)
    complete = {**base, "experimental_protocol_capture": exported}
    assert compact_size(exported) <= MAX_PROTOCOL_EXPORT_BYTES
    assert compact_size(complete) <= 64 * 1024 + 24 * 1024 + MAX_PROTOCOL_EXPORT_BYTES
    assert exported["privacy_warning"]
    assert exported["events"]
    assert all(item["topic"] == "{prefix}/device/{host}/status" for item in exported["events"])
    assert exported["export_omitted_count"] == raw["stored_count"] - len(exported["events"])
    await capture.async_clear()


async def test_protocol_store_is_private_versioned_and_entry_scoped(hass, monkeypatch) -> None:
    real_store = capture_storage_module.Store
    created: list[tuple[int, str, bool]] = []

    def recording_store(hass, version: int, key: str, *args, **kwargs):
        created.append((version, key, kwargs.get("private", False)))
        return real_store(hass, version, key, *args, **kwargs)

    monkeypatch.setattr(capture_storage_module, "Store", recording_store)
    capture = _capture(hass, entry_id="private-entry")
    await capture.async_load()
    await capture.async_clear()
    assert created == [
        (
            PROTOCOL_CAPTURE_VERSION,
            f"{DOMAIN}.private-entry.experimental_protocol_discovery",
            True,
        ),
    ]
