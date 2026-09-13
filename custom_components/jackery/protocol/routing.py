"""Pure structural routing for established Jackery MQTT messages.

This module parses topics and envelopes and classifies message routes. Runtime
state, cache mutation, freshness, reauthentication, discovery and entity fan-out
remain coordinator responsibilities.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .normalization import extract_flat_body

_CHILD_ARRAY_KEYS: tuple[str, ...] = (
    "plugs",
    "plug",
    "socket",
    "sockets",
    "cts",
    "ct",
    "collectors",
)


class MessageRoute(StrEnum):
    """Coordinator mutation branch selected for a parsed message."""

    TYPE_23 = "type_23"
    TYPE_101 = "type_101"
    TYPE_102 = "type_102"
    TYPE_106 = "type_106"
    TYPE_107 = "type_107"
    TYPE_123 = "type_123"
    GENERIC = "generic"


@dataclass(frozen=True, slots=True)
class TopicInfo:
    """A structurally valid Jackery status or event topic."""

    device_sn: str
    channel: str


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    """Pure message-type decisions consumed by the coordinator."""

    message_type: Any
    route: MessageRoute
    captures_host_metadata: bool
    refreshes_generic_children: bool


@dataclass(frozen=True, slots=True)
class ParsedEnvelope:
    """Validated envelope and sanitized body ready for coordinator handling."""

    raw_data: dict[str, Any]
    body: dict[str, Any]
    decision: RoutingDecision


def parse_topic(topic_root: str, topic: str) -> TopicInfo | None:
    """Parse an exact ``{root}/device/{sn}/status|event`` topic."""
    match = re.fullmatch(
        rf"{re.escape(topic_root)}/device/([^/]+)/(status|event)",
        topic,
    )
    if match is None:
        return None
    return TopicInfo(device_sn=match.group(1), channel=match.group(2))


def subdevice_serial(payload: Mapping[str, Any]) -> str | None:
    """Return the established non-empty string child serial, without coercion."""
    serial = payload.get("deviceSn") or payload.get("sn")
    return serial if isinstance(serial, str) and serial else None


def route_message_type(message_type: Any) -> RoutingDecision:
    """Classify a message type without hashing or coercing wire metadata."""
    if message_type == 23:
        route = MessageRoute.TYPE_23
    elif message_type == 101:
        route = MessageRoute.TYPE_101
    elif message_type == 102:
        route = MessageRoute.TYPE_102
    elif message_type == 106:
        route = MessageRoute.TYPE_106
    elif message_type == 107:
        route = MessageRoute.TYPE_107
    elif message_type == 123:
        route = MessageRoute.TYPE_123
    else:
        route = MessageRoute.GENERIC

    return RoutingDecision(
        message_type=message_type,
        route=route,
        captures_host_metadata=message_type in (2, 23, 25, 106, 107),
        refreshes_generic_children=message_type not in (23, 101, 102, 123),
    )


def is_host_message_body(body: Mapping[str, Any], host_serial: str) -> bool:
    """Return whether body metadata identifies the host rather than a child."""
    return body.get("deviceSn") in (None, "system", host_serial)


def _sanitize_child_arrays(body: dict[str, Any]) -> dict[str, Any]:
    """Copy and sanitize known child-array containers and members."""
    result = dict(body)
    for key in _CHILD_ARRAY_KEYS:
        value = result.get(key)
        if isinstance(value, list):
            result[key] = [
                item
                for item in value
                if isinstance(item, dict)
                and (
                    not (item.get("deviceSn") or item.get("sn"))
                    or subdevice_serial(item)
                )
            ]
        elif value is not None:
            del result[key]
    return result


def parse_envelope(payload: str | bytes) -> ParsedEnvelope | None:
    """Decode and structurally validate an MQTT envelope.

    JSON decoding errors intentionally propagate so the coordinator can retain
    its topic-aware warning. Other unsupported shapes return ``None``.
    """
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")
    raw_data = json.loads(payload)
    if not isinstance(raw_data, dict):
        return None

    message_type = raw_data.get("type")
    body = raw_data.get("body")
    if body is None:
        if message_type == 101:
            return None
        flat_body = extract_flat_body(raw_data)
        body = flat_body if flat_body else {}
    if not isinstance(body, dict):
        return None

    return ParsedEnvelope(
        raw_data=raw_data,
        body=_sanitize_child_arrays(body),
        decision=route_message_type(message_type),
    )
