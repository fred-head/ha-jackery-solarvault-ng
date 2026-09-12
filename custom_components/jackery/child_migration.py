"""Preflight and in-place migration of host-scoped child registry identities."""

import logging
from dataclasses import dataclass, field
from hashlib import sha256
from typing import cast

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from . import DOMAIN
from .identity import (
    child_device_identifier,
    child_unique_id,
    http_unique_id,
    parse_child_device_identifier,
    parse_child_unique_id,
)

_LOGGER = logging.getLogger(__name__)
_FAMILIES = {
    "battery": "expansion_battery", "ct": "ct", "smartmeter": "ct_3phase",
    "collector": "collector", "plug": "plug",
}
_PREFIXES = {**{family: family for family in _FAMILIES}, "SmartMeter": "smartmeter", "Battery": "battery"}


@dataclass
class ChildMigrationResult:
    """Discovery must not create replacements for unresolved registry records."""

    blocked_children: set[str] = field(default_factory=set)
    block_all: bool = False
    protected_entities: set[str] = field(default_factory=set)
    _reported_conflicts: set[tuple[str | None, str]] = field(default_factory=set, repr=False)

    def allows(self, serial: str) -> bool:
        return not self.block_all and serial not in self.blocked_children


@dataclass(frozen=True)
class _ChildPlan:
    serial: str
    device_id: str | None
    identifiers: frozenset[tuple[str, str]]
    entities: tuple[tuple[str, str], ...]


def _conflict(result: ChildMigrationResult, entry_id: str, serial: str | None, category: str) -> None:
    if serial is None:
        result.block_all = True
    else:
        result.blocked_children.add(serial)
    if (serial, category) in result._reported_conflicts:
        return
    result._reported_conflicts.add((serial, category))
    # Stable opaque references allow correlation without disclosing raw serials.
    reference = sha256((serial or "unknown").encode()).hexdigest()[:12]
    _LOGGER.warning(
        "Child identity migration refused for entry %s, child ref %s (%s). "
        "Existing records are retained and affected child discovery is paused. "
        "Back up the registries, resolve ownership/identity conflicts with maintainer "
        "assistance, then reload the entry; do not delete history to retry migration.",
        entry_id, reference, category,
    )


def _legacy_candidates(uid: str, domain: str, keys: dict[str, set[str]]) -> set[tuple[str, str, str]]:
    """Match known prefix/field boundaries, preserving the entire middle serial."""
    matches = set()
    for prefix, family in _PREFIXES.items():
        start = f"jackery_{prefix}_"
        if not uid.startswith(start):
            continue
        fields = {"switch"} if domain == "switch" and family == "plug" else keys[family] if domain == "sensor" else set()
        for key in fields:
            end = f"_{key}"
            if uid.endswith(end) and len(uid) > len(start) + len(end):
                matches.add((uid[len(start):-len(end)], family, key.replace("_", "")))
    return matches


def _known_field(domain: str, family: str, key: str, keys: dict[str, set[str]], http_keys: set[str]) -> bool:
    """Use the same HA domain and canonical field tokens as entity creation."""
    return (
        (domain == "sensor" and family in keys and key in {k.replace("_", "") for k in keys[family]})
        or (domain == "switch" and family == "plug" and key == "switch")
        or (domain == "sensor" and family == "http" and key in http_keys)
    )


def _http_serials(uid: str, host: str, keys: set[str]) -> set[str]:
    """Match a legacy HTTP identity with known host and field boundaries."""
    start = f"jackery_{host}_http_sm_"
    return {
        uid[len(start):-len(key) - 1] for key in keys
        if uid.startswith(start) and uid.endswith(f"_{key}") and len(uid) > len(start) + len(key) + 1
    }


def migrate_child_identities(hass: HomeAssistant, entry: ConfigEntry) -> ChildMigrationResult:
    """Inspect the complete entry before applying any validated child plan.

    Run on every setup. Persistent registry state is the resume marker; a config
    version cannot represent a mixture of successful and conflicted children.
    All calls here are synchronous HA callbacks, so preflight/apply cannot yield
    to discovery or another entry's setup between validation and registry writes.
    """
    from .sensor import SENSORS, SMARTMETER_HTTP_SENSOR_CONFIGS, SUBDEVICE_SENSORS

    result = ChildMigrationResult()
    host = entry.data.get("device_sn")
    if not isinstance(host, str) or not host or host != host.strip():
        _conflict(result, entry.entry_id, None, "ambiguous-host-identity")
        return result

    keys: dict[str, set[str]] = {}
    for family, group in _FAMILIES.items():
        fields = cast(dict[str, object], SUBDEVICE_SENSORS[group])
        keys[family] = {key for raw in fields for key in (raw, raw.replace("_", ""))}
    # Recorded historical SmartMeter IDs predate the current phase-specific fields.
    keys["smartmeter"].update({"power", "energy"})
    http_keys = set(SMARTMETER_HTTP_SENSOR_CONFIGS)

    devices, entities = dr.async_get(hass), er.async_get(hass)
    own_entities = list(er.async_entries_for_config_entry(entities, entry.entry_id))
    referenced = {entity.device_id for entity in own_entities if entity.device_id}
    by_device: dict[str, str] = {}
    child_devices: dict[str, list[dr.DeviceEntry]] = {}
    child_entities: dict[str, dict[str, er.RegistryEntry]] = {}
    main_identifiers = {(DOMAIN, host), (DOMAIN, entry.entry_id)}
    main_target = devices.async_get_device(identifiers={(DOMAIN, host)})
    if parse_child_device_identifier(host) and main_target and main_target.config_entries != {entry.entry_id}:
        _conflict(result, entry.entry_id, None, "main-child-namespace-conflict")
        raise ConfigEntryError(
            "The configured host identity overlaps an existing child owned by another entry. "
            "Registry records were retained; resolve the identity conflict before reloading."
        )

    for entity in entities.entities.values():
        if entity.platform == DOMAIN and entity.config_entry_id != entry.entry_id:
            scoped_entity = parse_child_unique_id(entity.unique_id)
            if scoped_entity and scoped_entity[0] == host and _known_field(entity.domain, *scoped_entity[2:], keys, http_keys):
                _conflict(result, entry.entry_id, scoped_entity[1], "foreign-entity-target")
            if entity.domain == "sensor" and "_http_sm_" not in host:
                for serial in _http_serials(entity.unique_id, host, http_keys):
                    if "_http_sm_" not in serial:
                        _conflict(result, entry.entry_id, serial, "foreign-http-entity-target")

    # Also inspect foreign new-format targets for this host, before HA can claim
    # them through entity device_info on setup. Foreign legacy children remain
    # available for their actual owner's later migration to a different namespace.
    for device in devices.devices.values():
        identifiers = [identifier for domain, identifier in device.identifiers if domain == DOMAIN]
        # Main serials themselves may start with "child:" or "sub_". An exact
        # main identifier is not a child-prefix match.
        if device.identifiers.intersection(main_identifiers) and len(identifiers) == 1:
            continue
        scoped = [decoded_device for identifier in identifiers if (decoded_device := parse_child_device_identifier(identifier))]
        if entry.entry_id not in device.config_entries and device.id not in referenced and not any(h == host for h, _ in scoped):
            continue
        serials = {identifier[len("sub_"):] for identifier in identifiers if identifier.startswith("sub_")}
        serials.update(serial for _, serial in scoped)
        malformed = any(identifier.startswith("child:") and parse_child_device_identifier(identifier) is None for identifier in identifiers)
        if malformed or "" in serials:
            _conflict(result, entry.entry_id, None, "malformed-device-identity")
        if not serials:
            continue
        if len(serials) != 1:
            for serial in serials:
                _conflict(result, entry.entry_id, serial, "multiple-child-identifiers")
            continue
        serial = next(iter(serials))
        if any(not identifier.startswith(("sub_", "child:")) for identifier in identifiers):
            _conflict(result, entry.entry_id, serial, "unrecognized-device-alias")
        by_device[device.id] = serial
        child_devices.setdefault(serial, []).append(device)
        child_entities.setdefault(serial, {}).update({
            e.entity_id: e for e in er.async_entries_for_device(entities, device.id, include_disabled_entities=True)
        })
        result.protected_entities.update(child_entities[serial])
        if device.config_entries != {entry.entry_id}:
            _conflict(result, entry.entry_id, serial, "foreign-or-shared-device")
        if any(h != host for h, _ in scoped):
            _conflict(result, entry.entry_id, serial, "host-identifier-mismatch")
        if device.via_device_id:
            parent = devices.async_get(device.via_device_id)
            if parent is None or parent.config_entries != {entry.entry_id} or not parent.identifiers.intersection({(DOMAIN, host), (DOMAIN, entry.entry_id)}):
                _conflict(result, entry.entry_id, serial, "parent-ownership-mismatch")

    # Resolve unlinked records conservatively as well: leaving one legacy record
    # behind while discovery creates its new counterpart would fragment history.
    for entity in own_entities:
        if entity.platform != DOMAIN or entity.device_id in by_device:
            continue
        uid = entity.unique_id
        linked_device = devices.async_get(entity.device_id) if entity.device_id else None
        if linked_device and linked_device.identifiers.intersection(main_identifiers):
            # The registry link disambiguates a main host named e.g. "plug"
            # from a legacy plug prefix. Unlinked ambiguous records are refused.
            main_suffix = uid.removeprefix(f"jackery_{host}_")
            if (
                (entity.domain == "sensor" and (main_suffix in SENSORS or uid.removeprefix("jackery_") in SENSORS))
                or (entity.domain in {"switch", "number"} and main_suffix.startswith(f"{entity.domain}_"))
                or (entity.domain == "select" and main_suffix in {"auto_standby_select", "work_mode_select", "max_feed_in_select"})
                or (entity.domain == "button" and main_suffix == "reboot")
            ):
                continue
        parsed = parse_child_unique_id(uid)
        candidates = _legacy_candidates(uid, entity.domain, keys)
        http_start = f"jackery_{host}_http_sm_"
        http_serials = _http_serials(uid, host, http_keys) if entity.domain == "sensor" else set()
        looks_child = uid.startswith(("jackery_child:", http_start, *(f"jackery_{prefix}_" for prefix in _PREFIXES)))
        if not looks_child:
            continue
        # A main device link disambiguates overlapping legacy main field names.
        is_main_key = entity.domain == "sensor" and uid.removeprefix("jackery_") in SENSORS
        if is_main_key and not candidates:
            continue
        result.protected_entities.add(entity.entity_id)
        serials = {c[0] for c in candidates} | http_serials
        if parsed:
            serials.add(parsed[1])
        if len(serials) != 1:
            _conflict(result, entry.entry_id, None, "unresolved-entity-identity")
            continue
        serial = next(iter(serials))
        child_entities.setdefault(serial, {})[entity.entity_id] = entity
        if entity.device_id or is_main_key:
            _conflict(result, entry.entry_id, serial, "ambiguous-entity-device-link")

    plans = []
    for serial in child_entities.keys() | child_devices.keys():
        associated = child_devices.get(serial, [])
        if len(associated) > 1:
            _conflict(result, entry.entry_id, serial, "duplicate-device-target")
            continue
        planned_device = associated[0] if associated else None
        target_identifier = (DOMAIN, child_device_identifier(host, serial))
        target_device = devices.async_get_device(identifiers={target_identifier})
        if target_device is not None and (planned_device is None or target_device.id != planned_device.id):
            _conflict(result, entry.entry_id, serial, "device-target-conflict")
        updates = []
        targets: set[tuple[str, str, str]] = set()
        for entity in child_entities.get(serial, {}).values():
            if entity.config_entry_id != entry.entry_id or entity.platform != DOMAIN:
                _conflict(result, entry.entry_id, serial, "foreign-entity-on-device")
                continue
            uid = entity.unique_id
            parsed = parse_child_unique_id(uid)
            if parsed:
                h, c, family, key = parsed
                valid = h == host and c == serial and _known_field(entity.domain, family, key, keys, http_keys)
                target = uid if valid else None
            else:
                matches = {m for m in _legacy_candidates(uid, entity.domain, keys) if m[0] == serial}
                target = child_unique_id(host, serial, *next(iter(matches))[1:]) if len(matches) == 1 else None
                if entity.domain == "sensor":
                    for key in SMARTMETER_HTTP_SENSOR_CONFIGS:
                        if uid == f"jackery_{host}_http_sm_{serial}_{key}":
                            target = http_unique_id(host, serial, key)
                            break
            if target is None:
                _conflict(result, entry.entry_id, serial, "unknown-or-mismatched-entity-id")
                continue
            identity = (entity.domain, entity.platform, target)
            existing = entities.async_get_entity_id(*identity)
            if (existing is not None and existing != entity.entity_id) or identity in targets:
                _conflict(result, entry.entry_id, serial, "entity-target-conflict")
            targets.add(identity)
            if target != uid:
                updates.append((entity.entity_id, target))
        new_identifiers = frozenset(
            (planned_device.identifiers - {(DOMAIN, f"sub_{serial}")}) | {target_identifier}
        ) if planned_device else frozenset()
        plans.append(_ChildPlan(serial, planned_device.id if planned_device else None, new_identifiers, tuple(updates)))

    # No mutation above this line. A conflict vetoes the entire child's plan,
    # including siblings whose own target would otherwise be safe.
    for plan in plans:
        if not result.allows(plan.serial):
            continue
        if plan.device_id:
            current = devices.async_get(plan.device_id)
            if current is not None and current.identifiers != plan.identifiers:
                devices.async_update_device(plan.device_id, new_identifiers=set(plan.identifiers))
        for entity_id, target in plan.entities:
            entities.async_update_entity(entity_id, new_unique_id=target)
    return result
