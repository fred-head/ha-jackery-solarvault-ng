"""PR2B migration against real HA registries, including interrupted writes."""

from unittest.mock import patch

import attr
import pytest
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import label_registry as lr

from custom_components.jackery import DOMAIN, _migrate_unique_ids
from custom_components.jackery.child_migration import migrate_child_identities
from custom_components.jackery.identity import child_device_identifier, child_unique_id, http_unique_id
from custom_components.jackery.sensor import SMARTMETER_HTTP_SENSOR_CONFIGS, SUBDEVICE_SENSORS

from .test_multi_instance_identity import HOSTS, coordinator_for, discover, registry_snapshot
from .test_multi_instance_identity import registry_entries as registry_entries
from .test_multi_instance_identity import setup_hosts as setup_hosts

FAMILIES = {
    "battery": "expansion_battery", "ct": "ct", "smartmeter": "ct_3phase",
    "collector": "collector", "plug": "plug",
}


def snapshot(record, *excluded):
    """Compare every persisted attribute, including IDs and user customization."""
    return {f.name: getattr(record, f.name) for f in attr.fields(type(record))
            if f.name != "_cache" and f.name not in excluded}


def seed_child(hass, entry, serial="lower_12:%", family="smartmeter", *, http=False, device_entry=None):
    devices, entities = dr.async_get(hass), er.async_get(hass)
    host = entry.data["device_sn"]
    parent = devices.async_get_or_create(config_entry_id=entry.entry_id, identifiers={(DOMAIN, host)})
    device = devices.async_get_or_create(
        config_entry_id=(device_entry or entry).entry_id, identifiers={(DOMAIN, f"sub_{serial}")},
        via_device=(DOMAIN, host), name="Original", manufacturer="Jackery", model="Synthetic meter",
        sw_version="1.2", hw_version="3", serial_number=serial,
    )
    assert device.via_device_id == parent.id
    pairs = [("sensor", f"jackery_{family}_{serial}_{key.replace('_', '')}",
              child_unique_id(host, serial, family, key.replace("_", "")))
             for key in SUBDEVICE_SENSORS[FAMILIES[family]]]
    if family == "plug":
        pairs.append(("switch", f"jackery_plug_{serial}_switch", child_unique_id(host, serial, "plug", "switch")))
    if http:
        pairs.extend(("sensor", f"jackery_{host}_http_sm_{serial}_{key}", http_unique_id(host, serial, key))
                     for key in SMARTMETER_HTTP_SENSOR_CONFIGS)
    records = [(entities.async_get_or_create(domain, DOMAIN, uid, config_entry=entry,
                                             device_id=device.id), target) for domain, uid, target in pairs]
    return device, records


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("disabled", [False, True])
async def test_all_fields_migrate_in_place_with_all_settings(hass, registry_entries, family, disabled):
    entry, _ = registry_entries
    device, records = seed_child(hass, entry, family=family, http=family == "smartmeter")
    devices, entities = dr.async_get(hass), er.async_get(hass)
    area = ar.async_get(hass).async_create("Utility room")
    label = lr.async_get(hass).async_create("Energy")
    device = devices.async_update_device(device.id, area_id=area.id, labels={label.label_id}, name_by_user="My meter")
    before_device = snapshot(device, "identifiers", "modified_at")
    before_entities = {}
    for record, _ in records:
        updated = entities.async_update_entity(
            record.entity_id, name="My measurement", area_id=area.id, labels={label.label_id},
            disabled_by=er.RegistryEntryDisabler.USER if disabled else None,
            hidden_by=er.RegistryEntryHider.USER, aliases={"Meter reading"}, icon="mdi:gauge",
        )
        entities.async_update_entity_options(updated.entity_id, "sensor", {"display_precision": 1})
        before_entities[record.entity_id] = snapshot(entities.async_get(record.entity_id), "unique_id", "previous_unique_id", "modified_at")
    result = migrate_child_identities(hass, entry)
    assert result.allows("lower_12:%")
    after_device = devices.async_get(device.id)
    assert after_device.identifiers == {(DOMAIN, child_device_identifier(HOSTS[0], "lower_12:%"))}
    assert snapshot(after_device, "identifiers", "modified_at") == before_device
    assert devices.async_get_device(identifiers={(DOMAIN, "sub_lower_12:%")}) is None
    for record, target in records:
        current = entities.async_get(record.entity_id)
        assert current.unique_id == target
        assert snapshot(current, "unique_id", "previous_unique_id", "modified_at") == before_entities[record.entity_id]
    after = [snapshot(entities.async_get(e.entity_id)) for e, _ in records], snapshot(after_device)
    assert migrate_child_identities(hass, entry).allows("lower_12:%")
    assert ([snapshot(entities.async_get(e.entity_id)) for e, _ in records], snapshot(devices.async_get(device.id))) == after


@pytest.mark.parametrize("stage", ["device_first", "entity_first", "some_entities", "all_entities", "both_identifiers"])
async def test_resume_partial_registry_states(hass, registry_entries, stage):
    entry, _ = registry_entries
    device, records = seed_child(hass, entry, family="plug")
    devices, entities = dr.async_get(hass), er.async_get(hass)
    target = (DOMAIN, child_device_identifier(HOSTS[0], "lower_12:%"))
    if stage in {"device_first", "some_entities", "both_identifiers"}:
        devices.async_update_device(device.id, new_identifiers={target} | (device.identifiers if stage == "both_identifiers" else set()))
    if stage in {"entity_first", "some_entities", "all_entities"}:
        for record, uid in records if stage == "all_entities" else records[:2]:
            entities.async_update_entity(record.entity_id, new_unique_id=uid)
    for _ in range(2):
        assert migrate_child_identities(hass, entry).allows("lower_12:%")
        assert devices.async_get(device.id).identifiers == {target}
        assert {r.id for r in entities.entities.values()} == {r.id for r, _ in records}
        assert all(entities.async_get(r.entity_id).unique_id == uid for r, uid in records)


async def test_actual_interrupted_apply_propagates_and_can_resume(hass, registry_entries):
    entry, _ = registry_entries
    device, records = seed_child(hass, entry)
    entities = er.async_get(hass)
    update = entities.async_update_entity
    calls = 0

    def interrupt(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise RuntimeError("simulated interrupted registry write")
        return update(*args, **kwargs)

    with patch.object(entities, "async_update_entity", interrupt), pytest.raises(RuntimeError, match="interrupted"):
        migrate_child_identities(hass, entry)
    assert dr.async_get(hass).async_get(device.id).identifiers == {(DOMAIN, child_device_identifier(HOSTS[0], "lower_12:%"))}
    assert sum(entities.async_get(r.entity_id).unique_id == target for r, target in records) == 2
    assert migrate_child_identities(hass, entry).allows("lower_12:%")
    assert all(entities.async_get(r.entity_id).unique_id == target for r, target in records)


@pytest.mark.parametrize("conflict", [
    "shared_device", "foreign_device", "foreign_parent", "shared_parent", "foreign_entity",
    "same_owner_target", "foreign_target", "duplicate_device", "foreign_target_device", "unknown_entity",
    "wrong_serial", "wrong_host", "malformed_uid", "multiple_identifiers",
])
async def test_conflicts_preserve_entire_child_and_allow_safe_sibling(hass, registry_entries, conflict, caplog):
    entry, other = registry_entries
    serial = "sensitive_child_%"
    device, records = seed_child(hass, entry, serial, device_entry=other if conflict == "foreign_device" else entry)
    safe_device, safe_records = seed_child(hass, entry, "SAFE", family="plug")
    devices, entities = dr.async_get(hass), er.async_get(hass)
    first, target = records[-1]
    if conflict == "shared_device":
        devices.async_update_device(device.id, add_config_entry_id=other.entry_id)
    elif conflict in {"foreign_parent", "shared_parent"}:
        parent = devices.async_get_or_create(config_entry_id=other.entry_id, identifiers={(DOMAIN, HOSTS[1])})
        if conflict == "shared_parent":
            devices.async_update_device(parent.id, add_config_entry_id=entry.entry_id)
        devices.async_update_device(device.id, via_device_id=parent.id)
    elif conflict == "foreign_entity":
        entities.async_get_or_create("sensor", "foreign_platform", "foreign", config_entry=other, device_id=device.id)
    elif conflict in {"same_owner_target", "foreign_target"}:
        entities.async_get_or_create(first.domain, DOMAIN, target, config_entry=entry if conflict == "same_owner_target" else other)
    elif conflict in {"duplicate_device", "foreign_target_device"}:
        devices.async_get_or_create(config_entry_id=entry.entry_id if conflict == "duplicate_device" else other.entry_id,
                                    identifiers={(DOMAIN, child_device_identifier(HOSTS[0], serial))})
    elif conflict == "unknown_entity":
        entities.async_get_or_create("sensor", DOMAIN, "jackery_custom_child_unknown", config_entry=entry, device_id=device.id)
    elif conflict in {"wrong_serial", "wrong_host", "malformed_uid"}:
        uid = child_unique_id(HOSTS[1] if conflict == "wrong_host" else HOSTS[0],
                              "DIFFERENT" if conflict == "wrong_serial" else serial, "smartmeter", "importtotal")
        entities.async_update_entity(first.entity_id, new_unique_id=uid if conflict != "malformed_uid" else "jackery_child:%zz:broken")
    elif conflict == "multiple_identifiers":
        devices.async_update_device(device.id, new_identifiers=device.identifiers | {(DOMAIN, "sub_DIFFERENT")})
    before_devices = {d.id: snapshot(d) for d in devices.devices.values() if d.id != safe_device.id}
    safe_ids = {e.entity_id for e, _ in safe_records}
    before_entities = {e.entity_id: snapshot(e) for e in entities.entities.values() if e.entity_id not in safe_ids}
    result = migrate_child_identities(hass, entry)
    assert not result.allows(serial)
    assert result.allows("SAFE")
    assert {d.id: snapshot(d) for d in devices.devices.values() if d.id != safe_device.id} == before_devices
    assert {e.entity_id: snapshot(e) for e in entities.entities.values() if e.entity_id not in safe_ids} == before_entities
    assert all(entities.async_get(e.entity_id).unique_id == target for e, target in safe_records)
    assert serial not in caplog.text
    assert entry.entry_id in caplog.text
    assert "retained" in caplog.text and "reload" in caplog.text


async def test_entity_target_uses_domain_and_platform_identity(hass, registry_entries):
    entry, other = registry_entries
    _, records = seed_child(hass, entry, family="plug")
    entities = er.async_get(hass)
    target = records[0][1]
    others = [entities.async_get_or_create("switch", DOMAIN, target, config_entry=other),
              entities.async_get_or_create("sensor", "unrelated", target, config_entry=other)]
    before = [snapshot(e) for e in others]
    assert migrate_child_identities(hass, entry).allows("lower_12:%")
    assert [snapshot(entities.async_get(e.entity_id)) for e in others] == before


@pytest.mark.parametrize("prefix,family,key", [("Battery", "battery", "chargeenergy"), ("SmartMeter", "smartmeter", "power"),
                                             ("smartmeter", "smartmeter", "import_total")])
async def test_historical_prefix_and_field_spelling(hass, registry_entries, prefix, family, key):
    entry, _ = registry_entries
    registry = er.async_get(hass)
    old = registry.async_get_or_create("sensor", DOMAIN, f"jackery_{prefix}_serial_with_underscores_{key}", config_entry=entry)
    assert migrate_child_identities(hass, entry).allows("serial_with_underscores")
    current = registry.async_get(old.entity_id)
    assert current.id == old.id
    assert current.unique_id == child_unique_id(HOSTS[0], "serial_with_underscores", family, key.replace("_", ""))


@pytest.mark.parametrize("host", ["battery", "plug", "smartmeter", "ct", "collector", "child:odd%_"])
async def test_main_identity_with_family_like_host_is_untouched(hass, registry_entries, host):
    entry, _ = registry_entries
    hass.config_entries.async_update_entry(entry, data={"device_sn": host}, unique_id=host)
    devices, entities = dr.async_get(hass), er.async_get(hass)
    parent = devices.async_get_or_create(config_entry_id=entry.entry_id, identifiers={(DOMAIN, host)})
    from custom_components.jackery.sensor import SENSORS

    records = [entities.async_get_or_create("sensor", DOMAIN, f"jackery_{host}_{key}", config_entry=entry,
                                           device_id=parent.id) for key in SENSORS]
    before = [snapshot(r) for r in records]
    result = migrate_child_identities(hass, entry)
    assert not result.block_all and not result.blocked_children
    assert [snapshot(entities.async_get(r.entity_id)) for r in records] == before


@pytest.mark.parametrize("kind", ["entity", "device", "http"])
async def test_foreign_scoped_target_blocks_fresh_discovery(hass, registry_entries, kind):
    entry, other = registry_entries
    if kind == "entity":
        er.async_get(hass).async_get_or_create("sensor", DOMAIN, child_unique_id(HOSTS[0], "CHILD", "plug", "power"), config_entry=other)
    elif kind == "http":
        er.async_get(hass).async_get_or_create("sensor", DOMAIN, http_unique_id(HOSTS[0], "CHILD", "frequency"), config_entry=other)
    else:
        dr.async_get(hass).async_get_or_create(config_entry_id=other.entry_id, identifiers={(DOMAIN, child_device_identifier(HOSTS[0], "CHILD"))})
    before = registry_snapshot(hass, other)
    result = migrate_child_identities(hass, entry)
    assert not result.allows("CHILD")
    assert registry_snapshot(hass, other) == before


@pytest.mark.parametrize("uid", ["jackery_child:SOLARVAULT_A:C:smartmeter:import_total", "jackery_child:SOLARVAULT_A:C:unknown:power"])
async def test_unknown_new_format_fields_are_retained_and_block_replacements(hass, registry_entries, uid):
    entry, _ = registry_entries
    entities = er.async_get(hass)
    record = entities.async_get_or_create("sensor", DOMAIN, uid, config_entry=entry)
    assert not migrate_child_identities(hass, entry).allows("C")
    assert snapshot(entities.async_get(record.entity_id)) == snapshot(record)


@pytest.mark.parametrize("order", [HOSTS, HOSTS[::-1]])
@pytest.mark.usefixtures("enable_custom_integrations")
async def test_shared_legacy_device_blocks_discovery_and_cleanup_in_both_orders(hass, setup_hosts, order):
    entries = await setup_hosts(order)
    device, _ = seed_child(hass, entries[HOSTS[0]], "SHARED", http=True)
    dr.async_get(hass).async_update_device(device.id, add_config_entry_id=entries[HOSTS[1]].entry_id)
    _, safe = seed_child(hass, entries[HOSTS[0]], "SAFE", family="plug")
    before_device = snapshot(dr.async_get(hass).async_get(device.id))
    before_entities = {e.entity_id: snapshot(e) for e in er.async_entries_for_device(er.async_get(hass), device.id, include_disabled_entities=True)}
    for host in order[::-1]:
        entry = entries[host]
        assert await hass.config_entries.async_reload(entry.entry_id)
        c = coordinator_for(hass, entry)
        assert not c.child_identity_allowed("SHARED")
        for group, dev_type, sub_type, data_key in [("ct_3phase", 3, 5, "cts"), ("plug", 6, 0, "plugs"), ("expansion_battery", 1, 0, "expansion_batteries")]:
            await discover(hass, c, "SHARED", group, dev_type, sub_type, data_key)
        await c._create_http_sensors("SHARED")
        c._remove_subdevice_from_ha("SHARED")
        await hass.async_block_till_done()
        assert "SHARED" not in c._known_plugs
        assert not c._entity_keys_for_subdevice("SHARED")
        assert dr.async_get(hass).async_get_device(identifiers={(DOMAIN, child_device_identifier(host, "SHARED"))}) is None
    assert snapshot(dr.async_get(hass).async_get(device.id)) == before_device
    assert {e.entity_id: snapshot(e) for e in er.async_entries_for_device(er.async_get(hass), device.id, include_disabled_entities=True)} == before_entities
    assert all(er.async_get(hass).async_get(e.entity_id).unique_id == uid for e, uid in safe)


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_setup_migration_discovery_reuses_legacy_http_mqtt_records(hass, setup_hosts):
    entry = (await setup_hosts())[HOSTS[0]]
    device, records = seed_child(hass, entry, "METER", http=True)
    ids = {record.entity_id: record.id for record, _ in records}
    for _ in range(2):
        assert await hass.config_entries.async_reload(entry.entry_id)
        c = coordinator_for(hass, entry)
        await discover(hass, c, "METER", "ct_3phase", 3, 5, "cts")
        await c._create_http_sensors("METER")
        await hass.async_block_till_done()
        current = er.async_entries_for_device(er.async_get(hass), device.id, include_disabled_entities=True)
        assert {record.entity_id: record.id for record in current} == ids
        assert all(er.async_get(hass).async_get(r.entity_id).unique_id == uid for r, uid in records)
        assert entry.version == 1


async def test_recorder_reads_same_entity_history_across_migration(recorder_mock, hass, registry_entries):
    from datetime import timedelta
    from functools import partial

    from homeassistant.components.recorder.history import get_significant_states
    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.components.recorder.common import async_wait_recording_done

    entry, _ = registry_entries
    _, records = seed_child(hass, entry, family="plug")
    record, target = records[0]
    start = dt_util.utcnow() - timedelta(seconds=1)
    hass.states.async_set(record.entity_id, "125", {"unit_of_measurement": "W"})
    await async_wait_recording_done(hass)
    assert migrate_child_identities(hass, entry).allows("lower_12:%")
    current = er.async_get(hass).async_get(record.entity_id)
    assert current.id == record.id and current.unique_id == target
    hass.states.async_set(current.entity_id, "250", {"unit_of_measurement": "W"})
    await async_wait_recording_done(hass)
    states = await recorder_mock.async_add_executor_job(partial(
        get_significant_states, hass, start, entity_ids=[record.entity_id], include_start_time_state=False,
    ))
    assert set(states) == {record.entity_id}
    assert [state.state for state in states[record.entity_id]] == ["125", "250"]


@pytest.mark.parametrize("link", ["none", "main", "child", "unknown"])
async def test_ambiguous_legacy_main_child_key_needs_matching_device(hass, registry_entries, link):
    entry, _ = registry_entries
    entities, devices = er.async_get(hass), dr.async_get(hass)
    device = None
    if link != "none":
        identifier = {"main": HOSTS[0], "child": "sub_import", "unknown": "unknown_device"}[link]
        device = devices.async_get_or_create(config_entry_id=entry.entry_id, identifiers={(DOMAIN, identifier)})
    record = entities.async_get_or_create("sensor", DOMAIN, "jackery_ct_import_energy", config_entry=entry,
                                         device_id=device.id if device else None)
    result = migrate_child_identities(hass, entry)
    await _migrate_unique_ids(hass, entry, protected_entities=result.protected_entities)
    current = entities.async_get(record.entity_id)
    if link == "main":
        assert result.allows("import")
        assert current.unique_id == f"jackery_{HOSTS[0]}_ct_import_energy"
    elif link == "child":
        assert result.allows("import")
        assert current.unique_id == child_unique_id(HOSTS[0], "import", "ct", "energy")
    else:
        assert not result.allows("import")
        assert snapshot(current) == snapshot(record)


@pytest.mark.parametrize("host,serial", [("Host:%_ä", "child_ä:%"), ("A_http_sm_B", "C"), ("A", "B_http_sm_C")])
async def test_special_host_child_components_migrate_without_loss(hass, registry_entries, host, serial):
    entry, _ = registry_entries
    hass.config_entries.async_update_entry(entry, data={"device_sn": host}, unique_id=host)
    device, records = seed_child(hass, entry, serial, http=True)
    assert migrate_child_identities(hass, entry).allows(serial)
    assert dr.async_get(hass).async_get(device.id).identifiers == {(DOMAIN, child_device_identifier(host, serial))}
    for record, target in records:
        current = er.async_get(hass).async_get(record.entity_id)
        assert current.id == record.id and current.unique_id == target


@pytest.mark.parametrize("host", [None, "", " A "])
async def test_ambiguous_configured_host_refuses_registry_writes(hass, registry_entries, host):
    entry, _ = registry_entries
    seed_child(hass, entry)
    hass.config_entries.async_update_entry(entry, data={"device_sn": host})
    before = registry_snapshot(hass, entry)
    result = migrate_child_identities(hass, entry)
    assert result.block_all
    assert registry_snapshot(hass, entry) == before


@pytest.mark.parametrize("identifier", ["child:%bad", "sub_", "child:OTHER:C", "unknown_alias"])
async def test_device_identity_ambiguity_cannot_become_new_record(hass, registry_entries, identifier):
    entry, _ = registry_entries
    device, _ = seed_child(hass, entry, "C")
    devices = dr.async_get(hass)
    devices.async_update_device(device.id, new_identifiers=device.identifiers | {(DOMAIN, identifier)})
    before = registry_snapshot(hass, entry)
    assert not migrate_child_identities(hass, entry).allows("C")
    assert registry_snapshot(hass, entry) == before


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_main_serial_cannot_claim_existing_scoped_child(hass, setup_hosts):
    entries = await setup_hosts((HOSTS[0],))
    entry = entries[HOSTS[0]]
    await discover(hass, coordinator_for(hass, entry), "C", "plug", 6, 0, "plugs")
    before = registry_snapshot(hass, entry)
    # A literal main serial can resemble the new child namespace. Preserve the
    # existing child instead of allowing HA device_info to claim it for this host.
    from homeassistant import config_entries

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER},
        data={"device_sn": child_device_identifier(HOSTS[0], "C"), "token": "synthetic", "topic_prefix": "hb"},
    )
    await hass.async_block_till_done()
    conflicting_entry = result["result"]
    assert conflicting_entry.state is config_entries.ConfigEntryState.SETUP_ERROR
    assert registry_snapshot(hass, entry) == before


@pytest.mark.parametrize("order", [HOSTS, HOSTS[::-1]])
@pytest.mark.usefixtures("enable_custom_integrations")
async def test_other_hosts_legacy_child_does_not_determine_ownership(hass, setup_hosts, order):
    entries = await setup_hosts(order)
    legacy_device, legacy_records = seed_child(hass, entries[HOSTS[1]], "SAME", family="plug")
    for host in order:
        assert await hass.config_entries.async_reload(entries[host].entry_id)
        await discover(hass, coordinator_for(hass, entries[host]), "SAME", "plug", 6, 0, "plugs")
    devices, entities = dr.async_get(hass), er.async_get(hass)
    children = [devices.async_get_device(identifiers={(DOMAIN, child_device_identifier(host, "SAME"))}) for host in HOSTS]
    assert children[0].id != children[1].id == legacy_device.id
    for host, child in zip(HOSTS, children, strict=True):
        assert child.config_entries == {entries[host].entry_id}
        assert child.via_device_id == devices.async_get_device(identifiers={(DOMAIN, host)}).id
    assert {r.id for r in er.async_entries_for_device(entities, legacy_device.id, include_disabled_entities=True)} == {r.id for r, _ in legacy_records}


async def test_resolved_shared_ownership_can_retry_without_new_records(hass, registry_entries):
    entry, other = registry_entries
    device, records = seed_child(hass, entry)
    devices, entities = dr.async_get(hass), er.async_get(hass)
    devices.async_update_device(device.id, add_config_entry_id=other.entry_id)
    before = registry_snapshot(hass, entry)
    for _ in range(2):
        assert not migrate_child_identities(hass, entry).allows("lower_12:%")
        assert registry_snapshot(hass, entry) == before
    # Simulate an explicit, externally resolved ownership decision. The
    # migration itself never removes the other config entry to achieve this.
    devices.async_update_device(device.id, remove_config_entry_id=other.entry_id)
    assert migrate_child_identities(hass, entry).allows("lower_12:%")
    assert {r.id for r in entities.entities.values()} == {r.id for r, _ in records}
    assert all(entities.async_get(r.entity_id).unique_id == uid for r, uid in records)
