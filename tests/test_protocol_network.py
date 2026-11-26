"""Regression coverage for independent Jackery interface state and cache changes."""

from custom_components.jackery.protocol.network import (
    ethernet_port_state,
    merge_network_fields,
    wifi_connection_state,
    wifi_is_disconnected,
)


def _merge(cache: dict, incoming: dict) -> dict:
    cache.update(merge_network_fields(cache, incoming))
    return cache


def test_ethernet_only_payload_proves_wifi_disconnected_without_wip() -> None:
    payload = {"ethPort": 1, "wname": "     ", "wsig": 0}

    assert ethernet_port_state(payload["ethPort"]) is True
    assert wifi_is_disconnected(payload)
    assert wifi_connection_state(payload) is False


def test_missing_wifi_fields_and_ethernet_alone_do_not_invent_a_link_state() -> None:
    assert wifi_connection_state({"ethPort": 1}) is None
    assert wifi_connection_state({"wname": " "}) is None
    assert not wifi_is_disconnected({"wname": " ", "ethPort": 1})
    assert not wifi_is_disconnected({"wname": " ", "wip": None, "wsig": -54})


def test_both_interfaces_can_be_active_at_the_same_time() -> None:
    payload = {
        "ethPort": 1,
        "eip": "192.0.2.10",
        "wname": "Home",
        "wip": "192.0.2.11",
        "wsig": -52,
    }

    assert ethernet_port_state(payload["ethPort"]) is True
    assert wifi_connection_state(payload) is True
    assert not wifi_is_disconnected(payload)


def test_wlan_only_is_independent_from_explicit_ethernet_down() -> None:
    payload = {"ethPort": 0, "wname": "Home", "wip": "192.0.2.11", "wsig": -61}

    assert ethernet_port_state(payload["ethPort"]) is False
    assert wifi_connection_state(payload) is True


def test_wifi_disconnect_clears_old_ip_and_reconnect_does_not_reuse_it() -> None:
    cache = {
        "wname": "Home",
        "wip": "192.0.2.10",
        "wsig": -48,
        "ethPort": 1,
    }

    _merge(cache, {"wname": "   ", "wsig": 0})
    assert cache["wip"] is None
    assert wifi_is_disconnected(cache)

    _merge(cache, {"wname": "Guest", "wsig": -67})
    assert cache["wip"] is None
    assert wifi_connection_state(cache) is True


def test_incremental_wifi_markers_can_prove_disconnect_without_ip_field() -> None:
    cache = {"wname": "Home", "wsig": -54, "wip": "192.0.2.10"}
    _merge(cache, {"wname": "   "})
    assert not wifi_is_disconnected(cache)

    _merge(cache, {"wsig": 0})
    assert cache["wip"] is None
    assert wifi_is_disconnected(cache)


def test_ethernet_disconnect_and_reconnect_clear_stale_ip_until_new_value() -> None:
    cache = {"ethPort": 1, "eip": "192.0.2.20"}

    _merge(cache, {"ethPort": 0})
    assert cache["eip"] is None
    _merge(cache, {"ethPort": 1})
    assert cache["eip"] is None
    _merge(cache, {"eip": "192.0.2.21"})
    assert cache["eip"] == "192.0.2.21"


def test_partial_updates_do_not_clear_fields_without_link_transition() -> None:
    cache = {"ethPort": 1, "eip": "192.0.2.20", "wname": "Home", "wip": "192.0.2.10", "wsig": -57}

    _merge(cache, {"pvPw": 500})

    assert cache["eip"] == "192.0.2.20"
    assert cache["wip"] == "192.0.2.10"
    assert cache["pvPw"] == 500
