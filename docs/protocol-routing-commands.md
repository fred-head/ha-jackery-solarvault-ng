# Protocol routing and command contract

Audit date: 2026-09-12. Branch: `test/protocol-routing-commands`; starting foundation
`016f849f8115a1478ba6faeb64fbc5daf0d988d2` (493 tests, 86.52% coverage).
This report supersedes the historical routing/command gaps in the Phase 0/1
inventories. The new tests use synthetic wire scenarios, not recorded hardware
captures. Production MQTT, cache, discovery, calculation and entity methods run;
network publication and HA state writing are replaced at their boundaries.
The number service wrapper is also exercised directly from installed HA.
Existing real HA registry, migration, lifecycle and recorder tests remain gates.

## Inbound routing

Every row below accepts both `{prefix}/device/{host}/status` and `/event` through
the same callback; there is no message-type/topic split. Matching is anchored and
the configured prefix is escaped literally. Foreign hosts, malformed topics,
invalid JSON, non-object envelopes and non-object bodies are ignored before
freshness advances. A coordinator configured without a host subscribes with `+`,
adopts the first valid topic host and subsequently rejects other hosts. Subscriptions
remain owned by that coordinator, including this fallback.

Accepted object bodies advance host last-seen, including empty bodies and unknown
types. Missing/null bodies use recognized flat fields or `{}`; type 101 instead
returns immediately. Flat recognition requires at least one known status key;
workModel/gridBuyPw/energy-only flat envelopes are not recognized. Metadata keys
are stripped from reconstructed flat bodies. Nested body unknown fields remain
raw cache evidence where that route merges them; they do not generate entities.
There is no timestamp ordering, deduplication or request/response correlation.

| Type | Body / host-child meaning | Cache and normalization | Discovery and freshness | Regression evidence |
| --- | --- | --- | --- | --- |
| 2 | Host settings/status; body.cmd=106 is a field, not top-level 106 | Normalized shallow main merge; valid list sections replace previous lists | Normal child discovery follows; only received array members refresh child clocks | Generic types, aliases, shapes, array poisoning, 106 ordering, command readback |
| 23 | Statistics: missing/system/actual host deviceSn means host; child devType=1 means battery | Host normalized merge; expansion map retains non-null energy; known plugs/plug/cts updated directly, including null | Creates two battery sensors; refreshes batteries or matched plug/CT children; collectors are not searched | Host-SN fix, metadata guards, mixed battery discovery/null retention, child search scope |
| 25 | Host status, also published as status request | Same generic merge as 2 | Same generic effects | Exact poll envelope plus inbound generic and metadata cases |
| 101 | Full/partial child arrays: plug/plugs/socket/sockets, ct/cts, collectors; body.devType is a query category | Nonempty lists merge by whole SN; duplicate fields last-write wins; omission/empty lists retain existing members; missing plug/CT devType defaults to 6/2 | Discovers recognized item families; each received valid serial refreshes child last-seen. Battery arrays have no dedicated handler | Alias matrix, duplicates, mixed arrays, defaults, omission, cached commMode, classification/identity matrix |
| 102 | Arrays or direct deviceSn/sn child point | Any nonempty valid section wins over point path. Known point patches in place, skipping null; untouched fields remain. New point uses type/field inference | Host/system/missing or non-string point SN ignored; valid unknown child SN can advance its clock even if no classification is possible | Inference matrix, known CT/SmartMeter/plug/collector, array precedence, metadata conflicts, malformed serials |
| 103 | Outbound plug control; no dedicated inbound acknowledgement handler | An incoming dict uses generic host merge | No correlation with a sent plug command | Generic inbound fallback and exact plug actions |
| 105 | Outbound full-system request; no dedicated inbound handler | An incoming dict uses generic host merge | No automatic confirmation of a poll | Generic inbound fallback and exact periodic request |
| 106 | Full host state | Normalized merge except the eleven protected keys below when already present | Settings and unprotected keys update each time; accepted traffic refreshes host, not individual measurement timestamps | All eleven protected keys with positive/zero/null seeds; repeat and 2/107 ordering |
| 107 | Incremental host state including soc/workModel | Normalized shallow merge, explicit null overwrites; missing fields retained; soc and batSoc remain independent | Ordinary fan-out; no command acknowledgement matching | Full→incremental→repeat/null, aliases, command confirmation/contradiction |
| 123 | Auth/error notification | No ordinary body-to-main merge; numeric 401 requests guarded reauth | Accepted message still reaches normal post-routing work; other error codes ignored | Numeric/string/missing code matrix; existing reauth guard tests |
| 1, 100, unknown, missing, string type | No special inbound branch; these are not assertions of firmware support | Object bodies use generic merge | Same generic effects; repeated messageId/older ts do not suppress updates | Explicit permissive-fallback cases |

Aliases are gridBuyPw→gridInPw, gridSellPw→gridOutPw and workModel→workMode.
An explicit non-null canonical field, including zero, wins. Original aliases
remain cached. Main nulls, array null fields, known-point null filtering and
expansion-energy null filtering are deliberately different contracts.

Known child array sections reject non-list, non-null containers and discard
non-object/malformed-serial members before cache mutation. Meter dicts without a
serial remain valid generic-route calculation input; they create no child identity.
This existing source behavior has its own regression. Valid list replacement
versus merge semantics are unchanged. Null sections retain their existing route
behavior. Serial values are never coerced, trimmed or case-normalized. Unknown
device metadata stays cached, but unsupported types no longer create plug sensors
or writable switches. Existing supported identities and migration are unchanged.

## Device classification matrix

These are software families and source-derived model associations, not new claims
of hardware certification. Classification currently depends on route, array and
item metadata; the tests deliberately exercise those scattered decisions.

| Item devType / subType | Identifying fields/path | Result and entity family | Fallback / limits |
| --- | --- | --- | --- |
| 1 / any | Type 23 child energy, inEgy/outEgy | Expansion battery: 2 cumulative kWh sensors, ×0.01 | No battery-array/SOC/power discovery; never treat type1 as an invented plug |
| 2 / 1,2,3,other | CT array or known/new 102; phase fields | Legacy CT: 2 power/energy sensors | Subtypes choose A/B/C; C may sum A+B; other subtype chooses total; existing energy fallback retained |
| 4 / not 7 | CT path | Legacy CT, same 2 sensors | Not promoted to collector without subtype7 |
| 3 / 5 | HTO907A association; lowercase phase fields | SmartMeter: 19 direct phase power/energy and comm entities | Optional existing HTTP remains separate |
| 3 / 2 | Shelly Pro 3EM association | Same 19 SmartMeter entities | Does not use legacy CT subtype phase-selection logic |
| 3 / unknown | Supported type, unknown subtype | Same established 19-field family | No extra capability inferred from unknown subtype/fields |
| 4 / 7 | HTO910A collectors, inPw/outPw | Collector: 5 import/export/communications/IP sensors | No type23 collector search; energy source choice untouched |
| 6 / any | Plug arrays or 102; outPw/totalEgy/sysSwitch | Plug: 2 power/energy sensors plus switch | Only commMode=1 permits entity control |
| Missing type | Plug arrays / CT arrays | Default 6 / 2 | Generic subtype-only path subType=2 retains legacy CT discovery |
| Missing type, new point | switchSta/sysSwitch/totalEgy; otherwise aPhasePw/AphasePw/tPhasePw/TphasePw/phasePw | Plug first; otherwise type3 meter | outPw alone does not imply plug locally; explicit unknown/string type is not inferred away |
| Unknown type | Any array/point | No new entities or switches | Raw array metadata retained; no speculative device support |

Array/type contradictions remain characterized: a type3 item inside `plugs`
creates SmartMeter entities reading `cts`; a type6 item inside `cts` creates
plug entities reading `plugs`; a collector in `cts` reads `collectors`. This can
leave a newly created entity without its expected source. Moving/reclassifying
data needs firmware evidence and is deferred. Known points changing devType patch
the existing section and do not dynamically recreate the family.

Physical device identity stays host+child serial, independent of classification.
The matrix tests the same child under two hosts with different classifications
in both orders and same-host subtype changes without duplicate discovery. Existing
PR2B registry tests prove reload reuses the physical device. Old family records
remain under the existing retention policy; dynamic reclassification is deferred.

## Outbound action matrix

There are six production `ha_mqtt.async_publish` sites, all in `sensor.py`: main
control, child control and four request sites in `_send_poll_requests`. No other
action publisher was found by repository-wide search. All publish to
`{prefix}/device/{host}/action`, QoS 0, retain false, using JSON strings.
The host serial is in the topic, not an added body field.

Every envelope contains type, eventId, messageId, integer wall-clock ts and body.
Each message calls `random.randint(1000, 9999)`: four-digit, inclusive bounds,
not monotonic or guaranteed unique. Polls share one timestamp per batch but obtain
an ID for each publish. Tests force repeat ID 4321 and timestamp 1700000000.75,
then assert complete decoded envelopes including ts=1700000000. Reused IDs are
accepted; there is no pending-command map, acknowledgement timeout or retry manager.
Controls include token only if truthy; requests always include it, even empty/null.
No command includes subtype or stale cache fields.

| Caller / control | Type / eventId / body | Values and immediate state | Rejection / execution evidence |
| --- | --- | --- | --- |
| isAutoStandby, swEps main switches | 1 / 3 / cmd=5,rc=1,field=0 or 1 | No optimistic UI/cache write | MQTT errors propagate; telemetry determines state |
| offGridDown, socForceChg switches | Same main envelope | UI/cache updated before publish; force charge remains binary | Errors propagate but optimistic value remains until telemetry; no acknowledgement tracked |
| isFollowMeterPw switch | Same main envelope | Optimistic; availability depends on workMode=4 | Existing availability gate, no additional direct-method command guard |
| socChgLimit, socDischgLimit numbers | 1 / 3 / cmd=5,rc=1,field=int(value) | Defaults 50–100 / 5–49, step1; dynamic device bounds; non-optimistic | HA service rejects outside current range |
| defaultPw, maxOutPw, maxFeedGrid numbers | Same main envelope | 0–200 / 0–2500 / 0–2500 W, step10; optimistic raw UI value, int cache/payload | Direct setter truncates toward zero; does not clamp or enforce step. HA service range check tested, including fractional input |
| autoStandby select | 1 / 3 / cmd=5,rc=1,autoStandby=0/1/2 | invalid/standby/on; optimistic UI/cache | Unsupported option returns without publish or state mutation |
| workModel select | Same main envelope, workModel=2/4/7/8 | self_consumption/custom/tariff/ai; optimistic UI plus both workModel/workMode cache aliases | Unsupported option no-op; subsequent canonical/aliased telemetry wins |
| Reboot button | 1 / 3 / cmd=5,rc=1,reboot=1 | No cache write | Publish error propagates; no reboot execution confirmation |
| Plug on/off/toggle | 103 / 0 / deviceSn=child,devType=entity type,sysSwitch=0/1 | No local optimism; toggle uses current displayed state | Entity commMode guard; no publish on rejection |
| Status/settings requests | 25 or 2 / 0 / null | Every batch; no cache write | 25 failure WARNING; 2 failure DEBUG; later request families still attempted |
| Full system request | 105 / 0 / null | First production batch and every third thereafter | Failure WARNING; later child requests continue |
| Child requests | 100 / 0 / devType=2,3,6 | In that order, 0.5s sleep after each successful publish | One failure logs WARNING and skips remaining child categories in that batch; next batch retries normally |

The coordinator returns without publishing when host SN is missing (controls log
a warning). This legacy no-op is documented, not redesigned. Setup with an explicit
None coordinator skips each writable platform; an absent runtime key raises a setup
error. Missing MQTT service/client is modeled by HomeAssistantError at publication;
no unavailable-client success is invented.

## Optimism, commMode and failures

Every production main switch, number, select and reboot path is obtained through
its platform setup; tests invoke actual entity actions and the actual coordinator
publisher. Assertions cover complete wire payload, initial state, immediate state,
confirming telemetry and contradictory telemetry. Non-optimistic entities wait
for data. MQTT publish success is **not confirmed device execution**. Commands
with optimistic state write before publish and retain that tentative value even
if publish raises. A subsequent device report wins, including after failure.
There is no bounded rollback timer; absent telemetry can leave the tentative value
cached. Existing freshness policy still applies and is not redesigned here.

Plug mode1 (also numeric string "1") allows on/off/toggle; mode2, missing, malformed
or unsupported mode blocks all three, creates the existing persistent notification
and raises HomeAssistantError. Cached commMode wins over the entity snapshot;
incremental messages omitting it retain the last mode. Updates 1→2→1 change control
permission immediately. Coordinator direct calls retain their current lack of a
second mode guard. Plug sysSwitch has priority over switchSta locally.

Malformed switch values and SOC bounds previously raised while processing a
shared MQTT update, preventing later listeners from receiving valid fields. Local
numeric conversion guards now leave the invalid measurement/bound unapplied and
allow other entities to update. Raw cache evidence remains. No blanket listener
exception suppression or new availability/source policy was introduced.

## Type-106 diagnosis and deferred work

Protected keys are batInPw, batOutPw, pvPw, pv1, pv2, pv3, pv4, swEpsInPw,
swEpsOutPw, stackInPw and stackOutPw. Reproduced sequence: 106 `{pvPw:12}` then
106 `{pvPw:90}` leaves 12, even without any type2 message. Zero and null seeds
also freeze. 2/107 overrides the stored value; later 106 still cannot replace it.
Settings, soc, gridInPw and other unprotected fields do overwrite. Missing keys
remain cached. Tests deliberately assert this current defect as diagnostic evidence
instead of adding skipped/xfailing tests or changing source policy.

Other deferred questions: whether type101 omission means unbinding on each firmware;
main-SN exclusion from child arrays; type23 empty-string SN and collector statistics;
top-level softver capture and changing model metadata; conflicting array/type and
subtype labels; generic point routing; malformed numeric CT/collector energy and
legacy phase fallback semantics; per-field freshness; optimistic rollback timing;
messageId/command acknowledgement semantics and live broker/device execution.
The outer calculation error guard is unchanged; this work does not claim exhaustive
validation of arbitrary numeric inputs in the energy layer. It specifically proves
the listed protocol and control malformed-input cases and continued normal delivery.

## Upstream comparison and fix evidence

Both configured upstreams were fetched for this task. Official main remains
`af97223ff17fc8f14314cbc6da7213a5eee7004d`; community main remains
`183d74b7e042061ccb985ddc023b3cb7a085452e`. These equal the Phase 0/1 pins;
the merged local foundation additionally contains the dispatch, freshness, identity
and lifecycle fixes. See the current section in [upstream-feature-matrix.md](upstream-feature-matrix.md)
and [upstream-sync.md](upstream-sync.md) for decisions and source provenance.

Official's actual-host type23 fix and host-message metadata guard are FIX_NOW:
small, source-backed and independent of energy-source decisions. Local code now
accepts actual host SN statistics and limits host metadata capture to host messages
of types 2/23/25/106/107. Expansion support, first-valid-int model capture, body-only
firmware capture and registry ownership protection are preserved.

Regression-first evidence (logs retained under `/tmp` during development):

- Initial routing matrix against unchanged foundation: 25 failed, 119 passed;
  failures demonstrated host statistics loss, child metadata contamination,
  malformed members/serials, unsupported plug creation and invalid model parsing.
- Additional control telemetry cases before conversion guards: 18 failed.
- Additional malformed array-container sequences before container filtering:
  27 failed, 11 other point/metadata cases passed.
- Five initial classification assertions used incorrect test sensor-key names;
  corrected against definitions (charge_energy, import_total, import_power/inPw).
  No production change was made to satisfy those mistaken test expectations.

Recommended next PR: dedicated energy/source behavior characterization and
resolution of the Type-106 frozen-value defect using explicit source/order evidence,
before any protocol/device/transport extraction. No such work starts in this branch.

## Validation

Final result: **862 passing tests, 92.28% statement coverage**, including all 493
foundation tests and **369 new cases** (203 routing, 24 classification, 142 command
and control-boundary cases). No skips or xfails. Python 3.13 and the existing HA
test environment are used; pytest runs outside the sandbox because of the known
HA teardown constraint documented in the original baseline.

| Command / check | Result |
| --- | --- |
| `.venv/bin/pytest tests/test_protocol_contract.py tests/test_classification_contract.py tests/test_command_contract.py tests/test_mqtt_routing.py tests/test_mqtt_lifecycle.py tests/test_multi_instance_identity.py tests/test_child_identity.py tests/test_child_migration.py tests/test_migration.py tests/test_availability_freshness.py tests/test_subdevice_availability.py tests/test_smartmeter_http.py tests/test_config_flow.py -q --no-cov --timeout=30 --tb=short` | 728 passed; includes every new case and requested targeted protection. |
| `COVERAGE_FILE=/tmp/protocol-hardening-final.coverage .venv/bin/pytest tests/ -q --timeout=30 --tb=short` | 862 passed in 21.72s; 92.28% coverage. |
| `.venv/bin/ruff check custom_components/jackery/ tests/` | Passed. |
| `python3 tools/check_translations.py` | Passed: de/en/fr. |
| `/tmp/jackery-baseline/lint-venv/bin/mypy custom_components/jackery/` | Passed, 9 source files, CI-compatible environment. |
| `.venv/bin/mypy custom_components/jackery/` | Same 23 known diagnostics in 4 files. Counter comparison against `/tmp/pr2b-mypy-final.log` matches after removing line/column numbers only. |
| `git diff --check` and new-file whitespace/final-newline check | Passed. |
| AST comparison against foundation | Energy/source, normalization, lifecycle and outgoing publisher functions unchanged. Identity/migration modules byte-for-byte unchanged. |
| `git fetch upstream-official`, `git fetch upstream-community` | Completed; pins unchanged, comparison documented above. |
| `command -v docker` | Unavailable; local HACS/Hassfest not run. Workflow definitions unchanged. |

The work remains on `test/protocol-routing-commands` for review. No commit, PR,
merge or next-roadmap implementation is part of this task.
