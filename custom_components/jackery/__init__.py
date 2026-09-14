"""Energy Monitor MQTT Integration for Home Assistant."""
import asyncio
import logging
from typing import cast

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

_LOGGER = logging.getLogger(__name__)

DOMAIN = "jackery"
PLATFORMS = [Platform.SENSOR, Platform.SWITCH, Platform.NUMBER, Platform.BUTTON, Platform.SELECT]


async def _migrate_unique_ids(
    hass: HomeAssistant, entry: ConfigEntry, *, protected_entities: set[str] | None = None,
) -> None:
    """Migrate entity unique IDs from v1.x single-instance format to v2.0 multi-instance format.

    Old main-sensor format:    jackery_{sensor_id}
    New main-sensor format:    jackery_{device_sn}_{sensor_id}

    Old switch/number format:  jackery_main_{mqtt_key}
    New switch format:         jackery_{device_sn}_switch_{mqtt_key}
    New number format:         jackery_{device_sn}_number_{mqtt_key}

    Old control-entity format: jackery_{config_entry_id}_{x}
    New control-entity format: jackery_{device_sn}_{x}

    Child identities belong to the separate preflight migration and are left as-is.
    Registry ownership and HA domain/platform identity govern every mutation.

    v2.0.1 bug residue: entities with unique_id jackery_{device_sn}_main_{key} were
    created by the buggy v2.0.1 migration — they are removed here.
    """
    device_sn = entry.data.get("device_sn", "").strip()
    if not device_sn:
        return

    from .entities.sensor_definitions import SENSORS, SUBDEVICE_SENSORS

    entry_id = entry.entry_id
    new_prefix = f"jackery_{device_sn}_"

    ent_reg = er.async_get(hass)
    all_entries = list(er.async_entries_for_config_entry(ent_reg, entry_id))
    device_reg = dr.async_get(hass)
    child_groups = {
        "smartmeter_": "ct_3phase", "SmartMeter_": "ct_3phase",
        "battery_": "expansion_battery", "Battery_": "expansion_battery",
        "plug_": "plug", "ct_": "ct", "collector_": "collector",
    }

    for entity_entry in all_entries:
        if protected_entities and entity_entry.entity_id in protected_entities:
            continue
        uid = entity_entry.unique_id
        if entity_entry.platform != DOMAIN or not uid or not uid.startswith("jackery_") or uid.startswith("jackery_child:"):
            continue

        device = device_reg.async_get(entity_entry.device_id) if entity_entry.device_id else None
        if device:
            if device.config_entries != {entry_id}:
                _LOGGER.warning("Skipping identity migration for entity %s: device ownership is ambiguous", entity_entry.entity_id)
                continue
            # The device identifier stores the whole serial; never split serials at underscores.
            if any(domain == DOMAIN and identifier.startswith(("sub_", "child:")) for domain, identifier in device.identifiers):
                continue

        if uid.startswith(new_prefix):
            suffix_after_sn = uid[len(new_prefix):]
            # Remove wrongly-migrated jackery_{sn}_main_* entities from v2.0.1 bug 2
            if (
                entity_entry.domain == "sensor"
                and suffix_after_sn.startswith("main_")
                and suffix_after_sn[len("main_"):] in SENSORS
            ):
                _LOGGER.info(
                    "Removing v2.0.1 wrongly-migrated entity: %s (%s)",
                    uid, entity_entry.entity_id,
                )
                ent_reg.async_remove(entity_entry.entity_id)
            # Remove obsolete select entity replaced by number slider in v2.3.2
            elif entity_entry.domain == "select" and suffix_after_sn == "max_feed_in_select":
                _LOGGER.info(
                    "Removing obsolete select entity (replaced by number slider): %s (%s)",
                    uid, entity_entry.entity_id,
                )
                ent_reg.async_remove(entity_entry.entity_id)
            continue

        suffix = uid[len("jackery_"):]

        # Known main keys (e.g. battery_soc) overlap child family prefixes.
        # Use exact keys and device links, never the serial's case or alphabet.
        child_prefix = next((prefix for prefix in child_groups if suffix.startswith(prefix)), None)
        if child_prefix:
            if entity_entry.domain != "sensor" or suffix not in SENSORS:
                continue
            if device is None:
                rest = suffix[len(child_prefix):]
                keys = cast(dict[str, object], SUBDEVICE_SENSORS[child_groups[child_prefix]])
                if any(
                    rest.endswith(f"_{key}") and len(rest) > len(key) + 1
                    for raw_key in keys for key in (raw_key, raw_key.replace("_", ""))
                ):
                    _LOGGER.warning("Skipping identity migration for %s: main/child identity is ambiguous", entity_entry.entity_id)
                    continue

        # Determine target unique_id
        if suffix.startswith(f"{entry_id}_"):
            # Control entities: jackery_{entry_id}_{x} → jackery_{device_sn}_{x}
            new_suffix = suffix[len(f"{entry_id}_"):]
            target_uid = f"{new_prefix}{new_suffix}"
        elif suffix.startswith("main_"):
            # Switches/numbers: use entity_id platform prefix to pick correct target
            mqtt_key = suffix[len("main_"):]
            if entity_entry.entity_id.startswith("switch."):
                target_uid = f"{new_prefix}switch_{mqtt_key}"
            elif entity_entry.entity_id.startswith("number."):
                target_uid = f"{new_prefix}number_{mqtt_key}"
            else:
                target_uid = f"{new_prefix}{suffix}"
        else:
            # Main sensors: jackery_{sensor_id} → jackery_{device_sn}_{sensor_id}
            target_uid = f"{new_prefix}{suffix}"

        target_id = ent_reg.async_get_entity_id(entity_entry.domain, entity_entry.platform, target_uid)
        if target_id is not None:
            # Even same-entry duplicates may hold user settings/history. A matching
            # UID does not establish that either record is an expendable orphan.
            _LOGGER.warning(
                "Skipping identity migration for %s: target %s already exists; retaining both records",
                entity_entry.entity_id, target_id,
            )
            continue
        _LOGGER.info("Migrating unique_id: %s → %s", uid, target_uid)
        ent_reg.async_update_entity(entity_entry.entity_id, new_unique_id=target_uid)

    # Global identifiers require exclusive ownership before an in-place update.
    old_device = device_reg.async_get_device(identifiers={(DOMAIN, entry_id)})
    if old_device:
        target_device = device_reg.async_get_device(identifiers={(DOMAIN, device_sn)})
        if old_device.config_entries != {entry_id} or (target_device and target_device.id != old_device.id):
            _LOGGER.warning("Skipping main device migration for entry %s: ownership or target conflict", entry_id)
            return
        device_reg.async_update_device(
            old_device.id,
            new_identifiers=(old_device.identifiers - {(DOMAIN, entry_id)}) | {(DOMAIN, device_sn)},
        )
        _LOGGER.info("Migrated device identifier: %s → %s", entry_id, device_sn)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Jackery from a config entry."""
    _LOGGER.info("Setting up Jackery integration")

    if not await mqtt.async_wait_for_mqtt_client(hass):
        _LOGGER.error(
            "MQTT integration is not available or not configured. "
            "Please set up the MQTT integration first: "
            "Settings -> Devices & Services -> Add Integration -> MQTT"
        )
        return False

    _LOGGER.info("MQTT integration is available and ready")

    from .child_migration import migrate_child_identities

    # Child preflight precedes all platform creation; conflicts must not cause
    # discovery to replace the retained legacy records with fresh entities.
    child_migration = migrate_child_identities(hass, entry)

    # Keep the existing main-device migration, excluding old/new child records.
    await _migrate_unique_ids(hass, entry, protected_entities=child_migration.protected_entities)

    # All platforms need the same runtime object, regardless of forwarding order.
    from .sensor import JackeryDataCoordinator

    config = entry.data
    coordinator = JackeryDataCoordinator(
        hass, config.get("topic_prefix", "hb"), config.get("token"),
        config.get("mqtt_host"), config.get("device_sn"),
    )
    coordinator.config_entry_id = entry.entry_id
    coordinator._child_migration = child_migration
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "config": entry.data,
        "coordinator": coordinator,
    }

    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        # Discovery must not run until both dynamic entity callbacks are installed.
        await coordinator.async_start()
    except (Exception, asyncio.CancelledError):
        # HA cannot unload a coordinator whose setup never completed. Release
        # resources here, including already-forwarded entity platforms.
        try:
            await coordinator.async_stop()
        finally:
            if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
                hass.data[DOMAIN].pop(entry.entry_id, None)
        raise

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.info("Unloading Jackery integration")

    entry_data = hass.data[DOMAIN].get(entry.entry_id, {})
    coordinator = entry_data.get("coordinator")
    try:
        if coordinator:
            await coordinator.async_stop()
    finally:
        # A faulty unsubscribe must not prevent entity references being released.
        unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
