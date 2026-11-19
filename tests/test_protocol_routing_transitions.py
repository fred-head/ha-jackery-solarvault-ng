"""Order-sensitive characterization of coordinator MQTT routing transitions."""

import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from custom_components.jackery import sensor as sensor_module
from custom_components.jackery.sensor import JackeryDataCoordinator

from .conftest import FakeMqttMsg


@pytest.fixture
def routing_state(hass, monkeypatch):
    clock = SimpleNamespace(now=1000.0)
    monkeypatch.setattr(sensor_module.time, "time", lambda: clock.now)
    coordinator = JackeryDataCoordinator(
        hass,
        "hb",
        "synthetic-token",
        "localhost",
        "HOST",
    )
    coordinator.config_entry_id = "entry"
    coordinator.add_entities_callback = Mock()
    coordinator.add_switch_entities_callback = Mock()
    listener = Mock()
    coordinator.register_sensor("listener", listener)
    return SimpleNamespace(
        coordinator=coordinator,
        clock=clock,
        listener=listener,
    )


def receive(state, message_type, body, *, host="HOST", channel="status", **envelope):
    state.clock.now += 1
    state.coordinator._handle_message(
        FakeMqttMsg(
            f"hb/device/{host}/{channel}",
            json.dumps({"type": message_type, "body": body, **envelope}),
        )
    )


@pytest.mark.parametrize(
    ("sequence", "expected_power", "expected_live"),
    [
        ((2, 106), 10, (2, 1001.0)),
        ((106, 2), 20, (2, 1002.0)),
        ((106, 107), 20, (107, 1002.0)),
    ],
)
def test_host_power_route_ordering(
    routing_state,
    sequence,
    expected_power,
    expected_live,
):
    for index, message_type in enumerate(sequence, 1):
        receive(
            routing_state,
            message_type,
            {"pvPw": index * 10, "soc": index},
        )

    coordinator = routing_state.coordinator
    assert coordinator._data_cache["pvPw"] == expected_power
    assert coordinator._data_cache["soc"] == 2
    assert coordinator._data_cache["calc_batt_net_power"] == expected_power
    assert coordinator._data_cache["total_battery_charge_power"] == expected_power
    assert coordinator._power_live_seen["pvPw"] == expected_live
    assert coordinator._power_106_samples["pvPw"] == (
        10 if sequence[0] == 106 else 20,
        1001.0 if sequence[0] == 106 else 1002.0,
    )
    assert coordinator._last_update_time == 1002.0
    assert routing_state.listener._update_from_coordinator.call_count == 2
    coordinator.add_entities_callback.assert_not_called()


@pytest.mark.parametrize("sequence", [(101, 102), (102, 101)])
def test_child_full_and_point_update_ordering(routing_state, sequence):
    for message_type in sequence:
        if message_type == 101:
            body = {
                "plugs": [
                    {
                        "sn": "PLUG",
                        "devType": 6,
                        "outPw": 10,
                        "totalEgy": 5,
                    }
                ]
            }
        else:
            body = {
                "sn": "PLUG",
                "devType": 6,
                "outPw": 20,
                "totalEgy": None,
                "pointOnly": True,
            }
        receive(routing_state, message_type, body)

    coordinator = routing_state.coordinator
    plug = coordinator._data_cache["plugs"][0]
    assert plug["outPw"] == (20 if sequence[-1] == 102 else 10)
    assert plug["totalEgy"] == 5
    assert plug["pointOnly"] is True
    assert coordinator._data_cache["plug"] is coordinator._data_cache["plugs"]
    assert coordinator._subdevice_last_seen["PLUG"] == 1002.0
    assert coordinator._known_plugs == {"PLUG"}
    assert coordinator.add_entities_callback.call_count == 1
    assert coordinator.add_switch_entities_callback.call_count == 1
    assert routing_state.listener._update_from_coordinator.call_count == 2


def test_generic_singular_plug_update_preserves_canonical_cache_and_entity(
    routing_state,
    monkeypatch,
):
    receive(
        routing_state,
        101,
        {
            "plugs": [
                {
                    "sn": "PLUG",
                    "devType": 6,
                    "outPw": 10,
                    "totalEgy": 5,
                }
            ]
        },
    )

    coordinator = routing_state.coordinator
    created_entities = coordinator.add_entities_callback.call_args.args[0]
    power = next(entity for entity in created_entities if entity._sensor_key == "power")
    monkeypatch.setattr(power, "async_write_ha_state", Mock())
    coordinator.register_sensor(power.unique_id, power)
    coordinator._distribute_data(coordinator._data_cache)
    assert power.native_value == 10

    original_entity_ids = tuple(entity.unique_id for entity in created_entities)
    receive(
        routing_state,
        2,
        {"plug": [{"sn": "PLUG", "outPw": 20}]},
    )

    assert coordinator._data_cache["plug"] is coordinator._data_cache["plugs"]
    assert coordinator._data_cache["plugs"] == [
        {"sn": "PLUG", "outPw": 20}
    ]
    assert coordinator.get_plug_item("PLUG")["outPw"] == 20
    assert power.native_value == 20
    assert coordinator._subdevice_last_seen["PLUG"] == 1002.0
    assert coordinator._known_plugs == {"PLUG"}
    assert coordinator.add_entities_callback.call_count == 1
    assert coordinator.add_switch_entities_callback.call_count == 1
    assert tuple(entity.unique_id for entity in created_entities) == original_entity_ids


def test_type23_host_then_type23_child(routing_state):
    receive(
        routing_state,
        23,
        {"deviceSn": "HOST", "pvEgy": 11},
    )
    receive(
        routing_state,
        23,
        {"deviceSn": "BATTERY", "devType": 1, "inEgy": 22},
    )

    coordinator = routing_state.coordinator
    assert coordinator._data_cache["pvEgy"] == 11
    assert coordinator._data_cache["expansion_batteries"] == {
        "BATTERY": {"deviceSn": "BATTERY", "devType": 1, "inEgy": 22}
    }
    assert coordinator._subdevice_last_seen["BATTERY"] == 1002.0
    assert coordinator._expansion_battery_sns == {"BATTERY"}
    assert len(coordinator.add_entities_callback.call_args.args[0]) == 2
    assert routing_state.listener._update_from_coordinator.call_count == 2


@pytest.mark.parametrize(
    ("serial_fields", "expected_serial"),
    [
        ({"deviceSn": "DEVICE"}, "DEVICE"),
        ({"sn": "FALLBACK"}, "FALLBACK"),
        ({"deviceSn": "SAME", "sn": "SAME"}, "SAME"),
        ({"deviceSn": "DEVICE", "sn": "FALLBACK"}, "DEVICE"),
        ({"deviceSn": "", "sn": "FALLBACK"}, "FALLBACK"),
        ({"deviceSn": 17, "sn": "FALLBACK"}, None),
        ({"sn": {"bad": "serial"}}, None),
    ],
)
def test_type23_expansion_uses_canonical_serial(
    routing_state, serial_fields, expected_serial
):
    receive(
        routing_state,
        23,
        {**serial_fields, "devType": 1, "subType": 0, "inEgy": 22},
    )

    coordinator = routing_state.coordinator
    if expected_serial is None:
        assert not coordinator._data_cache.get("expansion_batteries")
        assert not coordinator._subdevice_last_seen
        assert not coordinator._expansion_battery_sns
        coordinator.add_entities_callback.assert_not_called()
        return

    assert coordinator._data_cache["expansion_batteries"] == {
        expected_serial: {
            **serial_fields,
            "devType": 1,
            "subType": 0,
            "inEgy": 22,
        }
    }
    assert coordinator._subdevice_last_seen == {expected_serial: 1001.0}
    assert coordinator._known_plugs == {expected_serial}
    assert coordinator._expansion_battery_sns == {expected_serial}
    entities = coordinator.add_entities_callback.call_args.args[0]
    assert len(entities) == 2
    assert {entity._plug_sn for entity in entities} == {expected_serial}
    charge = next(entity for entity in entities if entity._sensor_key == "charge_energy")
    assert charge.native_value == 0.22


def test_type23_conflicting_host_device_serial_remains_host_message(routing_state):
    receive(
        routing_state,
        23,
        {"deviceSn": "HOST", "sn": "BATTERY", "devType": 1, "inEgy": 22},
    )

    coordinator = routing_state.coordinator
    assert coordinator._data_cache["inEgy"] == 22
    assert "expansion_batteries" not in coordinator._data_cache
    assert not coordinator._subdevice_last_seen
    coordinator.add_entities_callback.assert_not_called()


def test_type23_child_then_type101(routing_state):
    receive(
        routing_state,
        23,
        {"deviceSn": "BATTERY", "devType": 1, "outEgy": 3},
    )
    receive(
        routing_state,
        101,
        {"plugs": [{"sn": "PLUG", "devType": 6, "outPw": 4}]},
    )

    coordinator = routing_state.coordinator
    assert coordinator._data_cache["expansion_batteries"]["BATTERY"]["outEgy"] == 3
    assert coordinator._data_cache["plugs"][0]["outPw"] == 4
    assert coordinator._expansion_battery_sns == {"BATTERY"}
    assert coordinator._known_plugs == {"BATTERY", "PLUG"}
    assert coordinator.add_entities_callback.call_count == 2
    assert routing_state.listener._update_from_coordinator.call_count == 2


@pytest.mark.parametrize(
    "bad_payload",
    [
        "{",
        "[]",
        "null",
        '{"type":2,"body":[]}',
        '{"type":2,"body":"bad"}',
        '{"type":2,"body":7}',
    ],
)
def test_malformed_message_then_valid_message(routing_state, bad_payload):
    state = routing_state
    state.clock.now += 1
    state.coordinator._handle_message(FakeMqttMsg("hb/device/HOST/status", bad_payload))
    assert state.coordinator._data_cache == {}
    assert state.coordinator._last_update_time == 1000.0
    state.listener._update_from_coordinator.assert_not_called()

    receive(state, 2, {"batSoc": 42})
    assert state.coordinator._data_cache["batSoc"] == 42
    assert state.coordinator._last_update_time == 1002.0
    state.listener._update_from_coordinator.assert_called_once()


def test_foreign_host_then_valid_host(routing_state):
    receive(routing_state, 2, {"batSoc": 99}, host="FOREIGN")
    assert routing_state.coordinator._data_cache == {}
    assert routing_state.coordinator._last_update_time == 1000.0
    routing_state.listener._update_from_coordinator.assert_not_called()

    receive(routing_state, 2, {"batSoc": 42})
    assert routing_state.coordinator._data_cache["batSoc"] == 42
    assert routing_state.coordinator._last_update_time == 1002.0
    routing_state.listener._update_from_coordinator.assert_called_once()


def test_unknown_type_then_known_type(routing_state):
    receive(routing_state, 999, {"future": {"value": 1}})
    receive(routing_state, 2, {"batSoc": 42})

    assert routing_state.coordinator._data_cache["future"] == {"value": 1}
    assert routing_state.coordinator._data_cache["batSoc"] == 42
    assert routing_state.listener._update_from_coordinator.call_count == 2


def test_auth_error_between_status_messages(routing_state, monkeypatch):
    trigger = Mock()
    monkeypatch.setattr(routing_state.coordinator, "_trigger_reauth", trigger)
    receive(routing_state, 2, {"batSoc": 41})
    receive(routing_state, 123, {"errorCode": 401, "batSoc": 99})
    receive(routing_state, 107, {"soc": 42})

    trigger.assert_called_once_with("device reported token mismatch (type-123/401)")
    assert routing_state.coordinator._data_cache["batSoc"] == 41
    assert routing_state.coordinator._data_cache["soc"] == 42
    assert "errorCode" not in routing_state.coordinator._data_cache
    assert routing_state.coordinator._last_update_time == 1003.0
    assert routing_state.listener._update_from_coordinator.call_count == 3


@pytest.mark.parametrize("message_type", [[], {}, "malformed"])
def test_malformed_type_uses_existing_generic_route_then_known_message(
    routing_state,
    message_type,
):
    receive(routing_state, message_type, {"future": 1})
    receive(routing_state, 2, {"batSoc": 42})

    assert routing_state.coordinator._data_cache["future"] == 1
    assert routing_state.coordinator._data_cache["batSoc"] == 42
    assert routing_state.listener._update_from_coordinator.call_count == 2


def test_malformed_arrays_and_metadata_then_valid_child(routing_state):
    receive(
        routing_state,
        2,
        {"plugs": {"bad": "container"}, "soc": 1},
        deviceType=[],
    )
    first_cache = deepcopy(routing_state.coordinator._data_cache)
    assert "plugs" not in first_cache
    assert first_cache["soc"] == 1
    assert routing_state.coordinator._device_type is None

    receive(
        routing_state,
        101,
        {
            "plugs": [
                7,
                {"deviceSn": [], "devType": 6},
                {"sn": "BAD-TYPE", "devType": []},
                {"sn": "GOOD", "devType": 6, "outPw": 0},
            ]
        },
    )
    assert routing_state.coordinator._data_cache["plugs"] == [
        {"sn": "BAD-TYPE", "devType": []},
        {"sn": "GOOD", "devType": 6, "outPw": 0}
    ]
    assert routing_state.coordinator._subdevice_last_seen["BAD-TYPE"] == 1002.0
    assert routing_state.coordinator._known_plugs == {"GOOD"}
    assert routing_state.listener._update_from_coordinator.call_count == 2
