"""The existing scattered classifiers exercised through MQTT and real entities."""

from unittest.mock import Mock

import pytest

from custom_components.jackery.identity import child_device_identifier
from custom_components.jackery.sensor import JackeryDataCoordinator

from .test_protocol_contract import protocol as protocol
from .test_protocol_contract import receive

# Query array and item type are intentionally separate: no model-name inference.
CASES = [
    ("battery", 23, None, 1, 0, "battery", 2, False, "inEgy", 100, "charge_energy", 1.0),
    ("ct", 101, "cts", 2, 1, "ct", 2, False, "aPhasePw", 50, "power", 50),
    ("legacy-ct", 101, "cts", 4, 2, "ct", 2, False, "bPhasePw", 60, "power", 60),
    ("hto907a", 101, "cts", 3, 5, "smartmeter", 19, False, "tPhasePw", 70, "import_total", 70),
    ("shelly-pro-3em", 101, "cts", 3, 2, "smartmeter", 19, False, "tPhasePw", 80, "import_total", 80),
    ("hto910a", 101, "collectors", 4, 7, "collector", 5, False, "inPw", 90, "import_power", 90),
    ("plug", 101, "plugs", 6, 0, "plug", 2, True, "outPw", 100, "power", 100),
    ("unknown-subtype", 101, "cts", 3, 999, "smartmeter", 19, False, "tPhasePw", 70, "import_total", 70),
    ("unknown-type", 101, "cts", 999, 5, None, 0, False, "tPhasePw", 70, None, None),
    ("ct-array-default", 101, "cts", None, 1, "ct", 2, False, "aPhasePw", 50, "power", 50),
    ("plug-array-default", 101, "plugs", None, 0, "plug", 2, True, "outPw", 50, "power", 50),
]


@pytest.mark.parametrize("name,kind,array,dtype,subtype,family,count,has_switch,field,value,key,expected", CASES,
                         ids=[case[0] for case in CASES])
def test_classification_entity_family_and_measurement(protocol, monkeypatch, name, kind, array, dtype,
                                                       subtype, family, count, has_switch, field, value, key, expected):
    item = {"deviceSn": "CHILD", "devType": dtype, "subType": subtype, field: value,
            "commMode": 1, "futureCapability": "not-an-entity"}
    body = {array: [item]} if array else item
    receive(protocol, kind, body)
    entities = [e for call in protocol.add_entities_callback.call_args_list for e in call.args[0]]
    switches = [e for call in protocol.add_switch_entities_callback.call_args_list for e in call.args[0]]
    assert len(entities) == count
    assert len(switches) == int(has_switch)
    if family is None:
        assert "CHILD" not in protocol._known_plugs
        return
    for e in entities + switches:
        assert f":{family}:" in e.unique_id
        assert e.device_info["identifiers"] == {("jackery", child_device_identifier("HOST_A", "CHILD"))}
        monkeypatch.setattr(e, "async_write_ha_state", Mock())
        protocol.register_sensor(e.unique_id, e)
    protocol._distribute_data(protocol._data_cache)
    measured = next(e for e in entities if e._sensor_key == key)
    assert measured.native_value == expected
    receive(protocol, kind, body)
    assert sum(len(call.args[0]) for call in protocol.add_entities_callback.call_args_list) == count


@pytest.mark.parametrize("array,dtype,subtype,source,family", [
    ("plugs", 3, 5, "cts", "smartmeter"),
    ("cts", 6, 0, "plugs", "plug"),
    ("cts", 4, 7, "collectors", "collector"),
    ("collectors", 4, 2, "cts", "ct"),
])
def test_conflicting_array_and_classification_is_characterized(protocol, array, dtype, subtype, source, family):
    receive(protocol, 101, {array: [{"sn": "CHILD", "devType": dtype, "subType": subtype, "outPw": 1}]})
    entities = protocol.add_entities_callback.call_args.args[0]
    assert all(e._data_key == source and f":{family}:" in e.unique_id for e in entities)
    # Existing classifier chooses item metadata but cache storage follows the array.
    # This can leave entities without a matching source; do not guess a repair.
    assert source not in protocol._data_cache


def test_legacy_subtype_only_generic_route(protocol):
    receive(protocol, 25, {"cts": [{"sn": "CHILD", "subType": 2, "bPhasePw": 3}]})
    entities = protocol.add_entities_callback.call_args.args[0]
    assert len(entities) == 2 and all(":ct:" in e.unique_id for e in entities)


@pytest.mark.parametrize("order", [("HOST_A", "HOST_B"), ("HOST_B", "HOST_A")])
def test_different_classifications_same_child_stay_host_scoped(hass, order):
    coords = {}
    for host in order:
        c = JackeryDataCoordinator(hass, "hb", "synthetic", "localhost", host)
        c.add_entities_callback = Mock()
        c.add_switch_entities_callback = Mock()
        coords[host] = c
        dtype = 3 if host == "HOST_A" else 6
        receive(c, 101, {"cts" if dtype == 3 else "plugs": [{"sn": "SAME", "devType": dtype, "subType": 5}]})
    first = coords["HOST_A"].add_entities_callback.call_args.args[0]
    second = coords["HOST_B"].add_entities_callback.call_args.args[0]
    assert {e.unique_id for e in first}.isdisjoint(e.unique_id for e in second)
    assert first[0].device_info["identifiers"].isdisjoint(second[0].device_info["identifiers"])
    original_ids = [e.unique_id for e in first]
    receive(coords["HOST_A"], 102, {"sn": "SAME", "devType": 3, "subType": 2})
    assert coords["HOST_A"].add_entities_callback.call_count == 1
    assert [e.unique_id for e in first] == original_ids
    assert coords["HOST_B"]._data_cache["plugs"][0]["subType"] == 5


@pytest.mark.parametrize("subtype,fields,expected", [
    (1, {"aPhasePw": 10}, 10), (2, {"bPhasePw": 20}, 20),
    (3, {"aPhasePw": 10, "bPhasePw": 20}, 30), (3, {"cPhasePw": 40}, 40),
    (4, {"tPhasePw": 50}, 50), (999, {"tPhasePw": 60}, 60),
])
def test_legacy_ct_phase_selection(protocol, monkeypatch, subtype, fields, expected):
    receive(protocol, 101, {"cts": [{"sn": "CT", "devType": 2, "subType": subtype, **fields}]})
    power = next(e for e in protocol.add_entities_callback.call_args.args[0] if e._sensor_key == "power")
    monkeypatch.setattr(power, "async_write_ha_state", Mock())
    power._update_from_coordinator(protocol._data_cache)
    assert power.native_value == expected
