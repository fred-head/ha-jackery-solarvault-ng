"""Passive, bounded runtime observations for future diagnostics adapters.

This module owns no operational decisions. Coordinators report events after or
at existing decision points, and consumers receive immutable copied snapshots.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum

MAX_OBSERVATION_COUNT = 2_147_483_647


class HttpOutcome(StrEnum):
    """Fixed result categories for one SmartMeter HTTP poll iteration."""

    UNKNOWN = "unknown"
    NO_TARGET = "no_target"
    SUCCESS = "success"
    TIMEOUT = "timeout"
    CLIENT_ERROR = "client_error"
    HTTP_STATUS_ERROR = "http_status_error"
    INVALID_JSON = "invalid_json"
    INVALID_PAYLOAD = "invalid_payload"
    UNEXPECTED_ERROR = "unexpected_error"


class HttpHealth(StrEnum):
    """Bounded diagnostic interpretation of the mirrored HTTP policy state."""

    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class HttpReplacementState(StrEnum):
    """Last observed target-selection transition."""

    UNKNOWN = "unknown"
    INITIAL = "initial"
    UNCHANGED = "unchanged"
    REPLACED = "replaced"


class ProtocolRouteBucket(StrEnum):
    """Fixed accepted-message buckets with bounded cardinality."""

    TYPE_23 = "type_23"
    TYPE_101 = "type_101"
    TYPE_102 = "type_102"
    TYPE_106 = "type_106"
    TYPE_107 = "type_107"
    TYPE_123 = "type_123"
    GENERIC_KNOWN = "generic_known"
    GENERIC_UNKNOWN = "generic_unknown"


class ProtocolErrorBucket(StrEnum):
    """Fixed rejection/failure buckets from coordinator orchestration."""

    INVALID_TOPIC = "invalid_topic"
    FOREIGN_HOST = "foreign_host"
    INVALID_JSON = "invalid_json"
    INVALID_ENVELOPE = "invalid_envelope"
    HANDLER_ERROR = "handler_error"


@dataclass(frozen=True, slots=True)
class HttpObservationSnapshot:
    """Immutable copy of mirrored SmartMeter HTTP observations.

    ``target_identifier`` is an internal relation for the future P3.3 adapter.
    It is not export-safe and must pass through P3.1 snapshot-local aliasing.
    """

    last_attempt_at: float | None
    last_success_at: float | None
    consecutive_failures: int
    last_outcome: str
    target_identifier: str | None
    replacement_state: str
    health: str


@dataclass(frozen=True, slots=True)
class ProtocolObservationSnapshot:
    """Immutable copied protocol counters."""

    route_counters: tuple[tuple[str, int], ...]
    error_counters: tuple[tuple[str, int], ...]
    unknown_message_count: int


@dataclass(frozen=True, slots=True)
class DiagnosticsObservationSnapshot:
    """Read-only P3.2 view for the future Home Assistant adapter."""

    http: HttpObservationSnapshot
    protocol: ProtocolObservationSnapshot


def _increment(counter: dict[str, int], key: str) -> None:
    counter[key] = min(counter.get(key, 0) + 1, MAX_OBSERVATION_COUNT)


def _timestamp(value: float) -> float | None:
    if type(value) not in (int, float):
        return None
    result = float(value)
    return result if result >= 0 and math.isfinite(result) else None


@dataclass(slots=True)
class DiagnosticsObservationState:
    """Per-coordinator passive observations with no operational authority."""

    _route_counters: dict[str, int] = field(default_factory=dict)
    _error_counters: dict[str, int] = field(default_factory=dict)
    _unknown_message_count: int = 0
    _http_last_attempt_at: float | None = None
    _http_last_success_at: float | None = None
    _http_consecutive_failures: int = 0
    _http_last_outcome: HttpOutcome = HttpOutcome.UNKNOWN
    _http_target_identifier: str | None = None
    _http_last_target_identifier: str | None = None
    _http_replacement_state: HttpReplacementState = HttpReplacementState.UNKNOWN
    _http_health: HttpHealth = HttpHealth.UNKNOWN

    def record_protocol_route(
        self,
        bucket: ProtocolRouteBucket,
        *,
        unknown_message_type: bool = False,
    ) -> None:
        """Count one message after its existing pipeline completed successfully."""
        _increment(self._route_counters, bucket.value)
        if unknown_message_type:
            self._unknown_message_count = min(
                self._unknown_message_count + 1,
                MAX_OBSERVATION_COUNT,
            )

    def record_protocol_error(self, bucket: ProtocolErrorBucket) -> None:
        """Count one message rejected or failed at an existing pipeline boundary."""
        _increment(self._error_counters, bucket.value)

    def observe_http_target(self, identifier: str | None) -> None:
        """Mirror the current target and retain only its last selection transition."""
        valid_identifier = (
            identifier
            if isinstance(identifier, str) and 0 < len(identifier) <= 256
            else None
        )
        self._http_target_identifier = valid_identifier
        if valid_identifier is None:
            return
        if self._http_last_target_identifier is None:
            self._http_replacement_state = HttpReplacementState.INITIAL
        elif valid_identifier != self._http_last_target_identifier:
            self._http_replacement_state = HttpReplacementState.REPLACED
        else:
            self._http_replacement_state = HttpReplacementState.UNCHANGED
        self._http_last_target_identifier = valid_identifier

    def record_http_attempt(self, now: float) -> None:
        """Record the receipt clock immediately before an existing HTTP request."""
        timestamp = _timestamp(now)
        if timestamp is not None:
            self._http_last_attempt_at = timestamp

    def record_http_outcome(
        self,
        outcome: HttpOutcome,
        *,
        now: float,
        consecutive_failures: int,
        failure_threshold: int,
    ) -> None:
        """Mirror one completed loop outcome and its authoritative local counter."""
        failures = (
            consecutive_failures
            if type(consecutive_failures) is int and consecutive_failures >= 0
            else 0
        )
        threshold = failure_threshold if type(failure_threshold) is int and failure_threshold > 0 else 1
        self._http_consecutive_failures = min(failures, MAX_OBSERVATION_COUNT)
        self._http_last_outcome = outcome
        timestamp = _timestamp(now)
        if outcome is HttpOutcome.SUCCESS:
            if timestamp is not None:
                self._http_last_success_at = timestamp
            self._http_health = HttpHealth.HEALTHY
        elif failures >= threshold:
            self._http_health = HttpHealth.UNAVAILABLE
        elif failures > 0 or outcome is HttpOutcome.UNEXPECTED_ERROR:
            self._http_health = HttpHealth.DEGRADED
        else:
            self._http_health = HttpHealth.UNKNOWN

    def snapshot(self) -> DiagnosticsObservationSnapshot:
        """Return an immutable copy without exposing mutable internal mappings."""
        return DiagnosticsObservationSnapshot(
            http=HttpObservationSnapshot(
                last_attempt_at=self._http_last_attempt_at,
                last_success_at=self._http_last_success_at,
                consecutive_failures=self._http_consecutive_failures,
                last_outcome=self._http_last_outcome.value,
                target_identifier=self._http_target_identifier,
                replacement_state=self._http_replacement_state.value,
                health=self._http_health.value,
            ),
            protocol=ProtocolObservationSnapshot(
                route_counters=tuple(sorted(self._route_counters.items())),
                error_counters=tuple(sorted(self._error_counters.items())),
                unknown_message_count=self._unknown_message_count,
            ),
        )


__all__ = [
    "MAX_OBSERVATION_COUNT",
    "DiagnosticsObservationSnapshot",
    "DiagnosticsObservationState",
    "HttpHealth",
    "HttpObservationSnapshot",
    "HttpOutcome",
    "HttpReplacementState",
    "ProtocolErrorBucket",
    "ProtocolObservationSnapshot",
    "ProtocolRouteBucket",
]
