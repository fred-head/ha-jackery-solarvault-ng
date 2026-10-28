"""Home Assistant device registry compatibility and ownership helpers.

Home Assistant 2025.8 exposes globally keyed devices and ``config_entries``.
Newer Home Assistant releases scope devices to a single config entry. Keep the
transition here so migrations and entities share the same fail-closed rules.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any, cast

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import DeviceInfo

_LOGGER = logging.getLogger(__name__)
_MISSING = object()


def device_owned_by_entry(device: object | None, entry_id: str) -> bool:
    """Return true only when the device is exclusively owned by this entry.

    The modern registry has one ``config_entry_id``. The old supported model
    has a set; in that model shared ownership is deliberately rejected.
    """
    if device is None:
        return False
    config_entry_id = getattr(device, "config_entry_id", _MISSING)
    if config_entry_id is not _MISSING:
        return config_entry_id == entry_id
    return getattr(device, "config_entries", None) == {entry_id}


def device_references_entry(device: object | None, entry_id: str) -> bool:
    """Return whether the old shared-owner set references this entry.

    This weaker predicate is for deciding which persisted records to inspect;
    it must never authorize mutation. Mutation requires exclusive ownership.
    """
    if device is None:
        return False
    config_entry_id = getattr(device, "config_entry_id", _MISSING)
    if config_entry_id is not _MISSING:
        return config_entry_id == entry_id
    owners = getattr(device, "config_entries", None)
    return isinstance(owners, (set, frozenset)) and entry_id in owners


def iter_all_devices(registry: dr.DeviceRegistry) -> tuple[dr.DeviceEntry, ...]:
    """Iterate devices without using the old mapping on modern registries."""
    modern_lookup = getattr(registry, "async_get_device_by_identifier", None)
    if callable(modern_lookup):
        # In HA 2026.10 async_get_devices is a filtered query, not an all-device
        # iterator. The public ``devices`` collection can be iterated directly;
        # only mapping operations such as .values() are deprecated.
        main_devices = tuple(cast(Iterable[dr.DeviceEntry], registry.devices))
        # HA 2026.10 stores lightweight children separately; async_get_devices
        # intentionally returns only main devices. ``child_devices`` is the
        # public read-only collection and must be included in migration scans.
        child_devices = getattr(registry, "child_devices", ())
        return (*main_devices, *cast(Iterable[dr.DeviceEntry], child_devices))

    # Home Assistant 2025.8 has no public all-device iterator. This access is
    # confined to the legacy adapter and is never taken on modern HA.
    return tuple(registry.devices.values())


def iter_devices_for_entry(
    registry: dr.DeviceRegistry,
    entry_id: str,
) -> tuple[dr.DeviceEntry, ...]:
    """Return only devices proven to be exclusively owned by ``entry_id``."""
    return tuple(device for device in iter_all_devices(registry) if device_owned_by_entry(device, entry_id))


def find_devices_by_identifier(
    registry: dr.DeviceRegistry,
    identifier: tuple[str, str],
) -> tuple[dr.DeviceEntry, ...]:
    """Find every device carrying an identifier, preserving conflict evidence."""
    modern_iterator = getattr(registry, "async_get_devices", None)
    if callable(modern_iterator):
        main_devices = modern_iterator(identifiers={identifier})
        child_devices = getattr(registry, "child_devices", ())
        return (
            *cast(Iterable[dr.DeviceEntry], main_devices),
            *(device for device in cast(Iterable[dr.DeviceEntry], child_devices) if identifier in device.identifiers),
        )

    legacy_lookup = getattr(registry, "async_get_device", None)
    if not callable(legacy_lookup):
        # A partially implemented modern API cannot establish that a foreign
        # device does not occupy this identifier. Refuse to guess.
        _LOGGER.warning("Cannot prove device identifier uniqueness with this registry API")
        return ()
    device = legacy_lookup(identifiers={identifier})
    return (device,) if device is not None else ()


def find_device_by_identifier(
    registry: dr.DeviceRegistry,
    identifier: tuple[str, str],
    entry_id: str,
) -> dr.DeviceEntry | None:
    """Find one identifier only within the expected entry's ownership scope."""
    modern_lookup = getattr(registry, "async_get_device_by_identifier", None)
    if callable(modern_lookup):
        scoped_matches = []
        for lookup_name in (
            "async_get_device_by_identifier",
            "async_get_child_device_by_identifier",
        ):
            lookup = getattr(registry, lookup_name, None)
            if callable(lookup) and (device := lookup(identifier, entry_id)) is not None:
                scoped_matches.append(device)
        if len(scoped_matches) != 1 or not device_owned_by_entry(scoped_matches[0], entry_id):
            return None
        return scoped_matches[0]

    matches = find_devices_by_identifier(registry, identifier)
    if len(matches) != 1 or not device_owned_by_entry(matches[0], entry_id):
        return None
    return matches[0]


def get_device_by_id(registry: dr.DeviceRegistry, device_id: str) -> dr.DeviceEntry | None:
    """Resolve a registry ID through the supported public lookup method."""
    modern_lookup = getattr(registry, "async_get_device_by_id", None)
    if callable(modern_lookup):
        return modern_lookup(device_id)
    if callable(getattr(registry, "async_get_devices", None)):
        return next((device for device in iter_all_devices(registry) if device.id == device_id), None)
    return registry.async_get(device_id)


def device_parent_id(device: object | None) -> str | None:
    """Read the parent link across DeviceEntry and ChildDeviceEntry shapes."""
    if device is None:
        return None
    modern_parent_id = getattr(device, "parent_device_id", _MISSING)
    if modern_parent_id is not _MISSING:
        return cast(str | None, modern_parent_id)
    return cast(str | None, getattr(device, "via_device_id", None))


def update_device_identifiers(
    registry: dr.DeviceRegistry,
    device: dr.DeviceEntry,
    identifiers: set[tuple[str, str]],
) -> None:
    """Update identifiers via the correct main-device or child-device API."""
    child_updater = getattr(registry, "async_update_child_device", None)
    if callable(child_updater) and getattr(device, "parent_device_id", _MISSING) is not _MISSING:
        child_updater(device.id, new_identifiers=identifiers)
        return
    registry.async_update_device(device.id, new_identifiers=identifiers)


def resolve_parent_device_id(
    registry: dr.DeviceRegistry,
    parent_identifier: tuple[str, str],
    entry_id: str,
) -> str | None:
    """Resolve a real, uniquely owned parent ID for modern ``DeviceInfo``."""
    parent = find_device_by_identifier(registry, parent_identifier, entry_id)
    if parent is None:
        return None
    # The new API guarantees uniqueness inside this ConfigEntry. Identical
    # identifiers in another entry are valid and must not affect this result.
    return parent.id


def build_device_info(
    hass: HomeAssistant | None,
    entry_id: str,
    *,
    identifiers: set[tuple[str, str]],
    name: str,
    manufacturer: str,
    model: str,
    parent_identifier: tuple[str, str] | None = None,
) -> DeviceInfo:
    """Build DeviceInfo using the parent-link contract supported by this HA."""
    info: dict[str, Any] = {
        "identifiers": identifiers,
        "name": name,
        "manufacturer": manufacturer,
        "model": model,
    }
    if parent_identifier is not None:
        if hass is None:
            # Lightweight constructor callers (including old API evidence)
            # have no registry context. Production coordinators always carry
            # hass, so modern setup still resolves a real via_device_id.
            info["via_device"] = parent_identifier
            return cast(DeviceInfo, info)
        registry = dr.async_get(hass)
        modern_lookup = getattr(registry, "async_get_device_by_identifier", None)
        if callable(modern_lookup):
            parent_id = resolve_parent_device_id(registry, parent_identifier, entry_id)
            if parent_id is None:
                _LOGGER.warning(
                    "Cannot link Jackery child device: parent ownership is unresolved for config entry %s",
                    entry_id,
                )
            else:
                info["via_device_id"] = parent_id
        else:
            # HA 2025.8 accepts the identifier pair and resolves it when
            # registering the child. No synthetic HA device ID is created.
            info["via_device"] = parent_identifier
    return cast(DeviceInfo, info)


def find_owned_main_entity(
    hass: HomeAssistant,
    *,
    domain: str,
    host: str,
    platform: str,
    config_entry_id: str,
    unique_id: str,
) -> er.RegistryEntry | None:
    """Find one exact entity owned by this entry and its exclusively owned host device."""
    entity_registry = er.async_get(hass)
    matches = [
        entity
        for entity in er.async_entries_for_config_entry(entity_registry, config_entry_id)
        if entity.domain == domain
        and entity.platform == platform
        and entity.unique_id == unique_id
    ]
    if len(matches) != 1:
        return None

    entity = matches[0]
    if entity.device_id is None:
        return None

    device_registry = dr.async_get(hass)
    main_devices = [
        device
        for device in find_devices_by_identifier(device_registry, (platform, host))
        if device.id == entity.device_id
        and device_owned_by_entry(device, config_entry_id)
        and not any(
            domain == platform and identifier.startswith(("sub_", "child:"))
            for domain, identifier in device.identifiers
        )
    ]
    return entity if len(main_devices) == 1 else None
