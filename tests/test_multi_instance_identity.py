"""Identity audit using actual platforms and HA registries, with synthetic serials.

PR2A safety and restored PR2B duplicate-serial regressions. Original evidence is
preserved in docs/future-tests/pr2b-child-identity.py.txt. See
docs/multi-instance-identity.md before changing public identity formats.
"""

import asyncio
import json
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant import config_entries
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.jackery import DOMAIN, _migrate_unique_ids
from custom_components.jackery.child_migration import migrate_child_identities
from custom_components.jackery.identity import child_device_identifier
from custom_components.jackery.number import NUMBERS
from custom_components.jackery.sensor import (
    SENSORS,
    SMARTMETER_HTTP_SENSOR_CONFIGS,
    SUBDEVICE_SENSORS,
    JackeryDataCoordinator,
    JackerySmartMeterHttpSensor,
    JackerySubDeviceSensor,
)
from custom_components.jackery.switch import JackeryPlugSwitch

from .conftest import FakeMqttMsg

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")
HOSTS = ("SOLARVAULT_A", "SOLARVAULT_B")
CHILDREN = [
    ("ct", 2, 1, "cts"),
    ("ct", 4, 1, "cts"),
    ("ct_3phase", 3, 5, "cts"),
    ("ct_3phase", 3, 2, "cts"),
    ("collector", 4, 7, "collectors"),
    ("plug", 6, 0, "plugs"),
    ("expansion_battery", 1, 0, "expansion_batteries"),
]


@pytest.fixture
async def setup_hosts(hass, request):
    """Real HA platforms in controlled orders; only transport is replaced."""
    entries = {}
    created = []
    started = []
    initialize = JackeryDataCoordinator.__init__
    start = JackeryDataCoordinator.async_start

    def counted_init(coordinator, *args, **kwargs):
        initialize(coordinator, *args, **kwargs)
        created.append(coordinator)

    async def counted_start(coordinator):
        assert coordinator.add_entities_callback is not None
        assert coordinator.add_switch_entities_callback is not None
        assert coordinator not in started
        started.append(coordinator)
        await start(coordinator)

    forward = hass.config_entries.async_forward_entry_setups

    async def ordered_forward(entry, platforms):
        mode = getattr(request, "param", False)
        if mode is None:
            await forward(entry, platforms)
            return
        others = [platform for platform in platforms if platform != "sensor"]
        batches = [others, ["sensor"]] if getattr(request, "param", False) else [["sensor"], others]
        for batch in batches:
            await forward(entry, batch)

    async def idle_poll(_coordinator):
        await asyncio.Future()

    async def setup(order=HOSTS):
        for host in order:
            result = await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": config_entries.SOURCE_USER},
                data={"device_sn": host, "token": "synthetic-token", "topic_prefix": "hb"},
            )
            await hass.async_block_till_done()
            entries[host] = result["result"]
            assert entries[host].state is config_entries.ConfigEntryState.LOADED
        return entries

    with (
        patch("homeassistant.components.mqtt.async_wait_for_mqtt_client", return_value=True),
        patch("homeassistant.components.mqtt.async_subscribe", new=AsyncMock(return_value=Mock())),
        patch.object(JackeryDataCoordinator, "__init__", counted_init),
        patch.object(JackeryDataCoordinator, "async_start", counted_start),
        patch.object(JackeryDataCoordinator, "_periodic_data_request", idle_poll),
        patch.object(hass.config_entries, "async_forward_entry_setups", ordered_forward),
    ):
        yield setup
        assert created == started
        assert len({id(c) for c in created}) == len(created)
        for entry in entries.values():
            if entry.state is config_entries.ConfigEntryState.LOADED:
                assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


@pytest.mark.parametrize("setup_hosts", [False, True, None], indirect=True)
async def test_platform_setup_order_does_not_drop_controls(hass, setup_hosts):
    entries = await setup_hosts()
    for entry in entries.values():
        domains = {e.domain for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)}
        assert domains == {"sensor", "switch", "number", "select", "button"}


def coordinator_for(hass, entry):
    return hass.data[DOMAIN][entry.entry_id]["coordinator"]


def report(coordinator, body, code=101):
    coordinator._handle_message(FakeMqttMsg(
        f"hb/device/{coordinator._device_sn}/event", json.dumps({"type": code, "body": body})
    ))


def registry_snapshot(hass, entry):
    """Include identities, ownership and user customization, not just counts."""
    entities = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    return (
        {e.entity_id: (e.unique_id, e.config_entry_id, e.device_id, e.name, e.disabled_by) for e in entities},
        {d.id: (d.identifiers, d.config_entries, d.via_device_id, d.name_by_user) for d in devices},
    )


@pytest.mark.parametrize("setup_hosts", [False, True, None], indirect=True)
@pytest.mark.parametrize("order", [HOSTS, HOSTS[::-1]])
async def test_two_hosts_all_platforms_and_reload_isolation(hass, setup_hosts, order):
    entries = await setup_hosts(order)
    ent_reg, dev_reg = er.async_get(hass), dr.async_get(hass)
    for host, entry in entries.items():
        main = dev_reg.async_get_device(identifiers={(DOMAIN, host)})
        assert main.config_entries == {entry.entry_id}
        entities = er.async_entries_for_config_entry(ent_reg, entry.entry_id)
        assert {e.domain for e in entities} == {"sensor", "switch", "number", "select", "button"}
        assert all(e.device_id == main.id for e in entities)
        expected = {f"jackery_{host}_{key}" for key, config in SENSORS.items() if config.get("json_key") is not None}
        expected |= {f"jackery_{host}_number_{key}" for key in NUMBERS}
        expected |= {f"jackery_{host}_switch_{key}" for key in ["isAutoStandby", "swEps", "offGridDown", "socForceChg", "isFollowMeterPw"]}
        expected |= {f"jackery_{host}_{key}" for key in ["auto_standby_select", "work_mode_select", "reboot"]}
        assert {e.unique_id for e in entities} == expected
    for host in order:
        other = entries[next(h for h in HOSTS if h != host)]
        before_other = registry_snapshot(hass, other)
        before_own = registry_snapshot(hass, entries[host])
        old_coordinator = coordinator_for(hass, entries[host])
        assert await hass.config_entries.async_unload(entries[host].entry_id)
        assert entries[host].entry_id not in hass.data[DOMAIN]
        assert not old_coordinator._sensors
        assert old_coordinator._data_task.done()
        assert registry_snapshot(hass, other) == before_other
        assert await hass.config_entries.async_setup(entries[host].entry_id)
        await hass.async_block_till_done()
        assert coordinator_for(hass, entries[host]) is not old_coordinator
        assert registry_snapshot(hass, entries[host]) == before_own
        assert registry_snapshot(hass, other) == before_other


async def discover(hass, coordinator, serial, group, dev_type, sub_type, data_key):
    item = {"deviceSn": serial, "devType": dev_type, "subType": sub_type, "name": "Same name", "commMode": 1}
    if group == "expansion_battery":
        report(coordinator, {**item, "inEgy": 100, "outEgy": 200}, 23)
    else:
        report(coordinator, {data_key: [item]})
    await hass.async_block_till_done()


@pytest.mark.parametrize("order", [HOSTS, HOSTS[::-1]])
@pytest.mark.parametrize("group,dev_type,sub_type,data_key", CHILDREN)
async def test_distinct_children_with_overlapping_metadata(hass, setup_hosts, order, group, dev_type, sub_type, data_key):
    entries = await setup_hosts(order)
    for host in order:
        c = coordinator_for(hass, entries[host])
        await discover(hass, c, f"CHILD_{host}", group, dev_type, sub_type, data_key)
        first = registry_snapshot(hass, entries[host])
        await discover(hass, c, f"CHILD_{host}", group, dev_type, sub_type, data_key)
        assert registry_snapshot(hass, entries[host]) == first
        device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, child_device_identifier(host, f"CHILD_{host}"))})
        parent = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, host)})
        assert device.config_entries == {entries[host].entry_id}
        assert device.via_device_id == parent.id
        child_entities = [e for e in er.async_entries_for_config_entry(er.async_get(hass), entries[host].entry_id)
                          if e.device_id == device.id]
        assert len(child_entities) == len(SUBDEVICE_SENSORS[group]) + (group == "plug")
    # Reload each entry and rediscover: same entity IDs/devices, other host unchanged.
    for host in order:
        other = entries[next(h for h in HOSTS if h != host)]
        before_other = registry_snapshot(hass, other)
        before_own = registry_snapshot(hass, entries[host])
        assert await hass.config_entries.async_reload(entries[host].entry_id)
        await hass.async_block_till_done()
        await discover(hass, coordinator_for(hass, entries[host]), f"CHILD_{host}", group, dev_type, sub_type, data_key)
        assert registry_snapshot(hass, entries[host]) == before_own
        assert registry_snapshot(hass, other) == before_other


@pytest.mark.parametrize("order", [HOSTS, HOSTS[::-1]])
@pytest.mark.parametrize("group,dev_type,sub_type,data_key", CHILDREN)
async def test_identical_children_discovery_reload_unload_cleanup(hass, setup_hosts, order, group, dev_type, sub_type, data_key):
    entries = await setup_hosts(order)
    devices, entities = dr.async_get(hass), er.async_get(hass)
    child_devices = {}
    for host in order:
        entry = entries[host]
        coordinator = coordinator_for(hass, entry)
        await discover(hass, coordinator, "SAME_child:%", group, dev_type, sub_type, data_key)
        device = devices.async_get_device(identifiers={(DOMAIN, child_device_identifier(host, "SAME_child:%"))})
        child_devices[host] = device
        assert device.config_entries == {entry.entry_id}
        assert device.via_device_id == devices.async_get_device(identifiers={(DOMAIN, host)}).id
        records = er.async_entries_for_device(entities, device.id, include_disabled_entities=True)
        assert len(records) == len(SUBDEVICE_SENSORS[group]) + (group == "plug")
        assert all(e.config_entry_id == entry.entry_id for e in records)
        assert "SAME_child:%" in coordinator._known_plugs
        before = registry_snapshot(hass, entry)
        listeners = dict(coordinator._sensors)
        await discover(hass, coordinator, "SAME_child:%", group, dev_type, sub_type, data_key)
        assert registry_snapshot(hass, entry) == before
        assert coordinator._sensors == listeners
    assert child_devices[HOSTS[0]].id != child_devices[HOSTS[1]].id
    for host in order[::-1]:
        entry = entries[host]
        other = entries[next(h for h in HOSTS if h != host)]
        before = registry_snapshot(hass, entry)
        other_before = registry_snapshot(hass, other)
        previous = coordinator_for(hass, entry)
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert not previous._sensors
        assert registry_snapshot(hass, other) == other_before
        assert await hass.config_entries.async_setup(entry.entry_id)
        await discover(hass, coordinator_for(hass, entry), "SAME_child:%", group, dev_type, sub_type, data_key)
        assert registry_snapshot(hass, entry) == before
        assert registry_snapshot(hass, other) == other_before
    first, other = (entries[h] for h in order)
    other_before = registry_snapshot(hass, other)
    c = coordinator_for(hass, first)
    c._remove_subdevice_from_ha("SAME_child:%")
    await hass.async_block_till_done()
    assert devices.async_get(child_devices[order[0]].id) is None
    assert not c._entity_keys_for_subdevice("SAME_child:%")
    assert registry_snapshot(hass, other) == other_before
    await discover(hass, c, "SAME_child:%", group, dev_type, sub_type, data_key)
    recovered = devices.async_get_device(identifiers={(DOMAIN, child_device_identifier(order[0], "SAME_child:%"))})
    assert recovered is not None and recovered.config_entries == {first.entry_id}
    assert registry_snapshot(hass, other) == other_before


@pytest.mark.parametrize("order", [HOSTS, HOSTS[::-1]])
async def test_http_mqtt_grouping_survives_both_reload_orders(hass, setup_hosts, order):
    entries = await setup_hosts(order)
    originals = {}
    for host in order:
        c = coordinator_for(hass, entries[host])
        await discover(hass, c, "SAME", "ct_3phase", 3, 5, "cts")
        await c._create_http_sensors("SAME")
        await hass.async_block_till_done()
        device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, child_device_identifier(host, "SAME"))})
        records = er.async_entries_for_device(er.async_get(hass), device.id, include_disabled_entities=True)
        assert len(records) == len(SUBDEVICE_SENSORS["ct_3phase"]) + len(SMARTMETER_HTTP_SENSOR_CONFIGS)
        originals[host] = registry_snapshot(hass, entries[host])
    for host in order[::-1]:
        assert await hass.config_entries.async_reload(entries[host].entry_id)
        c = coordinator_for(hass, entries[host])
        await discover(hass, c, "SAME", "ct_3phase", 3, 5, "cts")
        await c._create_http_sensors("SAME")
        await hass.async_block_till_done()
        assert {h: registry_snapshot(hass, e) for h, e in entries.items()} == originals


async def test_reclassification_reuses_physical_device(hass, setup_hosts):
    entry = (await setup_hosts())[HOSTS[0]]
    c = coordinator_for(hass, entry)
    await discover(hass, c, "SAME", "ct", 2, 1, "cts")
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, child_device_identifier(HOSTS[0], "SAME"))})
    old = registry_snapshot(hass, entry)[0]
    # The existing discovery set fixes a family's fields for this runtime.
    await discover(hass, c, "SAME", "ct_3phase", 3, 5, "cts")
    assert registry_snapshot(hass, entry)[0] == old
    assert await hass.config_entries.async_reload(entry.entry_id)
    await discover(hass, coordinator_for(hass, entry), "SAME", "ct_3phase", 3, 5, "cts")
    current = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, child_device_identifier(HOSTS[0], "SAME"))})
    assert current.id == device.id
    records = er.async_entries_for_device(er.async_get(hass), device.id, include_disabled_entities=True)
    assert len(records) == len(SUBDEVICE_SENSORS["ct"]) + len(SUBDEVICE_SENSORS["ct_3phase"])
    assert {e.entity_id for e in records} >= {eid for eid, values in old.items() if values[2] == device.id}


def child_entities(coordinator, serial, group, dev_type, data_key):
    return [JackerySubDeviceSensor(
        serial, dev_type, key, config, coordinator, coordinator.config_entry_id,
        data_key=data_key, use_expansion=group == "expansion_battery", sensor_group=group,
    ) for key, config in SUBDEVICE_SENSORS[group].items()]


@pytest.mark.parametrize("group,dev_type,sub_type,data_key", CHILDREN)
def test_duplicate_child_serial_unique_ids_are_host_scoped(group, dev_type, sub_type, data_key):
    """Every current child sensor definition must resist a cross-host collision."""
    coordinators = [JackeryDataCoordinator(None, "hb", "tok", "localhost", host) for host in HOSTS]
    ids = [{e.unique_id for e in child_entities(c, "DUPLICATE", group, dev_type, data_key)} for c in coordinators]
    assert all(len(values) == len(SUBDEVICE_SENSORS[group]) for values in ids)
    assert ids[0].isdisjoint(ids[1])


def test_duplicate_plug_switch_unique_id_is_host_scoped():
    switches = [JackeryPlugSwitch("DUPLICATE", 6, JackeryDataCoordinator(None, "hb", "tok", "localhost", host), host)
                for host in HOSTS]
    assert switches[0].unique_id != switches[1].unique_id


async def test_http_unique_ids_differ_but_devices_must_also_be_separate(hass):
    devices = []
    ids = []
    registry = dr.async_get(hass)
    for host in HOSTS:
        entry = MockConfigEntry(domain=DOMAIN, data={"device_sn": host}, unique_id=host)
        entry.add_to_hass(hass)
        registry.async_get_or_create(config_entry_id=entry.entry_id, identifiers={(DOMAIN, host)})
        c = JackeryDataCoordinator(hass, "hb", "tok", "localhost", host)
        entities = [JackerySmartMeterHttpSensor("DUPLICATE", key, config, c, entry.entry_id)
                    for key, config in SMARTMETER_HTTP_SENSOR_CONFIGS.items()]
        ids.append({e.unique_id for e in entities})
        devices.append(registry.async_get_or_create(config_entry_id=entry.entry_id, **entities[0].device_info))
    assert ids[0].isdisjoint(ids[1])
    assert devices[0].id != devices[1].id


@pytest.mark.parametrize("order", [HOSTS, HOSTS[::-1]])
async def test_duplicate_child_discovery_does_not_claim_other_host(hass, setup_hosts, order):
    entries = await setup_hosts(order)
    await discover(hass, coordinator_for(hass, entries[order[0]]), "DUPLICATE", "plug", 6, 0, "plugs")
    first = registry_snapshot(hass, entries[order[0]])
    await discover(hass, coordinator_for(hass, entries[order[1]]), "DUPLICATE", "plug", 6, 0, "plugs")
    assert registry_snapshot(hass, entries[order[0]]) == first
    second_children = [e for e in er.async_entries_for_config_entry(er.async_get(hass), entries[order[1]].entry_id)
                       if "DUPLICATE" in e.unique_id]
    assert len(second_children) == len(SUBDEVICE_SENSORS["plug"]) + 1


async def test_child_cleanup_cannot_delete_another_entries_device(hass, setup_hosts):
    entries = await setup_hosts()
    await discover(hass, coordinator_for(hass, entries[HOSTS[1]]), "DUPLICATE", "plug", 6, 0, "plugs")
    before = registry_snapshot(hass, entries[HOSTS[1]])
    coordinator_for(hass, entries[HOSTS[0]])._remove_subdevice_from_ha("DUPLICATE")
    await hass.async_block_till_done()
    assert registry_snapshot(hass, entries[HOSTS[1]]) == before


@pytest.fixture
def registry_entries(hass):
    entries = []
    for host in HOSTS:
        entry = MockConfigEntry(domain=DOMAIN, data={"device_sn": host}, unique_id=host)
        entry.add_to_hass(hass)
        entries.append(entry)
    return entries


@pytest.mark.parametrize("prefix", ["smartmeter", "battery", "ct", "plug", "collector", "SmartMeter", "Battery"])
@pytest.mark.parametrize("serial", ["UPPER001", "lower001", "123456"])
async def test_child_migration_preserves_identity(hass, registry_entries, prefix, serial):
    entry, other = registry_entries
    registry = er.async_get(hass)
    devices = dr.async_get(hass)
    devices.async_get_or_create(config_entry_id=entry.entry_id, identifiers={(DOMAIN, HOSTS[0])})
    child = devices.async_get_or_create(config_entry_id=entry.entry_id, identifiers={(DOMAIN, f"sub_{serial}")},
                                        via_device=(DOMAIN, HOSTS[0]))
    key = {"battery": "chargeenergy", "collector": "importpower"}.get(prefix.lower(), "power")
    uid = f"jackery_{prefix}_{serial}_{key}"
    source = registry.async_get_or_create("sensor", DOMAIN, uid, config_entry=entry,
                                          device_id=child.id, suggested_object_id="custom_meter")
    registry.async_get_or_create("sensor", DOMAIN, "jackery_plug_FOREIGN_power", config_entry=other)
    registry.async_update_entity(source.entity_id, name="My meter", disabled_by=er.RegistryEntryDisabler.USER)
    before = registry_snapshot(hass, entry)
    other_before = registry_snapshot(hass, other)
    await _migrate_unique_ids(hass, entry)
    assert registry_snapshot(hass, entry) == before
    await _migrate_unique_ids(hass, entry)
    assert registry_snapshot(hass, entry) == before
    assert registry_snapshot(hass, other) == other_before


@pytest.mark.parametrize("order", [(0, 1), (1, 0)])
async def test_legacy_migration_is_entry_scoped_and_idempotent(hass, registry_entries, order):
    registry, devices = er.async_get(hass), dr.async_get(hass)
    targets = {}
    for i, entry in enumerate(registry_entries):
        old_device = devices.async_get_or_create(config_entry_id=entry.entry_id, identifiers={(DOMAIN, entry.entry_id)})
        child = devices.async_get_or_create(config_entry_id=entry.entry_id, identifiers={(DOMAIN, f"sub_CHILD{i}")},
                                            via_device=(DOMAIN, entry.entry_id))
        # Different legitimate v1 main fields can coexist in the global registry.
        for domain, old, suffix in [
            ("sensor", f"jackery_{'battery_soc' if i == 0 else 'solar_power'}", "battery_soc" if i == 0 else "solar_power"),
            ("switch", f"jackery_main_{'swEps' if i == 0 else 'isAutoStandby'}", "switch_swEps" if i == 0 else "switch_isAutoStandby"),
            ("number", f"jackery_main_{'maxOutPw' if i == 0 else 'defaultPw'}", "number_maxOutPw" if i == 0 else "number_defaultPw"),
            ("select", f"jackery_{entry.entry_id}_work_mode_select", "work_mode_select"),
            ("button", f"jackery_{entry.entry_id}_reboot", "reboot"),
        ]:
            entity = registry.async_get_or_create(domain, DOMAIN, old, config_entry=entry, device_id=old_device.id)
            registry.async_update_entity(entity.entity_id, name="Keep my name")
            targets[entity.entity_id] = (entry.entry_id, f"jackery_{entry.data['device_sn']}_{suffix}", old_device.id)
        registry.async_get_or_create("sensor", DOMAIN, f"jackery_plug_CHILD{i}_power", config_entry=entry, device_id=child.id)
    for i in order:
        other_before = registry_snapshot(hass, registry_entries[1 - i])
        await _migrate_unique_ids(hass, registry_entries[i])
        assert registry_snapshot(hass, registry_entries[1 - i]) == other_before
        first = registry_snapshot(hass, registry_entries[i])
        await _migrate_unique_ids(hass, registry_entries[i])
        assert registry_snapshot(hass, registry_entries[i]) == first
    for entity_id, (owner, uid, device_id) in targets.items():
        entity = registry.async_get(entity_id)
        assert (entity.config_entry_id, entity.unique_id, entity.device_id, entity.name) == (owner, uid, device_id, "Keep my name")
    for i, entry in enumerate(registry_entries):
        parent = devices.async_get_device(identifiers={(DOMAIN, entry.data["device_sn"])})
        child = devices.async_get_device(identifiers={(DOMAIN, f"sub_CHILD{i}")})
        assert child.via_device_id == parent.id
        assert parent.config_entries == {entry.entry_id}


async def test_migration_conflict_is_scoped_to_entity_domain(hass, registry_entries):
    entry = registry_entries[0]
    registry = er.async_get(hass)
    source = registry.async_get_or_create("sensor", DOMAIN, "jackery_battery_soc", config_entry=entry)
    registry.async_get_or_create("switch", DOMAIN, f"jackery_{HOSTS[0]}_battery_soc", config_entry=entry)
    await _migrate_unique_ids(hass, entry)
    migrated = registry.async_get(source.entity_id)
    assert migrated is not None
    assert migrated.unique_id == f"jackery_{HOSTS[0]}_battery_soc"


async def test_main_device_migration_cannot_rewrite_foreign_device(hass, registry_entries):
    entry, other = registry_entries
    registry = dr.async_get(hass)
    registry.async_get_or_create(config_entry_id=other.entry_id, identifiers={(DOMAIN, entry.entry_id)})
    before = registry_snapshot(hass, other)
    await _migrate_unique_ids(hass, entry)
    assert registry_snapshot(hass, other) == before


@pytest.mark.parametrize("index", [0, 1])
async def test_migration_target_owned_by_other_entry_is_not_claimed(hass, registry_entries, index):
    entry, other = registry_entries[index], registry_entries[1 - index]
    registry = er.async_get(hass)
    registry.async_get_or_create("sensor", DOMAIN, "jackery_battery_soc", config_entry=entry)
    # A restored registry may already associate A's target ID with B.
    registry.async_get_or_create("sensor", DOMAIN, f"jackery_{entry.data['device_sn']}_battery_soc", config_entry=other)
    before_other = registry_snapshot(hass, other)
    before_source = registry_snapshot(hass, entry)
    await _migrate_unique_ids(hass, entry)
    assert registry_snapshot(hass, other) == before_other
    assert registry_snapshot(hass, entry) == before_source


@pytest.mark.parametrize("index", [0, 1])
async def test_existing_cleanup_policy_is_scoped_and_idempotent(hass, registry_entries, index):
    registry = er.async_get(hass)
    removals = {}
    for entry in registry_entries:
        host = entry.data["device_sn"]
        removals[entry.entry_id] = [registry.async_get_or_create(domain, DOMAIN, uid, config_entry=entry).entity_id
                                  for domain, uid in [
                                      ("sensor", f"jackery_{host}_main_battery_soc"),
                                      ("select", f"jackery_{host}_max_feed_in_select"),
                                  ]]
        registry.async_get_or_create("sensor", DOMAIN, f"jackery_{host}_battery_soc", config_entry=entry)
        registry.async_get_or_create("sensor", DOMAIN, f"jackery_{entry.entry_id}_battery_soc", config_entry=entry)
    entry, other = registry_entries[index], registry_entries[1 - index]
    before_other = registry_snapshot(hass, other)
    await _migrate_unique_ids(hass, entry)
    assert all(registry.async_get(entity_id) is None for entity_id in removals[entry.entry_id])
    assert registry.async_get_entity_id("sensor", DOMAIN, f"jackery_{entry.entry_id}_battery_soc") is not None
    first = registry_snapshot(hass, entry)
    await _migrate_unique_ids(hass, entry)
    assert registry_snapshot(hass, entry) == first
    assert registry_snapshot(hass, other) == before_other


@pytest.mark.parametrize("order", [HOSTS, HOSTS[::-1]])
async def test_meters_and_plugs_reappear_without_changing_ownership(hass, setup_hosts, order):
    entries = await setup_hosts(order)
    for host in order:
        c = coordinator_for(hass, entries[host])
        await discover(hass, c, f"METER_{host}", "ct_3phase", 3, 5, "cts")
        await discover(hass, c, f"PLUG_{host}", "plug", 6, 0, "plugs")
    for host in order:
        c = coordinator_for(hass, entries[host])
        other = entries[next(h for h in HOSTS if h != host)]
        before_other = registry_snapshot(hass, other)
        before_own = registry_snapshot(hass, entries[host])
        report(c, {"cts": [], "plugs": []})
        report(c, {"cts": [{"deviceSn": f"METER_{host}", "devType": 3, "subType": 5, "name": "Renamed"}]})
        await discover(hass, c, f"PLUG_{host}", "plug", 6, 0, "plugs")
        assert registry_snapshot(hass, entries[host]) == before_own
        await discover(hass, c, f"REPLACEMENT_{host}", "ct_3phase", 3, 5, "cts")
        after = registry_snapshot(hass, entries[host])
        # Retention is the existing policy; do not invent automatic unpair cleanup.
        assert before_own[0].items() <= after[0].items()
        assert before_own[1].items() <= after[1].items()
        assert len(after[0]) == len(before_own[0]) + len(SUBDEVICE_SENSORS["ct_3phase"])
        assert registry_snapshot(hass, other) == before_other


@pytest.mark.parametrize("prefix", ["smartmeter", "battery", "ct", "plug", "collector", "SmartMeter", "Battery"])
@pytest.mark.parametrize("serial", ["123_abc", "lower001"])
async def test_child_without_device_association_is_preserved(hass, registry_entries, prefix, serial):
    entry = registry_entries[0]
    registry = er.async_get(hass)
    source = registry.async_get_or_create("sensor", DOMAIN, f"jackery_{prefix}_{serial}_comm_mode", config_entry=entry)
    before = registry_snapshot(hass, entry)
    await _migrate_unique_ids(hass, entry)
    await _migrate_unique_ids(hass, entry)
    assert registry_snapshot(hass, entry) == before
    assert registry.async_get(source.entity_id) is not None


@pytest.mark.parametrize("index", [0, 1])
@pytest.mark.parametrize("shared", [False, True])
async def test_device_migration_checks_exclusive_ownership(hass, registry_entries, index, shared):
    entry, other = registry_entries[index], registry_entries[1 - index]
    registry = dr.async_get(hass)
    identifiers = {(DOMAIN, entry.entry_id)}
    registry.async_get_or_create(config_entry_id=other.entry_id, identifiers=identifiers)
    if shared:
        registry.async_get_or_create(config_entry_id=entry.entry_id, identifiers=identifiers)
    before = [registry_snapshot(hass, e) for e in registry_entries]
    await _migrate_unique_ids(hass, entry)
    await _migrate_unique_ids(hass, entry)
    assert [registry_snapshot(hass, e) for e in registry_entries] == before


@pytest.mark.parametrize("target_owner", [0, 1])
async def test_device_migration_preserves_both_conflicting_devices(hass, registry_entries, target_owner):
    entry = registry_entries[0]
    registry = dr.async_get(hass)
    registry.async_get_or_create(config_entry_id=entry.entry_id, identifiers={(DOMAIN, entry.entry_id)})
    registry.async_get_or_create(config_entry_id=registry_entries[target_owner].entry_id,
                                 identifiers={(DOMAIN, HOSTS[0])})
    before = [registry_snapshot(hass, e) for e in registry_entries]
    await _migrate_unique_ids(hass, entry)
    await _migrate_unique_ids(hass, entry)
    assert [registry_snapshot(hass, e) for e in registry_entries] == before


@pytest.mark.parametrize("index", [0, 1])
async def test_metadata_update_cannot_mutate_foreign_host(hass, registry_entries, index):
    entry, other = registry_entries[index], registry_entries[1 - index]
    registry = dr.async_get(hass)
    device = registry.async_get_or_create(config_entry_id=other.entry_id,
                                          identifiers={(DOMAIN, entry.data["device_sn"])},
                                          model="Keep model", sw_version="Keep firmware")
    c = JackeryDataCoordinator(hass, "hb", "tok", "localhost", entry.data["device_sn"])
    c.config_entry_id = entry.entry_id
    c._soft_ver = "New firmware"
    await c._update_device_registry()
    assert registry.async_get(device.id) == device


@pytest.mark.parametrize("group,dev_type,sub_type,data_key", [CHILDREN[0], CHILDREN[2], CHILDREN[5]])
@pytest.mark.parametrize("ownership", ["own", "foreign", "shared"])
async def test_child_cleanup_requires_exclusive_ownership(hass, setup_hosts, group, dev_type, sub_type, data_key, ownership):
    entries = await setup_hosts()
    own, other = entries[HOSTS[0]], entries[HOSTS[1]]
    owner = own if ownership == "own" else other
    c = coordinator_for(hass, own)
    await discover(hass, coordinator_for(hass, owner), "ABC", group, dev_type, sub_type, data_key)
    # Substring/underscore overlap must not remove these listeners or devices.
    for serial in ["ABC1", "XABC", "ABC_extra", "X_ABC"]:
        await discover(hass, c, serial, group, dev_type, sub_type, data_key)
    registry = dr.async_get(hass)
    identifier = child_device_identifier(owner.data["device_sn"], "ABC")
    device = registry.async_get_device(identifiers={(DOMAIN, identifier)})
    if ownership == "shared":
        registry.async_get_or_create(config_entry_id=own.entry_id, identifiers={(DOMAIN, identifier)})
    before_other = registry_snapshot(hass, other)
    other_listeners = {key: entity for key, entity in c._sensors.items() if getattr(entity, "_plug_sn", None) != "ABC"}
    c._remove_subdevice_from_ha("ABC")
    await hass.async_block_till_done()
    assert registry_snapshot(hass, other) == before_other
    assert (registry.async_get(device.id) is None) == (ownership == "own")
    assert c._sensors == other_listeners
    if ownership == "own":
        assert not er.async_entries_for_device(er.async_get(hass), device.id)
        await discover(hass, c, "ABC", group, dev_type, sub_type, data_key)
        assert registry.async_get_device(identifiers={(DOMAIN, identifier)}) is not None


def test_listener_matching_uses_stored_child_serial():
    c = JackeryDataCoordinator(None, "hb", "tok", "localhost", "ABC")
    from custom_components.jackery.sensor import JackerySensor
    main = JackerySensor("battery_soc", c, "entry")
    c.register_sensor("jackery_ABC_battery_soc", main)
    expected = []
    for sn in ["ABC", "ABC1", "XABC", "ABC_extra", "X_ABC"]:
        entities = [*child_entities(c, sn, "plug", 6, "plugs"), JackeryPlugSwitch(sn, 6, c, "entry"),
                    JackerySmartMeterHttpSensor(sn, "frequency", SMARTMETER_HTTP_SENSOR_CONFIGS["frequency"], c, "entry")]
        for entity in entities:
            c.register_sensor(entity.unique_id, entity)
            if sn == "ABC":
                expected.append(entity.unique_id)
    assert c._entity_keys_for_subdevice("ABC") == expected


@pytest.mark.parametrize("platform", ["switch", "other_integration"])
async def test_migration_target_respects_domain_and_platform(hass, registry_entries, platform):
    registry = er.async_get(hass)
    entry = registry_entries[0]
    source = registry.async_get_or_create("sensor", DOMAIN, "jackery_battery_soc", config_entry=entry)
    target_uid = f"jackery_{HOSTS[0]}_battery_soc"
    unrelated = registry.async_get_or_create("switch" if platform == "switch" else "sensor",
                                            DOMAIN if platform == "switch" else platform,
                                            target_uid, config_entry=entry)
    await _migrate_unique_ids(hass, entry)
    assert registry.async_get(source.entity_id).unique_id == target_uid
    assert registry.async_get(unrelated.entity_id) == unrelated


@pytest.mark.parametrize("domain,uid", [
    ("switch", "jackery_SOLARVAULT_A_max_feed_in_select"),
    ("sensor", "jackery_SOLARVAULT_A_main_unknown"),
])
async def test_obsolete_cleanup_does_not_delete_unrelated_records(hass, registry_entries, domain, uid):
    registry = er.async_get(hass)
    entity = registry.async_get_or_create(domain, DOMAIN, uid, config_entry=registry_entries[0])
    await _migrate_unique_ids(hass, registry_entries[0])
    assert registry.async_get(entity.entity_id) == entity


@pytest.mark.parametrize("group,dev_type,sub_type,data_key", CHILDREN)
def test_host_scoped_child_formats_preserve_family_and_fields(group, dev_type, sub_type, data_key):
    c = JackeryDataCoordinator(None, "hb", "tok", "localhost", HOSTS[0])
    family = {"ct_3phase": "smartmeter", "expansion_battery": "battery"}.get(group, group)
    for entity, key in zip(child_entities(c, "123_abc", group, dev_type, data_key), SUBDEVICE_SENSORS[group], strict=True):
        assert entity.unique_id == f"jackery_child:{HOSTS[0]}:123_abc:{family}:{key.replace('_', '')}"
        assert entity.device_info["identifiers"] == {(DOMAIN, f"child:{HOSTS[0]}:123_abc")}
        assert entity.device_info["via_device"] == (DOMAIN, HOSTS[0])
    switch = JackeryPlugSwitch("123_abc", 6, c, "entry")
    assert switch.unique_id == f"jackery_child:{HOSTS[0]}:123_abc:plug:switch"
    assert switch.device_info["identifiers"] == {(DOMAIN, f"child:{HOSTS[0]}:123_abc")}
    for key, config in SMARTMETER_HTTP_SENSOR_CONFIGS.items():
        entity = JackerySmartMeterHttpSensor("123_abc", key, config, c, "entry")
        assert entity.unique_id == f"jackery_{HOSTS[0]}_http_sm_123_abc_{key}"
        assert entity.device_info["identifiers"] == {(DOMAIN, f"child:{HOSTS[0]}:123_abc")}


@pytest.mark.parametrize("setup_hosts", [False, True, None], indirect=True)
async def test_http_polling_reload_has_one_task_per_entry(hass, setup_hosts):
    polls = []

    async def idle_http(coordinator):
        polls.append(coordinator)
        await asyncio.Future()

    with patch.object(JackeryDataCoordinator, "_smartmeter_http_poll_loop", idle_http):
        entries = await setup_hosts()
        own, other = entries[HOSTS[0]], entries[HOSTS[1]]
        other_coordinator = coordinator_for(hass, other)
        for entry in entries.values():
            assert coordinator_for(hass, entry)._smartmeter_http_task is None
        hass.config_entries.async_update_entry(own, options={"smartmeter_http_poll": True})
        for _ in range(2):
            assert await hass.config_entries.async_reload(own.entry_id)
            await hass.async_block_till_done()
            c = coordinator_for(hass, own)
            assert polls.count(c) == 1
            task = c._smartmeter_http_task
            assert task is not None and not task.done()
            assert coordinator_for(hass, other) is other_coordinator
            assert other_coordinator._smartmeter_http_task is None
            assert await hass.config_entries.async_unload(own.entry_id)
            assert task.done() and c._data_task.done()
            assert not c._sensors
        assert len(polls) == 2


async def test_ambiguous_unlinked_ct_identity_is_not_guessed(hass, registry_entries, caplog):
    # This is both a legacy main sensor key and the current CT sensor ID for
    # serial "import", key "energy". Without its device link, ownership is unclear.
    registry = er.async_get(hass)
    source = registry.async_get_or_create("sensor", DOMAIN, "jackery_ct_import_energy",
                                          config_entry=registry_entries[0])
    await _migrate_unique_ids(hass, registry_entries[0])
    assert registry.async_get(source.entity_id) == source
    assert "ambiguous" in caplog.text


@pytest.mark.parametrize("child", [False, True])
async def test_device_link_disambiguates_overlapping_ct_identity(hass, registry_entries, child):
    entry = registry_entries[0]
    devices, registry = dr.async_get(hass), er.async_get(hass)
    device = devices.async_get_or_create(config_entry_id=entry.entry_id,
                                         identifiers={(DOMAIN, "sub_import" if child else entry.entry_id)})
    source = registry.async_get_or_create("sensor", DOMAIN, "jackery_ct_import_energy",
                                          config_entry=entry, device_id=device.id)
    await _migrate_unique_ids(hass, entry)
    assert registry.async_get(source.entity_id).unique_id == (
        "jackery_ct_import_energy" if child else f"jackery_{HOSTS[0]}_ct_import_energy"
    )


async def test_shared_http_mqtt_device_cleanup_retains_both_entries(hass, setup_hosts):
    entries = await setup_hosts()
    a, b = (coordinator_for(hass, entries[host]) for host in HOSTS)
    # Seed the historical state explicitly: current discovery correctly keeps
    # these two hosts separate, but existing shared records must stay protected.
    mqtt = child_entities(b, "SHARED", "ct_3phase", 3, "cts")[0]
    mqtt._attr_unique_id = "jackery_smartmeter_SHARED_importtotal"
    mqtt._attr_device_info["identifiers"] = {(DOMAIN, "sub_SHARED")}
    http = JackerySmartMeterHttpSensor("SHARED", "frequency", SMARTMETER_HTTP_SENSOR_CONFIGS["frequency"], a, a.config_entry_id)
    http._attr_device_info["identifiers"] = {(DOMAIN, "sub_SHARED")}
    b.add_entities_callback([mqtt])
    a.add_entities_callback([http])
    await hass.async_block_till_done()
    registry = dr.async_get(hass)
    device = registry.async_get_device(identifiers={(DOMAIN, "sub_SHARED")})
    assert device.config_entries == {entry.entry_id for entry in entries.values()}
    before = [registry_snapshot(hass, entry) for entry in entries.values()]
    listeners = dict(a._sensors)
    for c in [a, b]:
        c._child_migration = migrate_child_identities(hass, entries[c._device_sn])
        c._remove_subdevice_from_ha("SHARED")
        await _migrate_unique_ids(hass, entries[c._device_sn])
    await hass.async_block_till_done()
    assert [registry_snapshot(hass, entry) for entry in entries.values()] == before
    assert a._sensors == listeners
