# Community / Official feature matrix

## Protocol/command follow-up (2026-09-12)

Fetched references still match Official `af97223ff17fc8f14314cbc6da7213a5eee7004d`
and community `183d74b7e042061ccb985ddc023b3cb7a085452e`. Current local comparison
starts from merged foundation `016f849`. The historical matrix below remains pinned
to Phase 0/1; this section supersedes its current-status implications.

| Behavior | Current comparison classification | Decision / evidence |
| --- | --- | --- |
| Type23 actual host deviceSn | OFFICIAL_FIX_CANDIDATE → CURRENT_EQUIVALENT for this case | FIX_NOW: regression failed locally; Official 12c2e7c recognizes host SN. Local host branch corrected without losing expansion handling. Empty-string SN remains deferred. |
| Child metadata contaminating host | OFFICIAL_FIX_CANDIDATE → CURRENT_EQUIVALENT for guard | FIX_NOW: Official d0e0c9f limits capture to host messages of selected types. Local adopts guard after failing tests. Top-level firmware and model-update behavior still differ. |
| Aliases, main/plug action envelopes, standby/reboot values | CURRENT_EQUIVALENT | Exact payload tests, explicit canonical zero preserved, IDs sampled in same range. No execution correlation in either source. |
| Host topic ownership | CURRENT_EQUIVALENT for topics | Local lifecycle/freshness fixes already merged; local strict parsing and unsubscribe retention exceed Official. No redesign here. |
| Type101 merge vs authoritative replacement | COMMUNITY_BEHAVIOR_INTENTIONAL | Preserve empty/omitted children and cached fields; Official category replacement/unbinding needs device evidence. |
| Type102/generic point routing and classification | NEEDS_LATER_INVESTIGATION | Official has broader inference and generic child routing; local arrays and point routes intentionally characterized separately. |
| HTO907A/Shelly/HTO910A/expansion groups | COMMUNITY_BEHAVIOR_INTENTIONAL | Preserve 19 SmartMeter, 5 collector and 2 expansion sensors; do not replace with Official generic CT table. |
| Unknown dynamic plug discovery | NEEDS_LATER_INVESTIGATION for taxonomy | Local unsupported types now produce no new entities, matching explicit project policy and existing type6 static control gate; no new taxonomy ported. |
| Type106 protected fields and energy sources | NEEDS_LATER_INVESTIGATION | Repeated-106 freeze reproduced for 11 keys, including null/zero seeds. Official overwrites all; port deferred to energy/source PR. |
| Plug optimistic cache, coordinator commMode gate and switchSta priority | NEEDS_LATER_INVESTIGATION | Official differs; keep local non-optimistic plug telemetry and entity guard. No acknowledgement evidence justifies a broader change. |
| Extra main switches/numbers/work mode | COMMUNITY_BEHAVIOR_INTENTIONAL | Preserve force charge, follow meter, defaultPw/maxFeedGrid and selective cache optimism. |
| Poll schedule and partial publish failures | COMMUNITY_BEHAVIOR_INTENTIONAL | Keep local type2 read, [2,3,6] requests, 105 throttling and pacing. Official requests [2,6] with different timing/error boundaries. |
| Command confirmation and top-level metadata | NEEDS_LATER_INVESTIGATION | Publish success is not execution; top-level softver and replacement deviceType behavior deferred. |

See [protocol-routing-commands.md](protocol-routing-commands.md) for full behavioral
matrices and [upstream-sync.md](upstream-sync.md) for exact source provenance.

## Historical Phase 0/1 comparison

Comparison is of actual source at [C and O](baseline.md), not repository age or names. `SAME` means the scoped behavior matches, not that the implementations are byte-identical. `COMMUNITY_ONLY` follows the task's terminology (`LOCAL_ONLY` in AGENTS.md). Hardware observations are not independently repeated here. Official contains no test directory.

## Behavior matrix

| Feature | Classification | Actual behavior and evidence |
| --- | --- | --- |
| HA MQTT prerequisite and entry storage | SAME | Both wait for HA MQTT, store coordinator per entry and forward five platforms. `C/O __init__.py::async_setup_entry`. |
| Wildcard vs host subscriptions | DIFFERENT | C always wildcard with SN filter; O uses specific host topics when configured, wildcard only otherwise. `C sensor.py:1314`; `O:1000`. |
| Heartbeat isolation | OFFICIAL_ONLY | O updates last_update_time after other-SN rejection; C updates before. Both still mark traffic received before valid JSON parsing. `C:1421`; `O:1097`; O history `a88befc` (heartbeat filter), `12c2e7c` (specific topics). |
| Scalar normalization | SAME | gridBuyPw/gridSellPw/workModel aliases, preserve explicit non-null target and original keys. `C:1280`; `O:216`. |
| Flat recognition | SAME | Same recognized field set and stripped envelope keys; aliases-only status is not recognized. `C:1301`; `O:232`. |
| Type2/25/unknown dict routing | DIFFERENT | C shallow-merges entire body into host cache. O additionally merges/deduplicates arrays, handles child points, strips child identity/sections from main dict when appropriate. `C:1535`; `O:1336`. |
| Type23 actual main-SN statistics | OFFICIAL_ONLY | O recognizes missing SN, system, **or actual host SN**. C only system or None, so literal main-SN energy is dropped unless misrouted by devType. `C:1468`; `O:1149`; introduced O `12c2e7c`. |
| Type23 child freshness | DIFFERENT | O timestamps any non-host child then patches plugs/cts. C timestamps expansion batteries only here; normal CT/plug energy updates do not refresh child last-seen and neither path patches collectors. `C:1468`; `O:1149`. |
| Expansion batteries | COMMUNITY_ONLY | Separate type23 devType1 cache, two energy sensors, null retention, once-seen indefinite availability and no deletion. O only updates already-known child entries, no expansion discovery/entities. `C:1475,1878`; O type23 path. |
| Type101 membership semantics | DIFFERENT | C always merges nonempty arrays and ignores empty sections. O replaces plugs for body.devType=6 and cts for body.devType=2, immediately removes recognized missing children; other categories merge. This can erase fields on partial full-category messages. `C:1556`; `O:1216`; O replacement history `5fe1159`. |
| Main-SN child exclusion and deduplication | OFFICIAL_ONLY | O filters main SN from child arrays and aggregates plugs+cts by unique SN, using array origin to classify CTs. C discovery concatenates plugs+plug+cts+collectors; known set prevents repeat creation but no main-SN filter. get_subdevices returns plugs **or** cts, omitting collectors. `C:1749,1916`; `O:332,353,1375,1451`. |
| Type102 | DIFFERENT | Both accept arrays/points and exclude main/system points. C known point updates skip null and understand collectors; O writes null and has broader inference (outPw/inPw imply plug, subType can imply CT). C total-phase aliases can imply CT. `C:1626`; `O:402`. |
| Type106 | DIFFERENT | C protects listed established live power keys against every later 106; O normalizes/overwrites all keys. C's policy is presence-based, including 106-seeded keys. `C:1510`; `O:1177`; C introduction `8043585`. |
| Type107 | SAME | Normalized incremental main cache merge. No tracked command confirmation. `C:1525`; `O:1188`. |
| Device type and firmware metadata | DIFFERENT | O only captures selected host message types, accepts top-level/body softver, updates changed type, maps types 1/2/3/4, and falls back to entry-ID registry lookup. C captures any dict body, first int deviceType only, body softver only, map only type3. `C:1674`; `O:1124,1556`; host guard O `d0e0c9f`. |
| Meter classification and sensor groups | DIFFERENT | O all CT-family/origin cts → generic CT with 10 power/total-energy entities. C type3 → 19 direct lowercase fields; type4/subtype7 → five collector fields; other CT → two legacy subtype-selected fields. `C:744,1749`; `O:304,888,1375`. |
| Shelly Pro 3EM / HTO907A 19 sensors | COMMUNITY_ONLY | All type3 subtypes share phase import/export power and energy plus comm diagnostics. O has overlapping power fields but no dedicated per-phase energy entities or the same IDs. C `d99b8ca`, `sensor.py:744`. |
| HTO910A collector path | COMMUNITY_ONLY | Separate collectors cache, discovery and grid fallback; not present in O helpers/group tables. `C:1606,1834,2084`. |
| Generic CT full phase power entities | OFFICIAL_ONLY | O exposes eight phase/total forward/reverse W plus two total energies for generic CT types 2/4. C has only subtype-selected power/energy for those types; type3 already has richer separate entities. `O:888,2164`; `C:744,2706`. |
| Legacy CT subtype energy fallback | COMMUNITY_ONLY | C maps subtypes to selected phase, C→A+B fallback and sole nonzero phase energy fallback. O reads reported total import/export energy, never sums energy. `C:2706`; `O:2198`. |
| Offline scheduler | DIFFERENT | Both main timeout 60s. O also checks child timers periodically while host active, even if child lists empty; C checks children on message fan-out only and returns early on no lists. `C:1749,2190`; `O:1375,1839`. |
| Child sensor availability | DIFFERENT | C entity update marks cached values available, undoing coordinator stale marking. O child sensor/plug updates leave availability to coordinator (main entities still set true). Expansion exception and HTTP are C-only. `C:2639`, `switch.py:149`; `O:2164`, `switch.py::_update_from_coordinator`. |
| Reauth triggers | DIFFERENT | Both 401 plus never-received 120s heuristic/guard. C schedules flow.async_init with reauth context; O obtains entry and calls entry.async_start_reauth. C helper lacks entry existence guard. `C:1699`; `O:1607`. |
| Reauth UI completion | SAME | Both accept token, update entry and reload/abort; C uses HA helper, O explicit update/reload. No network token verification at form submit. `C/O config_flow.py`. |
| Options flow / HTTP transport | COMMUNITY_ONLY | Token/topic edits plus optional type3/subtype5 HTTP telemetry with 16 new entities, failure threshold and task cancellation. No implementation in O. `C config_flow.py:99`, `sensor.py:2293`; commits `2787aca`, `1990d0a`. |
| Config flow YAML-import step | OFFICIAL_ONLY | O async_step_import delegates to user step. No integration YAML schema/discovery wiring found, so automatic YAML provisioning is not established. `O config_flow.py::async_step_import`, origin `a66ad4d`. |
| Multi-instance main IDs | SAME | Both main sensor IDs include host SN, config unique IDs reject duplicates. Fallback and whitespace differ. `C/O config_flow.py`, sensor constructors. |
| Child / control IDs and migrations | DIFFERENT | O child IDs and child registry IDs include host SN; C preserves historical child IDs without it. O controls use main_ suffix, which C migration removes as residue; C switches/numbers/select/buttons use separate formats. O main device has both entry and SN identifiers + serial_number; C only SN after migration. `C/O __init__.py` and platform constructors. |
| Auto standby, EPS switch wire action | SAME | isAutoStandby/swEps 1/0 through main type1/cmd5. `C/O switch.py`; no optimistic C base switch. |
| Additional main switches | COMMUNITY_ONLY | offGridDown, socForceChg, isFollowMeterPw (mode4 gate), optimistic cache patch. O only two main switches. `C switch.py:28,284,300`. |
| Plug command wire format / mode helper | SAME | Type103 body deviceSn/devType/sysSwitch; entity allows only local commMode=1 and notifies on block. `C:1939`, `O:1470`; switch helpers. |
| Coordinator plug guard / optimistic plug cache | OFFICIAL_ONLY | O also validates mode at coordinator boundary, raises if host missing, patches sysSwitch and switchSta and distributes after publish. C coordinator lacks guard and patch, returns if host missing. `O:1470,1515`; introduced cache behavior `d1f4f68`. |
| Plug state source priority | DIFFERENT | C sysSwitch before switchSta; O switchSta before sysSwitch. Distinct when command/control and status fields disagree. `C switch.py:149`; O equivalent. |
| Numbers | DIFFERENT | Shared SOC limits/dynamic bounds and maxOutPw range. C adds explicit units, startup-unavailable, defaultPw and maxFeedGrid, selective optimistic cache writes. O optimistically sets every number UI without cache write; no units in number definitions. `C/O number.py`. |
| Selects / reboot | DIFFERENT | Standby option values and reboot command same; C adds work-mode select and standby optimistic cache update. IDs/names differ. `C/O select.py,button.py`. |
| Main entity fields | DIFFERENT | O-only logical keys average_soc(soc), work_mode(workMode) already represented in C by bms_soc and work-mode select. Shared grid_import_power/export_power **change source**: O gridInPw/gridOutPw; C inOngridPw/outOngridPw (C also exposes O fields separately). `C:60`; `O:442`. |
| Enum state keys / naming | DIFFERENT | C translated names, connected/disconnected and linked/not_linked; O mostly explicit English names, on_grid/off_grid, online/offline, normal/abnormal. device_status options match. Do not replace entity metadata with O tables. `C/O SENSORS`, constructors and strings. |
| funcEnable interpretation | SAME | 12 bit names 0–11, raw value plus boolean attributes; not writable. `C:1050,2542`; `O:60,2086`. |
| CT usability calculation | DIFFERENT | O helpers retain explicit zero alias, may replace total zero by phase sum, accept zero only if commState online, otherwise system fallback; accepts nonzero even offline. C first CT can fabricate zero from missing phases and ignore collector/system, no commState gate. `C:2044`; `O:132,160,1629`. O helper history `aac1022` and predecessor `c7894d3`. |
| Battery calculation | DIFFERENT | C total stack via PV+inOngrid−outOngrid−EPSout+EPSin, separate raw battery powers. O net prefers batInPw−batOutPw, otherwise PV+EPSnet+chosen port; stores extra calc_battery_* cache keys without separate sensor definitions. `C:2115`; `O:1709`; C `0d70fa3`. |
| Home/grid calculation | DIFFERENT | C excludes ongrid-only meter fallback, keeps two charging anomaly branches and >=0 clamp; O includes ongrid fallback, zero-CT substitution, export anomaly branches, otherLoadPw fallback and no final clamp. C regression example 301W output/29W export → 272W home; O branch gives -272W. `C:1997`; `O:1629`; `test_home_power_phase_balanced_feed_in`. |
| AC socket calculated cache value | OFFICIAL_ONLY | O stores calc_ac_socket_power=in if positive else out; **no SENSORS entry consumes it**. C EPS output entity computes signed out−in. `O:1666,1766`; `C:2479`. |
| Poll cadence / error isolation | DIFFERENT | C 10s post-batch, type105 every 3, type100 [2,3,6] with 0.5s gaps; one child-loop exception skips subsequent categories. O 5s post-batch, type105 every cycle, categories [2,6] individually caught. `C:2232`; `O:1880`. |
| Unload cleanup | SAME | Both cancel/await poll task, stop coordinator then unload platforms/pop entry. Both omit subscription unsubscribe handles; C also cancels HTTP task. `C/O async_stop,async_unload_entry`. |
| Logging | DIFFERENT | O INFO logs every 101/106 and plug command with serial/topic; C 106 is DEBUG, discoveries INFO, HTTP failure threshold warning. Both emit identifiers and plug raw_data attributes; no redacted diagnostics. `C/O _LOGGER sites`, [logging plan](logging-plan.md). |
| Error handling | DIFFERENT | Both broad exception guards prevent parse/calc exceptions escaping but can abandon remaining fan-out. O guards more metadata/child boundaries and each child poll separately; C adds HTTP-specific catches/null guards. Neither centrally validates payload types or isolates every entity callback. |
| Translations | DIFFERENT | C de/en/fr complete relative to strings; O zh-Hans and English source names, different entity translation structure. Not a drop-in language-file port. |
| Command execution/firmware guarantees | UNKNOWN | Neither implements correlated positive acknowledgements or firmware capability negotiation. Comments/captures do not establish universal firmware support. |

## History provenance

### Official is not uniformly correct

A source probe against the isolated O snapshot confirmed a startup edge case: the first type101 message with `body.devType=2` and a cts array sets only `cache['cts']`, then reads `cache['plugs']` unconditionally. It logs `Error handling message: 'plugs'`, skips calculation/discovery/distribution for that message and leaves `_known_plugs` empty. A subsequent plug response can initialize the missing list. This is a reason to test message ordering before adopting O's full-list replacement logic, not to discard its independently useful guards. See the [reproducible probe](baseline-test-results.md#official-startup-probe).

Commit IDs above were located using `git log <ref> -S '<distinctive source text>' -- <path>` and checked against the final source. They identify introduction/change in that upstream history, not necessarily the first vendor firmware release. Relevant community changes also include `d1a6da9` obsolete select migration, `47c51fd` maxOutPw slider, `b069e24` binary force-charge switch, and `d99b8ca` all-type3 Shelly path. No historical commit was merged or cherry-picked.

The [port candidates](upstream-port-candidates.md) assess every Official-only row, and the Official side of material differences. Same or differently-solved functionality is not automatically a missing feature.
