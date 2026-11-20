"""Read-only recognition of the inherited Official 1.0 -> 2.0 CT split."""

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from . import DOMAIN
from .entities.sensor_definitions import SMARTMETER_HTTP_SENSOR_CONFIGS, SUBDEVICE_SENSORS
from .identity import child_device_identifier, child_unique_id, http_unique_id
from .registry_identity import device_owned_by_entry, device_parent_id, get_device_by_id, iter_all_devices

OFFICIAL_TYPE3_CT_KEYS = {
    "powertotalforward": "import_total",
    "poweraforward": "import_l1",
    "powerbforward": "import_l2",
    "powercforward": "import_l3",
    "powertotalreverse": "export_total",
    "powerareverse": "export_l1",
    "powerbreverse": "export_l2",
    "powercreverse": "export_l3",
    "energyforward": "import_energy_total",
    "energyreverse": "export_energy_total",
}


@dataclass(frozen=True)
class OfficialResidue:
    """A proven historical/active pair; names and labels are never evidence."""

    historical_device_id: str
    active_device_id: str


def match_official_residue(
    hass: HomeAssistant, entry: ConfigEntry, serial: str, associated: list[dr.DeviceEntry],
) -> OfficialResidue | None:
    """Accept only the observed two old CT fields alongside all ten newer ones.

    Support partial NG writes and later NG discovery without broadening this
    into a generic duplicate-device repair. No registry mutations occur here.
    """
    host = entry.data.get("device_sn")
    if not isinstance(host, str) or not host or host != host.strip() or len(associated) != 2:
        return None
    devices, entities = dr.async_get(hass), er.async_get(hass)
    old_identifier = (DOMAIN, f"sub_{serial}")
    old = [device for device in associated if device.identifiers == {old_identifier}]
    if len(old) != 1:
        return None
    historical = old[0]
    active = next(device for device in associated if device.id != historical.id)
    allowed_identifiers = {
        (DOMAIN, f"sub_{host}_{serial}"),
        (DOMAIN, child_device_identifier(host, serial)),
    }
    if not active.identifiers or not active.identifiers.issubset(allowed_identifiers):
        return None
    # Even another entry's record must not occupy one of these exact targets.
    candidates = [
        device for device in iter_all_devices(devices)
        if device.identifiers.intersection(allowed_identifiers | {old_identifier})
    ]
    if {device.id for device in candidates} != {historical.id, active.id}:
        return None

    parent_id = device_parent_id(historical)
    parent = get_device_by_id(devices, parent_id) if parent_id else None
    if (
        parent is None
        or device_parent_id(active) != parent_id
        or (DOMAIN, host) not in parent.identifiers
        or not device_owned_by_entry(parent, entry.entry_id)
    ):
        return None
    for device, expected_type in ((historical, 2), (active, 3)):
        if not device_owned_by_entry(device, entry.entry_id):
            return None
        # Lightweight modern children have neither model nor connections.
        # Avoid their deprecated compatibility attributes entirely.
        if getattr(device, "parent_device_id", None) is None and (
            device.manufacturer != "Jackery"
            or device.model != f"Sub-device Type {expected_type}"
            or device.connections
        ):
            return None
    if any(device_parent_id(device) in {historical.id, active.id} for device in iter_all_devices(devices)):
        return None

    def linked(device_id: str) -> list[er.RegistryEntry]:
        return list(er.async_entries_for_device(entities, device_id, include_disabled_entities=True))

    old_entities, active_entities = linked(historical.id), linked(active.id)
    if any(
        entity.platform != DOMAIN or entity.domain != "sensor" or entity.config_entry_id != entry.entry_id
        for entity in (*old_entities, *active_entities)
    ):
        return None
    prefix = f"jackery_{host}_ct_{serial}_"
    if len(old_entities) != 2 or {entity.unique_id for entity in old_entities} != {
        f"{prefix}power", f"{prefix}energy",
    }:
        return None

    core_targets = {
        child_unique_id(host, serial, "smartmeter", key.replace("_", ""))
        for key in OFFICIAL_TYPE3_CT_KEYS.values()
    }
    aliases = {
        f"{prefix}{old_key}": child_unique_id(host, serial, "smartmeter", key.replace("_", ""))
        for old_key, key in OFFICIAL_TYPE3_CT_KEYS.items()
    }
    known_targets = {
        child_unique_id(host, serial, "smartmeter", key.replace("_", ""))
        for key in SUBDEVICE_SENSORS["ct_3phase"]
    } | {http_unique_id(host, serial, key) for key in SMARTMETER_HTTP_SENSOR_CONFIGS}
    observed = set()
    for entity in active_entities:
        target = aliases.get(entity.unique_id, entity.unique_id)
        existing = entities.async_get_entity_id("sensor", DOMAIN, target)
        if (
            target not in known_targets
            or target in observed
            or (existing is not None and existing != entity.entity_id)
        ):
            return None
        observed.add(target)
    if not core_targets.issubset(observed):
        return None
    return OfficialResidue(historical.id, active.id)


def historical_device_serial(hass: HomeAssistant, entry: ConfigEntry, device: dr.DeviceEntry) -> str | None:
    """Validate the historical half independently of the active card's lifetime."""
    if len(device.identifiers) != 1:
        return None
    raw = next(iter(device.identifiers))
    if not isinstance(raw, tuple) or len(raw) != 2:
        return None
    domain, identifier = raw
    if domain != DOMAIN or not isinstance(identifier, str) or not identifier.startswith("sub_") or not identifier[4:]:
        return None
    serial = identifier[4:]
    host = entry.data.get("device_sn")
    if not isinstance(host, str) or not host or host != host.strip() or not device_owned_by_entry(device, entry.entry_id):
        return None
    if getattr(device, "parent_device_id", None) is None and (
        device.manufacturer != "Jackery" or device.model != "Sub-device Type 2" or device.connections
    ):
        return None
    devices = dr.async_get(hass)
    parent_id = device_parent_id(device)
    parent = get_device_by_id(devices, parent_id) if parent_id else None
    if parent is None or not device_owned_by_entry(parent, entry.entry_id) or (DOMAIN, host) not in parent.identifiers:
        return None
    linked = er.async_entries_for_device(er.async_get(hass), device.id, include_disabled_entities=True)
    if len(linked) != 2 or any(
        entity.domain != "sensor" or entity.platform != DOMAIN or entity.config_entry_id != entry.entry_id
        for entity in linked
    ) or {entity.unique_id for entity in linked} != {
        f"jackery_{host}_ct_{serial}_power", f"jackery_{host}_ct_{serial}_energy",
    }:
        return None
    if any(device_parent_id(candidate) == device.id for candidate in iter_all_devices(devices)):
        return None
    return serial


def historical_device_is_removable(
    hass: HomeAssistant, entry: ConfigEntry, device: dr.DeviceEntry, *, retained_ids: frozenset[str] = frozenset(),
) -> bool:
    """Revalidate persisted registry evidence at the user's deletion request."""
    current = get_device_by_id(dr.async_get(hass), device.id)
    if current is None:
        return False
    device = current
    serial = historical_device_serial(hass, entry, device)
    if serial is None:
        return False
    host = entry.data["device_sn"]
    identifiers = {
        (DOMAIN, f"sub_{serial}"),
        (DOMAIN, f"sub_{host}_{serial}"),
        (DOMAIN, child_device_identifier(host, serial)),
    }
    associated = [
        candidate for candidate in iter_all_devices(dr.async_get(hass))
        if candidate.identifiers.intersection(identifiers)
    ]
    pair = match_official_residue(hass, entry, serial, associated)
    return (pair is not None and pair.historical_device_id == device.id) or (
        device.id in retained_ids and len(associated) == 1 and associated[0].id == device.id
    )
