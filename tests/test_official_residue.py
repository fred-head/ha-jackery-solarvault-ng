"""Issue 58: preserve inherited Official inventory and recover after RC1."""

import asyncio
import json
from datetime import timedelta
from functools import partial
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from homeassistant.components import persistent_notification as pn
from homeassistant.components.config.device_registry import websocket_remove_config_entry_from_device
from homeassistant.components.recorder.history import get_significant_states
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import label_registry as lr
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import async_wait_recording_done

from custom_components.jackery import DOMAIN, _migrate_unique_ids, async_remove_config_entry_device, async_remove_entry
from custom_components.jackery.child_migration import migrate_child_identities
from custom_components.jackery.historical_devices import (
    STORAGE_PREFIX,
    async_load_historical_state,
    async_mark_historical_devices,
    notification_id,
    retained_device_ids,
)
from custom_components.jackery.identity import child_device_identifier, child_unique_id, http_unique_id
from custom_components.jackery.official_residue import historical_device_is_removable
from custom_components.jackery.registry_identity import get_device_by_id, iter_all_devices, update_device_identifiers

from .conftest import child_device_info
from .test_child_migration import snapshot
from .test_multi_instance_identity import discover, report
from .test_upgrade_migration_evidence import (
    OFFICIAL_CT3_KEYS,
    SeededState,
    load_fixture,
    setup_current_ng_entry,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")
HOST, CHILD = "SVHOST0001", "SHELLY0001"


def update_device(registry, device, **kwargs):
    updater = (
        registry.async_update_child_device
        if getattr(device, "parent_device_id", None) is not None
        else registry.async_update_device
    )
    return updater(device.id, **kwargs)


def seed_residue(hass, *, lightweight=False):
    """Compose the source-based Official fixture with the reported old residue."""
    residue = json.loads((Path(__file__).parent / "fixtures/upgrades/official_1_to_2_residue.json").read_text())
    fixture = load_fixture(residue["base_fixture"])
    # The base's separate Type 2 example intentionally has unsupported fields;
    # this scenario tests only the proven Type 2 -> Type 3 split and a safe plug.
    fixture["devices"] = [source for source in fixture["devices"] if source["key"] != "meter"]
    fixture["entities"] = [source for source in fixture["entities"] if source["device_key"] != "meter"]
    old = residue["historical_device"]
    fixture["devices"].append({**old, "key": "historical", "area": "Utility room", "serial_number": None})
    fixture["entities"].extend({
        "device_key": "historical", "domain": "sensor", "unique_id": source["unique_id"],
        "role": f"historical_{index}",
        "customization": {"entity_id": source["entity_id"], "name": source["name"], "area": "Utility room"},
    } for index, source in enumerate(residue["historical_entities"]))
    config = fixture["config_entry"]
    entry = MockConfigEntry(domain=DOMAIN, **config)
    entry.add_to_hass(hass)
    devices, entities = dr.async_get(hass), er.async_get(hass)
    area = ar.async_get(hass).async_create("Utility room")
    label = lr.async_get(hass).async_create("My existing label")
    seeded_devices, seeded_entities = {}, {}
    for source in fixture["devices"]:
        info = {
            "identifiers": {tuple(identifier) for identifier in source["identifiers"]},
            "name": source["name"], "manufacturer": source["manufacturer"], "model": source["model"],
        }
        if source["via_device"]:
            info = child_device_info(hass, entry.entry_id, **info, parent_identifier=tuple(source["via_device"]))
        if lightweight and source["key"] in {"historical", "ct3"}:
            device = devices.async_get_or_create_child(
                config_entry_id=entry.entry_id, identifiers=info["identifiers"],
                parent_device_id=seeded_devices["main"].id, name=source["name"],
            )
        else:
            device = devices.async_get_or_create(config_entry_id=entry.entry_id, **info)
        seeded_devices[source["key"]] = update_device(
            devices, device, name_by_user=source["name_by_user"], area_id=area.id, labels={label.label_id},
        )
    for source in fixture["entities"]:
        custom = source["customization"]
        entity = entities.async_get_or_create(
            source["domain"], DOMAIN, source["unique_id"], config_entry=entry,
            device_id=seeded_devices[source["device_key"]].id, suggested_object_id=source["role"],
        )
        seeded_entities[source["role"]] = entities.async_update_entity(
            entity.entity_id, new_entity_id=custom["entity_id"], name=custom["name"],
            icon="mdi:gauge", area_id=area.id, aliases={"My measurement"}, labels={label.label_id},
            hidden_by=er.RegistryEntryHider.USER,
            disabled_by=er.RegistryEntryDisabler.USER if custom.get("disabled_by") else None,
        )
    return SeededState(fixture, entry, seeded_devices, seeded_entities)


@pytest.mark.parametrize("after_rc1", [False, True])
async def test_inherited_official_split_recovers_in_place_including_after_rc1(hass, caplog, after_rc1):
    state = seed_residue(hass)
    devices, entities = dr.async_get(hass), er.async_get(hass)
    historical, active = state.devices["historical"], state.devices["ct3"]
    originals = {entity.entity_id: snapshot(entity) for entity in state.entities.values()}
    if after_rc1:
        # This is RC1's actual refusal path: no recognized exception for the pair.
        with patch("custom_components.jackery.child_migration.match_official_residue", return_value=None):
            refused = migrate_child_identities(hass, state.entry)
        await _migrate_unique_ids(hass, state.entry, protected_entities=refused.protected_entities)
        assert not refused.allows(CHILD)
        assert "duplicate-device-target" in caplog.text
        assert snapshot(get_device_by_id(devices, historical.id)) == snapshot(historical)
        assert snapshot(get_device_by_id(devices, active.id)) == snapshot(active)
        assert all(snapshot(entities.async_get(entity.entity_id)) == originals[entity.entity_id]
                   for role, entity in state.entities.items() if role.startswith(("historical", "ct3")))
        # The safe plug has already migrated and must survive the next setup.
        safe_plug = snapshot(get_device_by_id(devices, state.devices["plug"].id))
    caplog.clear()
    result = migrate_child_identities(hass, state.entry)
    await _migrate_unique_ids(hass, state.entry, protected_entities=result.protected_entities)
    assert result.allows(CHILD)
    assert result.historical_devices == {historical.id: active.id}
    assert "duplicate-device-target" not in caplog.text
    assert snapshot(get_device_by_id(devices, historical.id)) == snapshot(historical)
    assert get_device_by_id(devices, active.id).identifiers == {(DOMAIN, child_device_identifier(HOST, CHILD))}
    for role, original in state.entities.items():
        current = entities.async_get(original.entity_id)
        if role.startswith("historical"):
            assert snapshot(current) == originals[original.entity_id]
            assert original.entity_id in result.protected_entities
        elif role in OFFICIAL_CT3_KEYS:
            assert current.unique_id == child_unique_id(HOST, CHILD, "smartmeter", OFFICIAL_CT3_KEYS[role].replace("_", ""))
            assert snapshot(current, "unique_id", "previous_unique_id", "modified_at") == snapshot(
                original, "unique_id", "previous_unique_id", "modified_at",
            )
    if after_rc1:
        assert snapshot(get_device_by_id(devices, state.devices["plug"].id)) == safe_plug
    before = [snapshot(device) for device in iter_all_devices(devices)], [snapshot(e) for e in entities.entities.values()]
    assert migrate_child_identities(hass, state.entry).historical_devices == result.historical_devices
    assert before == ([snapshot(device) for device in iter_all_devices(devices)], [snapshot(e) for e in entities.entities.values()])


@pytest.mark.parametrize("stage", ["device_first", "entity_first", "some_entities", "both_identifiers"])
async def test_recovers_partial_writes_and_accepts_later_ng_entities(hass, stage):
    state = seed_residue(hass)
    devices, entities = dr.async_get(hass), er.async_get(hass)
    active = state.devices["ct3"]
    target = {(DOMAIN, child_device_identifier(HOST, CHILD))}
    if stage in {"device_first", "both_identifiers"}:
        update_device_identifiers(devices, active, target | (active.identifiers if stage == "both_identifiers" else set()))
    if stage in {"entity_first", "some_entities", "both_identifiers"}:
        for role, key in list(OFFICIAL_CT3_KEYS.items())[:2 if stage == "some_entities" else 10]:
            entities.async_update_entity(state.entities[role].entity_id,
                                         new_unique_id=child_unique_id(HOST, CHILD, "smartmeter", key.replace("_", "")))
    # Additional supported phase energy / HTTP rows must not break recognition.
    for uid in (child_unique_id(HOST, CHILD, "smartmeter", "importenergyl1"), http_unique_id(HOST, CHILD, "frequency")):
        entities.async_get_or_create("sensor", DOMAIN, uid, config_entry=state.entry, device_id=active.id)
    assert migrate_child_identities(hass, state.entry).allows(CHILD)
    assert historical_device_is_removable(hass, state.entry, state.devices["historical"])


@pytest.mark.parametrize("conflict", [
    "foreign_entity", "shared_old_device", "foreign_parent", "extra_old_field", "missing_old_field",
    "missing_active_field", "wrong_model", "foreign_alias", "third_device", "unknown_active_field",
    "target_collision", "dependent_device", "different_old_serial",
])
async def test_only_proven_residue_is_reconciled(hass, caplog, conflict):
    state = seed_residue(hass)
    devices, entities = dr.async_get(hass), er.async_get(hass)
    old, active = state.devices["historical"], state.devices["ct3"]
    other = MockConfigEntry(domain=DOMAIN, unique_id="OTHER", data={"device_sn": "OTHER"})
    other.add_to_hass(hass)
    if conflict == "foreign_entity":
        entities.async_get_or_create("sensor", "shelly", "foreign", config_entry=other, device_id=old.id)
    elif conflict == "shared_old_device":
        if callable(getattr(devices, "async_get_device_by_identifier", None)):
            pytest.skip("Shared device ownership exists only on legacy HA")
        devices.async_update_device(old.id, add_config_entry_id=other.entry_id)
    elif conflict == "foreign_parent":
        parent = devices.async_get_or_create(config_entry_id=other.entry_id, identifiers={(DOMAIN, "OTHER")})
        if getattr(old, "parent_device_id", None) is not None:
            pytest.skip("Modern child parents cannot be reassigned through the update API")
        devices.async_update_device(old.id, via_device_id=parent.id)
    elif conflict == "wrong_model":
        if getattr(old, "parent_device_id", None) is not None:
            pytest.skip("Modern lightweight children intentionally have no model metadata")
        devices.async_update_device(old.id, model="An unrelated model")
    elif conflict == "foreign_alias":
        update_device_identifiers(devices, old, set(old.identifiers) | {("shelly", "foreign")})
    elif conflict in {"extra_old_field", "unknown_active_field"}:
        device = old if conflict == "extra_old_field" else active
        entities.async_get_or_create("sensor", DOMAIN, "unknown", config_entry=state.entry, device_id=device.id)
    elif conflict == "different_old_serial":
        entities.async_update_entity(state.entities["historical_0"].entity_id, new_unique_id="jackery_SVHOST0001_ct_OTHER_power")
    elif conflict in {"missing_old_field", "missing_active_field"}:
        role = "historical_0" if conflict == "missing_old_field" else "ct3_import_total"
        entities.async_remove(state.entities[role].entity_id)
    elif conflict == "third_device":
        devices.async_get_or_create(config_entry_id=state.entry.entry_id, **child_device_info(
            hass, state.entry.entry_id, identifiers={(DOMAIN, child_device_identifier(HOST, CHILD))},
            parent_identifier=(DOMAIN, HOST), name="Third record", manufacturer="Jackery", model="Unknown",
        ))
    elif conflict == "target_collision":
        entities.async_get_or_create("sensor", DOMAIN, child_unique_id(HOST, CHILD, "smartmeter", "importtotal"),
                                     config_entry=state.entry)
    elif conflict == "dependent_device":
        if getattr(old, "parent_device_id", None) is not None:
            pytest.skip("Lightweight children cannot themselves be parents")
        devices.async_get_or_create(config_entry_id=state.entry.entry_id, identifiers={(DOMAIN, "dependent")},
                                    **({"via_device_id": old.id}
                                       if callable(getattr(devices, "async_get_device_by_identifier", None))
                                       else {"via_device": (DOMAIN, f"sub_{CHILD}")}))
    before_old = snapshot(get_device_by_id(devices, old.id))
    before_active = snapshot(get_device_by_id(devices, active.id))
    before_entities = {e.entity_id: snapshot(e) for e in entities.entities.values() if e.device_id in {old.id, active.id}}
    result = migrate_child_identities(hass, state.entry)
    assert not result.allows(CHILD)
    assert not result.historical_devices
    assert not await async_remove_config_entry_device(hass, state.entry, get_device_by_id(devices, old.id))
    assert snapshot(get_device_by_id(devices, old.id)) == before_old
    assert snapshot(get_device_by_id(devices, active.id)) == before_active
    assert {e.entity_id: snapshot(e) for e in entities.entities.values() if e.device_id in {old.id, active.id}} == before_entities
    assert CHILD not in caplog.text


async def test_interrupted_apply_resumes_without_touching_old_inventory(hass):
    state = seed_residue(hass)
    entities = er.async_get(hass)
    update = entities.async_update_entity
    count = 0

    def interrupt(entity_id, **kwargs):
        nonlocal count
        if entity_id in {state.entities[role].entity_id for role in OFFICIAL_CT3_KEYS}:
            count += 1
            if count == 3:
                raise RuntimeError("interrupted")
        return update(entity_id, **kwargs)

    with patch.object(entities, "async_update_entity", interrupt), pytest.raises(RuntimeError, match="interrupted"):
        migrate_child_identities(hass, state.entry)
    result = migrate_child_identities(hass, state.entry)
    assert result.historical_devices == {state.devices["historical"].id: state.devices["ct3"].id}
    assert entities.async_get(state.entities["historical_0"].entity_id) == state.entities["historical_0"]


@pytest.mark.parametrize("language,expected", [("en", "old device"), ("de", "Altbestand"), ("fr", "ancien appareil")])
async def test_marking_notice_and_dismissal_survive_reload(hass, hass_storage, language, expected):
    state = seed_residue(hass)
    hass.config.language = language
    result = migrate_child_identities(hass, state.entry)
    old, active = state.devices["historical"], state.devices["ct3"]
    nid = notification_id(state.entry.entry_id, old.id)
    with patch("custom_components.jackery.historical_devices.pn.async_create", wraps=pn.async_create) as create:
        await async_mark_historical_devices(hass, state.entry, result.historical_devices)
        assert create.call_count == 1
        notice = create.call_args
        assert expected in notice.kwargs["title"]
        assert f"/config/devices/device/{old.id}" in notice.args[1]
        assert f"/config/devices/device/{active.id}" in notice.args[1]
        assert CHILD not in notice.args[1] and HOST not in notice.args[1]
        current = get_device_by_id(dr.async_get(hass), old.id)
        assert current.name_by_user == old.name_by_user
        assert current.labels > old.labels
        assert snapshot(current, "labels", "modified_at") == snapshot(old, "labels", "modified_at")
        assert get_device_by_id(dr.async_get(hass), active.id).labels == active.labels
        assert await async_remove_config_entry_device(hass, state.entry, current)
        assert not await async_remove_config_entry_device(hass, state.entry, active)
        assert not await async_remove_config_entry_device(hass, state.entry, state.devices["main"])
        pn.async_dismiss(hass, nid)
        await asyncio.sleep(0)
        await hass.async_block_till_done()
        key = f"{STORAGE_PREFIX}.{state.entry.entry_id}"
        assert hass_storage[key]["data"]["acknowledged"] == [old.id]
        await state.entry._async_process_on_unload(hass)
        create.reset_mock()
        await async_mark_historical_devices(hass, state.entry, migrate_child_identities(hass, state.entry).historical_devices)
        assert create.call_count == 0
        assert get_device_by_id(dr.async_get(hass), old.id).labels == current.labels
        # Removing the old card clears both the notice and associated entities.
        dr.async_get(hass).async_remove_device(old.id)
        await asyncio.sleep(0)
        await hass.async_block_till_done()
        assert hass_storage[key]["data"]["devices"] == {}
        assert entities_for_device(hass, old.id) == []
        assert entities_for_device(hass, active.id)
        assert migrate_child_identities(hass, state.entry).allows(CHILD)
        await state.entry._async_process_on_unload(hass)


@pytest.mark.parametrize("changed", [False, True])
async def test_archived_card_does_not_reactivate_if_active_meter_was_removed(hass, changed):
    state = seed_residue(hass)
    result = migrate_child_identities(hass, state.entry)
    await async_mark_historical_devices(hass, state.entry, result.historical_devices)
    old = state.devices["historical"]
    dr.async_get(hass).async_remove_device(state.devices["ct3"].id)
    await hass.async_block_till_done()
    await state.entry._async_process_on_unload(hass)
    if changed:
        er.async_get(hass).async_remove(state.entities["historical_0"].entity_id)
    saved = await async_load_historical_state(hass, state.entry)
    assert retained_device_ids(saved) == {old.id}
    current = get_device_by_id(dr.async_get(hass), old.id)
    before = snapshot(current)
    result = migrate_child_identities(hass, state.entry, retained_historical_ids=retained_device_ids(saved))
    await _migrate_unique_ids(hass, state.entry, protected_entities=result.protected_entities)
    assert result.allows(CHILD) is not changed
    assert snapshot(get_device_by_id(dr.async_get(hass), old.id)) == before
    assert await async_remove_config_entry_device(hass, state.entry, current) is not changed


def entities_for_device(hass, device_id):
    return list(er.async_entries_for_device(er.async_get(hass), device_id, include_disabled_entities=True))


async def test_reload_and_manual_deletion_do_not_recreate_old_card(hass):
    state = seed_residue(hass)
    old, active = state.devices["historical"], state.devices["ct3"]
    # The Shelly integration owns a separate device: it must remain untouched.
    shelly_entry = MockConfigEntry(domain="shelly", unique_id="shelly-test")
    shelly_entry.add_to_hass(hass)
    shelly = dr.async_get(hass).async_get_or_create(config_entry_id=shelly_entry.entry_id,
                                                  identifiers={("shelly", "separate-meter")})
    for cycle in range(3):
        coordinator = await setup_current_ng_entry(hass, state.entry)
        assert coordinator.child_identity_allowed(CHILD)
        await discover(hass, coordinator, CHILD, "ct_3phase", 3, 2, "cts")
        report(coordinator, {"cts": [{"sn": CHILD, "devType": 3, "subType": 2, "tPhasePw": 321}]})
        await hass.async_block_till_done()
        assert hass.states.get(state.entities["ct3_import_total"].entity_id).state == "321.0"
        assert not any(getattr(entity, "unique_id", None) == state.entities["historical_0"].unique_id
                       for entity in coordinator._sensors.values())
        if cycle == 0:
            # Exercise the actual HA user-removal API, including integration approval.
            connection = Mock()
            websocket_remove_config_entry_from_device(hass, connection, {
                "id": 1, "type": "config/device_registry/remove_config_entry",
                "config_entry_id": state.entry.entry_id, "device_id": old.id,
            })
            await hass.async_block_till_done()
            assert connection.send_message.called
        assert get_device_by_id(dr.async_get(hass), old.id) is None
        assert get_device_by_id(dr.async_get(hass), active.id) is not None
        assert get_device_by_id(dr.async_get(hass), shelly.id) == shelly
        assert all((DOMAIN, f"sub_{CHILD}") not in device.identifiers for device in iter_all_devices(dr.async_get(hass)))
        assert await hass.config_entries.async_unload(state.entry.entry_id)
        await hass.async_block_till_done()


async def test_history_is_retained_for_old_and_active_entities(recorder_mock, hass):
    state = seed_residue(hass)
    roles = ("historical_0", "historical_1", "ct3_import_total", "ct3_import_energy_total")
    start = dt_util.utcnow() - timedelta(seconds=1)
    for role in roles:
        hass.states.async_set(state.entities[role].entity_id, "10", {"phase": "before"})
    await async_wait_recording_done(hass)
    result = migrate_child_identities(hass, state.entry)
    await async_mark_historical_devices(hass, state.entry, result.historical_devices)
    for role in roles[2:]:
        hass.states.async_set(state.entities[role].entity_id, "11", {"phase": "after"})
    await async_wait_recording_done(hass)
    history = await recorder_mock.async_add_executor_job(partial(
        get_significant_states, hass, start,
        entity_ids=[state.entities[role].entity_id for role in roles], include_start_time_state=False,
    ))
    for role in roles:
        assert [item.state for item in history[state.entities[role].entity_id]] == (["10"] if role.startswith("historical") else ["10", "11"])
        current = er.async_get(hass).async_get(state.entities[role].entity_id)
        assert current.id == state.entities[role].id
    await state.entry._async_process_on_unload(hass)


async def test_lightweight_child_registry_preserves_ids_without_deprecated_attributes(hass):
    devices = dr.async_get(hass)
    if getattr(devices, "async_get_or_create_child", None) is None:
        pytest.skip("Lightweight ChildDeviceEntry is a modern HA API")
    state = seed_residue(hass, lightweight=True)
    with patch.object(dr, "report_usage", side_effect=AssertionError("Deprecated registry API used")):
        result = migrate_child_identities(hass, state.entry)
        assert result.allows(CHILD)
        assert result.historical_devices == {state.devices["historical"].id: state.devices["ct3"].id}
        await async_mark_historical_devices(hass, state.entry, result.historical_devices)
        assert migrate_child_identities(hass, state.entry).historical_devices == result.historical_devices
        assert await async_remove_config_entry_device(hass, state.entry, state.devices["historical"])
        assert not await async_remove_config_entry_device(hass, state.entry, state.devices["ct3"])
    await state.entry._async_process_on_unload(hass)


@pytest.mark.parametrize("remove_entry", [False, True])
async def test_unread_notice_is_cleared_on_device_or_entry_removal(hass, hass_storage, remove_entry):
    state = seed_residue(hass)
    result = migrate_child_identities(hass, state.entry)
    await async_mark_historical_devices(hass, state.entry, result.historical_devices)
    old = state.devices["historical"]
    nid = notification_id(state.entry.entry_id, old.id)
    with patch("custom_components.jackery.historical_devices.pn.async_dismiss", wraps=pn.async_dismiss) as dismiss:
        if remove_entry:
            await state.entry._async_process_on_unload(hass)
            await async_remove_entry(hass, state.entry)
            assert f"{STORAGE_PREFIX}.{state.entry.entry_id}" not in hass_storage
        else:
            dr.async_get(hass).async_remove_device(old.id)
            await hass.async_block_till_done()
            await state.entry._async_process_on_unload(hass)
            saved = await async_load_historical_state(hass, state.entry)
            assert saved["devices"] == {} and saved["historical_device_ids"] == []
        dismiss.assert_any_call(hass, nid)


async def test_label_and_custom_name_never_authorize_deletion(hass):
    state = seed_residue(hass)
    label = lr.async_get(hass).async_create("Jackery: old device – review")
    old = update_device(dr.async_get(hass), state.devices["historical"],
                        name_by_user="Obsolete device – can be deleted", labels={label.label_id})
    er.async_get(hass).async_update_entity(state.entities["historical_0"].entity_id, new_unique_id="unproven_sensor")
    assert not await async_remove_config_entry_device(hass, state.entry, old)


async def test_stale_device_snapshot_cannot_authorize_orphan_deletion(hass):
    state = seed_residue(hass)
    result = migrate_child_identities(hass, state.entry)
    await async_mark_historical_devices(hass, state.entry, result.historical_devices)
    devices = dr.async_get(hass)
    old = state.devices["historical"]
    devices.async_remove_device(state.devices["ct3"].id)
    await hass.async_block_till_done()
    update_device(devices, old, model="Unproven replacement")
    assert not await async_remove_config_entry_device(hass, state.entry, old)
    await state.entry._async_process_on_unload(hass)
