"""Synthetic wire scenarios; assertions describe source behavior, not hardware captures."""

import json
import logging
from copy import deepcopy
from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.jackery import sensor as sensor_module
from custom_components.jackery.sensor import JackeryDataCoordinator
from custom_components.jackery.transport import mqtt as mqtt_transport_module

from .conftest import FakeMqttMsg


def receive(c, msg_type=2, body=None, **envelope):
    c._handle_message(FakeMqttMsg(f"{c._topic_root}/device/{c._device_sn}/status",
                                 json.dumps({"type": msg_type, "body": body, **envelope})))


@pytest.fixture
def protocol(hass, monkeypatch):
    c = JackeryDataCoordinator(hass, "lab.+/hb", "synthetic-token", "localhost", "HOST_A")
    c.config_entry_id = "entry-a"
    c.add_entities_callback = Mock()
    c.add_switch_entities_callback = Mock()
    monkeypatch.setattr(c, "_update_device_registry", AsyncMock())
    return c


@pytest.mark.parametrize("suffix,accepted", [
    ("HOST_A/status", True), ("HOST_A/event", True), ("HOST_B/status", False),
    ("HOST_A/action", False), ("HOST_A/status/extra", False), ("/status", False),
    ("HOST_A", False),
])
def test_topic_routes_and_freshness(protocol, suffix, accepted):
    protocol._runtime_state.last_update_time = 1
    protocol._handle_message(FakeMqttMsg(f"lab.+/hb/device/{suffix}", '{"type":2,"body":{"batSoc":0}}'))
    assert (protocol._data_cache.get("batSoc") == 0) == accepted
    assert protocol._ever_received == accepted
    assert (protocol._last_update_time > 1) == accepted


@pytest.mark.parametrize("prefix", ["other", "labZZ/hb", "extra/lab.+/hb"])
def test_prefix_is_literal_and_anchored(protocol, prefix):
    protocol._handle_message(FakeMqttMsg(f"{prefix}/device/HOST_A/status", '{"body":{"batSoc":7}}'))
    assert protocol._data_cache == {}


def test_empty_host_discovers_only_first_valid_host(protocol):
    protocol._device_sn = ""
    for host, payload in [("BAD", "{"), ("HOST_A", '{"body":{"batSoc":7}}'),
                          ("HOST_B", '{"body":{"batSoc":99}}')]:
        protocol._handle_message(FakeMqttMsg(f"{protocol._topic_root}/device/{host}/event", payload))
    assert protocol._device_sn == "HOST_A"
    assert protocol._data_cache["batSoc"] == 7


@pytest.mark.parametrize("payload,expected,accepted", [
    ({"type": 2, "body": {"batSoc": 0, "future": {"x": 1}}}, {"batSoc": 0, "future": {"x": 1}}, True),
    ({"type": 25, "batSoc": 0, "token": "synthetic"}, {"batSoc": 0}, True),
    ({"type": 2}, {}, True), ({"type": 2, "body": {}}, {}, True),
    ({"type": 2, "body": None, "batSoc": 4}, {"batSoc": 4}, True),
    ({"type": 2, "body": [], "batSoc": 4}, {}, False),
    ({"type": 2, "body": "bad"}, {}, False),
    ({"type": 101, "batSoc": 4}, {}, False),
    ({"type": 2, "workModel": 4}, {}, True),
    ({"type": 2, "body": {"batSoc": None}}, {"batSoc": None}, True),
    ([], {}, False), (None, {}, False), (7, {}, False),
])
def test_payload_shape_contract(protocol, payload, expected, accepted):
    protocol._handle_message(FakeMqttMsg(f"{protocol._topic_root}/device/HOST_A/status", json.dumps(payload)))
    assert protocol._ever_received == accepted
    for key, value in expected.items():
        assert protocol._data_cache[key] == value
    if not expected:
        assert "batSoc" not in protocol._data_cache
    assert "token" not in protocol._data_cache


@pytest.mark.parametrize("kind", [2, 25, 103, 105, 100, 1, 999, None, "107"])
def test_generic_types_merge_without_ack_correlation(protocol, kind):
    receive(protocol, kind, {"batSoc": 12, "futureFlag": 8}, messageId=1000, ts=900)
    receive(protocol, kind, {"batSoc": 0}, messageId=1000, ts=1)
    assert protocol._data_cache["batSoc"] == 0
    assert protocol._data_cache["futureFlag"] == 8
    protocol.add_entities_callback.assert_not_called()


@pytest.mark.parametrize("alias,canonical", [("gridBuyPw", "gridInPw"), ("gridSellPw", "gridOutPw"),
                                            ("workModel", "workMode")])
@pytest.mark.parametrize("explicit,expected", [(None, 7), (0, 0), (4, 4)])
def test_aliases_preserve_explicit_zero_and_raw_field(protocol, alias, canonical, explicit, expected):
    receive(protocol, 107, {alias: 7, canonical: explicit})
    assert protocol._data_cache[alias] == 7
    assert protocol._data_cache[canonical] == expected


def test_107_full_incremental_null_and_repeat(protocol):
    receive(protocol, 2, {"batSoc": 80, "soc": 70, "workModel": 2, "maxOutPw": 600})
    for _ in range(2):
        receive(protocol, 107, {"soc": 0, "workModel": 4})
        assert {k: protocol._data_cache[k] for k in ("batSoc", "soc", "workMode", "maxOutPw")} == {
            "batSoc": 80, "soc": 0, "workMode": 4, "maxOutPw": 600}
    receive(protocol, 107, {"soc": None})
    assert protocol._data_cache["soc"] is None
    assert protocol._data_cache["workMode"] == 4


PROTECTED = ["batInPw", "batOutPw", "pvPw", "pv1", "pv2", "pv3", "pv4",
             "swEpsInPw", "swEpsOutPw", "stackInPw", "stackOutPw"]


@pytest.mark.parametrize("field", PROTECTED)
@pytest.mark.parametrize("first,new", [(12, 90), (0, 90), (None, 90), (12, 0), (12, None)])
def test_106_repeated_field_contract(protocol, field, first, new):
    """A snapshot cannot establish a permanent lock, including zero/null seeds."""
    receive(protocol, 106, {field: first, "maxOutPw": 600, "future": "retained"})
    receive(protocol, 106, {field: new, "maxOutPw": 700})
    assert protocol._data_cache[field] == new
    assert protocol._data_cache["maxOutPw"] == 700
    assert protocol._data_cache["future"] == "retained"


@pytest.mark.parametrize("live_type", [2, 107])
@pytest.mark.parametrize("sequence", [(106, "live", 106), ("live", 106)])
def test_106_ordering_and_unprotected_overwrite(protocol, live_type, sequence):
    for kind in sequence:
        is_live = kind == "live"
        receive(protocol, live_type if is_live else kind,
                {"pvPw": 44 if is_live else 99, "soc": 4 if is_live else 8, "gridInPw": 0})
    assert protocol._data_cache["pvPw"] == 44
    assert protocol._data_cache["soc"] == 8
    assert protocol._data_cache["gridInPw"] == 0


@pytest.mark.parametrize("array", ["plug", "plugs", "socket", "sockets", "ct", "cts", "collectors"])
def test_101_alias_merge_duplicates_and_omissions(protocol, array):
    dtype = 4 if array == "collectors" else 2 if array in ("ct", "cts") else 6
    item = {"deviceSn": "CHILD", "devType": dtype, "subType": 7, "commMode": 1, "outPw": 12}
    receive(protocol, 101, {array: [item, {**item, "outPw": 0}]})
    key = "cts" if array in ("ct", "cts") else "collectors" if array == "collectors" else "plugs"
    assert protocol._data_cache[key] == [{**item, "outPw": 0}]
    count = protocol.add_entities_callback.call_count
    for body in [{array: []}, {}, {array: [{"deviceSn": "CHILD", "devType": dtype, "extra": 9}]}]:
        receive(protocol, 101, body)
    cached = protocol._data_cache[key][0]
    assert cached["commMode"] == 1 and cached["outPw"] == 0 and cached["extra"] == 9
    assert protocol.add_entities_callback.call_count == count
    if key == "plugs":
        assert protocol._data_cache["plug"] is protocol._data_cache["plugs"]


def test_101_child_array_rejects_configured_host_identity(protocol):
    """The configured host must never enter child-owned runtime state."""
    receive(
        protocol,
        101,
        {
            "plugs": [
                {"deviceSn": "CHILD_A", "devType": 6, "outPw": 10},
                {"deviceSn": "HOST_A", "devType": 6, "outPw": 20},
                {"deviceSn": "CHILD_B", "devType": 6, "outPw": 30},
            ]
        },
    )

    assert [item["deviceSn"] for item in protocol._data_cache["plugs"]] == [
        "CHILD_A",
        "CHILD_B",
    ]
    assert set(protocol._subdevice_last_seen) == {"CHILD_A", "CHILD_B"}
    assert protocol._known_plugs == {"CHILD_A", "CHILD_B"}


@pytest.mark.parametrize(
    ("array", "serial_key"),
    [
        ("plug", "deviceSn"),
        ("plugs", "sn"),
        ("socket", "deviceSn"),
        ("sockets", "sn"),
        ("ct", "deviceSn"),
        ("cts", "sn"),
        ("collectors", "deviceSn"),
    ],
)
def test_101_child_array_aliases_reject_host_only(protocol, array, serial_key):
    dtype = 4 if array == "collectors" else 2 if array in ("ct", "cts") else 6
    receive(protocol, 101, {array: [{serial_key: "HOST_A", "devType": dtype}]})

    assert not any(
        key in protocol._data_cache
        for key in ("plug", "plugs", "socket", "sockets", "ct", "cts", "collectors")
    )
    assert not protocol._subdevice_last_seen
    assert not protocol._known_plugs
    protocol.add_entities_callback.assert_not_called()
    protocol.add_switch_entities_callback.assert_not_called()


@pytest.mark.parametrize(
    ("array", "position"),
    [
        ("plug", 0),
        ("plugs", 1),
        ("socket", 2),
        ("sockets", 0),
        ("ct", 1),
        ("cts", 2),
        ("collectors", 1),
    ],
)
def test_101_child_array_aliases_keep_real_children(protocol, array, position):
    dtype = 4 if array == "collectors" else 2 if array in ("ct", "cts") else 6
    items = [
        {"deviceSn": "CHILD_A", "devType": dtype, "outPw": 10},
        {"sn": "CHILD_B", "devType": dtype, "outPw": 30},
    ]
    items.insert(position, {"sn": "HOST_A", "devType": dtype, "outPw": 20})
    receive(protocol, 101, {array: items})

    cache_key = (
        "cts"
        if array in ("ct", "cts")
        else "collectors"
        if array == "collectors"
        else "plugs"
    )
    assert {
        item.get("deviceSn") or item.get("sn")
        for item in protocol._data_cache[cache_key]
    } == {"CHILD_A", "CHILD_B"}
    assert set(protocol._subdevice_last_seen) == {"CHILD_A", "CHILD_B"}
    assert protocol._known_plugs == {"CHILD_A", "CHILD_B"}
    created = [
        entity
        for call in protocol.add_entities_callback.call_args_list
        for entity in call.args[0]
    ]
    assert created
    assert all(entity._plug_sn != "HOST_A" for entity in created)


@pytest.mark.parametrize("message_type", [2, 107, 999])
def test_generic_child_array_rejects_host_before_cache_freshness_and_discovery(
    protocol,
    message_type,
):
    receive(
        protocol,
        message_type,
        {
            "plugs": [
                {"deviceSn": "HOST_A", "devType": 6, "outPw": 20},
                {"deviceSn": "CHILD", "devType": 6, "outPw": 30},
            ]
        },
    )

    assert [item["deviceSn"] for item in protocol._data_cache["plugs"]] == [
        "CHILD"
    ]
    assert set(protocol._subdevice_last_seen) == {"CHILD"}
    assert protocol._known_plugs == {"CHILD"}


def test_101_mixed_arrays_do_not_discover_battery_until_23(protocol):
    receive(protocol, 101, {"devType": 2, "plugs": [{"sn": "P", "commMode": 1}],
                            "cts": [{"sn": "CT"}, {"sn": "SM", "devType": 3, "subType": 5}],
                            "collectors": [{"sn": "COL", "devType": 4, "subType": 7}],
                            "batteries": [{"sn": "BAT", "devType": 1}]})
    assert protocol._known_plugs == {"P", "CT", "SM", "COL"}
    receive(protocol, 23, {"deviceSn": "BAT", "devType": 1, "inEgy": 123, "outEgy": 0})
    assert protocol._expansion_battery_sns == {"BAT"}
    receive(protocol, 23, {"deviceSn": "BAT", "devType": 1, "inEgy": None})
    assert protocol._data_cache["expansion_batteries"]["BAT"]["inEgy"] == 123


@pytest.mark.parametrize("item,key", [
    ({"devType": 2}, "cts"), ({"devType": 3, "subType": 5}, "cts"),
    ({"devType": 6}, "plugs"), ({"devType": 4, "subType": 7}, "collectors"),
    ({"sysSwitch": 0}, "plugs"), ({"totalEgy": 0}, "plugs"),
    ({"aPhasePw": 0}, "cts"), ({"AphasePw": 0}, "cts"),
    ({"phasePw": 0}, "cts"), ({"devType": 99}, None), ({"outPw": 9}, None),
    ({"devType": "3", "aPhasePw": 1}, None),
])
def test_102_inference_and_known_point_preservation(protocol, item, key, monkeypatch):
    with monkeypatch.context() as m:
        m.setattr(sensor_module.time, "time", lambda: 1000)
        receive(protocol, 102, {"sn": "CHILD", **item, "extra": 7})
    assert protocol._subdevice_last_seen["CHILD"] == 1000
    if key is None:
        assert "CHILD" not in protocol._known_plugs
        return
    with monkeypatch.context() as m:
        m.setattr(sensor_module.time, "time", lambda: 1001)
        receive(protocol, 102, {"deviceSn": "CHILD", "outPw": 0, "extra": None})
    cached = protocol._data_cache[key][0]
    assert cached["extra"] == 7 and cached["outPw"] == 0
    assert protocol._subdevice_last_seen["CHILD"] == 1001


@pytest.mark.parametrize("sn", ["HOST_A", "system", "", None])
def test_102_rejects_host_system_missing_serial(protocol, sn):
    receive(protocol, 102, {"deviceSn": sn, "devType": 6, "sysSwitch": 1})
    assert not protocol._known_plugs
    assert not protocol._subdevice_last_seen


def test_102_arrays_win_and_conflicts_do_not_reclassify_known_device(protocol):
    receive(protocol, 102, {"cts": [{"sn": "CHILD", "devType": 3, "subType": 5}],
                            "deviceSn": "POINT", "devType": 6})
    assert protocol._known_plugs == {"CHILD"}
    count = protocol.add_entities_callback.call_count
    receive(protocol, 102, {"deviceSn": "CHILD", "devType": 6, "sysSwitch": 1})
    assert protocol._data_cache["cts"][0]["devType"] == 6
    assert "plugs" not in protocol._data_cache
    assert protocol.add_entities_callback.call_count == count
    protocol.add_switch_entities_callback.assert_not_called()


@pytest.mark.parametrize("sn", [None, "system", "HOST_A"])
async def test_23_host_statistics_and_metadata(protocol, sn):
    receive(protocol, 23, {"deviceSn": sn, "inEgy": 42, "softver": "host-fw"}, deviceType=3)
    assert protocol._data_cache.get("inEgy") == 42
    assert protocol._soft_ver == "host-fw"
    assert protocol._device_type == 3


@pytest.mark.parametrize("kind", [23, 101, 102])
async def test_child_metadata_cannot_contaminate_host(protocol, kind):
    receive(protocol, kind, {"deviceSn": "CHILD", "devType": 6, "softver": "child-fw"}, deviceType=99)
    assert protocol._soft_ver is None
    assert protocol._device_type is None
    receive(protocol, 25, {"softver": "host-fw"}, deviceType=3)
    assert protocol._device_type == 3 and protocol._soft_ver == "host-fw"


@pytest.mark.parametrize("key,dtype,subtype,updated", [("plugs", 6, 0, True), ("cts", 3, 5, True),
                                                     ("collectors", 4, 7, False)])
def test_23_child_search_scope(protocol, key, dtype, subtype, updated):
    receive(protocol, 101, {key: [{"deviceSn": "CHILD", "devType": dtype, "subType": subtype, "inEgy": 4}]})
    receive(protocol, 23, {"deviceSn": "CHILD", "devType": dtype, "inEgy": 0})
    assert protocol._data_cache[key][0]["inEgy"] == (0 if updated else 4)
    assert "inEgy" not in protocol._data_cache


@pytest.mark.parametrize("code,called", [(401, True), (403, False), (None, False), ("401", False)])
def test_123_only_numeric_401_requests_reauth(protocol, code, called, monkeypatch):
    trigger = Mock()
    monkeypatch.setattr(protocol, "_trigger_reauth", trigger)
    receive(protocol, 123, {"errorCode": code, "batSoc": 99})
    assert trigger.called == called
    assert "batSoc" not in protocol._data_cache


@pytest.mark.parametrize("kind", [101, 102, 2, 107])
@pytest.mark.parametrize("bad", [5, ["bad"], {"deviceSn": ["bad"]}, {"deviceSn": 17}, {"sn": {"bad": 1}}])
def test_malformed_array_member_does_not_block_valid_listener(protocol, kind, bad, caplog):
    listener = Mock()
    protocol.register_sensor("sentinel", listener)
    receive(protocol, kind, {"plugs": [bad, {"sn": "GOOD", "devType": 6, "outPw": 0}]})
    assert "GOOD" in protocol._known_plugs
    listener._update_from_coordinator.assert_called_once()
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


@pytest.mark.parametrize("dtype", [99, "new", [3], {"type": 3}])
def test_unknown_device_type_does_not_invent_entities(protocol, dtype):
    receive(protocol, 101, {"plugs": [{"sn": "UNKNOWN", "devType": dtype, "future": 1}]})
    protocol.add_entities_callback.assert_not_called()
    protocol.add_switch_entities_callback.assert_not_called()
    assert "UNKNOWN" not in protocol._known_plugs


async def test_invalid_host_metadata_does_not_drop_other_fields(protocol, caplog):
    receive(protocol, 25, {"batSoc": 42}, deviceType="future-model")
    assert protocol._data_cache.get("batSoc") == 42
    assert protocol._device_type is None
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_unknown_keys_and_bad_numeric_power_preserve_other_data(protocol):
    receive(protocol, 25, {"pvPw": "not-numeric", "batSoc": 42, "future": [{"v": None}]})
    assert protocol._data_cache["batSoc"] == 42
    assert protocol._data_cache["pvPw"] == "not-numeric"
    assert protocol._data_cache["future"] == [{"v": None}]
    before = deepcopy(protocol._data_cache)
    protocol._handle_message(FakeMqttMsg(f"{protocol._topic_root}/device/HOST_A/status", "{"))
    assert protocol._data_cache == before


@pytest.mark.parametrize("kind", [2, 107, 106])
@pytest.mark.parametrize("key", ["plugs", "cts", "collectors"])
@pytest.mark.parametrize("bad", ["bad-array", {"wrong": "shape"}, 12])
def test_invalid_array_shape_cannot_poison_next_merge(protocol, kind, key, bad, caplog):
    receive(protocol, 101, {key: [{"sn": "KNOWN", "devType": 6 if key == "plugs" else 3}]})
    listener = Mock()
    protocol.register_sensor("later", listener)
    receive(protocol, kind, {key: bad, "soc": 1})
    receive(protocol, 101, {key: [{"sn": "NEW", "devType": 6 if key == "plugs" else 3}]})
    assert {item["sn"] for item in protocol._data_cache[key]} == {"KNOWN", "NEW"}
    assert listener._update_from_coordinator.call_count == 2
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


@pytest.mark.parametrize("kind", [23, 102])
@pytest.mark.parametrize("bad", [17, ["child"], {"child": 1}])
def test_non_string_point_serial_is_ignored_without_coercion(protocol, kind, bad, caplog):
    receive(protocol, kind, {"deviceSn": bad, "devType": 1 if kind == 23 else 6, "sysSwitch": 1})
    assert not protocol._known_plugs
    assert not protocol._subdevice_last_seen
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


@pytest.mark.parametrize("kind", [2, 23, 25, 106, 107])
async def test_only_host_body_metadata_updates_registry(protocol, kind):
    receive(protocol, kind, {"deviceSn": "CHILD", "softver": "child-fw"}, deviceType=99)
    assert protocol._soft_ver is None and protocol._device_type is None
    receive(protocol, kind, {"deviceSn": "HOST_A", "softver": "host-fw"}, deviceType=3)
    await protocol.hass.async_block_till_done()
    assert protocol._soft_ver == "host-fw" and protocol._device_type == 3
    protocol._update_device_registry.assert_awaited_once()


@pytest.mark.parametrize("channel", ["status", "event"])
@pytest.mark.parametrize("kind,body,key,value", [
    (2, {"soc": 1}, "soc", 1), (25, {"soc": 2}, "soc", 2),
    (23, {"deviceSn": "system", "inEgy": 3}, "inEgy", 3),
    (101, {"plugs": [{"sn": "P", "devType": 6}]}, "plugs", [{"sn": "P", "devType": 6}]),
    (102, {"sn": "P", "devType": 6}, "plugs", [{"sn": "P", "devType": 6}]),
    (106, {"soc": 4}, "soc", 4), (107, {"soc": 5}, "soc", 5),
    (123, {"errorCode": 403}, "errorCode", None),
])
def test_message_types_have_no_status_event_split(protocol, channel, kind, body, key, value):
    protocol._handle_message(FakeMqttMsg(f"{protocol._topic_root}/device/HOST_A/{channel}",
                                       json.dumps({"type": kind, "body": body})))
    assert protocol._data_cache.get(key) == value
    assert protocol._ever_received


async def test_empty_host_subscription_fallback_remains_owned(hass, monkeypatch):
    from .test_mqtt_lifecycle import Subscriptions

    broker = Subscriptions()
    monkeypatch.setattr(mqtt_transport_module.ha_mqtt, "async_subscribe", broker.subscribe)
    c = JackeryDataCoordinator(hass, "hb", "synthetic", "localhost", "")
    monkeypatch.setattr(c, "_periodic_data_request", AsyncMock())
    try:
        await c.async_start()
        assert [r.topic for r in broker.active] == ["hb/device/+/status", "hb/device/+/event"]
        assert broker.send("HOST_A", value=3) == 1
        assert c._device_sn == "HOST_A"
        assert broker.send("HOST_B", value=9) == 1  # delivered, but rejected by host filter
        assert c._data_cache["batSoc"] == 3
    finally:
        await c.async_stop()
    assert not broker.active


@pytest.mark.parametrize("kind", [2, 25, 106, 107])
def test_generic_meter_without_serial_remains_calculation_input(protocol, kind):
    """Generic routes historically calculate from meter dicts without discovery IDs."""
    meter = {"tPhasePw": 80, "tnPhasePw": 0}
    receive(protocol, kind, {"cts": [meter]})
    assert protocol._data_cache["cts"] == [meter]
    assert protocol._data_cache["calc_grid_net_power"] == 80
    assert not protocol._known_plugs
