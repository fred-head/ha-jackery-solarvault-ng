# Responsibility and coupling map

Phase 2 now extracts the energy calculation bundle into
`calculations/energy_flow.py`; see [architecture.md](architecture.md). Pure
numeric/presence/net helpers, CT/collector/system selection and derived formulas
live there. The module accepts coordinator-prepared `SourceFreshness` and has no
Home Assistant dependency. `sensor.py` retains a narrow adapter for protocol
normalization, runtime child-age ownership, source metadata and error logging.
Type-106 live/snapshot state, timer/entity updates and all transport behavior
remain in `sensor.py`. The extraction preserves the contract in
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
| `_normalize_payload_fields`, `_extract_flat_body`, `_FLAT_*`, `_TYPE106_LIVE_PREFERRED` | Normalize called during all main merges and the calculation adapter; flat extraction only handler. 106 policy depends on cache, not pure normalization. | Helpers return copies; explicit target/null rules; `TestNormalizePayloadFields`, `TestExtractFlatBody`, route tests. | `protocol/normalization.py`; keep 106 cache policy outside helper initially. LOW–MEDIUM. |
| `plug_comm_mode`, `plug_mqtt_control_allowed`, `should_create_plug_switch`; discovery type/subtype branches | switch imports helpers from sensor; sensor dynamically imports switch during discovery. `_merge_subdevice_point_update` also classifies. | Input dict semantics, known sets; v230 helper tests only, no whole discovery coverage. | `devices/classification.py` containing functions and small capability records. HIGH: phase-vs-hardware subtype ambiguity, dynamic/static filter mismatch, HTO/Shelly differentiation. |
| `_subdevice_sn`, `_merge_subdevice_list`, `_merge_subdevice_arrays`, `_merge_subdevice_point_update` | `_handle_message`; use normalization-independent wire keys, classifier, wall clock; point writes existing dict. | `_data_cache`, alias `plug is plugs`, `_subdevice_last_seen`; routing/upstream-sync tests. | Pure structural parsing into `protocol/parser.py`; cache application to `devices/state.py` only once transitions covered. HIGH: identity/aliasing/null/empty-list policy differs by route. |
| `_handle_message` envelope parse/routing (1421–1550) | HA callback calls it; JSON/regex/time/meta capture; calculation, discovery, distribution chained. | `_last_update_time`, `_ever_received`, `_device_sn`, cache; route tests bypass constructor and often entity creation. | `protocol/parser.py` for validated structural decode; coordinator applies state. HIGH: preserve type/body.cmd distinctions and permissive unknown fallback until separate fixes approved. |
| Main cache/derived state and listener dispatch (`_merge_normalized_cache`, `_distribute_data`, register/unregister) | All entity platforms share coordinator; controls patch private cache; HTTP registers in same map. | `_data_cache`, `_sensors`; optimistic tests, not full fan-out. | `coordinator.py` initially retains cache and updates; later minimal `devices/state.py` if needed. HIGH: HTTP callback mismatch and exception stopping remaining listeners. |
| Subdevice discovery/lifecycle (`_check_for_new_plugs`, `_check_for_new_expansion_batteries`, get_subdevices/get_plug_item) | Message handling; creates Sensor and Switch HA classes; callbacks installed by different platform setups. | `_known_plugs`, `_expansion_battery_sns`, callbacks; current type23 tests do not exercise real entity creation. | Classification in devices; creation remains platform-side via coordinator discovery notifications. HIGH: startup ordering, duplicate callbacks and cached data before entity registration. |
| Availability/removal (`_entity_keys_for_subdevice`, `_remove_subdevice_from_ha`, `_mark_all_offline`, child parts of `_check_for_new_plugs`) | Uses time and HA registry, sensor private availability/write methods; called during messages or periodic main timeout. | Missing-since/last-seen/start time/known sets, `_sensors`; isolated subdevice tests. | Explicit state transitions in coordinator initially; HA registry effects in adapter. HIGH: cached revival, deletion semantics, battery exception, child IDs. |
| Metadata and reauth (`_capture_device_meta`, `_update_device_registry`, `_trigger_reauth`) | Handler schedules registry task; periodic loop triggers heuristic; config flow handles credential form. | `_device_type`, `_soft_ver`, `_reauth_started`, config_entry_id, HA task scheduling. Routing tests only guard flag. | `coordinator.py` orchestration with HA entry/registry adapter in `__init__.py`; no extra framework. MEDIUM–HIGH: child contamination, unload races. |
| MQTT lifecycle (`async_start`, `async_stop`, `_periodic_data_request`, `_send_poll_requests`) | HA mqtt subscribe/publish; asyncio tasks, sleep, random message IDs; metadata/auth/availability folded into poll loop. | `_subscribed`, `_data_task`, `_poll_105_counter`; subscriptions not retained. No wire/lifecycle tests. | `transport/mqtt.py` for subscription/publish/task lifecycle; coordinator schedules policy. HIGH: initial double batch, poll pacing and missing unsubscribe. |
| Command building (`async_control_main_device`, `async_control_subdevice_switch`, poll envelope literals) | Called from switch/number/select/button; all depend on token, host SN, clock/random and HA publish. | Optimistic entity cache writes outside coordinator; fake-coordinator control tests. | `protocol/commands.py` pure builders; `transport/mqtt.py` sends; coordinator boundary retains validation. HIGH: pending-vs-confirmed unknown; do not add command queue during extraction. |
| HTTP (`_find_smartmeter_ip_and_sn`, `_smartmeter_http_poll_loop`, `_create_http_sensors`, `_distribute_http_data`, `_mark_http_sensors_unavailable`) | MQTT child cache supplies discovery IP/SN; HA session/options/task; creates sensor classes directly. | `_smartmeter_http_task`, `_http_sm_sensors_created`; failure counter and last_sm_sn are loop locals, no tests. | `transport/smartmeter_http.py` produces data/health events; sensor platform creates entities. HIGH: malformed JSON failure accounting, mode/IP disappearance, meter replacement, cancellation and interface mismatch. |
| Main/sub/HTTP definitions and entity classes | HA SensorEntity/enums, cache and calculation keys, coordinator internals. Subdevice transforms still contain firmware rules. | Entity native state/availability/raw_data; sensor transforms and direct ENUM tests. | `sensor.py` plus optional `entity.py` for proven common identity/listener lifecycle; transforms into normalization only after characterization. MEDIUM–HIGH: raw units, IDs, parent device, translations, availability. |
| Switch/number/select/button adapters | HA entities and private cache mutations; switch imports sensor helpers, discovery imports switch. | Entity state + cache; optimistic/base/dynamic bounds tests partial. | Keep platform modules; gradually route through stable coordinator API. MEDIUM: preserve cache timing and different optimistic behaviors; do not unify all controls automatically. |
| Config/setup/unload/migration (`__init__.py`, `config_flow.py`) | HA entries/registry, platform forwarding, options and token; sensor setup constructs coordinator. | hass.data per entry, entity/device registry; four flow + six migration tests. | Keep migration in `__init__.py` until independently covered; coordinator construction moves here only after lifecycle tests. HIGH: compatibility and partial setup cleanup. |

## Dependency direction to untangle

Today `__init__.py` forwards platforms; sensor setup stores the coordinator; other platform setups assume it already exists. `switch.py → sensor.py` for protocol helpers and `sensor.py → switch.py` dynamically for entities form a cycle. All platforms can reach `_data_cache`, `_device_sn` and `_sensors`. HTTP entities use a different update interface in the same listener map. Transport extraction alone will not resolve these ownership conflicts.

Pure calculations have no operational HA dependency but importing their current file loads HA. Moving them first is a tractable cut, provided their normalization dependency is retained without importing sensor back into the new module. For the initial extraction, pass normalized input through the wrapper or also move only the tiny shared normalization helper with a compatibility export; select the smallest change whose tests prove byte-for-byte state equivalence. The [roadmap](refactoring-roadmap.md) instead recommends extracting the independent normalization helper first to remove this dependency, then the calculation bundle.

Keep registry identifiers and unique-ID migration outside structural changes. Fix source-confirmed defects separately. Never replace raw keys with canonical names during a move; alias precedence and raw retention are part of the observed contract.
