"""Identity audit using actual platforms and HA registries, with synthetic serials.

Safety assertions intentionally expose unresolved baseline defects. See
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
from custom_components.jackery.sensor import (
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
    """Real HA platforms, sensor-first ordering, mocked MQTT and timed polling.

    Production forwards concurrently despite other platforms needing the sensor
    coordinator. Control ordering here so that separate startup defect does not
    obscure registry assertions; one explicit case exercises the inverse order.
    """
    entries = {}
    forward = hass.config_entries.async_forward_entry_setups

    async def ordered_forward(entry, platforms):
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
        patch.object(JackeryDataCoordinator, "_periodic_data_request", idle_poll),
        patch.object(hass.config_entries, "async_forward_entry_setups", ordered_forward),
    ):
        yield setup
        for entry in entries.values():
            if entry.state is config_entries.ConfigEntryState.LOADED:
                assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


@pytest.mark.parametrize("setup_hosts", [True], indirect=True)
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
        assert all(e.unique_id.startswith(f"jackery_{host}_") for e in entities)
    for host in order:
        other = entries[next(h for h in HOSTS if h != host)]
        before_other = registry_snapshot(hass, other)
        before_own = registry_snapshot(hass, entries[host])
        old_coordinator = coordinator_for(hass, entries[host])
        assert await hass.config_entries.async_unload(entries[host].entry_id)
        assert not old_coordinator._sensors
        assert old_coordinator._data_task.done()
        assert registry_snapshot(hass, other) == before_other
        assert await hass.config_entries.async_setup(entries[host].entry_id)
        await hass.async_block_till_done()
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
        device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, f"sub_CHILD_{host}")})
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
                                      ("sensor", f"jackery_{entry.entry_id}_battery_soc"),
                                  ]]
        registry.async_get_or_create("sensor", DOMAIN, f"jackery_{host}_battery_soc", config_entry=entry)
    entry, other = registry_entries[index], registry_entries[1 - index]
    before_other = registry_snapshot(hass, other)
    await _migrate_unique_ids(hass, entry)
    assert all(registry.async_get(entity_id) is None for entity_id in removals[entry.entry_id])
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
