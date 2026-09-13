"""Build established Jackery MQTT action topics and payloads.

The helpers are deterministic and transport-independent. Callers retain
timestamp/message-ID generation, JSON serialization, publication and effects.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def action_topic(topic_root: str, host_serial: str) -> str:
    """Build the established MQTT action topic for one host."""
    return f"{topic_root}/device/{host_serial}/action"


def _request(
    message_type: int,
    *,
    message_id: int,
    timestamp: int,
    token: str | None,
    body: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build a request envelope whose token is always present."""
    return {
        "type": message_type,
        "eventId": 0,
        "messageId": message_id,
        "ts": timestamp,
        "token": token,
        "body": body,
    }


def build_main_control(
    *,
    message_id: int,
    timestamp: int,
    token: str | None,
    params: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a type-1 main-device control with the existing cmd/rc merge."""
    body: dict[str, Any] = {"cmd": 5, "rc": 1}
    body.update(params)
    payload: dict[str, Any] = {
        "type": 1,
        "eventId": 3,
        "messageId": message_id,
        "ts": timestamp,
        "body": body,
    }
    if token:
        payload["token"] = token
    return payload


def build_subdevice_switch(
    *,
    message_id: int,
    timestamp: int,
    token: str | None,
    device_serial: str,
    device_type: int,
    is_on: bool,
) -> dict[str, Any]:
    """Build a type-103 sub-device switch control."""
    payload: dict[str, Any] = {
        "type": 103,
        "eventId": 0,
        "messageId": message_id,
        "ts": timestamp,
        "body": {
            "deviceSn": device_serial,
            "devType": device_type,
            "sysSwitch": 1 if is_on else 0,
        },
    }
    if token:
        payload["token"] = token
    return payload


def build_status_request(
    *, message_id: int, timestamp: int, token: str | None
) -> dict[str, Any]:
    """Build a type-25 status request."""
    return _request(25, message_id=message_id, timestamp=timestamp, token=token, body=None)


def build_settings_request(
    *, message_id: int, timestamp: int, token: str | None
) -> dict[str, Any]:
    """Build a type-2 settings request."""
    return _request(2, message_id=message_id, timestamp=timestamp, token=token, body=None)


def build_full_state_request(
    *, message_id: int, timestamp: int, token: str | None
) -> dict[str, Any]:
    """Build a type-105 full-state request."""
    return _request(105, message_id=message_id, timestamp=timestamp, token=token, body=None)


def build_subdevice_request(
    *, message_id: int, timestamp: int, token: str | None, device_type: int
) -> dict[str, Any]:
    """Build a type-100 child-category request."""
    return _request(
        100,
        message_id=message_id,
        timestamp=timestamp,
        token=token,
        body={"devType": device_type},
    )
