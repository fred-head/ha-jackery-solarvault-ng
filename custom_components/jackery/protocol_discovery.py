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

DISCOVERY_VERSION: Final = 2
MAX_COUNTER: Final = 2_147_483_647
MAX_SAFE_PROTOCOL_INTEGER: Final = 65_535
MAX_MESSAGE_TYPE_BUCKETS: Final = 32
MAX_COMMAND_BUCKETS: Final = 32
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
    {"child_item", "envelope", "expansion_item", "payload", "pv_item"}
)
_SAFE_SHAPE_CHARS: Final = re.compile(r"[a-zA-Z0-9:(),]+\Z")

_KNOWN_MESSAGE_TYPES: Final = frozenset({2, 23, 25, 101, 102, 106, 107, 123})
_KNOWN_COMMANDS: Final = {
    2: frozenset({106, 107}),
    101: frozenset({110}),
    106: frozenset({120}),
}
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
_COMMON_METADATA_FIELDS: Final = frozenset(
    {
        "type", "cmd", "deviceSn", "sn", "deviceType", "devType", "subType",
        "softver", "errorCode",
    }
)
_CHILD_ARRAY_CONTAINER_FIELDS: Final = frozenset(
    {"plugs", "plug", "socket", "sockets", "cts", "ct", "collectors"}
)
_COMMON_PAYLOAD_FIELDS: Final = _COMMON_METADATA_FIELDS | _CHILD_ARRAY_CONTAINER_FIELDS
_TYPE2_CAPTURE_FIELDS: Final = frozenset(
    {
        "maxCellTemp", "minCellTemp", "maxCellVolt", "minCellVolt",
        "stackChgCurLimit", "stackDischgCurLimit", "emsChgCurLimit",
        "emsDischgCurLimit", "pcsSetPw",
    }
)
_HOST_TYPE2_FIELDS: Final = _COMMON_METADATA_FIELDS | frozenset(
    {
        "batSoc", "soc", "batInPw", "batOutPw", "cellTemp", "batNum", "batState",
        "pvPw", "pv1", "pv2", "pv3", "pv4", "inOngridPw", "outOngridPw",
        "maxOutPw", "maxFeedGrid", "maxInvStdPw", "maxGridStdPw", "swEpsInPw",
        "swEpsOutPw", "swEpsState", "swEps", "stackInPw", "stackOutPw",
        "socChgLimit", "socDischgLimit", "socForceChg", "autoStandby",
        "isAutoStandby", "ethPort", "wsig", "wname", "eip", "emac", "wip",
        "ability", "maxIotNum", "stat", "workMode", "workModel", "ongridStat",
        "ctStat", "gridSate", "otherLoadPw", "inCtEgy", "outCtEgy",
    }
) | _TYPE2_CAPTURE_FIELDS
_HOST_TYPE2_ACK_FIELDS: Final = _COMMON_METADATA_FIELDS | frozenset(
    {
        "socChgLimit", "socDischgLimit", "maxOutPw", "maxFeedGrid", "autoStandby",
        "isAutoStandby", "swEps", "socForceChg", "reboot", "workModel",
        "defaultPw", "isFollowMeterPw", "offGridDown",
    }
)
_TYPE107_INCREMENTAL_FIELDS: Final = _COMMON_METADATA_FIELDS | frozenset(
    {"batSoc", "soc", "workMode", "workModel", "stat"}
)
_HOST_TYPE106_FIELDS: Final = (_HOST_TYPE2_FIELDS - _TYPE2_CAPTURE_FIELDS) | frozenset(
    {
        "gridInPw", "gridOutPw", "gridBuyPw", "gridSellPw", "inGridSidePw",
        "outGridSidePw", "defaultPw", "energyPlanPw", "isFollowMeterPw",
        "offGridDown", "offGridTime", "standbyPw", "pvMaxChgPower",
        "maxSysOutPw", "maxSysInPw", "chargePlanPw", "wps", "wpc", "funcEnable",
        "tempUnit",
    }
)
_TYPE23_HOST_FIELDS: Final = _COMMON_METADATA_FIELDS | frozenset(
    {
        "pvEgy", "pv1Egy", "pv2Egy", "pv3Egy", "pv4Egy", "batChgEgy",
        "batDisChgEgy", "inOngridEgy", "outOngridEgy", "inEpsEgy", "outEpsEgy",
        "pvOtBatEgy", "pvOtAcEgy", "pvOtOngridEgy", "ongridOtAcLoadEgy",
        "batOtAcEgy", "batOtGridEgy", "ongridOtBatEgy", "acOtBatEgy",
        "acOtOngridEgy",
    }
)
_CHILD_COMMON_FIELDS: Final = frozenset(
    {"deviceSn", "sn", "devType", "subType", "softver", "name", "scanName", "commMode", "commState"}
)
_CHILD_PLUG_FIELDS: Final = _CHILD_COMMON_FIELDS | frozenset(
    {"switchSta", "sysSwitch", "totalEgy", "inPw", "outPw", "power"}
)
_CHILD_METER_FIELDS: Final = _CHILD_COMMON_FIELDS | frozenset(
    {
        "phasePw", "phaseEgy", "aPhasePw", "bPhasePw", "cPhasePw", "tPhasePw",
        "anPhasePw", "bnPhasePw", "cnPhasePw", "tnPhasePw", "AphasePw",
        "BphasePw", "CphasePw", "TphasePw", "aPhaseEgy", "bPhaseEgy",
        "cPhaseEgy", "tPhaseEgy", "anPhaseEgy", "bnPhaseEgy", "cnPhaseEgy",
        "tnPhaseEgy", "AphaseEgy", "BphaseEgy", "CphaseEgy", "TphaseEgy",
        "inPw", "outPw", "wip",
    }
)
_CHILD_COLLECTOR_FIELDS: Final = _CHILD_COMMON_FIELDS | frozenset(
    {"inPw", "outPw", "wip"}
)
_CHILD_EXPANSION_FIELDS: Final = _CHILD_COMMON_FIELDS | frozenset({"inEgy", "outEgy"})
_TYPE23_SMARTMETER_FIELDS: Final = _CHILD_COMMON_FIELDS | frozenset(
    {
        "tPhaseEgy", "tnPhaseEgy", "aPhaseEgy", "bPhaseEgy", "cPhaseEgy",
        "anPhaseEgy", "bnPhaseEgy", "cnPhaseEgy",
    }
)
_CHILD_ARRAY_FIELDS: Final = _COMMON_PAYLOAD_FIELDS
_PV_ITEM_FIELDS: Final = frozenset({"pvPw", "commState"})

_KNOWN_PAYLOAD_FIELDS: Final = frozenset().union(
    _COMMON_PAYLOAD_FIELDS,
    _HOST_TYPE2_FIELDS,
    _HOST_TYPE106_FIELDS,
    _TYPE23_HOST_FIELDS,
    _CHILD_PLUG_FIELDS,
    _CHILD_METER_FIELDS,
    _CHILD_COLLECTOR_FIELDS,
    _CHILD_EXPANSION_FIELDS,
    _TYPE23_SMARTMETER_FIELDS,
    _PV_ITEM_FIELDS,
)
_KNOWN_CHILD_FIELDS: Final = frozenset().union(
    _CHILD_COMMON_FIELDS,
    _CHILD_PLUG_FIELDS,
    _CHILD_METER_FIELDS,
    _CHILD_COLLECTOR_FIELDS,
    _CHILD_EXPANSION_FIELDS,
)

_NUMERIC_TYPES: Final[frozenset[str]] = frozenset({"integer", "number"})
_COMMON_EXPECTED_TYPES: Final[dict[str, str | frozenset[str]]] = {
    "type": "integer", "cmd": "integer", "deviceSn": "string", "sn": "string",
    "deviceType": "integer", "devType": "integer", "subType": "integer",
    "softver": "string", "errorCode": "integer",
}
_HOST_NUMERIC_FIELDS: Final = frozenset(
    {
        "batSoc", "soc", "batInPw", "batOutPw", "cellTemp", "batNum", "batState",
        "pvPw", "inOngridPw", "outOngridPw", "maxOutPw", "maxFeedGrid",
        "maxInvStdPw", "maxGridStdPw", "swEpsInPw", "swEpsOutPw", "swEpsState",
        "swEps", "stackInPw", "stackOutPw", "socChgLimit", "socDischgLimit",
        "socForceChg", "autoStandby", "isAutoStandby", "reboot", "ethPort", "wsig",
        "ability", "maxIotNum", "stat", "workMode", "workModel", "ongridStat", "ctStat",
        "gridSate", "otherLoadPw", "inCtEgy", "outCtEgy", "gridInPw", "gridOutPw",
        "gridBuyPw", "gridSellPw", "inGridSidePw", "outGridSidePw", "defaultPw",
        "energyPlanPw", "isFollowMeterPw", "offGridDown", "offGridTime", "standbyPw",
        "pvMaxChgPower", "maxSysOutPw", "maxSysInPw", "chargePlanPw", "wps", "wpc",
        "funcEnable", "maxCellTemp", "minCellTemp", "maxCellVolt", "minCellVolt",
        "stackChgCurLimit", "stackDischgCurLimit", "emsChgCurLimit",
        "emsDischgCurLimit", "pcsSetPw",
    }
)
_ENERGY_NUMERIC_FIELDS: Final = frozenset(
    {
        "pvEgy", "pv1Egy", "pv2Egy", "pv3Egy", "pv4Egy", "batChgEgy", "batDisChgEgy",
        "inOngridEgy", "outOngridEgy", "inEpsEgy", "outEpsEgy", "pvOtBatEgy",
        "pvOtAcEgy", "pvOtOngridEgy", "ongridOtAcLoadEgy", "batOtAcEgy", "batOtGridEgy",
        "ongridOtBatEgy", "acOtBatEgy", "acOtOngridEgy", "inEgy", "outEgy",
        "totalEgy", "phasePw", "phaseEgy", "aPhasePw", "bPhasePw", "cPhasePw",
        "tPhasePw", "anPhasePw", "bnPhasePw", "cnPhasePw", "tnPhasePw", "AphasePw",
        "BphasePw", "CphasePw", "TphasePw", "aPhaseEgy", "bPhaseEgy", "cPhaseEgy",
        "tPhaseEgy", "anPhaseEgy", "bnPhaseEgy", "cnPhaseEgy", "tnPhaseEgy",
        "AphaseEgy", "BphaseEgy", "CphaseEgy", "TphaseEgy", "inPw", "outPw", "power",
    }
)
_CHILD_EXPECTED_TYPES: Final[dict[str, str | frozenset[str]]] = {
    **_COMMON_EXPECTED_TYPES,
    "name": "string", "scanName": "string", "commMode": "integer", "commState": "integer",
    "switchSta": "integer", "sysSwitch": "integer",
    **dict.fromkeys(_ENERGY_NUMERIC_FIELDS, _NUMERIC_TYPES),
}
_EXPECTED_ENVELOPE_TYPES: Final = {"type": "integer", "body": "object"}
_EXPECTED_PAYLOAD_TYPES: Final[dict[str, str | frozenset[str]]] = {
    **_COMMON_EXPECTED_TYPES,
    **dict.fromkeys(_HOST_NUMERIC_FIELDS | _ENERGY_NUMERIC_FIELDS, _NUMERIC_TYPES),
    **dict.fromkeys({"wname", "eip", "emac", "wip"}, "string"),
    **dict.fromkeys({"pv1", "pv2", "pv3", "pv4"}, "object"),
    **dict.fromkeys({"plugs", "plug", "socket", "sockets", "cts", "ct", "collectors"}, "array"),
    "tempUnit": "integer",
}
_EXPECTED_CHILD_TYPES: Final = _CHILD_EXPECTED_TYPES
_EXPECTED_PV_ITEM_TYPES: Final[dict[str, str | frozenset[str]]] = {
    "pvPw": _NUMERIC_TYPES,
    "commState": "integer",
}
_STORED_KNOWN_FIELDS: Final = _KNOWN_ENVELOPE_FIELDS | _KNOWN_PAYLOAD_FIELDS | _KNOWN_CHILD_FIELDS | {"cmd"}


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


def _expected_type_matches(observed: str, expected: str | frozenset[str]) -> bool:
    return observed in expected if isinstance(expected, frozenset) else observed == expected


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
class CommandKey:
    """Safe command identifier in a known message-type namespace."""

    message_type: int
    command: int | None


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
class CommandDiscovery:
    key: CommandKey
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
    unknown_commands: tuple[CommandDiscovery, ...]
    unknown_device_types: tuple[DeviceTypeDiscovery, ...]
    structures: tuple[StructuralDiscovery, ...]
    message_type_overflow: int
    command_overflow: int
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
        self._commands: dict[CommandKey, _MutableObservation] = {}
        self._device_types: dict[DeviceTypeKey, _MutableObservation] = {}
        self._structures: dict[StructuralKey, _MutableObservation] = {}
        self._message_type_overflow = 0
        self._command_overflow = 0
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

    def _observe_command(
        self,
        message_type: Any,
        body: Mapping[str, Any],
        now: float,
    ) -> CommandKey | None:
        safe_message_type = _safe_protocol_integer(message_type)
        if safe_message_type is None or "cmd" not in body:
            return None
        known_commands = _KNOWN_COMMANDS.get(safe_message_type)
        if known_commands is None:
            return None
        command_value = body.get("cmd")
        if type(command_value) is not int or command_value in known_commands:
            return None
        safe_command = _safe_protocol_integer(command_value)
        key = CommandKey(safe_message_type, safe_command)
        if not self._record_bucket(
            self._commands,
            key,
            now=now,
            limit=MAX_COMMAND_BUCKETS,
        ):
            self._command_overflow = _saturating_add(self._command_overflow)
        return key

    def _observe_structure(
        self,
        path: str,
        value: Mapping[str, Any],
        *,
        known_fields: frozenset[str],
        expected_types: Mapping[str, str | frozenset[str]],
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
                if expected is not None and not _expected_type_matches(observed, expected):
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

    @staticmethod
    def _device_payload_fields(
        item: Mapping[str, Any],
        *,
        container: str | None = None,
        type23: bool = False,
    ) -> tuple[frozenset[str], Mapping[str, str | frozenset[str]]]:
        """Select only fields supported by this child family and route."""
        dev_type = _safe_protocol_integer(item.get("devType"))
        sub_type = _safe_protocol_integer(item.get("subType"))

        if type23:
            if dev_type == 1 and sub_type == 0:
                return _CHILD_EXPANSION_FIELDS, _CHILD_EXPECTED_TYPES
            if dev_type == 3 and sub_type == 5:
                return _TYPE23_SMARTMETER_FIELDS, _CHILD_EXPECTED_TYPES
            return _CHILD_COMMON_FIELDS, _COMMON_EXPECTED_TYPES
        if not type23 and dev_type == 1 and container in {"plug", "plugs", "socket", "sockets"}:
            return _CHILD_PLUG_FIELDS, _CHILD_EXPECTED_TYPES
        if not type23 and (dev_type == 6 or (
            dev_type is None and container in {"plug", "plugs", "socket", "sockets"}
        )):
            return _CHILD_PLUG_FIELDS, _CHILD_EXPECTED_TYPES
        if dev_type == 4 and sub_type == 7:
            return _CHILD_COLLECTOR_FIELDS, _CHILD_EXPECTED_TYPES
        if dev_type in {2, 3, 4}:
            # A recognized type with an unrecognized subtype still uses the
            # generic device fallback; do not treat its family payload as fully known.
            known_meter_subtype = (
                dev_type == 2 and sub_type in {1, 2, 3, 4, 5, 6, 7}
            ) or (dev_type == 3 and sub_type in {2, 5}) or (
                dev_type == 4 and sub_type in {1, 2, 3, 4, 5, 6}
            )
            if known_meter_subtype or (dev_type == 2 and container in {"ct", "cts"} and sub_type is None):
                return _CHILD_METER_FIELDS, _CHILD_EXPECTED_TYPES
            return _CHILD_COMMON_FIELDS, _COMMON_EXPECTED_TYPES
        if container in {"collectors"} and dev_type is None:
            return _CHILD_COLLECTOR_FIELDS, _CHILD_EXPECTED_TYPES
        return _CHILD_COMMON_FIELDS, _COMMON_EXPECTED_TYPES

    @staticmethod
    def _payload_context(
        message_type: Any,
        body: Mapping[str, Any],
    ) -> tuple[str, frozenset[str], Mapping[str, str | frozenset[str]]]:
        """Return a bounded context name and the field contract for one body."""
        safe_message_type = _safe_protocol_integer(message_type)
        command = body.get("cmd")

        if safe_message_type == 2:
            if type(command) is int and command == 107:
                return "payload", _HOST_TYPE2_ACK_FIELDS, _EXPECTED_PAYLOAD_TYPES
            if "cmd" not in body or (type(command) is int and command == 106):
                return "payload", _HOST_TYPE2_FIELDS, _EXPECTED_PAYLOAD_TYPES
        if safe_message_type == 106 and (
            "cmd" not in body or (type(command) is int and command == 120)
        ):
            return "payload", _HOST_TYPE106_FIELDS, _EXPECTED_PAYLOAD_TYPES
        if safe_message_type == 23:
            dev_type = _safe_protocol_integer(body.get("devType"))
            sub_type = _safe_protocol_integer(body.get("subType"))
            if dev_type == 1:
                fields, expected = ProtocolDiscoveryState._device_payload_fields(body, type23=True)
                path = "expansion_item" if sub_type == 0 else "child_item"
                return path, fields, expected
            if dev_type in {2, 3, 4, 6}:
                fields, expected = ProtocolDiscoveryState._device_payload_fields(body, type23=True)
                return "child_item", fields, expected
            if dev_type is None or dev_type == 0:
                return "payload", _TYPE23_HOST_FIELDS, _EXPECTED_PAYLOAD_TYPES
            return "child_item", _CHILD_COMMON_FIELDS, _COMMON_EXPECTED_TYPES
        if safe_message_type in {101, 102}:
            has_child_container = any(
                isinstance(body.get(key), list) for key in _CHILD_ARRAY_KEYS
            )
            if safe_message_type == 101 or has_child_container:
                return "payload", _CHILD_ARRAY_FIELDS, _EXPECTED_PAYLOAD_TYPES
            fields, expected = ProtocolDiscoveryState._device_payload_fields(body)
            return "child_item", fields, expected
        if safe_message_type == 25:
            return "payload", _HOST_TYPE2_FIELDS, _EXPECTED_PAYLOAD_TYPES
        if safe_message_type == 107:
            return "payload", _TYPE107_INCREMENTAL_FIELDS, _EXPECTED_PAYLOAD_TYPES
        if safe_message_type == 123:
            return "payload", _COMMON_METADATA_FIELDS, _EXPECTED_PAYLOAD_TYPES
        return "payload", _COMMON_METADATA_FIELDS, _COMMON_EXPECTED_TYPES

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
        unknown_command = self._observe_command(message_type, body, now)
        if unknown_command is not None and unknown_message_type is None:
            signals.append(
                DiscoverySignal(
                    "unknown_command",
                    json.dumps(
                        [unknown_command.message_type, unknown_command.command],
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
        path, known_fields, expected_types = self._payload_context(message_type, body)
        structure = self._observe_structure(
            path,
            body,
            known_fields=known_fields,
            expected_types=expected_types,
            now=now,
        )
        if structure is not None:
            structures.append(structure)
        device_type = self._observe_device_type(body, now)
        if device_type is not None:
            device_types.append(device_type)

        has_type2_status_context = message_type == 2 and (
            "cmd" not in body
            or (type(body.get("cmd")) is int and body.get("cmd") == 106)
        )
        has_type106_state_context = message_type == 106 and (
            "cmd" not in body
            or (type(body.get("cmd")) is int and body.get("cmd") == 120)
        )
        if has_type2_status_context or has_type106_state_context:
            for pv_key in ("pv1", "pv2", "pv3", "pv4"):
                item = body.get(pv_key)
                if not isinstance(item, Mapping):
                    continue
                structure = self._observe_structure(
                    "pv_item",
                    item,
                    known_fields=_PV_ITEM_FIELDS,
                    expected_types=_EXPECTED_PV_ITEM_TYPES,
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
                known_fields, expected_types = self._device_payload_fields(
                    item,
                    container=container,
                )
                structure = self._observe_structure(
                    "child_item",
                    item,
                    known_fields=known_fields,
                    expected_types=expected_types,
                    now=now,
                )
                if structure is not None:
                    structures.append(structure)

        if unknown_message_type is None:
            for device_type_key in device_types:
                signals.append(
                    DiscoverySignal(
                        "unknown_device_type",
                        json.dumps(
                            [device_type_key.dev_type, device_type_key.sub_type],
                            separators=(",", ":"),
                        ),
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
            "unknown_commands": [
                {
                    "message_type": item.key.message_type,
                    "command": item.key.command,
                    "count": item.observation.count,
                    "first_seen_at": item.observation.first_seen_at,
                    "last_seen_at": item.observation.last_seen_at,
                }
                for item in snapshot.unknown_commands
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
            "command_overflow": snapshot.command_overflow,
            "device_type_overflow": snapshot.device_type_overflow,
            "structural_overflow": snapshot.structural_overflow,
            "traversal_dropped": snapshot.traversal_dropped,
        }

    @classmethod
    def from_storage(cls, value: object) -> ProtocolDiscoveryState | None:
        """Restore a strictly validated value-free state or reject it entirely."""
        if not isinstance(value, Mapping):
            return None
        stored_version = value.get("version")
        if type(stored_version) is not int or stored_version not in {1, DISCOVERY_VERSION}:
            return None
        state = cls()
        raw_message_types = value.get("unknown_message_types")
        raw_commands = value.get("unknown_commands", [] if stored_version == 1 else None)
        raw_device_types = value.get("unknown_device_types")
        raw_structures = value.get("structures")
        if (
            not isinstance(raw_message_types, list)
            or not isinstance(raw_commands, list)
            or not isinstance(raw_device_types, list)
            or not isinstance(raw_structures, list)
        ):
            return None
        if (
            len(raw_message_types) > MAX_MESSAGE_TYPE_BUCKETS
            or len(raw_commands) > MAX_COMMAND_BUCKETS
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
                # None is the privacy-preserving bucket for integers outside
                # the supported range; their original numeric value is omitted.
                if protocol_value is not None and (
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

        for item in raw_commands:
            if not isinstance(item, Mapping):
                return None
            message_type = item.get("message_type")
            command = item.get("command")
            if (
                type(message_type) is not int
                or message_type not in _KNOWN_COMMANDS
                or (
                    command is not None
                    and (
                        type(command) is not int
                        or not 0 <= command <= MAX_SAFE_PROTOCOL_INTEGER
                        or command in _KNOWN_COMMANDS[message_type]
                    )
                )
            ):
                return None
            observation = _restore_observation(item)
            if observation is None:
                return None
            command_key = CommandKey(message_type, command)
            if command_key in state._commands:
                return None
            state._commands[command_key] = observation

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
                or len(raw_mismatches)
                > len(_STORED_KNOWN_FIELDS)
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
                    or pair[0]
                    not in _STORED_KNOWN_FIELDS
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
            "command_overflow",
            "device_type_overflow",
            "structural_overflow",
            "traversal_dropped",
        ):
            counter = value.get(name, 0 if stored_version == 1 and name == "command_overflow" else None)
            if type(counter) is not int or not 0 <= counter <= MAX_COUNTER:
                return None
            counters.append(counter)
        (
            state._message_type_overflow,
            state._command_overflow,
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
                for key, value in sorted(
                    self._message_types.items(),
                    key=lambda item: (
                        item[0].kind,
                        item[0].value is None,
                        item[0].value if item[0].value is not None else 0,
                    ),
                )
            ),
            unknown_commands=tuple(
                CommandDiscovery(
                    key,
                    DiscoveryObservation(value.count, value.first_seen_at, value.last_seen_at),
                )
                for key, value in sorted(
                    self._commands.items(),
                    key=lambda item: (
                        item[0].message_type,
                        item[0].command is None,
                        item[0].command if item[0].command is not None else 0,
                    ),
                )
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
            command_overflow=self._command_overflow,
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
    "MAX_COMMAND_BUCKETS",
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
