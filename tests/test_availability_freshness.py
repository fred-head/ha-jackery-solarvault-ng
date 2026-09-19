"""Synthetic MQTT → cache → real entity freshness and timer regressions."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.jackery import sensor as sensor_module
from custom_components.jackery.number import JackeryMainNumber
from custom_components.jackery.select import JackeryWorkModeSelect
from custom_components.jackery.sensor import (
    OFFLINE_TIMEOUT,
    SMARTMETER_HTTP_SENSOR_CONFIGS,
    SUBDEVICE_SENSORS,
    JackeryDataCoordinator,
    JackerySensor,
    JackerySmartMeterHttpSensor,
    JackerySubDeviceSensor,
)
from custom_components.jackery.switch import JackeryFollowMeterSwitch, JackeryMainSwitch, JackeryPlugSwitch

from .conftest import FakeMqttMsg


def receive(coordinator, body, code=2, host="MAIN", channel="status"):
    coordinator._handle_message(FakeMqttMsg(
        f"{coordinator._topic_root}/device/{host}/{channel}",
        json.dumps({"type": code, "body": body}),
    ))


@pytest.fixture
async def runtime(monkeypatch):
    clock = SimpleNamespace(now=1000.0)
    monkeypatch.setattr(sensor_module, "time", SimpleNamespace(time=lambda: clock.now))
    coordinator = JackeryDataCoordinator(None, "hb", "testtoken", "localhost", "MAIN")
    entities = []

    async def add(entity):
        monkeypatch.setattr(entity, "async_write_ha_state", Mock())
        await entity.async_added_to_hass()
        entities.append(entity)
        return entity

    main = await add(JackerySensor("battery_soc", coordinator, "ENTRY"))
    http = await add(JackerySmartMeterHttpSensor(
        "METER", "frequency", SMARTMETER_HTTP_SENSOR_CONFIGS["frequency"], coordinator, "ENTRY"
    ))
    yield SimpleNamespace(coordinator=coordinator, clock=clock, add=add, main=main, http=http)
    await coordinator.async_stop()
    for entity in entities:
        await entity.async_will_remove_from_hass()
    assert coordinator._sensors == {}


@pytest.fixture
async def mqtt_tick(runtime, monkeypatch):
    """Advance the real periodic health check without network or wall-clock sleeps."""
    paused, resume = asyncio.Queue(), asyncio.Queue()

    async def sleep(delay):
        await paused.put(delay)
        await resume.get()

    monkeypatch.setattr(sensor_module.asyncio, "sleep", sleep)
    monkeypatch.setattr(runtime.coordinator, "_send_poll_requests", AsyncMock())
    task = asyncio.create_task(runtime.coordinator._periodic_data_request())
    runtime.coordinator._data_task = task
    assert await paused.get() == 2

    async def tick():
        await resume.put(None)
        assert await paused.get() == sensor_module.REQUEST_INTERVAL

    yield tick
    await runtime.coordinator.async_stop()
    assert task.done()


@pytest.mark.parametrize("channel", ["status", "event"])
def test_foreign_host_cannot_refresh_heartbeat(runtime, channel):
    c, clock = runtime.coordinator, runtime.clock
    other = JackeryDataCoordinator(None, "hb", "testtoken", "localhost", "OTHER")
    initial = c._last_update_time
    clock.now += 40
    for target in (c, other):
        receive(target, {"batSoc": 55}, host="OTHER", channel=channel)
    assert c._last_update_time == initial
    assert not c._ever_received
    assert c._data_cache == {}
    assert other._last_update_time == clock.now
    assert other._ever_received
    assert other._data_cache["batSoc"] == 55


@pytest.mark.parametrize("payload", ["{bad json", "[]", "null", '{"type":2,"body":[]}'])
def test_invalid_payload_does_not_refresh_or_suppress_reauth(runtime, payload):
    c = runtime.coordinator
    initial = c._last_update_time
    runtime.clock.now += 40
    c._handle_message(FakeMqttMsg("hb/device/MAIN/status", payload))
    assert c._last_update_time == initial
    assert not c._ever_received


@pytest.mark.parametrize("topic", [
    "other/device/MAIN/status", "xhb/device/MAIN/status", "hb/device/MAIN/status/extra",
])
def test_nonmatching_topic_does_not_refresh_host(runtime, topic):
    initial = runtime.coordinator._last_update_time
    runtime.clock.now += 40
    runtime.coordinator._handle_message(FakeMqttMsg(topic, '{"batSoc":42}'))
    assert runtime.coordinator._last_update_time == initial
    assert not runtime.coordinator._ever_received


def test_topic_prefix_is_literal_and_supports_multiple_levels(runtime):
    c = runtime.coordinator
    c._topic_root = "site/hb.v1"
    initial = c._last_update_time
    runtime.clock.now += 40
    c._handle_message(FakeMqttMsg("site/hbXv1/device/MAIN/status", '{"batSoc":42}'))
    assert c._last_update_time == initial
    receive(c, {"batSoc": 43})
    assert c._last_update_time == runtime.clock.now


@pytest.mark.parametrize("code,body", [
    (2, {"batSoc": 42}), (25, {"batSoc": 42}), (106, {"soc": 42}),
    (107, {"soc": 42}), (23, {"deviceSn": "system", "pvEgy": 5}),
    (23, {"deviceSn": "BATTERY", "devType": 1, "inEgy": 5}),
    (101, {"cts": [{"deviceSn": "METER", "devType": 3, "tPhasePw": 5}]}),
    (102, {"deviceSn": "METER", "devType": 3, "tPhasePw": 5}),
    (99, {"batSoc": 42}),
])
def test_host_and_relayed_child_messages_refresh_host(runtime, code, body):
    runtime.clock.now += 40
    receive(runtime.coordinator, body, code=code)
    assert runtime.coordinator._last_update_time == runtime.clock.now
    assert runtime.coordinator._ever_received


async def test_main_timeout_boundary_foreign_traffic_and_recovery(runtime, mqtt_tick):
    c, main, clock = runtime.coordinator, runtime.main, runtime.clock
    receive(c, {"batSoc": 42})
    registration = dict(c._sensors)
    clock.now += OFFLINE_TIMEOUT
    await mqtt_tick()
    assert main.available
    clock.now += 1
    receive(c, {"batSoc": 99}, host="OTHER")
    await mqtt_tick()
    assert not main.available
    assert main.native_value == 42
    receive(c, {"batSoc": 43})
    assert main.available
    assert main.native_value == 43
    assert c._sensors == registration


CHILD_CASES = [
    ("plug", "plugs", 6, 0, "power", "outPw"),
    ("ct", "cts", 2, 1, "power", "aPhasePw"),
    ("ct_3phase", "cts", 3, 5, "import_total", "tPhasePw"),
    ("ct_3phase", "cts", 3, 2, "import_total", "tPhasePw"),
    ("collector", "collectors", 4, 7, "import_power", "inPw"),
    ("ct", "cts", 4, 1, "power", "aPhasePw"),
]


async def add_child(runtime, case, sn):
    group, section, dev_type, sub_type, key, field = case
    entity = await runtime.add(JackerySubDeviceSensor(
        sn, dev_type, key, SUBDEVICE_SENSORS[group][key], runtime.coordinator, "ENTRY",
        data_key=section, sensor_group=group,
    ))
    item = {"deviceSn": sn, "devType": dev_type, "subType": sub_type, field: 100}
    if group == "plug":
        item.update(sysSwitch=1, commMode=1)
    return entity, item


@pytest.mark.parametrize("case", CHILD_CASES)
async def test_child_stale_fanout_isolation_and_recovery(runtime, case):
    c, clock = runtime.coordinator, runtime.clock
    child, item = await add_child(runtime, case, "CHILD_A")
    sibling, other = await add_child(runtime, case, "CHILD_B")
    switch = None
    if case[0] == "plug":
        switch = await runtime.add(JackeryPlugSwitch("CHILD_A", 6, c, "ENTRY"))
    receive(c, {case[1]: [item, other]}, code=101)
    assert child.available and sibling.available
    assert child.native_value == 100
    registrations = dict(c._sensors)
    clock.now += OFFLINE_TIMEOUT + 1
    receive(c, {**other, case[-1]: 200}, code=102)
    assert not child.available
    assert child.native_value == 100
    assert sibling.available and sibling.native_value == 200
    if switch:
        assert not switch.available
    receive(c, {"batSoc": 43})
    assert not child.available  # Main fan-out cannot revive cached child values.
    receive(c, {**item, case[-1]: 0}, code=102)
    assert child.available and child.native_value == 0
    assert sibling.available
    if switch:
        assert switch.available
    assert c._sensors == registrations
    assert c._subdevice_missing_since == {}


@pytest.mark.parametrize(
    "malformed",
    [
        pytest.param("bad", id="non-numeric-string"),
        pytest.param([1], id="non-numeric-container"),
        pytest.param(10**4000, id="overflowing-integer"),
    ],
)
@pytest.mark.parametrize(
    ("sensor_key", "a_key", "b_key", "initial_value", "recovered_value"),
    [
        pytest.param("power", "AphasePw", "BphasePw", 5, 4, id="power"),
        pytest.param("energy", "AphaseEgy", "BphaseEgy", 0.05, 0.04, id="energy"),
    ],
)
async def test_malformed_subtype3_phase_sum_does_not_interrupt_fanout(
    runtime,
    malformed,
    sensor_key,
    a_key,
    b_key,
    initial_value,
    recovered_value,
    caplog,
):
    coordinator = runtime.coordinator
    power = await runtime.add(
        JackerySubDeviceSensor(
            "CT",
            2,
            sensor_key,
            SUBDEVICE_SENSORS["ct"][sensor_key],
            coordinator,
            "ENTRY",
            data_key="cts",
            sensor_group="ct",
        )
    )
    receive(
        coordinator,
        {
            "cts": [
                {
                    "deviceSn": "CT",
                    "devType": 2,
                    "subType": 3,
                    a_key: 2,
                    b_key: 3,
                }
            ]
        },
        code=101,
    )
    assert power.native_value == initial_value

    later_update = Mock()
    coordinator.register_sensor(
        "later",
        SimpleNamespace(_update_from_coordinator=later_update),
    )
    try:
        receive(
            coordinator,
            {
                "cts": [
                    {
                        "deviceSn": "CT",
                        "devType": 2,
                        "subType": 3,
                        a_key: malformed,
                        b_key: 1,
                    }
                ]
            },
            code=101,
        )
        assert power.native_value == initial_value
        later_update.assert_called_once_with(coordinator._data_cache)
        assert "Error handling message" not in caplog.text

        receive(
            coordinator,
            {
                "cts": [
                    {
                        "deviceSn": "CT",
                        "devType": 2,
                        "subType": 3,
                        a_key: "2.5",
                        b_key: "1.5",
                    }
                ]
            },
            code=101,
        )
        assert power.native_value == recovered_value
        assert later_update.call_count == 2
    finally:
        coordinator.unregister_sensor("later")


@pytest.mark.parametrize("case", CHILD_CASES)
async def test_child_expires_on_timer_without_new_messages(runtime, mqtt_tick, case):
    child, item = await add_child(runtime, case, "CHILD")
    receive(runtime.coordinator, {case[1]: [item]}, code=101)
    runtime.clock.now += OFFLINE_TIMEOUT
    await mqtt_tick()
    assert child.available
    # Host refreshed just before the child expires: independent child timer required.
    receive(runtime.coordinator, {"batSoc": 42})
    runtime.clock.now += 1
    await mqtt_tick()
    assert runtime.main.available
    assert not child.available


@pytest.mark.parametrize("case", CHILD_CASES)
async def test_full_list_omission_retains_entities_but_not_freshness(runtime, case):
    c = runtime.coordinator
    child, item = await add_child(runtime, case, "CHILD_A")
    sibling, other = await add_child(runtime, case, "CHILD_B")
    receive(c, {case[1]: [item, other]}, code=101)
    initial = c._subdevice_last_seen["CHILD_A"]
    runtime.clock.now += OFFLINE_TIMEOUT + 1
    receive(c, {case[1]: [other]}, code=101)
    receive(c, {case[1]: []}, code=101)
    assert "CHILD_A" in c._known_plugs
    assert child in c._sensors.values()
    assert c._subdevice_missing_since == {}
    assert c._subdevice_last_seen["CHILD_A"] == initial
    assert not child.available
    assert sibling.available


@pytest.mark.parametrize("case", CHILD_CASES[:4])
async def test_child_statistics_refresh_only_matching_child(runtime, case):
    child, item = await add_child(runtime, case, "CHILD_A")
    sibling, other = await add_child(runtime, case, "CHILD_B")
    receive(runtime.coordinator, {case[1]: [item, other]}, code=101)
    runtime.clock.now += OFFLINE_TIMEOUT + 1
    receive(runtime.coordinator, {"deviceSn": "CHILD_A", "totalEgy": 50}, code=23)
    assert runtime.coordinator._subdevice_last_seen["CHILD_A"] == runtime.clock.now
    assert child.available
    assert not sibling.available


async def test_metadata_only_child_message_preserves_existing_activity_policy(runtime):
    child, item = await add_child(runtime, CHILD_CASES[2], "CHILD")
    receive(runtime.coordinator, {"cts": [item]}, code=101)
    runtime.clock.now += OFFLINE_TIMEOUT + 1
    receive(runtime.coordinator, {"deviceSn": "CHILD", "commMode": 2, "commState": 0}, code=102)
    assert child.available
    assert child.native_value == 100  # Measurement age is not tracked individually.


async def test_mqtt_timeouts_do_not_invalidate_healthy_http(runtime, mqtt_tick):
    c, http = runtime.coordinator, runtime.http
    receive(c, {"cts": [{"deviceSn": "METER", "devType": 3, "tPhasePw": 10}]}, code=101)
    c._distribute_http_data("METER", {"freq": 50})
    runtime.clock.now += OFFLINE_TIMEOUT + 1
    # The child health check also finds the HTTP entity by its meter SN.
    receive(c, {"batSoc": 42})
    assert http.available
    runtime.clock.now += OFFLINE_TIMEOUT + 1
    await mqtt_tick()
    assert not runtime.main.available
    assert http.available and http.native_value == 50


async def test_mqtt_cannot_revive_failed_http_for_same_child(runtime):
    c, http = runtime.coordinator, runtime.http
    receive(c, {"cts": [{"deviceSn": "METER", "devType": 3, "tPhasePw": 10}]}, code=101)
    c._distribute_http_data("METER", {"freq": 50})
    c._mark_http_sensors_unavailable("METER")
    receive(c, {"deviceSn": "METER", "tPhasePw": 20}, code=102)
    assert not http.available
    assert http.native_value == 50


@pytest.mark.parametrize("mqtt_healthy,http_healthy", [(True, True), (False, True), (True, False), (False, False)])
async def test_energy_sources_keep_http_health_independent(runtime, mqtt_tick, mqtt_healthy, http_healthy):
    c, clock, http = runtime.coordinator, runtime.clock, runtime.http
    grid = await runtime.add(JackerySensor("grid_net_power", c, "ENTRY"))
    receive(c, {"cts": [{"deviceSn": "METER", "devType": 3, "tPhasePw": 0}]}, code=101)
    c._distribute_http_data("METER", {"freq": 0})
    assert grid.native_value == http.native_value == 0
    if not http_healthy:
        c._mark_http_sensors_unavailable("METER")
    clock.now += 61
    if mqtt_healthy:
        receive(c, {"deviceSn": "METER", "tPhasePw": 0}, code=102)
    await mqtt_tick()
    assert grid.available == mqtt_healthy
    assert http.available == http_healthy
    assert http.native_value == 0
    # HTTP recovery cannot make MQTT current; MQTT recovery cannot change HTTP.
    c._distribute_http_data("METER", {"freq": 50})
    assert grid.available == mqtt_healthy
    receive(c, {"deviceSn": "METER", "tPhasePw": 20}, code=102)
    assert grid.available and grid.native_value == 20
    assert http.available and http.native_value == 50


@pytest.mark.parametrize("fallback", [None, 100])
async def test_meter_expiry_updates_derived_entities_on_existing_timer(runtime, mqtt_tick, fallback):
    c, clock = runtime.coordinator, runtime.clock
    grid = await runtime.add(JackerySensor("grid_net_power", c, "ENTRY"))
    home = await runtime.add(JackerySensor("home_power", c, "ENTRY"))
    receive(c, {"cts": [{"deviceSn": "METER", "devType": 3, "tPhasePw": 800}]}, code=101)
    assert grid.native_value == home.native_value == 800
    clock.now += 40
    body = {"batSoc": 42}
    if fallback is not None:
        body["gridInPw"] = fallback
    receive(c, body)
    main_writes = runtime.main.async_write_ha_state.call_count
    clock.now += 21
    await mqtt_tick()
    assert grid.available == (fallback is not None)
    if fallback is not None:
        assert grid.native_value == fallback
    assert home.native_value == 0
    assert runtime.main.async_write_ha_state.call_count == main_writes
    writes = grid.async_write_ha_state.call_count
    await mqtt_tick()
    assert grid.async_write_ha_state.call_count == writes
    assert c._data_cache["cts"][0]["tPhasePw"] == 800
    receive(c, {"deviceSn": "METER", "tPhasePw": 0}, code=102)
    assert grid.available and grid.native_value == 0


@pytest.mark.parametrize("field", ["swEpsInPw", "swEpsOutPw"])
async def test_106_null_eps_does_not_interrupt_energy_entity_fanout(runtime, field):
    c = runtime.coordinator
    eps = await runtime.add(JackerySensor("eps_output_power", c, "ENTRY"))
    battery = await runtime.add(JackerySensor("battery_net_power", c, "ENTRY"))
    receive(c, {"swEpsInPw": 0, "swEpsOutPw": 20, "pvPw": 100}, code=106)
    assert eps.native_value == 20 and battery.native_value == 80
    receive(c, {field: None, "pvPw": 200}, code=106)
    assert not eps.available
    assert battery.native_value == (200 if field == "swEpsOutPw" else 180)
    receive(c, {field: 0}, code=106)
    assert eps.available


async def test_expansion_cumulative_energy_survives_silence(runtime, mqtt_tick):
    c = runtime.coordinator
    config = SUBDEVICE_SENSORS["expansion_battery"]["charge_energy"]
    battery = await runtime.add(JackerySubDeviceSensor(
        "BATTERY", 1, "charge_energy", config, c, "ENTRY", use_expansion=True,
    ))
    receive(c, {"deviceSn": "BATTERY", "devType": 1, "inEgy": 1234}, code=23)
    assert battery.available and battery.native_value == 12.34
    runtime.clock.now += 600
    await mqtt_tick()
    assert battery.available and battery.native_value == 12.34
    assert "BATTERY" not in c._subdevice_missing_since


@pytest.mark.parametrize("code", [2, 25, 106, 107, 99])
@pytest.mark.parametrize("case", [CHILD_CASES[0], CHILD_CASES[2], CHILD_CASES[4]])
async def test_child_arrays_in_generic_system_messages_refresh_their_members(runtime, code, case):
    child, item = await add_child(runtime, case, "CHILD")
    receive(runtime.coordinator, {case[1]: [item]}, code=101)
    runtime.clock.now += OFFLINE_TIMEOUT + 1
    receive(runtime.coordinator, {case[1]: [{**item, case[-1]: 200}]}, code=code)
    assert runtime.coordinator._subdevice_last_seen["CHILD"] == runtime.clock.now
    assert child.available and child.native_value == 200


async def test_host_controls_timeout_and_recover_with_mode_gate_preserved(runtime, mqtt_tick):
    c = runtime.coordinator
    switch = await runtime.add(JackeryMainSwitch("swEps", c, "ENTRY", translation_key="eps_switch"))
    follow = await runtime.add(JackeryFollowMeterSwitch("isFollowMeterPw", c, "ENTRY", translation_key="follow_meter_power"))
    select = await runtime.add(JackeryWorkModeSelect(c, "ENTRY"))
    number = await runtime.add(JackeryMainNumber("maxOutPw", 0, 2500, 10, c, "ENTRY"))
    data = {"swEps": 1, "workMode": 4, "isFollowMeterPw": 1, "maxOutPw": 800}
    receive(c, data)
    assert all(entity.available for entity in (switch, follow, select, number))
    runtime.clock.now += OFFLINE_TIMEOUT + 1
    await mqtt_tick()
    assert all(not entity.available for entity in (switch, follow, select, number))
    receive(c, {**data, "workMode": 2})
    assert all(entity.available for entity in (switch, select, number))
    assert not follow.available
    receive(c, {"workMode": 4})
    assert follow.available


async def test_repeated_child_timeout_does_not_repeat_state_writes(runtime, mqtt_tick):
    child, item = await add_child(runtime, CHILD_CASES[0], "CHILD")
    receive(runtime.coordinator, {"plugs": [item]}, code=101)
    runtime.clock.now += OFFLINE_TIMEOUT + 1
    await mqtt_tick()
    writes = child.async_write_ha_state.call_count
    await mqtt_tick()
    assert child.async_write_ha_state.call_count == writes


async def test_health_transition_can_unregister_child_listener(runtime, mqtt_tick):
    child, item = await add_child(runtime, CHILD_CASES[0], "CHILD")
    sibling, other = await add_child(runtime, CHILD_CASES[0], "SIBLING")
    receive(runtime.coordinator, {"plugs": [item, other]}, code=101)
    child.async_write_ha_state.side_effect = lambda: runtime.coordinator.unregister_sensor(child.unique_id)
    runtime.clock.now += OFFLINE_TIMEOUT + 1
    await mqtt_tick()
    assert child.unique_id not in runtime.coordinator._sensors
    assert not sibling.available


def test_conflicting_payload_sn_keeps_existing_topic_authority(runtime):
    """Generic payload SN ownership is ambiguous; do not invent a new rejection rule."""
    runtime.clock.now += 40
    receive(runtime.coordinator, {"deviceSn": "DIFFERENT", "batSoc": 42})
    assert runtime.coordinator._last_update_time == runtime.clock.now
    assert runtime.main.available and runtime.main.native_value == 42
