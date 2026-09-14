# Responsibility and coupling map

Phase 2 now extracts pure topic/envelope routing into `protocol/routing.py`,
payload normalization into `protocol/normalization.py`, the energy calculation
bundle into `calculations/energy_flow.py` and child-device classification into
`devices/classification.py`. Ephemeral cache, freshness, Type-106 evidence and
source metadata now live in `coordinator_state.py`; see
[architecture.md](architecture.md). The routing
module depends only on normalization and the standard library; the other four
use only the standard library. `sensor.py` retains route application, child
cache placement, discovery orchestration, entity effects and error logging.
Child membership/timer decisions live in `discovery.py`; registry/entity updates
and all transport behavior remain in `sensor.py`. The
runtime-state extraction preserves the contract in
[energy-source-policy.md](energy-source-policy.md).

The subsequent [MQTT lifecycle fix](mqtt-lifecycle.md) retains subscription
cleanup handles per coordinator and adds setup-failure/unload cleanup in place.
Subscription ownership is now tested before any transport extraction.

Follow-up [identity audit](multi-instance-identity.md): registry tests now reproduce
the child identity/migration risks below, and a forced platform ordering test
confirms controls can return before sensor setup creates their coordinator.
PR2A fixes migration/cleanup safety and creates the coordinator before platform
forwarding. PR2B now isolates child identities by host and migrates unambiguous
registry records in place. `identity.py` owns shared identity construction and
canonical recognition; `child_migration.py` owns registry preflight/apply. Setup
runs migration before forwarding; discovery and cleanup consult its conflict
result. These additions are confined to persistent identity correctness. At that
point, no protocol, transport, calculation or coordinator extraction had been
performed; the source map below preserves that pinned baseline before the Phase
2 completion record above.

Pinned historical source: [baseline](baseline.md). Destinations below describe
the original plan; completion labels record implemented extractions. At that
baseline C `sensor.py` had 2,913 lines: definitions 60–1123, protocol helpers
1126–1310, coordinator 1311–2393, setup/entities 2396–2913. The coordinator
remains a custom class, not HA DataUpdateCoordinator.

| Cohesive concern / existing symbols | Dependencies and callers | Mutable state / relevant tests | Destination / risk |
| --- | --- | --- | --- |
| DOMAIN, PLATFORMS; timing/model/status/comm/subtype/bit constants | `__init__.py`; sensor, switch, select, config flow imports. HA-specific enum metadata in SENSORS must stay near entities. | Constants only; `TestConstants`, `TestCommModeLabels`, SOC bound tests | `const.py` for integration policy; `protocol/constants.py` for actual wire maps. LOW, but avoid circular imports and re-export old names initially. |
| `_field_present`, `_safe_float`, `_power_sample`, `_ct_power`, `_pick_best_power_net`, `_effective_ongrid_net`, `_grid_net_from_system`, `select_grid_source`, `calculate_energy_flow` | **Extracted:** `calculations/energy_flow.py`, imported by sensor coordinator adapter. Standard library only. | Pure selection plus established mutation/return contract for derived keys. Direct calculation/helper/source tests and full coordinator regressions. | **COMPLETED Phase 2.** Runtime normalization/freshness preparation and logging remain in `_calculate_energy_flow`; no semantic redesign. |
| `normalize_payload_fields`, `extract_flat_body`, `_FLAT_*` | **Extracted:** `protocol/normalization.py`, imported by the sensor coordinator and calculation adapter. Standard library only. `_TYPE106_LIVE_PREFERRED` remains in sensor because its policy depends on cache age/state. | Pure shallow copies; explicit canonical/null/zero rules, alias and unknown-field retention, unchanged flat whitelist and metadata stripping. Direct normalization and route tests. | **COMPLETED Phase 2.** Routing, host/type acceptance, cache application, classification, freshness and Type-106 policy remain outside normalization. |
| `should_create_plug_switch`; discovery and point-update type/subtype branches | **Extracted:** `devices/classification.py`, imported by sensor and switch. Contexts retain route-specific plug/CT defaults, Type-102 field inference and Type-23 expansion-battery recognition. `plug_comm_mode` and `plug_mqtt_control_allowed` remain in sensor as control policy. | Pure immutable result; direct family/model/context tests plus full discovery/entity snapshots, contradictory metadata, subtype changes and two-host identity coverage. | **COMPLETED Phase 2.** Classification only: routing, cache/source-array selection, entity construction, identity and communication policy remain with their existing owners. Diagnostic subtype labels are not used as the classifier. |
| `_subdevice_sn`, `_merge_subdevice_list`, `_merge_subdevice_arrays`, `_merge_subdevice_point_update` | **Partly extracted:** serial validation is `protocol.routing.subdevice_serial`; cache storage/activity timestamps are runtime state; coordinator merge helpers retain classifier/default/list placement logic. | Runtime `data_cache`, alias `plug is plugs`, runtime `subdevice_last_seen`; direct state/routing and ordered transition tests. | **COMPLETED safe Phase 2 portion.** Child merge policy stays coordinator-owned because identity/aliasing/null/empty-list behavior differs by route and feeds discovery. |
| `_handle_message` envelope parse/routing | **Extracted pure boundary:** `protocol.routing` parses exact topics, validates/reconstructs envelopes, sanitizes array shapes and returns immutable route decisions. Coordinator applies each route and retains the final pipeline. | Host activity/cache live in runtime state; `_device_sn` and route/HA side effects remain coordinator-owned; direct module tests plus explicit ordered transitions. | **COMPLETED Phase 2 partial extraction.** Preserve type/body.cmd distinctions, generic fallback, Type-123 post-processing and exception containment. |
| Main cache/derived state and listener dispatch (`_merge_normalized_cache`, `_distribute_data`, register/unregister) | **Partly extracted:** `CoordinatorRuntimeState` owns cache/main merges/source evidence. Platforms retain a compatibility cache view; coordinator owns listener dispatch. | Runtime `data_cache`; coordinator `_sensors`; optimistic, direct state and real fan-out tests. | **COMPLETED safe Phase 2 state portion.** Entity references and callbacks never enter runtime state. Further public coordinator API work belongs with later platform simplification. |
| Subdevice discovery/lifecycle (`_check_for_new_plugs`, `_check_for_new_expansion_batteries`, get_subdevices/get_plug_item) | **Partly extracted:** `discovery.py` owns HA-independent membership/timer decisions and family-to-entity specifications. Coordinator retains array collection, identity eligibility, construction and callbacks. | `ChildDiscoveryState` owns known/expansion/missing collections; compatibility aliases remain. Direct transitions plus existing callback, reload and identity suites. | **COMPLETED safe Phase 2 portion.** No entity factory: the sensor class remains in `sensor.py`, and moving it would broaden the platform change. HTTP replacement policy is unchanged. |
| Availability/removal (`_entity_keys_for_subdevice`, `_remove_subdevice_from_ha`, `_mark_all_offline`, child parts of `_check_for_new_plugs`) | Runtime state answers freshness; discovery state decides missing/reappeared/due; coordinator uses HA registry and entity write methods. | Runtime last-seen/start state; discovery membership/timers; coordinator `_sensors`; ordered state and HA availability tests. | **COMPLETED safe Phase 2 state/discovery portion.** Registry ownership, actual deletion, listener cleanup and availability effects remain coordinator-owned. |
| Metadata and reauth (`_capture_device_meta`, `_update_device_registry`, `_trigger_reauth`) | Handler schedules registry task; periodic loop triggers heuristic; config flow handles credential form. | `_device_type`, `_soft_ver`, `_reauth_started`, config_entry_id, HA task scheduling. Routing tests only guard flag. | `coordinator.py` orchestration with HA entry/registry adapter in `__init__.py`; no extra framework. MEDIUM–HIGH: child contamination, unload races. |
| MQTT lifecycle (`async_start`, `async_stop`, `_periodic_data_request`, `_send_poll_requests`) | **Extracted low-level boundary:** `transport/mqtt.py` owns HA subscribe/publish, JSON serialization and unsubscribe handles. Coordinator retains locks, tasks, topics, cadence, command/poll decisions and log policy. | Transport-local handles; coordinator `_subscribed`, `_data_task`, `_poll_105_counter`; direct transport tests and full lifecycle integration tests. | **COMPLETED safe Phase 2 transport portion.** Per-coordinator transport preserves partial-start cleanup, idempotence and isolation. Poll scheduling and HTTP remain coordinator-owned; no reconnect/ack/retry redesign. |
| Command building (`async_control_main_device`, `async_control_subdevice_switch`, poll envelopes) | **Extracted:** `protocol/commands.py` builds the action topic and exact plain-dict envelopes; coordinator supplies runtime IDs/time and publishes. | Direct exact-dict tests plus existing entity/control, cadence, failure and optimism contracts. | **COMPLETED Phase 2.** Standard-library-only builders; coordinator retains validation, JSON/MQTT, logging, sequencing and state effects. No command manager, acknowledgement, retry or correlation semantics added. |
| HTTP (`_find_smartmeter_ip_and_sn`, `_smartmeter_http_poll_loop`, `_create_http_sensors`, `_distribute_http_data`, `_mark_http_sensors_unavailable`) | **Extracted low-level boundary:** `transport/smartmeter_http.py` owns URL construction, the shared-session GET, five-second timeout, status/JSON handling and configured-key numeric validation. Coordinator retains MQTT-cache target discovery, task/cadence, health and all entity effects. | Coordinator `_smartmeter_http_task`, per-serial `_http_sm_sensor_sns_created`; failure counter and `last_sm_sn` remain loop locals. Direct transport tests plus replacement/lifecycle/isolation tests. | **COMPLETED safe Phase 2 transport portion.** Replacement serials receive distinct entity sets; returning serials do not duplicate them. Old-meter removal, source, threshold and entity policy remain unchanged. |
| Main/sub/HTTP definitions and entity classes | **Definitions extracted:** `entities/sensor_definitions.py` owns unchanged HA metadata; entity classes retain cache access, transforms and HA writes in `sensor.py`. | Direct export/group-boundary tests plus existing entity/identity/translation snapshots. | **COMPLETED safe declarative portion.** `sensor.py` compatibility re-exports preserve imports. Complex route-specific value transforms and registration remain with entities. |
| Switch/number/select/button adapters | Platform modules own entities and current cache/control effects. Pure plug `commMode` and control-eligibility transforms moved to `entities/transforms.py`; discovery still imports the switch class dynamically. | Direct transform tests plus existing command, optimism, bounds and lifecycle contracts. | **COMPLETED small transform portion.** The prior runtime `switch.py → sensor.py` helper dependency is removed. Further coordinator API work remains separate. |
| Config/setup/unload/migration (`__init__.py`, `config_flow.py`) | HA entries/registry, platform forwarding, options and token; sensor setup constructs coordinator. | hass.data per entry, entity/device registry; four flow + six migration tests. | Keep migration in `__init__.py` until independently covered; coordinator construction moves here only after lifecycle tests. HIGH: compatibility and partial setup cleanup. |

## Dependency direction to untangle

Today `__init__.py` creates and stores the coordinator before forwarding
platforms, and starts it after dynamic callbacks exist. The former runtime
`switch.py → sensor.py` helper edge is removed; `sensor.py` still imports the
switch entity dynamically for discovery. All platforms can still reach
coordinator internals, and HTTP entities use a different update interface in the
same listener map. The remaining discovery/entity coupling is documented for a
separate change.

Pure calculations, protocol normalization, structural routing, runtime state and
device classification have no operational HA dependency. `sensor.py` imports
these lower-level packages; routing imports normalization, while runtime state
uses only the standard library. None imports the coordinator. Discovery and HA
effects remain coupled in the coordinator by design.

Keep registry identifiers and unique-ID migration outside structural changes. Fix source-confirmed defects separately. Never replace raw keys with canonical names during a move; alias precedence and raw retention are part of the observed contract.
