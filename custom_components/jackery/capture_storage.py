"""Small shared primitives for private, host-bound MQTT capture stores."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store


def host_fingerprint(device_sn: object, namespace: str) -> str | None:
    """Return a stable host fingerprint without retaining the serial itself."""
    if (
        not isinstance(device_sn, str)
        or not device_sn
        or device_sn != device_sn.strip()
        or any(character in "/+#\x00" or ord(character) < 32 or ord(character) == 127 for character in device_sn)
    ):
        return None
    try:
        encoded = device_sn.encode("utf-8")
    except UnicodeEncodeError:
        return None
    return hashlib.sha256(namespace.encode("ascii") + b"\0" + encoded).hexdigest()


def private_entry_store(
    hass: HomeAssistant,
    *,
    version: int,
    key: str,
) -> Store[dict[str, Any]]:
    """Create an HA Store with the private-storage behavior used by captures."""
    return Store(hass, version, key, private=True)


def compact_size(value: Any) -> int:
    """Return deterministic compact UTF-8 JSON size for bounded storage."""
    return len(
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )


async def async_remove_store_without_save_race(
    store: Store[dict[str, Any]],
    empty_data: Mapping[str, Any],
) -> None:
    """Drain a delayed save, then remove the store so it cannot be recreated."""
    await store.async_save(dict(empty_data))
    await store.async_remove()
