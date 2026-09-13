# Coordinator state ownership

This inventory records the mutable `JackeryDataCoordinator` state and the
implemented Phase 2 runtime-state boundary. It distinguishes stored
protocol/runtime data from Home Assistant effects and transport lifetime. A
field being mutable does not by itself justify moving it.

## Mutable-state inventory

| Field | Writers | Readers | Lifetime and category | Ownership decision |
| --- | --- | --- | --- | --- |
| `_data_cache` | MQTT route handlers, energy calculation, optimistic controls | entities, discovery, commands, HTTP meter lookup, diagnostics tests | One coordinator instance; protocol/runtime data | Runtime state owns storage and protocol-derived values; coordinator and platform compatibility access remain |
| `_power_live_seen` | live Type 2/23/25/107 merge, Type-106 expiry | Type-106 arbitration, tests | Ephemeral per coordinator; protocol/runtime source evidence | Runtime state |
| `_power_106_samples` | every preferred Type-106 field | source diagnostics/tests | Ephemeral per coordinator; raw snapshot evidence | Runtime state |
| `_energy_sources` | calculation adapter | diagnostics/tests | Recomputed per coordinator; source diagnostics | Runtime state |
| `_subdevice_last_seen` | child array, point, Type-23 and generic route handling | availability and source selection | Ephemeral per coordinator; freshness | Runtime state |
| `_last_update_time` | accepted host-topic messages | host timeout and Type-106 receipt time | Ephemeral per coordinator; host freshness | Runtime state |
| `_start_time` | constructor | startup grace and reauth heuristic | Ephemeral per coordinator; freshness/lifecycle reference | Runtime state |
| `_ever_received` | accepted messages | reauth heuristic | Ephemeral per coordinator; host activity | Runtime state |
| `_subdevice_missing_since` | discovery reconciliation and removal | deletion timer | Ephemeral per coordinator; discovery/controller state | Coordinator: semantics depend on cached membership, entity removal and registry effects |
| `_known_plugs` | discovery and removal | discovery, availability, migration tests | Ephemeral per coordinator; discovery state | Coordinator: directly gates entity creation |
| `_expansion_battery_sns` | expansion discovery/removal | availability, deletion and offline exceptions | Ephemeral per coordinator; discovery policy | Coordinator: membership is established while creating entities; runtime state receives only the resulting policy flag |
| `_device_sn` | configuration or first accepted topic | topics, identity, commands, registry, routing | Coordinator lifetime; configuration/host identity | Coordinator |
| `_device_type` | host metadata capture | device registry update | Coordinator lifetime; HA device metadata | Coordinator |
| `_soft_ver` | host metadata capture | device registry update | Coordinator lifetime; HA device metadata | Coordinator |
| `_reauth_started` | reauth trigger | reauth guard | Coordinator lifetime; HA config-flow state | Coordinator |
| `_http_sm_sensors_created` | HTTP polling loop | HTTP polling loop | Coordinator lifetime; HTTP/entity lifecycle | Coordinator |
| `_sensors` | entity registration/unregistration/removal | fan-out, availability and offline effects | HA entity lifetime | Coordinator; never runtime state |
| `add_entities_callback` | sensor platform setup | discovery | HA platform lifetime | Coordinator |
| `add_switch_entities_callback` | switch platform setup | discovery | HA platform lifetime | Coordinator |
| `_data_task` | MQTT start/tests | stop/cleanup | Transport lifetime | Coordinator |
| `_smartmeter_http_task` | optional HTTP start/tests | stop/cleanup | Transport lifetime | Coordinator |
| `_subscribed` | start/cleanup | lifecycle guard/tests | Transport lifetime | Coordinator |
| `_mqtt_unsubscribers` | each successful subscribe/cleanup | cleanup/tests | Transport lifetime | Coordinator |
| `_lifecycle_lock` | constructor | start/stop | Transport concurrency lifetime | Coordinator |
| `_poll_105_counter` | poll sender | poll sender | Transport polling lifetime | Coordinator |
| `_child_migration` | setup | discovery/removal identity guard | Config-entry lifetime; persistent-registry adapter result | Coordinator |
| `config_entry_id` | setup/tests | registry, identity, reauth and entity creation | Config-entry lifetime | Coordinator |

Configuration values (`hass`, topic/token/host fields and derived topic strings)
are stable dependencies after construction apart from the documented empty-host
serial adoption. They remain coordinator-owned.

## Availability ownership contract

The runtime state records activity; it does not update Home Assistant entities.
An accepted host-topic envelope records host activity. Child array, point and
matching Type-23 reports record per-child activity. The runtime availability
query applies the existing 60-second timeout and startup grace; a discovered
expansion battery remains eligible once it has been seen. The coordinator uses
that answer to set `_attr_available` and call `async_write_ha_state`.

The calculation adapter passes the same child availability and activity age to
`calculations.energy_flow.select_grid_source`. An expired child can therefore
be excluded from source selection while its raw cached measurements remain.
HTTP sensor health is separate: MQTT activity never marks an HTTP sensor healthy,
and HTTP polling does not refresh MQTT timestamps.

`CoordinatorRuntimeState.child_is_available()` owns only the deterministic
freshness answer. `JackeryDataCoordinator._update_subdevice_availability()`,
`_distribute_data()` and `_mark_all_offline()` retain every entity mutation and
state write. The host timeout decision delegates to
`CoordinatorRuntimeState.host_is_stale()`; the polling loop still decides when
to evaluate it and which MQTT entities to mark unavailable.

Missing-child timing is distinct from activity freshness. It belongs to the
discovery/controller path because expiry can remove registry objects and entity
references. Expansion batteries keep their existing deletion and cumulative
energy exceptions.

## Lifecycle and reset

Runtime state is created once with each coordinator and is discarded on unload;
a reload constructs empty cache/evidence maps, fresh timestamps and
`ever_received=False`. Registry identity and migration results are not runtime
state. MQTT unsubscribe callbacks, tasks, locks, HTTP creation state and reauth
guards also remain coordinator-owned and reset with the coordinator.

Compatibility properties on `JackeryDataCoordinator` preserve the established
private cache/freshness access used by current platform adapters and tests. They
refer to the same runtime-state objects and do not duplicate storage.
