"""Interpret explicit Jackery interface state without conflating missing fields."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any


def _signal_is_zero(value: Any) -> bool:
    """Jackery reports zero as its no-Wi-Fi-signal sentinel, not a dBm value."""
    if isinstance(value, bool):
        return False
    try:
        signal = float(value)
    except (TypeError, ValueError, OverflowError):
        return False
    return math.isfinite(signal) and signal == 0


def _signal_is_measured(value: Any) -> bool:
    """Return whether a valid negative RSSI measurement is present."""
    if isinstance(value, bool):
        return False
    try:
        signal = float(value)
    except (TypeError, ValueError, OverflowError):
        return False
    return math.isfinite(signal) and signal < 0


def ip_address_is_missing(value: Any) -> bool:
    """Return whether an explicitly reported IP value has no assigned address."""
    return value is None or (
        isinstance(value, str) and value.strip() in {"", "0.0.0.0"}
    )


def _has_ip(value: Any) -> bool:
    return isinstance(value, str) and value.strip() not in {"", "0.0.0.0"}


def wifi_is_disconnected(data: Mapping[str, Any]) -> bool:
    """Require blank SSID plus explicit no-signal/no-IP evidence.

    Ethernet state is deliberately ignored: both interfaces can be active at
    once. A valid Wi-Fi IP or negative RSSI contradicts the disconnected state.
    """
    ssid = data.get("wname")
    if "wname" not in data or not isinstance(ssid, str) or ssid.strip():
        return False
    if _has_ip(data.get("wip")) or _signal_is_measured(data.get("wsig")):
        return False
    return (
        ("wip" in data and ip_address_is_missing(data["wip"]))
        or ("wsig" in data and _signal_is_zero(data["wsig"]))
    )


def wifi_connection_state(data: Mapping[str, Any]) -> bool | None:
    """Return an interface state only where the payload provides clear evidence."""
    if wifi_is_disconnected(data):
        return False
    if _has_ip(data.get("wip")):
        return True
    ssid = data.get("wname")
    if isinstance(ssid, str) and ssid.strip():
        return True
    if _signal_is_measured(data.get("wsig")):
        return True
    return None


def ethernet_port_state(value: Any) -> bool | None:
    """Parse ethPort only when it explicitly reports 0 (down) or 1 (up)."""
    if isinstance(value, bool):
        return value
    try:
        port_state = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if port_state == 0:
        return False
    if port_state == 1:
        return True
    return None


def merge_network_fields(
    current: Mapping[str, Any], incoming: Mapping[str, Any]
) -> dict[str, Any]:
    """Return only incoming network fields plus invalidations proven by a link change.

    The caller merges the returned payload fields into its regular cache. This
    keeps unrelated protocol fields untouched and prevents a prior interface IP from surviving
    a proven disconnect/reconnect transition.
    """
    update = dict(incoming)
    old_ethernet = ethernet_port_state(current.get("ethPort"))
    new_ethernet = (
        ethernet_port_state(incoming["ethPort"])
        if "ethPort" in incoming
        else None
    )
    if new_ethernet is False:
        update["eip"] = None
    elif old_ethernet is False and new_ethernet is True and "eip" not in incoming:
        update["eip"] = None

    combined = dict(current)
    combined.update(incoming)
    # A cached IP from an earlier connection must not veto a disconnect proven
    # by the latest SSID/signal fields. A same-payload valid IP remains contrary
    # evidence and is left for the caller to treat as unknown/connected.
    wifi_candidate = dict(combined)
    if "wip" not in incoming and "wip" in current:
        wifi_candidate["wip"] = None
    if (
        wifi_is_disconnected(wifi_candidate)
        and not _has_ip(incoming.get("wip"))
    ):
        update["wip"] = None
    elif (
        wifi_is_disconnected(current)
        and wifi_connection_state(combined) is True
        and "wip" not in incoming
    ):
        update["wip"] = None

    return update


__all__ = [
    "ethernet_port_state",
    "ip_address_is_missing",
    "merge_network_fields",
    "wifi_connection_state",
    "wifi_is_disconnected",
]
