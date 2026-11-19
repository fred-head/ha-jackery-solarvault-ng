"""Direct contracts for pure outbound Jackery command builders."""

from copy import deepcopy

import pytest

from custom_components.jackery.protocol.commands import (
    action_topic,
    build_full_state_request,
    build_main_control,
    build_settings_request,
    build_status_request,
    build_subdevice_request,
    build_subdevice_switch,
)


def test_action_topic_preserves_root_and_host() -> None:
    assert action_topic("custom/hb", "HOST_A") == "custom/hb/device/HOST_A/action"


@pytest.mark.parametrize("token", ["secret", "", None])
def test_main_control_exact_payload_and_token_semantics(token: str | None) -> None:
    params = {"reboot": 1}
    before = deepcopy(params)

    payload = build_main_control(
        message_id=4321,
        timestamp=1700000000,
        token=token,
        params=params,
    )

    assert payload == {
        "type": 1,
        "eventId": 3,
        "messageId": 4321,
        "ts": 1700000000,
        "body": {"cmd": 5, "rc": 1, "reboot": 1},
        **({"token": token} if token else {}),
    }
    assert params == before


def test_main_control_preserves_params_merge_precedence() -> None:
    assert build_main_control(
        message_id=1,
        timestamp=2,
        token="token",
        params={"cmd": "caller", "rc": 0},
    )["body"] == {"cmd": "caller", "rc": 0}


@pytest.mark.parametrize("is_on,wire_value", [(False, 0), (True, 1)])
@pytest.mark.parametrize("token", ["secret", "", None])
def test_subdevice_switch_exact_payload(
    token: str | None, is_on: bool, wire_value: int
) -> None:
    payload = build_subdevice_switch(
        message_id=9876,
        timestamp=1700000001,
        token=token,
        device_serial="PLUG_A",
        device_type=6,
        is_on=is_on,
    )

    assert payload == {
        "type": 103,
        "eventId": 0,
        "messageId": 9876,
        "ts": 1700000001,
        "body": {"deviceSn": "PLUG_A", "devType": 6, "sysSwitch": wire_value},
        **({"token": token} if token else {}),
    }


@pytest.mark.parametrize(
    "builder,message_type",
    [
        (build_status_request, 25),
        (build_settings_request, 2),
        (build_full_state_request, 105),
    ],
)
@pytest.mark.parametrize("token", ["secret", "", None])
def test_host_requests_preserve_token_and_null_body(builder, message_type, token) -> None:
    assert builder(message_id=1234, timestamp=1700000002, token=token) == {
        "type": message_type,
        "eventId": 0,
        "messageId": 1234,
        "ts": 1700000002,
        "token": token,
        "body": None,
    }


@pytest.mark.parametrize("device_type", [2, 3, 6])
@pytest.mark.parametrize("token", ["secret", "", None])
def test_subdevice_request_exact_payload(device_type: int, token: str | None) -> None:
    assert build_subdevice_request(
        message_id=2468,
        timestamp=1700000003,
        token=token,
        device_type=device_type,
    ) == {
        "type": 100,
        "eventId": 0,
        "messageId": 2468,
        "ts": 1700000003,
        "token": token,
        "body": {"devType": device_type},
    }
