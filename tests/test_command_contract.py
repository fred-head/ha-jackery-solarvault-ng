"""Exact action envelopes through production entities; no live device commands."""

import asyncio
import json
import logging
from copy import deepcopy
from functools import partial
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.components.number import async_set_value
from homeassistant.core import ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from custom_components.jackery import DOMAIN, button, number, select, switch
from custom_components.jackery import sensor as sensor_module
from custom_components.jackery.sensor import JackeryDataCoordinator
from custom_components.jackery.switch import JackeryPlugSwitch
from custom_components.jackery.transport import mqtt as mqtt_transport_module

from .test_protocol_contract import receive


@pytest.fixture
async def commands(hass, monkeypatch):
    c = JackeryDataCoordinator(hass, "custom/hb", "synthetic-token", "localhost", "HOST_A")
    c.config_entry_id = "command-entry"
    hass.data[DOMAIN] = {c.config_entry_id: {"coordinator": c}}
    entry = SimpleNamespace(entry_id=c.config_entry_id)
    entities = []
    for platform in (switch, number, select, button):
        await platform.async_setup_entry(hass, entry, entities.extend)
    for entity in entities:
        entity.hass = hass
        monkeypatch.setattr(entity, "async_write_ha_state", Mock())
        if hasattr(entity, "_update_from_coordinator"):
            c.register_sensor(entity.unique_id, entity)
    publish = AsyncMock()
    monkeypatch.setattr(mqtt_transport_module.ha_mqtt, "async_publish", publish)
    # Replace module references rather than the global asyncio/time modules used by HA.
    monkeypatch.setattr(sensor_module, "time", SimpleNamespace(time=lambda: 1700000000.75))
    randint = Mock(return_value=4321)
    monkeypatch.setattr(sensor_module, "random", SimpleNamespace(randint=randint))
    return SimpleNamespace(c=c, entities=entities, publish=publish, randint=randint)


def entity_for(ctx, field):
    if field == "reboot":
        return next(e for e in ctx.entities if isinstance(e, button.JackeryRebootButton))
    if field == "autoStandby":
        return next(e for e in ctx.entities if isinstance(e, select.JackeryAutoStandbySelect))
    if field == "workModel":
        return next(e for e in ctx.entities if isinstance(e, select.JackeryWorkModeSelect))
    return next(e for e in ctx.entities if getattr(e, "_key", None) == field)


def envelope(kind, body, *, token="synthetic-token", message_id=4321):
    result = {"type": kind, "eventId": 3 if kind == 1 else 0,
              "messageId": message_id, "ts": 1700000000, "body": body}
    if token is not None:
        result["token"] = token
    return result


def assert_publish(ctx, expected, index=-1):
    args = ctx.publish.await_args_list[index]
    assert not args.kwargs
    hass, topic, payload, qos, retain = args.args
    assert hass is ctx.c.hass
    assert topic == "custom/hb/device/HOST_A/action"
    assert qos == 0 and retain is False
    assert json.loads(payload) == expected
    ctx.randint.assert_called_with(1000, 9999)


SWITCHES = ["isAutoStandby", "swEps", "offGridDown", "socForceChg", "isFollowMeterPw"]
OPTIMISTIC_SWITCHES = SWITCHES[2:]
SELECTS = [("autoStandby", "invalid", 0), ("autoStandby", "standby", 1), ("autoStandby", "on", 2),
           ("workModel", "self_consumption", 2), ("workModel", "custom", 4),
           ("workModel", "tariff", 7), ("workModel", "ai", 8)]


@pytest.mark.parametrize("field", SWITCHES)
@pytest.mark.parametrize("on", [False, True])
async def test_all_main_switch_payloads_and_optimism(commands, field, on):
    e = entity_for(commands, field)
    receive(commands.c, 107, {field: int(not on), "workMode": 4, "unrelated": 17})
    assert e.is_on == (not on)
    await (e.async_turn_on() if on else e.async_turn_off())
    assert_publish(commands, envelope(1, {"cmd": 5, "rc": 1, field: int(on)}))
    assert commands.publish.await_count == 1
    optimistic = field in OPTIMISTIC_SWITCHES
    assert e.is_on == (on if optimistic else not on)
    assert commands.c._data_cache[field] == int(on if optimistic else not on)
    for state in (on, not on):
        receive(commands.c, 107, {field: int(state)})
        assert e.is_on == state
    assert commands.c._data_cache["unrelated"] == 17


@pytest.mark.parametrize("field,option,value", SELECTS)
async def test_all_select_values_exact_payload_and_telemetry_wins(commands, field, option, value):
    e = entity_for(commands, field)
    previous = 2 if value != 2 else 4 if field == "workModel" else 1
    receive(commands.c, 106, {field: previous, "unrelated": 3})
    await e.async_select_option(option)
    assert_publish(commands, envelope(1, {"cmd": 5, "rc": 1, field: value}))
    assert e.current_option == option
    assert commands.c._data_cache[field] == value
    if field == "workModel":
        assert commands.c._data_cache["workMode"] == value
    receive(commands.c, 107, {field: value})
    assert e.current_option == option
    receive(commands.c, 107, {field: previous})
    assert e.current_option != option
    assert commands.c._data_cache[field] == previous
    assert commands.c._data_cache["unrelated"] == 3


@pytest.mark.parametrize("field", list(number.NUMBERS))
@pytest.mark.parametrize("boundary", ["min", "max", "fractional", "out-of-range"])
async def test_number_encoding_and_existing_boundary_contract(commands, field, boundary):
    cfg = number.NUMBERS[field]
    e = entity_for(commands, field)
    assert (e.native_min_value, e.native_max_value, e.native_step) == (cfg["min"], cfg["max"], cfg["step"])
    value = cfg[boundary] if boundary in ("min", "max") else cfg["min"] + 0.9 if boundary == "fractional" else cfg["max"] + 1
    receive(commands.c, 2, {field: 50, "unrelated": 6})
    await e.async_set_native_value(value)
    assert_publish(commands, envelope(1, {"cmd": 5, "rc": 1, field: int(value)}))
    optimistic = cfg.get("optimistic", False)
    assert e.native_value == (value if optimistic else 50)
    assert commands.c._data_cache[field] == (int(value) if optimistic else 50)
    # Entity methods truncate; HA's service layer owns range validation. No extra clamp/step rounding.
    receive(commands.c, 107, {field: int(value)})
    assert e.native_value == int(value)
    receive(commands.c, 107, {field: 55})
    assert e.native_value == 55
    assert commands.c._data_cache["unrelated"] == 6


@pytest.mark.parametrize("field,min_key,max_key", [("socChgLimit", "minSocChg", "maxSocChg"),
                                                 ("socDischgLimit", "minSocDischg", "maxSocDischg")])
async def test_device_reported_number_bounds(commands, field, min_key, max_key):
    e = entity_for(commands, field)
    receive(commands.c, 2, {min_key: 10, max_key: 90, field: 50})
    assert (e.native_min_value, e.native_max_value) == (10, 90)
    for value in (10, 90):
        await e.async_set_native_value(value)
        assert_publish(commands, envelope(1, {"cmd": 5, "rc": 1, field: value}))


@pytest.mark.parametrize("field", ["autoStandby", "workModel"])
async def test_invalid_select_no_publish_or_optimistic_write(commands, field):
    e = entity_for(commands, field)
    receive(commands.c, 2, {field: 2})
    before = deepcopy(commands.c._data_cache)
    await e.async_select_option("not-supported")
    commands.publish.assert_not_awaited()
    assert commands.c._data_cache == before


async def test_reboot_exact_command(commands):
    before = deepcopy(commands.c._data_cache)
    await entity_for(commands, "reboot").async_press()
    assert_publish(commands, envelope(1, {"cmd": 5, "rc": 1, "reboot": 1}))
    assert commands.c._data_cache == before


def plug_for(ctx, monkeypatch, mode=1):
    receive(ctx.c, 101, {"plugs": [{"sn": "PLUG", "devType": 6, "sysSwitch": 0, "commMode": mode}]})
    e = JackeryPlugSwitch("PLUG", 6, ctx.c, "command-entry")
    e.hass = ctx.c.hass
    monkeypatch.setattr(e, "async_write_ha_state", Mock())
    ctx.c.register_sensor("plug_switch_PLUG", e)
    ctx.c._distribute_data(ctx.c._data_cache)
    return e


@pytest.mark.parametrize("action,initial,value", [("async_turn_on", 0, 1), ("async_turn_off", 1, 0),
                                                ("async_toggle", 0, 1), ("async_toggle", 1, 0)])
async def test_plug_commands_are_not_optimistic(commands, monkeypatch, action, initial, value):
    e = plug_for(commands, monkeypatch)
    receive(commands.c, 102, {"sn": "PLUG", "sysSwitch": initial})
    await getattr(e, action)()
    assert_publish(commands, envelope(103, {"deviceSn": "PLUG", "devType": 6, "sysSwitch": value}))
    assert e.is_on == bool(initial)
    assert commands.c.get_plug_item("PLUG")["sysSwitch"] == initial
    for state in (value, initial):
        receive(commands.c, 102, {"sn": "PLUG", "sysSwitch": state})
        assert e.is_on == bool(state)


@pytest.mark.parametrize("mode", [1, "1"])
async def test_direct_coordinator_allows_local_plug(commands, mode):
    receive(
        commands.c,
        101,
        {"plugs": [{"sn": "PLUG", "devType": 6, "commMode": mode}]},
    )

    await commands.c.async_control_subdevice_switch("PLUG", 6, True)

    assert_publish(commands, envelope(103, {"deviceSn": "PLUG", "devType": 6, "sysSwitch": 1}))
    assert commands.publish.await_count == 1


@pytest.mark.parametrize("mode", [2, "2", None, "bad", {}, 3])
async def test_direct_coordinator_blocks_nonlocal_plug(commands, mode, caplog):
    receive(
        commands.c,
        101,
        {"plugs": [{"sn": "PLUG", "devType": 6, "commMode": mode}]},
    )

    with pytest.raises(HomeAssistantError, match="commMode"):
        await commands.c.async_control_subdevice_switch("PLUG", 6, True)

    commands.publish.assert_not_awaited()
    assert "PLUG" in caplog.text
    assert "commMode" in caplog.text


async def test_direct_coordinator_blocks_missing_plug(commands, caplog):
    with pytest.raises(HomeAssistantError, match="Unknown commMode"):
        await commands.c.async_control_subdevice_switch("MISSING", 6, True)

    commands.publish.assert_not_awaited()
    assert "MISSING" in caplog.text
    assert "Unknown commMode" in caplog.text


async def test_direct_local_plug_publish_failure_propagates(commands):
    receive(
        commands.c,
        101,
        {"plugs": [{"sn": "PLUG", "devType": 6, "commMode": 1}]},
    )
    commands.publish.side_effect = HomeAssistantError("MQTT unavailable")

    with pytest.raises(HomeAssistantError, match="MQTT unavailable"):
        await commands.c.async_control_subdevice_switch("PLUG", 6, True)

    assert commands.publish.await_count == 1


@pytest.mark.parametrize("mode,allowed", [(1, True), ("1", True), (2, False), (None, False),
                                         ("bad", False), ({}, False), (3, False)])
@pytest.mark.parametrize("action", ["async_turn_on", "async_turn_off", "async_toggle"])
async def test_commmode_gates_all_plug_actions(commands, monkeypatch, mode, allowed, action):
    e = plug_for(commands, monkeypatch, mode)
    notify = Mock()
    monkeypatch.setattr(switch.persistent_notification, "async_create", notify)
    if allowed:
        await getattr(e, action)()
        assert commands.publish.await_count == 1
        notify.assert_not_called()
    else:
        with pytest.raises(HomeAssistantError, match="commMode"):
            await getattr(e, action)()
        commands.publish.assert_not_awaited()
        notify.assert_called_once()
        assert notify.call_args.kwargs["title"] == "Jackery Smart Plug"
        assert notify.call_args.kwargs["notification_id"] == "jackery_plug_PLUG_mqtt_blocked"


async def test_latest_cached_commmode_wins_over_entity_snapshot(commands, monkeypatch):
    e = plug_for(commands, monkeypatch)
    monkeypatch.setattr(switch.persistent_notification, "async_create", Mock())
    receive(commands.c, 102, {"sn": "PLUG", "outPw": 15})
    assert e._plug_item()["commMode"] == 1
    e._raw_data["commMode"] = 2
    await e.async_turn_on()
    receive(commands.c, 102, {"sn": "PLUG", "commMode": 2})
    e._raw_data["commMode"] = 1
    with pytest.raises(HomeAssistantError):
        await e.async_turn_on()
    assert commands.publish.await_count == 1
    receive(commands.c, 102, {"sn": "PLUG", "commMode": 1})
    await e.async_turn_on()
    assert commands.publish.await_count == 2


@pytest.mark.parametrize("field", SWITCHES + list(number.NUMBERS) + ["autoStandby", "workModel", "reboot", "plug"])
async def test_publish_failure_propagates_and_real_telemetry_wins(commands, monkeypatch, field):
    if field == "plug":
        e = plug_for(commands, monkeypatch)
        invoke = e.async_turn_on
    else:
        e = entity_for(commands, field)
        receive(commands.c, 2, {field: 2 if field in ("autoStandby", "workModel") else 0, "workMode": 4})
        if field in SWITCHES:
            invoke = e.async_turn_on
        elif field in number.NUMBERS:
            invoke = partial(e.async_set_native_value, 70)
        elif field == "reboot":
            invoke = e.async_press
        else:
            invoke = partial(e.async_select_option, "standby" if field == "autoStandby" else "ai")
    commands.c._data_cache["unrelated"] = 91
    commands.publish.side_effect = HomeAssistantError("MQTT unavailable")
    with pytest.raises(HomeAssistantError, match="MQTT unavailable"):
        await invoke()
    assert commands.publish.await_count == 1
    if field in OPTIMISTIC_SWITCHES:
        assert commands.c._data_cache[field] == 1
    elif field in ("defaultPw", "maxOutPw", "maxFeedGrid"):
        assert commands.c._data_cache[field] == 70
    elif field in ("autoStandby", "workModel"):
        assert commands.c._data_cache[field] == (1 if field == "autoStandby" else 8)
    if field == "plug":
        assert e.is_on is False
        receive(commands.c, 102, {"sn": "PLUG", "sysSwitch": 1})
        assert e.is_on is True
    elif field != "reboot":
        receive(commands.c, 107, {field: 2 if field in ("autoStandby", "workModel") else 0, "workMode": 4})
        assert commands.c._data_cache[field] == (2 if field in ("autoStandby", "workModel") else 0)
        if field in SWITCHES:
            assert e.is_on is False
        elif field in number.NUMBERS:
            assert e.native_value == 0
    assert commands.c._data_cache["unrelated"] == 91


@pytest.mark.parametrize("token", ["", None])
async def test_controls_omit_empty_token_polls_include_it(commands, monkeypatch, token):
    commands.c._token = token
    await entity_for(commands, "reboot").async_press()
    assert_publish(commands, envelope(1, {"cmd": 5, "rc": 1, "reboot": 1}, token=None))
    receive(commands.c, 101, {"plugs": [{"sn": "PLUG", "devType": 6, "commMode": 1}]})
    await commands.c.async_control_subdevice_switch("PLUG", 6, False)
    assert_publish(commands, envelope(103, {"deviceSn": "PLUG", "devType": 6, "sysSwitch": 0}, token=None))
    monkeypatch.setattr(sensor_module, "asyncio", SimpleNamespace(sleep=AsyncMock()))
    await commands.c._send_poll_requests()
    assert "token" in json.loads(commands.publish.await_args.args[2])
    assert json.loads(commands.publish.await_args.args[2])["token"] == token


async def test_poll_payloads_cadence_pacing_and_message_id_reuse(commands, monkeypatch):
    sleep = AsyncMock()
    monkeypatch.setattr(sensor_module, "asyncio", SimpleNamespace(sleep=sleep))
    for cycle in range(4):
        commands.publish.reset_mock()
        await commands.c._send_poll_requests()
        expected = [(25, None), (2, None)]
        if cycle in (0, 3):
            expected.append((105, None))
        expected.extend((100, {"devType": t}) for t in (2, 3, 6))
        assert commands.publish.await_count == len(expected)
        for index, (kind, body) in enumerate(expected):
            assert_publish(commands, envelope(kind, body), index)
    assert sleep.await_count == 12
    assert all(call.args == (0.5,) for call in sleep.await_args_list)
    # Forced repeated RNG output is accepted: there is no correlation or dedup map.
    assert commands.randint.call_count == 22


@pytest.mark.parametrize("failed_devtype", [2, 3, 6])
async def test_type_100_publish_failure_isolated_per_child_category(
    commands, monkeypatch, caplog, failed_devtype
):
    async def fail_one_category(hass, topic, payload, qos, retain):
        data = json.loads(payload)
        if data["type"] == 100 and data["body"]["devType"] == failed_devtype:
            raise HomeAssistantError(f"synthetic devType {failed_devtype} failure")

    commands.publish.side_effect = fail_one_category
    sleep = AsyncMock()
    monkeypatch.setattr(sensor_module, "asyncio", SimpleNamespace(sleep=sleep))
    caplog.set_level(logging.DEBUG, logger="custom_components.jackery.sensor")

    await commands.c._send_poll_requests()

    attempted_devtypes = [
        data["body"]["devType"]
        for call in commands.publish.await_args_list
        if (data := json.loads(call.args[2]))["type"] == 100
    ]
    assert attempted_devtypes == [2, 3, 6]
    for index, dev_type in enumerate((2, 3, 6), start=3):
        assert_publish(commands, envelope(100, {"devType": dev_type}), index)
    assert sleep.await_count == 2
    assert all(call.args == (0.5,) for call in sleep.await_args_list)
    assert f"type-100 devType={failed_devtype}" in caplog.text
    assert f"synthetic devType {failed_devtype} failure" in caplog.text


async def test_type_100_poll_cancellation_propagates(commands, monkeypatch):
    async def cancel_devtype_3(hass, topic, payload, qos, retain):
        data = json.loads(payload)
        if data["type"] == 100 and data["body"]["devType"] == 3:
            raise asyncio.CancelledError

    commands.publish.side_effect = cancel_devtype_3
    sleep = AsyncMock()
    monkeypatch.setattr(sensor_module, "asyncio", SimpleNamespace(sleep=sleep))

    with pytest.raises(asyncio.CancelledError):
        await commands.c._send_poll_requests()

    attempted_devtypes = [
        data["body"]["devType"]
        for call in commands.publish.await_args_list
        if (data := json.loads(call.args[2]))["type"] == 100
    ]
    assert attempted_devtypes == [2, 3]
    sleep.assert_awaited_once_with(0.5)


@pytest.mark.parametrize("failed_type,failed_devtype,expected", [
    (25, None, [25, 2, 105, 100, 100, 100]),
    (2, None, [25, 2, 105, 100, 100, 100]),
    (105, None, [25, 2, 105, 100, 100, 100]),
])
async def test_poll_errors_are_logged_and_current_batch_boundaries_preserved(commands, monkeypatch, caplog,
                                                                           failed_type, failed_devtype, expected):
    async def fail(hass, topic, payload, qos, retain):
        data = json.loads(payload)
        if data["type"] == failed_type and (data["body"] or {}).get("devType") == failed_devtype:
            raise HomeAssistantError("synthetic publish failure")
    commands.publish.side_effect = fail
    monkeypatch.setattr(sensor_module, "asyncio", SimpleNamespace(sleep=AsyncMock()))
    caplog.set_level(logging.DEBUG, logger="custom_components.jackery.sensor")
    await commands.c._send_poll_requests()
    assert [json.loads(c.args[2])["type"] for c in commands.publish.await_args_list] == expected
    assert "synthetic publish failure" in caplog.text
    commands.publish.side_effect = None
    commands.publish.reset_mock()
    await commands.c._send_poll_requests()
    assert commands.publish.await_count == 5


async def test_missing_host_commands_and_poll_return_without_publish(commands, caplog):
    commands.c._device_sn = ""
    await commands.c.async_control_main_device({"reboot": 1})
    await commands.c.async_control_subdevice_switch("PLUG", 6, True)
    await commands.c._send_poll_requests()
    commands.publish.assert_not_awaited()
    assert "SN not discovered" in caplog.text


@pytest.mark.parametrize("platform", [switch, number, select, button])
async def test_platform_with_explicitly_missing_coordinator_skips_entities(commands, platform):
    commands.c.hass.data[DOMAIN]["command-entry"]["coordinator"] = None
    add = Mock()
    await platform.async_setup_entry(commands.c.hass, SimpleNamespace(entry_id="command-entry"), add)
    add.assert_not_called()


@pytest.mark.parametrize("platform", [switch, number, select, button])
async def test_absent_runtime_is_a_setup_error(commands, platform):
    add = Mock()
    with pytest.raises(KeyError):
        await platform.async_setup_entry(commands.c.hass, SimpleNamespace(entry_id="absent"), add)
    add.assert_not_called()


@pytest.mark.parametrize("field", ["swEps", "offGridDown", "isFollowMeterPw", "minSocChg", "maxSocChg"])
@pytest.mark.parametrize("bad", ["not-numeric", [], {}])
async def test_malformed_control_telemetry_does_not_block_other_entities(commands, field, bad, caplog):
    receive(commands.c, 2, {"swEps": 1, "offGridDown": 1, "isFollowMeterPw": 1,
                            "socChgLimit": 80, "workMode": 4, "autoStandby": 1})
    standby = entity_for(commands, "autoStandby")
    receive(commands.c, 107, {field: bad, "autoStandby": 2})
    assert standby.current_option == "on"
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert commands.c._data_cache[field] == bad  # raw evidence remains available
    if field in SWITCHES:
        assert entity_for(commands, field).is_on is True
    else:
        e = entity_for(commands, "socChgLimit")
        assert (e.native_min_value, e.native_max_value) == (50, 100)


@pytest.mark.parametrize("bad", ["not-numeric", [], {}])
async def test_malformed_plug_switch_value_does_not_abort_delivery(commands, monkeypatch, bad, caplog):
    e = plug_for(commands, monkeypatch)
    later = Mock()
    commands.c.register_sensor("later", later)
    receive(commands.c, 102, {"sn": "PLUG", "sysSwitch": bad})
    later._update_from_coordinator.assert_called_once()
    assert e.is_on is False
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
    receive(commands.c, 102, {"sn": "PLUG", "sysSwitch": "1"})
    assert e.is_on is True


@pytest.mark.parametrize("field", list(number.NUMBERS))
@pytest.mark.parametrize("boundary", ["below", "above", "min", "max", "fractional"])
async def test_ha_number_service_owns_range_validation(commands, field, boundary):
    e = entity_for(commands, field)
    e.entity_id = "number.synthetic"
    cfg = number.NUMBERS[field]
    value = {"below": cfg["min"] - 1, "above": cfg["max"] + 1,
             "min": cfg["min"], "max": cfg["max"], "fractional": cfg["min"] + 0.9}[boundary]
    call = ServiceCall(commands.c.hass, "number", "set_value", {"value": value})
    if boundary in ("below", "above"):
        with pytest.raises(ServiceValidationError):
            await async_set_value(e, call)
        commands.publish.assert_not_awaited()
    else:
        await async_set_value(e, call)
        assert_publish(commands, envelope(1, {"cmd": 5, "rc": 1, field: int(value)}))
