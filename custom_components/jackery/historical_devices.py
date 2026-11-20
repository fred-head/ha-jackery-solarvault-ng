"""Label retained Official inventory and explain user-controlled cleanup."""

from typing import Any

from homeassistant.components import persistent_notification as pn
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import label_registry as lr
from homeassistant.helpers.storage import Store
from homeassistant.helpers.translation import async_get_translations

from . import DOMAIN
from .registry_identity import get_device_by_id

STORAGE_PREFIX = f"{DOMAIN}.historical_devices"
_TRANSLATION_PREFIX = f"component.{DOMAIN}.issues.official_child_residue"
_TITLE = "Jackery: old device – review"
_DESCRIPTION = (
    "An earlier update of the official Jackery integration left two device records for the same meter. "
    "SolarVault NG has completed takeover of the [active device]({active_device_url}). "
    "The [old device]({old_device_url}) and its sensor entries have been retained; these old sensors "
    "will not receive new readings. Check automations, dashboards and external monitoring for references "
    "to the old sensors and update them if needed. You may keep the old device or delete it after checking. "
    "Deleting it also removes its associated entity entries; continued access to their history is not guaranteed. "
    "The separate Shelly integration is unaffected."
)


def notification_id(entry_id: str, device_id: str) -> str:
    """Use registry IDs rather than serials for UI notification identity."""
    return f"{STORAGE_PREFIX}.{entry_id}.{device_id}"


async def async_load_historical_state(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    """Load durable inventory classification and notification acknowledgements."""
    saved = await Store[dict[str, Any]](hass, 1, f"{STORAGE_PREFIX}.{entry.entry_id}").async_load()
    return saved if isinstance(saved, dict) else {}


def retained_device_ids(saved: dict[str, Any]) -> frozenset[str]:
    """Persisted IDs are hints; callers must also revalidate registry evidence."""
    values = saved.get("historical_device_ids", [])
    return frozenset(value for value in values if isinstance(value, str)) if isinstance(values, list) else frozenset()


async def async_mark_historical_devices(
    hass: HomeAssistant, entry: ConfigEntry, pairs: dict[str, str], *, saved: dict[str, Any] | None = None,
) -> None:
    """Keep dismissal across restarts and clear notices when old cards go away.

    Stored classification also prevents old inventory from being reactivated
    after the active meter is unbound. Never authorize writes/deletion from
    these IDs without independently revalidating actual registry evidence.
    """
    store: Store[dict[str, Any]] = Store(hass, 1, f"{STORAGE_PREFIX}.{entry.entry_id}")
    saved = saved if saved is not None else await async_load_historical_state(hass, entry)
    if not pairs and not saved:
        return
    acknowledged = {
        value for value in saved.get("acknowledged", []) if isinstance(value, str)
    } if isinstance(saved.get("acknowledged"), list) else set()
    previous = saved.get("devices", {})
    if not isinstance(previous, dict):
        previous = {}
    devices = dr.async_get(hass)
    retained = {old for old in retained_device_ids(saved) | pairs.keys() if get_device_by_id(devices, old) is not None}
    pairs = {
        old: active for old, active in pairs.items()
        if get_device_by_id(devices, old) is not None and get_device_by_id(devices, active) is not None
    }
    # A conflict on a later setup also withdraws the old success notice.
    for old in previous.keys() - pairs.keys():
        if isinstance(old, str):
            pn.async_dismiss(hass, notification_id(entry.entry_id, old))
    acknowledged.intersection_update(pairs)
    translations = await async_get_translations(hass, hass.config.language, "issues", {DOMAIN}) if pairs else {}
    title = translations.get(f"{_TRANSLATION_PREFIX}.title", _TITLE)
    description = translations.get(f"{_TRANSLATION_PREFIX}.description", _DESCRIPTION)
    labels = lr.async_get(hass)
    label_id = saved.get("label_id")
    label = labels.async_get_label(label_id) if isinstance(label_id, str) else None
    if pairs and label is None:
        label = labels.async_get_label_by_name(title) or labels.async_create(title, icon="mdi:archive-outline")

    for old in pairs:
        device = get_device_by_id(devices, old)
        if device is not None and label is not None and label.label_id not in device.labels:
            updater = (
                getattr(devices, "async_update_child_device")
                if getattr(device, "parent_device_id", None) is not None
                else devices.async_update_device
            )
            updater(device.id, labels=set(device.labels) | {label.label_id})

    @callback
    def data() -> dict[str, Any]:
        return {
            "devices": dict(pairs),
            "acknowledged": sorted(acknowledged),
            "label_id": label.label_id if label is not None else None,
            "historical_device_ids": sorted(retained),
        }

    await store.async_save(data())
    # Flush pending acknowledgements before a reload creates another Store for
    # this key, or explicit config-entry removal deletes the bookkeeping file.
    entry.async_on_unload(lambda: store.async_save(data()))

    @callback
    def notification_updated(update_type: pn.UpdateType, notifications: dict[str, pn.Notification]) -> None:
        if update_type != pn.UpdateType.REMOVED:
            return
        for old in pairs:
            if notification_id(entry.entry_id, old) in notifications:
                acknowledged.add(old)
                store.async_delay_save(data, 0)

    @callback
    def device_removed(event: Event[dr.EventDeviceRegistryUpdatedData]) -> None:
        if event.data["action"] != "remove":
            return
        device_id = event.data["device_id"]
        if device_id in retained:
            retained.remove(device_id)
            store.async_delay_save(data, 0)
        for old, active in list(pairs.items()):
            if device_id not in {old, active}:
                continue
            del pairs[old]
            acknowledged.discard(old)
            pn.async_dismiss(hass, notification_id(entry.entry_id, old))
            store.async_delay_save(data, 0)

    if retained:
        entry.async_on_unload(pn.async_register_callback(hass, notification_updated))
        entry.async_on_unload(hass.bus.async_listen(dr.EVENT_DEVICE_REGISTRY_UPDATED, device_removed))
    for old, active in pairs.items():
        if old not in acknowledged:
            pn.async_create(
                hass,
                description.format(
                    old_device_url=f"/config/devices/device/{old}",
                    active_device_url=f"/config/devices/device/{active}",
                ),
                title=title,
                notification_id=notification_id(entry.entry_id, old),
            )


async def async_remove_historical_state(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove this entry's notices and bookkeeping on explicit integration removal."""
    saved = await async_load_historical_state(hass, entry)
    for old in retained_device_ids(saved):
        pn.async_dismiss(hass, notification_id(entry.entry_id, old))
    await Store[dict[str, Any]](hass, 1, f"{STORAGE_PREFIX}.{entry.entry_id}").async_remove()
