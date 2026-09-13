"""Classify established Jackery child-device payload shapes.

Classification is intentionally limited to the integration's existing software
families. Routing, cache placement, discovery and entity construction remain
with the caller.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

# CT/meter subtype labels retained for entity diagnostic attributes.
CT_SUBTYPE_MAP: dict[int, str] = {
    1: "Shelly Single Phase",
    2: "Shelly Three Phase",
    3: "Shelly 63A",
    4: "Eastron Single Phase (4002)",
    5: "Eastron Three Phase (4003)",
    6: "Jackery Wireless Smart Meter (US L1/L2 4007)",
    7: "Jackery Smart Meter 3P (UK 4008)",
}


class ClassificationContext(StrEnum):
    """Payload location when it changes the established classification rules."""

    DISCOVERY = "discovery"
    PLUG_ARRAY = "plug_array"
    CT_ARRAY = "ct_array"
    COLLECTOR_ARRAY = "collector_array"
    POINT_UPDATE = "point_update"
    TYPE23_CHILD = "type23_child"


class DeviceFamily(StrEnum):
    """Entity/discovery families currently supported by the integration."""

    EXPANSION_BATTERY = "expansion_battery"
    CT = "ct"
    SMARTMETER = "smartmeter"
    COLLECTOR = "collector"
    PLUG = "plug"
    UNKNOWN = "unknown"


class DeviceModel(StrEnum):
    """Existing subtype-derived associations used by current behavior."""

    HTO907A = "hto907a"
    SHELLY_PRO_3EM = "shelly_pro_3em"
    HTO910A = "hto910a"


@dataclass(frozen=True, slots=True)
class DeviceClassification:
    """Pure classification result with the effective device type."""

    family: DeviceFamily
    dev_type: Any = None
    model: DeviceModel | None = None


_PLUG_INFERENCE_FIELDS: frozenset[str] = frozenset(
    {"switchSta", "sysSwitch", "totalEgy"}
)
_METER_INFERENCE_FIELDS: frozenset[str] = frozenset(
    {"aPhasePw", "AphasePw", "tPhasePw", "TphasePw", "phasePw"}
)


def classify_device(
    payload: Mapping[str, Any],
    context: ClassificationContext = ClassificationContext.DISCOVERY,
) -> DeviceClassification:
    """Classify a child payload without mutating it.

    Context preserves the route-specific defaults and point-field inference of
    the existing coordinator. Explicit unknown types are never inferred away.
    """
    dev_type = payload.get("devType")
    sub_type = payload.get("subType")

    if context is ClassificationContext.TYPE23_CHILD:
        if dev_type == 1:
            return DeviceClassification(DeviceFamily.EXPANSION_BATTERY, dev_type)
        return DeviceClassification(DeviceFamily.UNKNOWN, dev_type)

    if dev_type is None:
        if context is ClassificationContext.PLUG_ARRAY:
            dev_type = 6
        elif context is ClassificationContext.CT_ARRAY:
            dev_type = 2
        elif context is ClassificationContext.POINT_UPDATE:
            if any(key in payload for key in _PLUG_INFERENCE_FIELDS):
                dev_type = 6
            elif any(key in payload for key in _METER_INFERENCE_FIELDS):
                dev_type = 3
        elif context is ClassificationContext.DISCOVERY and sub_type == 2:
            dev_type = 2

    if dev_type == 2:
        return DeviceClassification(DeviceFamily.CT, dev_type)
    if dev_type == 3:
        if sub_type == 5:
            model = DeviceModel.HTO907A
        elif sub_type == 2:
            model = DeviceModel.SHELLY_PRO_3EM
        else:
            model = None
        return DeviceClassification(DeviceFamily.SMARTMETER, dev_type, model)
    if dev_type == 4:
        if sub_type == 7:
            return DeviceClassification(
                DeviceFamily.COLLECTOR,
                dev_type,
                DeviceModel.HTO910A,
            )
        return DeviceClassification(DeviceFamily.CT, dev_type)
    if dev_type == 6:
        return DeviceClassification(DeviceFamily.PLUG, dev_type)
    return DeviceClassification(DeviceFamily.UNKNOWN, dev_type)


def should_create_plug_switch(payload: Mapping[str, Any]) -> bool:
    """Return whether existing static switch setup treats a payload as a plug."""
    return payload.get("devType") == 6
