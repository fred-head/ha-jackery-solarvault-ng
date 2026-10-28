"""Bounded, value-free structural observation for opt-in protocol discovery.

The state in this module is deliberately unable to retain raw field names or
scalar values.  It records only code-owned path tokens, JSON type/count shapes,
safe numeric protocol identifiers and bounded occurrence metadata.
"""

from __future__ import annotations

import json
import math
import re
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
_JSON_TYPES: Final = frozenset(
    {"array", "bool", "integer", "null", "number", "object", "string", "unsupported"}
)
_STRUCTURAL_PATHS: Final = frozenset(
    {"child_item", "envelope", "expansion_item", "payload"}
)
_SAFE_SHAPE_CHARS: Final = re.compile(r"[a-zA-Z0-9:(),]+\Z")

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


def _restore_observation(value: Mapping[str, Any]) -> _MutableObservation | None:
    """Validate persisted counters and wall-clock times before restoring them."""
    count = value.get("count")
    first_seen_at = value.get("first_seen_at")
    last_seen_at = value.get("last_seen_at")
    if (
        type(count) is not int
        or not 1 <= count <= MAX_COUNTER
        or isinstance(first_seen_at, bool)
        or not isinstance(first_seen_at, (int, float))
        or not math.isfinite(first_seen_at)
        or first_seen_at < 0
        or isinstance(last_seen_at, bool)
        or not isinstance(last_seen_at, (int, float))
        or not math.isfinite(last_seen_at)
        or last_seen_at < first_seen_at
    ):
        return None
    return _MutableObservation(count, float(first_seen_at), float(last_seen_at))


def _is_safe_shape(value: object) -> bool:
    """Accept only the generated type/count grammar, never stored field text."""
    if not isinstance(value, str) or len(value) > 2_048 or not _SAFE_SHAPE_CHARS.fullmatch(value):
        return False
    if any(token not in _JSON_TYPES for token in re.findall(r"[a-zA-Z]+", value)):
        return False
    if any(int(number) > MAX_MAPPING_ENTRIES for number in re.findall(r"\d+", value)):
        return False
    depth = 0
    for character in value:
        if character == "(":
            depth += 1
            if depth > MAX_STRUCTURAL_DEPTH:
                return False
        elif character == ")":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


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


@dataclass(frozen=True, slots=True)
class DiscoverySignal:
    """Value-free finding used to decide whether a raw example is relevant."""

    reason: str
    signature: str


@dataclass(slots=True)
class _MutableObservation:
    count: int
    first_seen_at: float
    last_seen_at: float

    def record(self, now: float) -> None:
        self.count = _saturating_add(self.count)
        self.last_seen_at = now


class ProtocolDiscoveryState:
    """Per-coordinator bounded, value-free structural discovery state."""

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

    def _observe_message_type(
        self,
        message_type: Any,
        now: float,
    ) -> MessageTypeKey | None:
        safe_integer = _safe_protocol_integer(message_type)
        if safe_integer is not None and safe_integer in _KNOWN_MESSAGE_TYPES:
            return None
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
            self._message_type_overflow = _saturating_add(self._message_type_overflow)
        return key

    @staticmethod
    def _known_device_pair(dev_type: int, sub_type: int) -> bool:
        # The current classifier supports these device types even when a new
        # subtype has no model-specific label yet.  Discovery must not relabel
        # that established fallback as an unknown combination.
        return dev_type in {1, 2, 3, 4, 6}

    def _observe_device_type(
        self,
        item: Mapping[str, Any],
        now: float,
    ) -> DeviceTypeKey | None:
        dev_type = _safe_protocol_integer(item.get("devType"))
        sub_type = _safe_protocol_integer(item.get("subType"))
        if dev_type is None or sub_type is None:
            return None
        if self._known_device_pair(dev_type, sub_type):
            return None
        key = DeviceTypeKey(dev_type, sub_type)
        if not self._record_bucket(
            self._device_types,
            key,
            now=now,
            limit=MAX_DEVICE_TYPE_BUCKETS,
        ):
            self._device_type_overflow = _saturating_add(self._device_type_overflow)
        return key

    def _observe_structure(
        self,
        path: str,
        value: Mapping[str, Any],
        *,
        known_fields: frozenset[str],
        expected_types: Mapping[str, str],
        now: float,
    ) -> StructuralKey | None:
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
                self._traversal_dropped = _saturating_add(self._traversal_dropped, dropped)

        if unknown_count == 0 and not mismatches:
            return None
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
        return key

    def observe(
        self,
        raw_envelope: Mapping[str, Any],
        body: Mapping[str, Any],
        *,
        message_type: Any,
        now: float,
    ) -> tuple[DiscoverySignal, ...]:
        """Observe one host-owned, parsed and structurally accepted envelope."""
        signals: list[DiscoverySignal] = []
        unknown_message_type = self._observe_message_type(message_type, now)
        if unknown_message_type is not None:
            signals.append(
                DiscoverySignal(
                    "unknown_message_type",
                    json.dumps(
                        [unknown_message_type.kind, unknown_message_type.value],
                        separators=(",", ":"),
                    ),
                )
            )
        structures: list[StructuralKey] = []
        device_types: list[DeviceTypeKey] = []
        structure = self._observe_structure(
            "envelope",
            raw_envelope,
            known_fields=_KNOWN_ENVELOPE_FIELDS,
            expected_types=_EXPECTED_ENVELOPE_TYPES,
            now=now,
        )
        if structure is not None:
            structures.append(structure)
        structure = self._observe_structure(
            "payload",
            body,
            known_fields=_KNOWN_PAYLOAD_FIELDS,
            expected_types={},
            now=now,
        )
        if structure is not None:
            structures.append(structure)
        device_type = self._observe_device_type(body, now)
        if device_type is not None:
            device_types.append(device_type)

        if body.get("devType") == 1:
            structure = self._observe_structure(
                "expansion_item",
                body,
                known_fields=_KNOWN_CHILD_FIELDS,
                expected_types=_EXPECTED_CHILD_TYPES,
                now=now,
            )
            if structure is not None:
                structures.append(structure)

        for container in _CHILD_ARRAY_KEYS:
            items = body.get(container)
            if not isinstance(items, list):
                continue
            sample = list(islice(items, MAX_ARRAY_ITEMS))
            self._traversal_dropped = _saturating_add(self._traversal_dropped, max(0, len(items) - len(sample)))
            for item in sample:
                if not isinstance(item, Mapping):
                    continue
                device_type = self._observe_device_type(item, now)
                if device_type is not None:
                    device_types.append(device_type)
                structure = self._observe_structure(
                    "child_item",
                    item,
                    known_fields=_KNOWN_CHILD_FIELDS,
                    expected_types=_EXPECTED_CHILD_TYPES,
                    now=now,
                )
                if structure is not None:
                    structures.append(structure)

        if unknown_message_type is None:
            for key in device_types:
                signals.append(
                    DiscoverySignal(
                        "unknown_device_type",
                        json.dumps([key.dev_type, key.sub_type], separators=(",", ":")),
                    )
                )
        if unknown_message_type is None and not device_types:
            for structure_key in structures:
                signals.append(
                    DiscoverySignal(
                        "unknown_structure",
                        json.dumps(
                            [
                                structure_key.path,
                                structure_key.unknown_field_count,
                                structure_key.unknown_value_types,
                                structure_key.nested_shapes,
                                structure_key.type_mismatches,
                            ],
                            separators=(",", ":"),
                        ),
                    )
                )
        return tuple(signals)

    def to_storage(self) -> dict[str, Any]:
        """Return bounded JSON data suitable for versioned private storage."""
        snapshot = self.snapshot()
        return {
            "version": snapshot.version,
            "unknown_message_types": [
                {
                    "kind": item.key.kind,
                    "value": item.key.value,
                    "count": item.observation.count,
                    "first_seen_at": item.observation.first_seen_at,
                    "last_seen_at": item.observation.last_seen_at,
                }
                for item in snapshot.unknown_message_types
            ],
            "unknown_device_types": [
                {
                    "dev_type": item.key.dev_type,
                    "sub_type": item.key.sub_type,
                    "count": item.observation.count,
                    "first_seen_at": item.observation.first_seen_at,
                    "last_seen_at": item.observation.last_seen_at,
                }
                for item in snapshot.unknown_device_types
            ],
            "structures": [
                {
                    "path": item.key.path,
                    "unknown_field_count": item.key.unknown_field_count,
                    "unknown_value_types": [list(value) for value in item.key.unknown_value_types],
                    "nested_shapes": list(item.key.nested_shapes),
                    "type_mismatches": [list(value) for value in item.key.type_mismatches],
                    "count": item.observation.count,
                    "first_seen_at": item.observation.first_seen_at,
                    "last_seen_at": item.observation.last_seen_at,
                }
                for item in snapshot.structures
            ],
            "message_type_overflow": snapshot.message_type_overflow,
            "device_type_overflow": snapshot.device_type_overflow,
            "structural_overflow": snapshot.structural_overflow,
            "traversal_dropped": snapshot.traversal_dropped,
        }

    @classmethod
    def from_storage(cls, value: object) -> ProtocolDiscoveryState | None:
        """Restore a strictly validated value-free state or reject it entirely."""
        if not isinstance(value, Mapping) or value.get("version") != DISCOVERY_VERSION:
            return None
        state = cls()
        raw_message_types = value.get("unknown_message_types")
        raw_device_types = value.get("unknown_device_types")
        raw_structures = value.get("structures")
        if (
            not isinstance(raw_message_types, list)
            or not isinstance(raw_device_types, list)
            or not isinstance(raw_structures, list)
        ):
            return None
        if (
            len(raw_message_types) > MAX_MESSAGE_TYPE_BUCKETS
            or len(raw_device_types) > MAX_DEVICE_TYPE_BUCKETS
            or len(raw_structures) > MAX_STRUCTURAL_SIGNATURES
        ):
            return None

        for item in raw_message_types:
            if not isinstance(item, Mapping):
                return None
            kind = item.get("kind")
            protocol_value = item.get("value")
            if not isinstance(kind, str) or kind not in _JSON_TYPES:
                return None
            if kind == "integer":
                if (
                    type(protocol_value) is not int
                    or not 0 <= protocol_value <= MAX_SAFE_PROTOCOL_INTEGER
                    or protocol_value in _KNOWN_MESSAGE_TYPES
                ):
                    return None
            elif protocol_value is not None:
                return None
            observation = _restore_observation(item)
            if observation is None:
                return None
            message_key = MessageTypeKey(kind, protocol_value)
            if message_key in state._message_types:
                return None
            state._message_types[message_key] = observation

        for item in raw_device_types:
            if not isinstance(item, Mapping):
                return None
            dev_type = item.get("dev_type")
            sub_type = item.get("sub_type")
            if (
                type(dev_type) is not int
                or type(sub_type) is not int
                or not 0 <= dev_type <= MAX_SAFE_PROTOCOL_INTEGER
                or not 0 <= sub_type <= MAX_SAFE_PROTOCOL_INTEGER
                or cls._known_device_pair(dev_type, sub_type)
            ):
                return None
            observation = _restore_observation(item)
            if observation is None:
                return None
            device_key = DeviceTypeKey(dev_type, sub_type)
            if device_key in state._device_types:
                return None
            state._device_types[device_key] = observation

        for item in raw_structures:
            if not isinstance(item, Mapping):
                return None
            path = item.get("path")
            unknown_count = item.get("unknown_field_count")
            raw_types = item.get("unknown_value_types")
            raw_shapes = item.get("nested_shapes")
            raw_mismatches = item.get("type_mismatches")
            if (
                not isinstance(path, str)
                or path not in _STRUCTURAL_PATHS
                or type(unknown_count) is not int
                or not 0 <= unknown_count <= MAX_MAPPING_ENTRIES
                or not isinstance(raw_types, list)
                or len(raw_types) > len(_JSON_TYPES)
                or not isinstance(raw_shapes, list)
                or len(raw_shapes) > MAX_NESTED_SHAPES
                or not isinstance(raw_mismatches, list)
                or len(raw_mismatches) > len(_KNOWN_ENVELOPE_FIELDS | _KNOWN_CHILD_FIELDS)
            ):
                return None
            unknown_types: list[tuple[str, int]] = []
            for pair in raw_types:
                if (
                    not isinstance(pair, list)
                    or len(pair) != 2
                    or not isinstance(pair[0], str)
                    or pair[0] not in _JSON_TYPES
                    or type(pair[1]) is not int
                    or not 1 <= pair[1] <= MAX_MAPPING_ENTRIES
                ):
                    return None
                unknown_types.append((pair[0], pair[1]))
            if len({kind for kind, _ in unknown_types}) != len(unknown_types):
                return None
            shapes: list[str] = []
            for shape in raw_shapes:
                if not _is_safe_shape(shape):
                    return None
                shapes.append(shape)
            mismatches: list[tuple[str, str]] = []
            for pair in raw_mismatches:
                if (
                    not isinstance(pair, list)
                    or len(pair) != 2
                    or not isinstance(pair[0], str)
                    or pair[0] not in (_KNOWN_ENVELOPE_FIELDS | _KNOWN_CHILD_FIELDS)
                    or not isinstance(pair[1], str)
                    or pair[1] not in _JSON_TYPES
                ):
                    return None
                mismatches.append((pair[0], pair[1]))
            if (
                (unknown_count == 0 and not mismatches)
                or sum(count for _, count in unknown_types) != unknown_count
                or len(set(mismatches)) != len(mismatches)
            ):
                return None
            observation = _restore_observation(item)
            if observation is None:
                return None
            structure_key = StructuralKey(
                path,
                unknown_count,
                tuple(sorted(unknown_types)),
                tuple(sorted(shapes)),
                tuple(sorted(mismatches)),
            )
            if structure_key in state._structures:
                return None
            state._structures[structure_key] = observation

        counters: list[int] = []
        for name in (
            "message_type_overflow",
            "device_type_overflow",
            "structural_overflow",
            "traversal_dropped",
        ):
            counter = value.get(name)
            if type(counter) is not int or not 0 <= counter <= MAX_COUNTER:
                return None
            counters.append(counter)
        (
            state._message_type_overflow,
            state._device_type_overflow,
            state._structural_overflow,
            state._traversal_dropped,
        ) = counters
        return state

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

    def enforce_storage_budget(self, budget_bytes: int) -> None:
        """Trim newest structural detail while retaining overflow evidence."""
        while (
            self._structures
            and len(
                json.dumps(
                    self.to_storage(),
                    allow_nan=False,
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
            )
            > budget_bytes
        ):
            self._structures.pop(next(reversed(self._structures)))
            self._structural_overflow = _saturating_add(self._structural_overflow)


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
