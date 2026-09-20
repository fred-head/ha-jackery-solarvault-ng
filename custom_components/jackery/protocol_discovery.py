"""Bounded, value-free structural observation for opt-in protocol discovery.

The state in this module is deliberately unable to retain raw field names or
scalar values.  It records only code-owned path tokens, JSON type/count shapes,
safe numeric protocol identifiers and bounded occurrence metadata.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import islice
from typing import Any, Final

OPTION_PROTOCOL_DISCOVERY_ENABLED: Final = "protocol_discovery_enabled"

DISCOVERY_VERSION: Final = 1
MAX_COUNTER: Final = 2_147_483_647
MAX_SAFE_PROTOCOL_INTEGER: Final = 65_535
MAX_MESSAGE_TYPE_BUCKETS: Final = 32
MAX_DEVICE_TYPE_BUCKETS: Final = 64
MAX_STRUCTURAL_SIGNATURES: Final = 64
MAX_MAPPING_ENTRIES: Final = 64
MAX_ARRAY_ITEMS: Final = 16
MAX_STRUCTURAL_DEPTH: Final = 3
MAX_NESTED_SHAPES: Final = 16
DISCOVERY_DETAIL_BUDGET_BYTES: Final = 8 * 1024

_KNOWN_MESSAGE_TYPES: Final = frozenset({2, 23, 25, 101, 102, 106, 107, 123})
_CHILD_ARRAY_KEYS: Final = (
    "plugs",
    "plug",
    "socket",
    "sockets",
    "cts",
    "ct",
    "collectors",
)
_KNOWN_ENVELOPE_FIELDS: Final = frozenset(
    {"type", "body", "eventId", "messageId", "ts", "deviceType", "token", "softver"}
)
_KNOWN_PAYLOAD_FIELDS: Final = frozenset(
    {
        "type", "deviceSn", "sn", "deviceType", "devType", "subType",
        "softver", "errorCode", "plugs", "plug", "socket", "sockets",
        "cts", "ct", "collectors", "batSoc", "soc", "pvPw", "pv1",
        "pv2", "pv3", "pv4", "batInPw", "batOutPw", "gridInPw",
        "gridOutPw", "gridBuyPw", "gridSellPw", "inGridSidePw",
        "outGridSidePw", "inOngridPw", "outOngridPw", "swEpsInPw",
        "swEpsOutPw", "stackInPw", "stackOutPw", "otherLoadPw", "stat",
        "workMode", "workModel", "funcEnable", "commMode", "commState",
        "switchSta", "sysSwitch", "totalEgy", "inPw", "outPw", "power",
        "aPhasePw", "bPhasePw", "cPhasePw", "tPhasePw", "anPhasePw",
        "bnPhasePw", "cnPhasePw", "tnPhasePw", "AphasePw", "BphasePw",
        "CphasePw", "TphasePw", "aPhaseEgy", "bPhaseEgy", "cPhaseEgy",
        "tPhaseEgy", "anPhaseEgy", "bnPhaseEgy", "cnPhaseEgy", "tnPhaseEgy",
        "AphaseEgy", "BphaseEgy", "CphaseEgy", "TphaseEgy", "schePhase",
        "funForm", "wip", "name", "scanName",
    }
)
_KNOWN_CHILD_FIELDS: Final = frozenset(
    {
        "deviceSn", "sn", "devType", "subType", "commMode", "commState",
        "switchSta", "sysSwitch", "totalEgy", "inPw", "outPw", "power",
        "aPhasePw", "bPhasePw", "cPhasePw", "tPhasePw", "anPhasePw",
        "bnPhasePw", "cnPhasePw", "tnPhasePw", "AphasePw", "BphasePw",
        "CphasePw", "TphasePw", "aPhaseEgy", "bPhaseEgy", "cPhaseEgy",
        "tPhaseEgy", "anPhaseEgy", "bnPhaseEgy", "cnPhaseEgy", "tnPhaseEgy",
        "AphaseEgy", "BphaseEgy", "CphaseEgy", "TphaseEgy", "schePhase",
        "funForm", "wip", "name", "scanName", "batSoc", "soc", "batInPw",
        "batOutPw", "temp", "softver",
    }
)
_EXPECTED_ENVELOPE_TYPES: Final = {"type": "integer", "body": "object"}
_EXPECTED_CHILD_TYPES: Final = {
    "deviceSn": "string",
    "sn": "string",
    "devType": "integer",
    "subType": "integer",
}


def _saturating_add(value: int, increment: int = 1) -> int:
    return min(MAX_COUNTER, value + max(0, increment))


def _json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, Mapping):
        return "object"
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return "array"
    return "unsupported"


def _safe_protocol_integer(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if 0 <= value <= MAX_SAFE_PROTOCOL_INTEGER:
        return value
    return None


def _shape(value: Any, *, depth: int) -> tuple[str, int]:
    """Return a bounded value-free container shape and dropped-item count."""
    kind = _json_type(value)
    if kind not in {"object", "array"} or depth >= MAX_STRUCTURAL_DEPTH:
        dropped = len(value) if kind in {"object", "array"} else 0
        return kind, dropped

    if kind == "object":
        mapping = value
        sample = list(islice(mapping.values(), MAX_MAPPING_ENTRIES))
        dropped = max(0, len(mapping) - len(sample))
    else:
        sequence = value
        sample = list(islice(sequence, MAX_ARRAY_ITEMS))
        dropped = max(0, len(sequence) - len(sample))

    children: list[str] = []
    for child in sample:
        child_shape, child_dropped = _shape(child, depth=depth + 1)
        children.append(child_shape)
        dropped += child_dropped
    counts = Counter(children)
    encoded = ",".join(f"{token}:{counts[token]}" for token in sorted(counts))
    return f"{kind}({encoded})", dropped


@dataclass(frozen=True, slots=True, order=True)
class MessageTypeKey:
    """Safe unknown message-type bucket key."""

    kind: str
    value: int | None = None


@dataclass(frozen=True, slots=True, order=True)
class DeviceTypeKey:
    """Safe unknown numeric device-type combination."""

    dev_type: int
    sub_type: int


@dataclass(frozen=True, slots=True, order=True)
class StructuralKey:
    """Value-free structural signature at one code-owned path."""

    path: str
    unknown_field_count: int
    unknown_value_types: tuple[tuple[str, int], ...]
    nested_shapes: tuple[str, ...]
    type_mismatches: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class DiscoveryObservation:
    """Immutable occurrence metadata."""

    count: int
    first_seen_at: float
    last_seen_at: float


@dataclass(frozen=True, slots=True)
class MessageTypeDiscovery:
    key: MessageTypeKey
    observation: DiscoveryObservation


@dataclass(frozen=True, slots=True)
class DeviceTypeDiscovery:
    key: DeviceTypeKey
    observation: DiscoveryObservation


@dataclass(frozen=True, slots=True)
class StructuralDiscovery:
    key: StructuralKey
    observation: DiscoveryObservation


@dataclass(frozen=True, slots=True)
class ProtocolDiscoverySnapshot:
    """Detached immutable snapshot of one coordinator's discovery state."""

    version: int
    unknown_message_types: tuple[MessageTypeDiscovery, ...]
    unknown_device_types: tuple[DeviceTypeDiscovery, ...]
    structures: tuple[StructuralDiscovery, ...]
    message_type_overflow: int
    device_type_overflow: int
    structural_overflow: int
    traversal_dropped: int


@dataclass(slots=True)
class _MutableObservation:
    count: int
    first_seen_at: float
    last_seen_at: float

    def record(self, now: float) -> None:
        self.count = _saturating_add(self.count)
        self.last_seen_at = now


class ProtocolDiscoveryState:
    """Per-coordinator, memory-only bounded protocol discovery state."""

    def __init__(self) -> None:
        self._message_types: dict[MessageTypeKey, _MutableObservation] = {}
        self._device_types: dict[DeviceTypeKey, _MutableObservation] = {}
        self._structures: dict[StructuralKey, _MutableObservation] = {}
        self._message_type_overflow = 0
        self._device_type_overflow = 0
        self._structural_overflow = 0
        self._traversal_dropped = 0

    @staticmethod
    def _record_bucket(
        buckets: dict[Any, _MutableObservation],
        key: Any,
        *,
        now: float,
        limit: int,
    ) -> bool:
        current = buckets.get(key)
        if current is not None:
            current.record(now)
            return True
        if len(buckets) >= limit:
            return False
        buckets[key] = _MutableObservation(1, now, now)
        return True

    def _observe_message_type(self, message_type: Any, now: float) -> None:
        safe_integer = _safe_protocol_integer(message_type)
        if safe_integer is not None and safe_integer in _KNOWN_MESSAGE_TYPES:
            return
        key = (
            MessageTypeKey("integer", safe_integer)
            if safe_integer is not None
            else MessageTypeKey(_json_type(message_type))
        )
        if not self._record_bucket(
            self._message_types,
            key,
            now=now,
            limit=MAX_MESSAGE_TYPE_BUCKETS,
        ):
            self._message_type_overflow = _saturating_add(
                self._message_type_overflow
            )

    @staticmethod
    def _known_device_pair(dev_type: int, sub_type: int) -> bool:
        # The current classifier supports these device types even when a new
        # subtype has no model-specific label yet.  Discovery must not relabel
        # that established fallback as an unknown combination.
        return dev_type in {1, 2, 3, 4, 6}

    def _observe_device_type(self, item: Mapping[str, Any], now: float) -> None:
        dev_type = _safe_protocol_integer(item.get("devType"))
        sub_type = _safe_protocol_integer(item.get("subType"))
        if dev_type is None or sub_type is None:
            return
        if self._known_device_pair(dev_type, sub_type):
            return
        key = DeviceTypeKey(dev_type, sub_type)
        if not self._record_bucket(
            self._device_types,
            key,
            now=now,
            limit=MAX_DEVICE_TYPE_BUCKETS,
        ):
            self._device_type_overflow = _saturating_add(
                self._device_type_overflow
            )

    def _observe_structure(
        self,
        path: str,
        value: Mapping[str, Any],
        *,
        known_fields: frozenset[str],
        expected_types: Mapping[str, str],
        now: float,
    ) -> None:
        sampled = list(islice(value.items(), MAX_MAPPING_ENTRIES))
        self._traversal_dropped = _saturating_add(
            self._traversal_dropped,
            max(0, len(value) - len(sampled)),
        )
        unknown_types: Counter[str] = Counter()
        nested_shapes: list[str] = []
        mismatches: list[tuple[str, str]] = []
        unknown_count = 0
        for raw_key, item in sampled:
            if raw_key in known_fields:
                expected = expected_types.get(raw_key)
                observed = _json_type(item)
                if expected is not None and observed != expected:
                    mismatches.append((raw_key, observed))
                continue
            unknown_count += 1
            kind = _json_type(item)
            unknown_types[kind] += 1
            if kind in {"object", "array"} and len(nested_shapes) < MAX_NESTED_SHAPES:
                shape, dropped = _shape(item, depth=1)
                nested_shapes.append(shape)
                self._traversal_dropped = _saturating_add(
                    self._traversal_dropped, dropped
                )

        if unknown_count == 0 and not mismatches:
            return
        key = StructuralKey(
            path=path,
            unknown_field_count=unknown_count,
            unknown_value_types=tuple(sorted(unknown_types.items())),
            nested_shapes=tuple(sorted(nested_shapes)),
            type_mismatches=tuple(sorted(mismatches)),
        )
        if not self._record_bucket(
            self._structures,
            key,
            now=now,
            limit=MAX_STRUCTURAL_SIGNATURES,
        ):
            self._structural_overflow = _saturating_add(self._structural_overflow)

    def observe(
        self,
        raw_envelope: Mapping[str, Any],
        body: Mapping[str, Any],
        *,
        message_type: Any,
        now: float,
    ) -> None:
        """Observe one host-owned, parsed and structurally accepted envelope."""
        self._observe_message_type(message_type, now)
        self._observe_structure(
            "envelope",
            raw_envelope,
            known_fields=_KNOWN_ENVELOPE_FIELDS,
            expected_types=_EXPECTED_ENVELOPE_TYPES,
            now=now,
        )
        self._observe_structure(
            "payload",
            body,
            known_fields=_KNOWN_PAYLOAD_FIELDS,
            expected_types={},
            now=now,
        )
        self._observe_device_type(body, now)

        if body.get("devType") == 1:
            self._observe_structure(
                "expansion_item",
                body,
                known_fields=_KNOWN_CHILD_FIELDS,
                expected_types=_EXPECTED_CHILD_TYPES,
                now=now,
            )

        for container in _CHILD_ARRAY_KEYS:
            items = body.get(container)
            if not isinstance(items, list):
                continue
            sample = list(islice(items, MAX_ARRAY_ITEMS))
            self._traversal_dropped = _saturating_add(
                self._traversal_dropped, max(0, len(items) - len(sample))
            )
            for item in sample:
                if not isinstance(item, Mapping):
                    continue
                self._observe_device_type(item, now)
                self._observe_structure(
                    "child_item",
                    item,
                    known_fields=_KNOWN_CHILD_FIELDS,
                    expected_types=_EXPECTED_CHILD_TYPES,
                    now=now,
                )

    def snapshot(self) -> ProtocolDiscoverySnapshot:
        """Return an immutable, detached and deterministically ordered view."""
        return ProtocolDiscoverySnapshot(
            version=DISCOVERY_VERSION,
            unknown_message_types=tuple(
                MessageTypeDiscovery(
                    key,
                    DiscoveryObservation(value.count, value.first_seen_at, value.last_seen_at),
                )
                for key, value in sorted(self._message_types.items())
            ),
            unknown_device_types=tuple(
                DeviceTypeDiscovery(
                    key,
                    DiscoveryObservation(value.count, value.first_seen_at, value.last_seen_at),
                )
                for key, value in sorted(self._device_types.items())
            ),
            structures=tuple(
                StructuralDiscovery(
                    key,
                    DiscoveryObservation(value.count, value.first_seen_at, value.last_seen_at),
                )
                for key, value in sorted(self._structures.items())
            ),
            message_type_overflow=self._message_type_overflow,
            device_type_overflow=self._device_type_overflow,
            structural_overflow=self._structural_overflow,
            traversal_dropped=self._traversal_dropped,
        )


__all__ = [
    "DISCOVERY_DETAIL_BUDGET_BYTES",
    "DISCOVERY_VERSION",
    "MAX_ARRAY_ITEMS",
    "MAX_DEVICE_TYPE_BUCKETS",
    "MAX_MAPPING_ENTRIES",
    "MAX_MESSAGE_TYPE_BUCKETS",
    "MAX_SAFE_PROTOCOL_INTEGER",
    "MAX_STRUCTURAL_DEPTH",
    "MAX_STRUCTURAL_SIGNATURES",
    "OPTION_PROTOCOL_DISCOVERY_ENABLED",
    "ProtocolDiscoverySnapshot",
    "ProtocolDiscoveryState",
]
