"""Regression tests for Jackery cloud firmware parsing, polling, and setup."""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from unittest.mock import AsyncMock, Mock, patch

import pytest

from custom_components.jackery.cloud_firmware import CloudFirmwareMonitor
from custom_components.jackery.protocol.ota import (
    OtaFirmwareStatus,
    OtaResponseError,
    parse_ota_list_response,
)
from custom_components.jackery.transport.jackery_cloud import (
    JackeryCloudError,
    JackeryCloudFirmwareTransport,
    build_login_envelope,
    derive_mac_id,
)


class _MemoryStore:
    """Small storage fake for monitor tests without HA disk/executor fixtures."""

    def __init__(self, *_args) -> None:
        self.data = {}

    async def async_load(self):
        return self.data

    async def async_save(self, data):
        self.data = dict(data)


@pytest.fixture
def hass(monkeypatch):
    """Replace only the HA session and storage edges used by the monitor."""
    fake_hass = object()
    monkeypatch.setattr(
        "custom_components.jackery.cloud_firmware.async_get_clientsession",
        lambda _hass: object(),
    )
    monkeypatch.setattr("custom_components.jackery.cloud_firmware.Store", _MemoryStore)
    monkeypatch.setattr(
        "custom_components.jackery.cloud_firmware.persistent_notification.async_create",
        Mock(),
    )
    monkeypatch.setattr(
        "custom_components.jackery.cloud_firmware.persistent_notification.async_dismiss",
        Mock(),
    )
    return fake_hass


def _row(serial: str, status: int | str | None, *, current: str = "1.6.0", target: str | None = None):
    return {
        "deviceSn": serial,
        "currentVersion": current,
        "targetVersion": target,
        "updateStatus": status,
        "targetVersionId": None,
    }


@pytest.mark.parametrize(
    ("code", "label", "available"),
    [
        (0, "update_available", True),
        (1, "downloading", False),
        (2, "installing", False),
        (6, "no_update", False),
        (3, "unknown", False),
        (4, "unknown", False),
        (5, "unknown", False),
        (1007, "unknown", False),
        (1008, "unknown", False),
        ("0", "unknown", False),
        (None, "unknown", False),
    ],
)
def test_update_status_uses_only_app_verified_list_values(code, label, available):
    status = parse_ota_list_response({"code": 0, "data": [_row("HOST1234", code)]}, "HOST1234")

    assert status.update_state == label
    assert status.update_available is available


def test_status_zero_is_authoritative_even_when_version_strings_match():
    status = parse_ota_list_response(
        {"code": 0, "data": [_row("HOST1234", 0, current="1.6.0", target="1.6.0")]},
        "HOST1234",
    )

    assert status.update_available is True


@pytest.mark.parametrize(
    ("document", "serial", "reason"),
    [
        ({"code": 1, "data": []}, "HOST1234", "api_rejected"),
        ({"code": 0, "data": []}, "HOST1234", "device_match_not_unique"),
        ({"code": 0, "data": [_row("HOST1234", 6), _row("HOST1234", 6)]}, "HOST1234", "device_match_not_unique"),
        ({"code": 0, "data": [_row("OTHER123", 6)]}, "HOST1234", "device_match_not_unique"),
    ],
)
def test_parser_requires_exactly_one_successful_device_row(document, serial, reason):
    with pytest.raises(OtaResponseError, match=reason):
        parse_ota_list_response(document, serial)


def test_parser_preserves_null_target_and_unknown_status():
    status = parse_ota_list_response(
        {"code": 0, "data": [_row("BATTERY1", 3, target=None)]},
        "BATTERY1",
    )

    assert status.current_version == "1.6.0"
    assert status.target_version is None
    assert status.app_display_target_version == "1.6.0"
    assert status.update_status == 3
    assert status.update_state == "unknown"


def test_account_mac_id_matches_existing_poc_algorithm():
    account = "user@example.com"
    digest = hashlib.md5(account.encode("utf-8"), usedforsecurity=False).digest()

    assert derive_mac_id(f"  {account}  ") == "2" + uuid.UUID(bytes=digest, version=3).hex
    assert derive_mac_id(account) == "2b58996c504c5338798eb6b511e6f49af"


def test_login_envelope_contains_only_encrypted_fields():
    envelope = build_login_envelope("user@example.com", "not-a-real-password", "DE")

    assert set(envelope) == {"aesEncryptData", "rsaForAesKey"}
    assert "not-a-real-password" not in json.dumps(envelope)
    assert len(envelope["aesEncryptData"]) > 32
    assert len(envelope["rsaForAesKey"]) > 32


class _FakeContent:
    def __init__(self, value: bytes) -> None:
        self.value = value

    async def read(self, size: int) -> bytes:
        return self.value[:size]


class _FakeResponse:
    def __init__(self, value: dict | bytes, *, status: int = 200) -> None:
        self.status = status
        self.content = _FakeContent(
            value if isinstance(value, bytes) else json.dumps(value).encode()
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None


class _FakeSession:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self.responses = responses
        self.requests: list[tuple[str, str, dict]] = []

    def request(self, method: str, url: str, **kwargs):
        self.requests.append((method, url, kwargs))
        return self.responses.pop(0)


async def test_transport_logs_in_once_and_gets_each_serial_separately():
    session = _FakeSession(
        [
            _FakeResponse({"code": 0, "token": "session-1"}),
            _FakeResponse({"code": 0, "token": "session-2", "data": [_row("HOST1234", 6)]}),
            _FakeResponse({"code": 0, "data": [_row("BATTERY1", 0, target="1.7.0")]}),
        ]
    )
    client = JackeryCloudFirmwareTransport(session)  # type: ignore[arg-type]

    await client.async_login("user@example.com", "secret", "DE")
    host = await client.async_get_firmware("HOST1234")
    battery = await client.async_get_firmware("BATTERY1")

    assert [request[0] for request in session.requests] == ["POST", "GET", "GET"]
    assert session.requests[1][2]["params"] == {"deviceSnList": "HOST1234"}
    assert session.requests[2][2]["params"] == {"deviceSnList": "BATTERY1"}
    assert session.requests[1][2]["headers"]["token"] == "session-1"
    assert session.requests[2][2]["headers"]["token"] == "session-2"
    assert all(request[2]["allow_redirects"] is False for request in session.requests)
    assert host.update_status == 6
    assert battery.update_available is True
    assert battery.target_version == "1.7.0"


async def test_transport_rejects_oversized_response():
    session = _FakeSession([_FakeResponse(b"x" * (4 * 1024 * 1024 + 1))])
    client = JackeryCloudFirmwareTransport(session)  # type: ignore[arg-type]

    with pytest.raises(JackeryCloudError, match="response_too_large"):
        await client._async_request("GET", "device/ota/list")


class _FakeFirmwareTransport:
    def __init__(self, results: dict[str, OtaFirmwareStatus | Exception]) -> None:
        self.results = results
        self.login_calls: list[tuple[str, str, str]] = []
        self.serial_calls: list[str] = []

    async def async_login(self, account: str, password: str, region: str) -> None:
        self.login_calls.append((account, password, region))

    async def async_get_firmware(self, serial: str) -> OtaFirmwareStatus:
        self.serial_calls.append(serial)
        result = self.results[serial]
        if isinstance(result, Exception):
            raise result
        return result


def _status(serial: str, update_status: int, *, target: str | None = None) -> OtaFirmwareStatus:
    return OtaFirmwareStatus(
        serial=serial,
        current_version="1.6.0",
        target_version=target,
        update_status=update_status,
        target_version_id=None,
    )


async def test_monitor_queries_host_and_each_known_battery_independently(hass):
    transport = _FakeFirmwareTransport(
        {
            "BATTERY1": _status("BATTERY1", 6),
            "BATTERY2": _status("BATTERY2", 0, target="1.7.0"),
            "HOST1234": _status("HOST1234", 6),
        }
    )
    monitor = CloudFirmwareMonitor(
        hass,
        "entry-1",
        "account@example.com",
        "secret",
        "DE",
        "HOST1234",
        transport_factory=lambda _session: transport,  # type: ignore[arg-type]
    )
    monitor._notification_store.async_save = AsyncMock()
    monitor.set_expansion_serials({"BATTERY2", "BATTERY1"})

    with patch("custom_components.jackery.cloud_firmware.persistent_notification.async_create") as create:
        await monitor.async_poll_once()

    assert transport.login_calls == [("account@example.com", "secret", "DE")]
    assert transport.serial_calls == ["BATTERY1", "BATTERY2", "HOST1234"]
    assert monitor.get_observation("BATTERY1").available
    assert monitor.get_observation("BATTERY2").status.update_available
    assert create.call_count == 1


async def test_monitor_failure_for_one_serial_does_not_stop_later_queries(hass):
    transport = _FakeFirmwareTransport(
        {
            "BATTERY1": JackeryCloudError("api_rejected"),
            "HOST1234": _status("HOST1234", 6),
        }
    )
    monitor = CloudFirmwareMonitor(
        hass,
        "entry-2",
        "account@example.com",
        "secret",
        "DE",
        "HOST1234",
        transport_factory=lambda _session: transport,  # type: ignore[arg-type]
    )
    monitor.set_expansion_serials({"BATTERY1"})

    await monitor.async_poll_once()

    assert transport.serial_calls == ["BATTERY1", "HOST1234"]
    assert not monitor.get_observation("BATTERY1").available
    assert monitor.get_observation("BATTERY1").error == "api_rejected"
    assert monitor.get_observation("HOST1234").available


async def test_monitor_deduplicates_offers_until_status_returns_to_no_update(hass):
    offered = _status("HOST1234", 0, target="1.7.0")
    transport = _FakeFirmwareTransport({"HOST1234": offered})
    monitor = CloudFirmwareMonitor(
        hass,
        "entry-3",
        "account@example.com",
        "secret",
        "DE",
        "HOST1234",
        transport_factory=lambda _session: transport,  # type: ignore[arg-type]
    )
    monitor._notification_store.async_save = AsyncMock()

    with (
        patch("custom_components.jackery.cloud_firmware.persistent_notification.async_create") as create,
        patch("custom_components.jackery.cloud_firmware.persistent_notification.async_dismiss") as dismiss,
    ):
        await monitor.async_poll_once()
        await monitor.async_poll_once()
        assert create.call_count == 1

        transport.results["HOST1234"] = _status("HOST1234", 6)
        await monitor.async_poll_once()
        assert dismiss.call_count == 1

        transport.results["HOST1234"] = offered
        await monitor.async_poll_once()
        assert create.call_count == 2


async def test_monitor_task_stops_cleanly(hass):
    transport = _FakeFirmwareTransport({"HOST1234": _status("HOST1234", 6)})
    monitor = CloudFirmwareMonitor(
        hass,
        "entry-4",
        "account@example.com",
        "secret",
        "DE",
        "HOST1234",
        transport_factory=lambda _session: transport,  # type: ignore[arg-type]
    )
    monitor._notification_store.async_load = AsyncMock(return_value={})

    await monitor.async_start()
    await asyncio.sleep(0)
    task = monitor._task
    await monitor.async_stop()

    assert task is not None and task.done()
    assert transport.serial_calls == ["HOST1234"]
