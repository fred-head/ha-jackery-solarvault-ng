# Test coverage map

Baseline: [baseline](baseline.md). All 10 test modules and `conftest.py` were read. Existing suite: **174 passed**, statement coverage **60.78%**; no branch coverage configured. [Results and limitations](baseline-test-results.md). No tests were added or changed in this phase.

`conftest.coordinator` bypasses `__init__` with `__new__`, omits config_entry_id and HTTP state, and uses poll counter=0 rather than production=2. Most routing tests therefore merge cache without creating actual child entities or running transport. Helpers frequently replace `async_write_ha_state`, timers or registry removal with mocks. Passing cache assertions do not establish end-to-end HA availability.

## Behavior to tests

| Behavior | Existing protection | What remains unprotected |
| --- | --- | --- |
| MQTT routing / type2 | `test_mqtt_routing`: merge, accumulation, wrong-SN cache isolation, malformed JSON, unknown type | Actual subscribe/publish, heartbeat isolation, regex/topic rejection, callbacks/unsubscribe |
| Type101 | Routing tests: CT/plug independence, SN merge, type 2/3/4/6 arrays, null body | Complete vs partial membership, main-SN filtering, mixed sections, null fields, dynamic entities, collectors |
| Type102 | `test_upstream_sync::test_type102_*`: known/new child, inference, arrays, last-seen, main SN excluded | Null filtering assertion, aliases/collectors, malformed fields, arrays plus point body, real firmware evidence |
| Type106 | `test_type106_*`: merge, workModel normalization/explicit key priority | Protected live-field set, first/second 106-only snapshots, null seed, 2→106→107 ordering |
| Type107 | `test_type107_*`: soc, workModel alias, unrelated cache retained | Command acknowledgement semantics, reordered/duplicate messages |
| Flat payloads | `TestExtractFlatBody`, two flat routing tests | Aliases-only/energy-only/arrays-only payloads, non-dict JSON, null body variants |
| Normalization | `TestNormalizePayloadFields`: three aliases, explicit value, zero alias, no input mutation | Explicit target zero against conflicting alias, null target/value combinations throughout all routes |
| Zero values | `_field_present`, `_safe_float`, `_pick_best_power_net`, explicit zero grid aliases, temperature zero | Upper/lower phase alias conflicts, zero totals vs nonzero phases, nonfinite values, empty CT suppressing collector fallback |
| Energy flow | 22 tests in `test_calculate_energy_flow`; helper and four total-battery tests in `test_upstream_sync` | Collector fallback, multi-meter choice, source freshness, contradictory sources and complete recorded scenarios |
| SmartMeter detection | Routing type3/subtype5 tests and generic enum sensor tests | Actual discovery-generated 19 sensors, metadata-only cache behavior, model fixtures |
| Shelly Pro 3EM | Shared devType=3 path has indirect protection | **No explicit Shelly or subtype=2 test**; hardware support is a README claim |
| HTO907A | Synthetic subtype5 route + devType3 direct update/enum path | End-to-end model matrix, full phase/energy entities, HTTP |
| HTO910A | None specific; generic devType4 routing test is for cts, not collectors | collectors parsing, discovery and grid calculation entirely unexecuted |
| Expansion battery | Routing type23 separate/null cache, isolated never-delete/once-seen tests | Actual entity creation/preinitialization, removal/reload, full main-offline sequence |
| SmartMeter HTTP | **None** | Entire lifecycle, data parsing/scaling, failure threshold/recovery, MQTT coexistence, meter replacement |
| Communication modes | `test_v230_changes`: pure plug helpers; `test_subdevice_entity`: meter enum mapping | Actual plug action block/notification; mode transitions with stale measurement state |
| Stale / unavailable / recovery | Six isolated subdevice tests; grid_net None preserves value; follow-meter mode cases | Real entity update after stale check, independent timeouts, main recovery, no-IP HTTP, cached stale CT priority |
| Multi-instance | Wrong-SN cache test; duplicate-SN config flow | Concurrent entries, unrelated heartbeat, same child SN under two hosts, subscription leakage |
| Unique-ID migration | Six `test_migration` HA tests: main sensor prefix, uppercase child preservation, main_ residue, orphan conflict, fresh device identity/idempotent no-op, empty SN | Legacy switches/numbers/entry-ID controls; actual old-device identifier migration; collector and numeric/lowercase child SN; obsolete select removal; complete before/after registry snapshots |
| Config flow | Four real HA tests: initial form, create, duplicate abort, missing MQTT error | Whitespace persistence, malformed inputs, full MQTT startup success |
| Options flow | **None** | Defaults, range validation, data/options persistence, applying changes/reload |
| Writable controls | Nine cache tests: optimistic base switch, work-mode select, maxOutPw number, follow-meter availability; v230 constants/dynamic SOC bounds | Real MQTT envelopes for all actions, publish failure, no-SN path, standby select, plug controls, reboot press, confirmation/timeouts |
| Unload/reload | HA fixture cleanup incidentally executes portions of unload; no lifecycle test | Stored unsubscribe handles, failed/partial start, repeated start/stop, duplicate subscriptions/tasks, HTTP task cleanup |
| Reauthentication | Type123 401 sets guard; non-401 doesn't | Reauth completion/reload, guard repeat, 120s heuristic, invalid traffic suppressing hint |

A test named `test_optimistic_switch_turn_on_patches_cache` uses the generic optimistic class with swEps, but **production swEps uses the non-optimistic class**. It is not proof that the actual EPS switch updates optimistically. Number coverage is 98%, yet wire encoding is uncovered because its coordinator is fake. Button coverage is 93%, yet pressing the button is not tested. These are examples of why statement coverage alone is insufficient.

## Critical test gaps

| Priority | Regression scenario required before related refactoring | Why |
| --- | --- | --- |
| HIGH | HTTP entity registered, then valid MQTT message; all MQTT entities update and HTTP is unaffected | Current interface mismatch throws; broad fan-out failure otherwise hidden |
| HIGH | Two hosts + foreign/malformed traffic + deterministic clock + unavailable/recovery | Cache isolation exists, but heartbeat and freshness are not isolated |
| HIGH | Stale CT/plug metadata followed by full `_handle_message` fan-out; no-list/unbind/reappear | Cached entity updates can undo offline state; deletion helper test bypasses merged-cache behavior |
| HIGH | Golden energy scenarios: Pro Max/BP2500 stack, Shelly subtype2, HTO907A, collector, zero/casing/no-meter | Physical boundaries and source precedence differ from Official |
| HIGH | 106-only startup, repeated snapshots, 2→106 ordering, null seed and 107 updates | Protected fields use key existence, not actual source/age |
| HIGH | Registry snapshot migration incl. collector, lowercase/numeric child SN, legacy controls, collision and repeated setup | Wrong migration can orphan history; Official IDs must not be adopted blindly |
| HIGH | Start/partial-start/stop/reload with real mocked MQTT unsubscribe and optional HTTP task | Neither upstream retains unsubscribe handles; duplicates possible |
| HIGH | All action envelopes + local/cloud/unknown plugs + publish errors and cache timing | Existing parameter-dict tests do not validate transmitted commands |
| MEDIUM | HTTP status/timeout/JSON/missing field/no-IP/meter swap/recovery sequences | Threshold is selective; one global sensor-created flag |
| MEDIUM | Options and completed reauth flows, reload and token replacement | New options feature and auth lifecycle untested |
| MEDIUM | Type23 actual main SN; child metadata must not update host firmware/model | Official handles forms that C drops or misattributes |
| MEDIUM | Unknown device types, arrays in generic messages, mismatched array and devType | Classification logic differs across entry points |
| LOW | Diagnostic redaction/size limits and logging rate tests when those features are designed | No endpoint exists yet; avoid introducing leakage/noise |
| LOW | Full metadata/translation-key snapshots and old HA compatibility matrix | Current translation test only checks key completeness |

Add fixtures with synthetic identifiers and documented capture provenance; do not call invented payloads recorded hardware evidence. For source-confirmed defects, first capture the existing behavior, then add the intended failure case and fix it in a separate bugfix PR rather than hiding it inside extraction.
## Complete test index

These are source test functions, not a hardware matrix. Parametrization is absent; 174 collected cases match the source index. Group descriptions above explain assertion scope.

### test_calculate_energy_flow.py (22)

- [test_battery_charging_when_pv_exceeds_load](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_calculate_energy_flow.py#L18)
- [test_battery_charging_when_grid_feeds_unit](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_calculate_energy_flow.py#L30)
- [test_battery_discharging_when_unit_feeds_grid](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_calculate_energy_flow.py#L42)
- [test_grid_net_power_with_ct_import](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_calculate_energy_flow.py#L58)
- [test_grid_net_power_with_ct_export](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_calculate_energy_flow.py#L70)
- [test_home_power_ct_available_normal](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_calculate_energy_flow.py#L86)
- [test_home_power_ct_feed_in_with_ongrid_supply](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_calculate_energy_flow.py#L99)
- [test_home_power_phase_balanced_feed_in](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_calculate_energy_flow.py#L114)
- [test_home_power_anomaly_branch_small_difference](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_calculate_energy_flow.py#L135)
- [test_home_power_anomaly_branch_large_difference](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_calculate_energy_flow.py#L148)
- [test_no_ct_grid_not_available](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_calculate_energy_flow.py#L165)
- [test_no_ct_home_power_uses_ongrid_supply](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_calculate_energy_flow.py#L176)
- [test_no_ct_home_power_zero_when_no_supply](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_calculate_energy_flow.py#L186)
- [test_ct_abc_phase_fallback_for_import](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_calculate_energy_flow.py#L200)
- [test_ct_abc_phase_fallback_for_export](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_calculate_energy_flow.py#L212)
- [test_pv_as_dict](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_calculate_energy_flow.py#L228)
- [test_fallback_to_grid_buy_sell_fields](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_calculate_energy_flow.py#L242)
- [test_empty_data_does_not_crash](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_calculate_energy_flow.py#L258)
- [test_ct_with_empty_cts_list](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_calculate_energy_flow.py#L266)
- [test_home_power_clamped_to_zero_on_sensor_timing_artefact](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_calculate_energy_flow.py#L277)
- [test_grid_available_true_when_grid_sell_is_explicitly_zero](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_calculate_energy_flow.py#L300)
- [test_grid_available_true_when_only_sell_is_present_and_zero](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_calculate_energy_flow.py#L318)

### test_config_flow.py (4)

- [test_shows_user_form](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_config_flow.py#L39)
- [test_creates_entry_with_valid_input](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_config_flow.py#L53)
- [test_duplicate_sn_aborts_flow](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_config_flow.py#L76)
- [test_mqtt_not_available_shows_error](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_config_flow.py#L105)

### test_migration.py (6)

- [test_main_sensor_gets_sn_prefix](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_migration.py#L46)
- [test_subdevice_uid_preserved](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_migration.py#L67)
- [test_main_infix_artifact_deleted](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_migration.py#L85)
- [test_conflict_orphan_deleted](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_migration.py#L103)
- [test_device_has_sn_identifier_after_setup](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_migration.py#L126)
- [test_empty_sn_skips_migration](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_migration.py#L153)

### test_mqtt_routing.py (24)

- [test_type2_merges_body_into_cache](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_mqtt_routing.py#L19)
- [test_type2_accumulates_multiple_messages](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_mqtt_routing.py#L28)
- [test_type23_system_merges_into_main_cache](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_mqtt_routing.py#L39)
- [test_type23_system_none_sn_also_merges](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_mqtt_routing.py#L48)
- [test_type23_expansion_battery_stored_separately](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_mqtt_routing.py#L56)
- [test_type101_ct_payload_sets_cts_cache](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_mqtt_routing.py#L72)
- [test_type101_plug_payload_sets_plugs_cache](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_mqtt_routing.py#L81)
- [test_ct_cache_not_wiped_by_plug_response](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_mqtt_routing.py#L90)
- [test_plug_cache_not_wiped_by_ct_response](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_mqtt_routing.py#L110)
- [test_type101_smartmeter_devtype3_goes_to_cts](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_mqtt_routing.py#L126)
- [test_type101_standard_ct_devtype2_goes_to_cts](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_mqtt_routing.py#L143)
- [test_type101_plug_devtype6_goes_to_plugs](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_mqtt_routing.py#L153)
- [test_type101_meter_collector_devtype4_goes_to_cts](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_mqtt_routing.py#L165)
- [test_type101_sn_merge_preserves_existing_fields](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_mqtt_routing.py#L177)
- [test_invalid_json_does_not_crash](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_mqtt_routing.py#L200)
- [test_unknown_message_type_falls_back_to_flat_merge](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_mqtt_routing.py#L206)
- [test_type101_body_none_returns_early](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_mqtt_routing.py#L214)
- [test_type106_merges_body_into_cache](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_mqtt_routing.py#L224)
- [test_type106_normalizes_workmodel_to_workmode](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_mqtt_routing.py#L233)
- [test_type106_does_not_overwrite_workmode_if_present](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_mqtt_routing.py#L242)
- [test_message_with_wrong_sn_is_ignored](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_mqtt_routing.py#L255)
- [test_type123_error_401_triggers_reauth](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_mqtt_routing.py#L273)
- [test_type123_non_401_does_not_trigger_reauth](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_mqtt_routing.py#L288)
- [test_expansion_battery_null_values_do_not_overwrite_cache](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_mqtt_routing.py#L302)

### test_sensor_transforms.py (15)

- [test_battery_temperature_scaling](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_sensor_transforms.py#L25)
- [test_battery_temperature_zero](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_sensor_transforms.py#L32)
- [test_eps_output_power_net_positive](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_sensor_transforms.py#L42)
- [test_eps_output_power_net_negative](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_sensor_transforms.py#L48)
- [test_eps_output_power_defaults_to_zero_when_missing](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_sensor_transforms.py#L54)
- [test_solar_pv1_dict_pvPw](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_sensor_transforms.py#L64)
- [test_solar_pv1_dict_w_key](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_sensor_transforms.py#L70)
- [test_solar_pv1_dict_power_key](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_sensor_transforms.py#L76)
- [test_solar_pv1_scalar_value](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_sensor_transforms.py#L82)
- [test_grid_import_energy_scale](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_sensor_transforms.py#L93)
- [test_battery_charge_energy_scale](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_sensor_transforms.py#L99)
- [test_grid_net_power_keeps_last_value_when_none](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_sensor_transforms.py#L109)
- [test_grid_net_power_updates_when_value_present](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_sensor_transforms.py#L120)
- [test_missing_key_leaves_sensor_unchanged](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_sensor_transforms.py#L130)
- [test_state_written_after_update](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_sensor_transforms.py#L146)

### test_subdevice_availability.py (6)

- [test_expansion_battery_not_added_to_deletion_timer](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_subdevice_availability.py#L46)
- [test_expansion_battery_not_deleted_even_if_timer_set](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_subdevice_availability.py#L60)
- [test_expansion_battery_stays_available_after_long_gap](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_subdevice_availability.py#L81)
- [test_expansion_battery_unavailable_if_never_seen](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_subdevice_availability.py#L100)
- [test_plug_deleted_after_offline_timeout](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_subdevice_availability.py#L122)
- [test_startup_grace_period_suppresses_offline](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_subdevice_availability.py#L140)

### test_subdevice_entity.py (9)

- [test_commmode_1_maps_to_lan](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_subdevice_entity.py#L36)
- [test_commmode_2_maps_to_cloud](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_subdevice_entity.py#L47)
- [test_commmode_invalid_value_uses_str_fallback](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_subdevice_entity.py#L58)
- [test_commstate_0_maps_to_offline](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_subdevice_entity.py#L73)
- [test_commstate_1_maps_to_online](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_subdevice_entity.py#L83)
- [test_null_guard_preserves_existing_value](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_subdevice_entity.py#L97)
- [test_key_absent_does_not_change_value](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_subdevice_entity.py#L111)
- [test_string_ip_field_stored_as_string](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_subdevice_entity.py#L129)
- [test_unitless_integer_no_float_suffix](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_subdevice_entity.py#L141)

### test_switch_select_cache.py (9)

- [test_optimistic_switch_turn_on_patches_cache](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_switch_select_cache.py#L82)
- [test_optimistic_switch_turn_off_patches_cache](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_switch_select_cache.py#L93)
- [test_work_mode_select_patches_both_cache_keys](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_switch_select_cache.py#L108)
- [test_work_mode_select_custom_mode](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_switch_select_cache.py#L119)
- [test_max_feed_in_number_patches_cache](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_switch_select_cache.py#L132)
- [test_max_feed_in_number_arbitrary_value](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_switch_select_cache.py#L143)
- [test_max_feed_in_number_bounds](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_switch_select_cache.py#L152)
- [test_follow_meter_switch_unavailable_when_work_mode_not_4](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_switch_select_cache.py#L164)
- [test_follow_meter_switch_available_and_on_when_work_mode_4](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_switch_select_cache.py#L175)

### test_upstream_sync.py (50)

- [TestFieldPresent::test_zero_is_present](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_upstream_sync.py#L35)
- [TestFieldPresent::test_none_is_absent](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_upstream_sync.py#L38)
- [TestFieldPresent::test_missing_key_is_absent](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_upstream_sync.py#L41)
- [TestSafeFloat::test_none_returns_default](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_upstream_sync.py#L46)
- [TestSafeFloat::test_custom_default](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_upstream_sync.py#L49)
- [TestSafeFloat::test_string_number](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_upstream_sync.py#L52)
- [TestSafeFloat::test_garbage_returns_default](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_upstream_sync.py#L55)
- [TestPickBestPowerNet::test_empty_returns_zero](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_upstream_sync.py#L60)
- [TestPickBestPowerNet::test_largest_magnitude_wins](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_upstream_sync.py#L63)
- [TestPickBestPowerNet::test_zero_does_not_mask_reading](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_upstream_sync.py#L66)
- [TestPickBestPowerNet::test_all_zero_returns_last](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_upstream_sync.py#L69)
- [TestEffectiveOngridNet::test_uses_ongrid_fields_when_only_source](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_upstream_sync.py#L78)
- [TestEffectiveOngridNet::test_type106_zero_does_not_mask_type2_reading](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_upstream_sync.py#L82)
- [TestEffectiveOngridNet::test_no_source_returns_zero](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_upstream_sync.py#L86)
- [TestGridNetFromSystem::test_no_fields_not_available](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_upstream_sync.py#L91)
- [TestGridNetFromSystem::test_grid_in_out_available](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_upstream_sync.py#L96)
- [TestGridNetFromSystem::test_ongrid_excluded_when_requested](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_upstream_sync.py#L102)
- [TestGridNetFromSystem::test_ongrid_included_by_default](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_upstream_sync.py#L110)
- [TestNormalizePayloadFields::test_grid_buy_aliased_to_grid_in](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_upstream_sync.py#L122)
- [TestNormalizePayloadFields::test_grid_sell_aliased_to_grid_out](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_upstream_sync.py#L125)
- [TestNormalizePayloadFields::test_work_model_aliased_to_work_mode](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_upstream_sync.py#L128)
- [TestNormalizePayloadFields::test_existing_value_wins_over_alias](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_upstream_sync.py#L131)
- [TestNormalizePayloadFields::test_zero_alias_is_kept](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_upstream_sync.py#L135)
- [TestNormalizePayloadFields::test_input_not_mutated](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_upstream_sync.py#L138)
- [TestExtractFlatBody::test_non_status_payload_returns_empty](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_upstream_sync.py#L149)
- [TestExtractFlatBody::test_status_fields_extracted](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_upstream_sync.py#L152)
- [TestExtractFlatBody::test_meta_keys_stripped](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_upstream_sync.py#L156)
- [test_flat_status_message_merged_into_cache](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_upstream_sync.py#L161)
- [test_flat_message_without_status_fields_ignored](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_upstream_sync.py#L168)
- [test_type102_patches_known_subdevice](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_upstream_sync.py#L177)
- [test_type102_creates_new_ct_from_devtype](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_upstream_sync.py#L192)
- [test_type102_creates_new_plug_from_devtype](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_upstream_sync.py#L200)
- [test_type102_infers_plug_devtype_from_fields](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_upstream_sync.py#L209)
- [test_type102_with_arrays_uses_array_merge](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_upstream_sync.py#L218)
- [test_type102_records_last_seen](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_upstream_sync.py#L226)
- [test_type102_ignores_main_device_sn](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_upstream_sync.py#L234)
- [test_type107_merges_soc](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_upstream_sync.py#L246)
- [test_type107_normalizes_workmodel](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_upstream_sync.py#L251)
- [test_type107_preserves_other_cached_fields](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_upstream_sync.py#L256)
- [test_type2_grid_buy_alias_normalized](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_upstream_sync.py#L267)
- [test_type23_system_alias_normalized](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_upstream_sync.py#L273)
- [test_total_battery_charge_uses_energy_balance](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_upstream_sync.py#L284)
- [test_total_battery_discharge_uses_energy_balance](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_upstream_sync.py#L294)
- [test_total_battery_charge_without_bat_fields](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_upstream_sync.py#L303)
- [test_total_battery_charge_with_eps_output](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_upstream_sync.py#L309)
- [TestConstants::test_func_enable_bits_are_contiguous](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_upstream_sync.py#L322)
- [TestConstants::test_func_enable_names_unique](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_upstream_sync.py#L325)
- [TestConstants::test_ct_subtype_map_has_jackery_3p](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_upstream_sync.py#L328)
- [test_func_enable_attributes_decode_bits](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_upstream_sync.py#L332)
- [test_func_enable_attributes_without_value](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_upstream_sync.py#L351)

### test_v230_changes.py (29)

- [TestSocBounds::test_soc_charge_limit_min](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_v230_changes.py#L19)
- [TestSocBounds::test_soc_charge_limit_max](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_v230_changes.py#L22)
- [TestSocBounds::test_soc_discharge_limit_min](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_v230_changes.py#L25)
- [TestSocBounds::test_soc_discharge_limit_max](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_v230_changes.py#L28)
- [TestSocBounds::test_soc_charge_limit_has_min_key](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_v230_changes.py#L31)
- [TestSocBounds::test_soc_charge_limit_has_max_key](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_v230_changes.py#L34)
- [TestSocBounds::test_soc_discharge_limit_has_min_key](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_v230_changes.py#L37)
- [TestSocBounds::test_soc_discharge_limit_has_max_key](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_v230_changes.py#L40)
- [TestSocBounds::test_charge_min_always_greater_than_discharge_max](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_v230_changes.py#L43)
- [TestDynamicBoundsUpdate::test_dynamic_min_updates_from_data](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_v230_changes.py#L71)
- [TestDynamicBoundsUpdate::test_dynamic_max_updates_from_data](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_v230_changes.py#L76)
- [TestDynamicBoundsUpdate::test_dynamic_bounds_absent_leaves_defaults](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_v230_changes.py#L81)
- [TestDynamicBoundsUpdate::test_value_updated_from_data](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_v230_changes.py#L87)
- [TestPlugCommMode::test_local_mode](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_v230_changes.py#L98)
- [TestPlugCommMode::test_cloud_mode](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_v230_changes.py#L101)
- [TestPlugCommMode::test_missing_returns_none](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_v230_changes.py#L104)
- [TestPlugCommMode::test_string_value_parsed](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_v230_changes.py#L107)
- [TestPlugCommMode::test_invalid_value_returns_none](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_v230_changes.py#L110)
- [TestPlugMqttControlAllowed::test_local_mode_allowed](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_v230_changes.py#L119)
- [TestPlugMqttControlAllowed::test_cloud_mode_blocked](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_v230_changes.py#L124)
- [TestPlugMqttControlAllowed::test_unknown_mode_blocked](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_v230_changes.py#L129)
- [TestPlugMqttControlAllowed::test_unexpected_mode_blocked](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_v230_changes.py#L134)
- [TestShouldCreatePlugSwitch::test_devtype6_is_plug](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_v230_changes.py#L145)
- [TestShouldCreatePlugSwitch::test_devtype2_is_not_plug](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_v230_changes.py#L148)
- [TestShouldCreatePlugSwitch::test_devtype3_is_not_plug](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_v230_changes.py#L151)
- [TestShouldCreatePlugSwitch::test_devtype4_is_not_plug](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_v230_changes.py#L154)
- [TestShouldCreatePlugSwitch::test_missing_devtype_is_not_plug](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_v230_changes.py#L157)
- [TestCommModeLabels::test_local_label](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_v230_changes.py#L166)
- [TestCommModeLabels::test_cloud_label](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/tests/test_v230_changes.py#L169)
