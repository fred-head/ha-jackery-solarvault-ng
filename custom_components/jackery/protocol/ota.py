"""Parsing helpers for Jackery's read-only cloud OTA list endpoint."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_SERIAL_RE = re.compile(r"[A-Za-z0-9_-]{4,64}\Z")


class OtaResponseError(ValueError):
    """The cloud OTA response cannot be safely matched to one device."""


@dataclass(frozen=True, slots=True)
class OtaFirmwareStatus:
    """Allowlisted OTA fields for one exact device serial number."""

    serial: str
    current_version: str | int | float | None
    target_version: str | int | float | None
    update_status: str | int | float | None
    target_version_id: str | int | float | None

    @property
    def update_available(self) -> bool:
        """Return true only for the app-confirmed UPDATE_STATE_HAVE value."""
        return type(self.update_status) is int and self.update_status == 0

    @property
    def app_display_target_version(self) -> str | int | float | None:
        """Mirror the app's target-label fallback while retaining the raw API value."""
        if self.target_version is None or self.target_version == "":
            return self.current_version
        return self.target_version

    @property
    def update_state(self) -> str:
        """Describe the four states explicitly handled by the app callback."""
        if type(self.update_status) is not int:
            return "unknown"
        return {
            0: "update_available",
            1: "downloading",
            2: "installing",
            6: "no_update",
        }.get(self.update_status, "unknown")


def validate_device_serial(serial: str) -> str:
    """Validate a serial before placing it in the cloud API query string."""
    if not isinstance(serial, str) or not _SERIAL_RE.fullmatch(serial):
        raise OtaResponseError("invalid_serial")
    return serial


def _simple_value(value: Any) -> str | int | float | None:
    """Retain scalar API values without interpreting firmware version strings."""
    if value is None:
        return value
    if isinstance(value, str):
        return value if len(value) <= 128 and value.isprintable() else None
    if type(value) is int:
        return value
    if type(value) is float:
        return value if value == value and abs(value) != float("inf") else None
    return None


def parse_ota_list_response(document: Any, serial: str) -> OtaFirmwareStatus:
    """Require a successful response with exactly one matching device row."""
    validate_device_serial(serial)
    if not isinstance(document, dict) or type(document.get("code")) is not int:
        raise OtaResponseError("invalid_api_response")
    if document["code"] != 0:
        raise OtaResponseError("api_rejected")

    rows = document.get("data")
    if not isinstance(rows, list):
        raise OtaResponseError("missing_device_rows")
    matches = [row for row in rows if isinstance(row, dict) and row.get("deviceSn") == serial]
    if len(matches) != 1:
        raise OtaResponseError("device_match_not_unique")

    row = matches[0]
    return OtaFirmwareStatus(
        serial=serial,
        current_version=_simple_value(row.get("currentVersion")),
        target_version=_simple_value(row.get("targetVersion")),
        update_status=_simple_value(row.get("updateStatus")),
        target_version_id=_simple_value(row.get("targetVersionId")),
    )
