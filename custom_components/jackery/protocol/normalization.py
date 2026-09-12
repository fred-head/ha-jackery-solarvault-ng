"""Normalize established Jackery MQTT payload variants.

These helpers only transform caller-provided dictionaries. Message routing,
cache mutation, freshness and device classification remain with the caller.
"""

from typing import Any

# Fields that identify a flat status message without a ``body`` wrapper.
_FLAT_PAYLOAD_KEYS: frozenset[str] = frozenset(
    {
        "batSoc",
        "soc",
        "pvPw",
        "stat",
        "workMode",
        "inOngridPw",
        "outOngridPw",
        "gridInPw",
        "gridOutPw",
        "inGridSidePw",
        "outGridSidePw",
        "swEpsInPw",
        "swEpsOutPw",
        "batInPw",
        "batOutPw",
        "otherLoadPw",
    }
)

# Top-level envelope keys that are never part of a reconstructed payload body.
_FLAT_META_KEYS: frozenset[str] = frozenset(
    {"type", "eventId", "messageId", "ts", "deviceType", "token", "softver", "body"}
)


def normalize_payload_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """Copy a payload and add established canonical aliases where needed.

    Original wire fields remain in the result. A non-null canonical value,
    including zero, wins over its alias; a null canonical value may be filled
    by a non-null alias.
    """
    result = dict(payload)

    if result.get("gridInPw") is None and result.get("gridBuyPw") is not None:
        result["gridInPw"] = result["gridBuyPw"]
    if result.get("gridOutPw") is None and result.get("gridSellPw") is not None:
        result["gridOutPw"] = result["gridSellPw"]
    if result.get("workMode") is None and result.get("workModel") is not None:
        result["workMode"] = result["workModel"]

    return result


def extract_flat_body(raw_data: dict[str, Any]) -> dict[str, Any]:
    """Copy status fields from a flat envelope, excluding envelope metadata.

    Return an empty dictionary when none of the established flat-status keys
    is present. Key presence is intentional: a recognized null or zero value
    still identifies the envelope as a flat status payload.
    """
    if not any(key in raw_data for key in _FLAT_PAYLOAD_KEYS):
        return {}
    return {
        key: value for key, value in raw_data.items() if key not in _FLAT_META_KEYS
    }
