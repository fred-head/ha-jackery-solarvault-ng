"""Read-only Jackery cloud transport used by optional firmware monitoring."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import uuid
from typing import Any

import aiohttp

from ..protocol.ota import OtaFirmwareStatus, OtaResponseError, parse_ota_list_response, validate_device_serial

API_BASE_URL = "https://iot.jackeryapp.com/v1/"
LOGIN_ENDPOINT = "auth/login"
OTA_LIST_ENDPOINT = "device/ota/list"
MAX_API_RESPONSE_BYTES = 4 * 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 30

# Public app key from the existing, read-only firmware POC. Jackery's login
# endpoint requires this envelope; credentials themselves are AES encrypted.
_RSA_KEY_B64 = (
    "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQCVmzgJy/4XolxPnkfu32YtJqYG"
    "FLYqf9/rnVgURJED+8J9J3Pccd6+9L97/+7COZE5OkejsgOkqeLNC9C3r5mhpE4z"
    "k/HStss7Q8/5DqkGD1annQ+eoICo3oi0dITZ0Qll56Dowb8lXi6WHViVDdih/oeUw"
    "VJY89uJNtTWrz7t7QIDAQAB"
)
_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "de-DE",
    "platform": "2",
    "app_version": "v2.4.1",
    "app_version_code": "100",
    "sys_version": "Android 16,level 36/[arm64-v8a, armeabi-v7a, armeabi]",
    "device_model": "samsung/SM-S918B",
    "network": "wifi",
    "User-Agent": "okhttp/5.3.2",
}


class JackeryCloudError(RuntimeError):
    """Sanitized transport, authentication, or API failure."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def derive_mac_id(account: str) -> str:
    """Reproduce the POC's stable account-derived Jackery API client ID."""
    account = account.strip()
    if not account or len(account) > 1024:
        raise JackeryCloudError("invalid_account")
    digest = hashlib.md5(account.encode("utf-8"), usedforsecurity=False).digest()
    return "2" + uuid.UUID(bytes=digest, version=3).hex


def _compact_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def build_login_envelope(account: str, password: str, region: str) -> dict[str, str]:
    """Encrypt the Jackery mobile-app login fields in the established envelope."""
    try:
        from cryptography.hazmat.primitives import padding, serialization
        from cryptography.hazmat.primitives.asymmetric import padding as rsa_padding
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    except ImportError as error:  # pragma: no cover - manifest installs this dependency
        raise JackeryCloudError("crypto_dependency_missing") from error

    plain = {
        "account": account.strip(),
        "loginType": 2,
        "macId": derive_mac_id(account),
        "password": password,
        "regionCode": region.upper(),
        "registerAppId": "com.hbxn.jackery",
    }
    # The mobile app base64-encodes 16 random bytes and uses the resulting ASCII
    # key with AES-ECB/PKCS7 before wrapping that key with RSA PKCS#1 v1.5.
    aes_key = base64.b64encode(os.urandom(16)).decode("ascii")
    padder = padding.PKCS7(128).padder()
    padded = padder.update(_compact_json(plain)) + padder.finalize()
    encryptor = Cipher(algorithms.AES(aes_key.encode("ascii")), modes.ECB()).encryptor()
    aes_data = base64.b64encode(encryptor.update(padded) + encryptor.finalize()).decode("ascii")
    public_key = serialization.load_der_public_key(base64.b64decode(_RSA_KEY_B64))
    if not isinstance(public_key, rsa.RSAPublicKey):
        raise JackeryCloudError("invalid_api_public_key")
    rsa_data = base64.b64encode(
        public_key.encrypt(aes_key.encode("ascii"), rsa_padding.PKCS1v15())
    ).decode("ascii")
    return {"aesEncryptData": aes_data, "rsaForAesKey": rsa_data}


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise ValueError("non-finite JSON value")


class JackeryCloudFirmwareTransport:
    """Authenticate once, then issue one fixed OTA-list GET per device serial."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session
        self._token: str | None = None

    async def async_login(self, account: str, password: str, region: str) -> None:
        """Authenticate without logging or persisting account credentials."""
        envelope = build_login_envelope(account, password, region)
        document = await self._async_request("POST", LOGIN_ENDPOINT, data=envelope)
        token = document.get("token")
        if type(document.get("code")) is not int or document["code"] != 0:
            raise JackeryCloudError("login_rejected")
        if not isinstance(token, str) or not token:
            raise JackeryCloudError("login_missing_token")
        self._token = token

    async def async_get_firmware(self, serial: str) -> OtaFirmwareStatus:
        """Fetch and match one device; serials are never batched into this GET."""
        validate_device_serial(serial)
        if not self._token:
            raise JackeryCloudError("not_authenticated")
        document = await self._async_request(
            "GET",
            OTA_LIST_ENDPOINT,
            params={"deviceSnList": serial},
        )
        refreshed_token = document.get("token")
        if isinstance(refreshed_token, str) and refreshed_token:
            self._token = refreshed_token
        try:
            return parse_ota_list_response(document, serial)
        except OtaResponseError as error:
            raise JackeryCloudError(error.args[0]) from error

    async def _async_request(
        self,
        method: str,
        endpoint: str,
        *,
        data: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        headers = dict(_HEADERS)
        if data is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded; charset=utf-8"
        if self._token:
            headers["token"] = self._token

        try:
            async with self._session.request(
                method,
                API_BASE_URL + endpoint,
                data=data,
                params=params,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS),
                allow_redirects=False,
            ) as response:
                if response.status != 200:
                    raise JackeryCloudError("http_error")
                raw = await response.content.read(MAX_API_RESPONSE_BYTES + 1)
        except JackeryCloudError:
            raise
        except (aiohttp.ClientError, TimeoutError, OSError) as error:
            raise JackeryCloudError("transport_error") from error

        if len(raw) > MAX_API_RESPONSE_BYTES:
            raise JackeryCloudError("response_too_large")
        try:
            document = json.loads(
                raw.decode("utf-8"),
                object_pairs_hook=_unique_object,
                parse_constant=_reject_constant,
            )
        except (UnicodeDecodeError, ValueError, RecursionError) as error:
            raise JackeryCloudError("invalid_json") from error
        if not isinstance(document, dict):
            raise JackeryCloudError("invalid_api_response")
        return document
