# Current community capabilities

The later [energy/source contract](energy-source-policy.md) inventories raw power
and energy fields, preserves total-stack formulas, corrects repeated Type-106
updates and excludes expired/measurement-less meters from grid selection. HTTP
measurements remain supplemental and do not supply active grid-power fallback.

This is the historical community inventory. The current tested classification and
command behavior, including explicitly rejected unknown-device discovery, is in
[protocol-routing-commands.md](protocol-routing-commands.md). Merged lifecycle,
freshness and identity fixes supersede the corresponding limitations below.

Pinned baseline and C/O source notation: [baseline](baseline.md). This is a description of C, including limitations, rather than a promise of hardware coverage.

Post-baseline availability corrections and intentionally retained policies are
documented in the [availability/freshness audit](availability-freshness.md).

## Main device

The user supplies `device_sn`, token and optional topic prefix (`hb`). A config-entry unique ID rejects duplicate trimmed SNs, although entry data retains the original submitted string. Runtime SNs are not model-validated. `sensor.py:1421` extracts the host SN from status/event topics and ignores a different matching SN; if configured SN is empty it can discover one. The matcher uses an unescaped, unanchored regular expression. Topic mismatch and malformed payload validation are not strict.

`DEVICE_TYPE_MODEL_MAP` (`sensor.py:46`) maps only top-level `deviceType=3` to `DIY3`; fallback is `Energy Monitor`. This is distinct from **subdevice** `devType`. `body.softver` updates the registry; top-level firmware is not captured. The first convertible deviceType wins, even when the message body belongs to a child (`sensor.py:1674`).

| Model | Evidence / scope |
| --- | --- |
| SolarVault 3 Pro Max | Explicit hardware-tested claim in [README](../README.md), including SmartMeter and Shelly installations. Synthetic calculations/routing tests support selected behaviors; no hardware test executed here. |
| SolarVault 3 | [CHANGELOG](../CHANGELOG.md) reports SOC bound confirmation on this model and Pro Max. This does not establish all-feature coverage. |
| SolarVault 3 Pro / other variants | No distinct runtime classifier or model-specific test fixture found. Generic field-based compatibility is inferred, not verified model support. |

75 main sensor definitions are created unconditionally; there is no capability-based suppression or disabled-by-default declaration. [Entity inventory](entity-inventory.md) enumerates every field, unit and transformation. Status includes SOC, battery count/temperature/state, device/ongrid/CT/link enums, EPS, network details, ability and funcEnable. Energy includes PV total/per-input, main battery, AC/grid-port paths and CT totals. Reported power limits/settings remain visible even when their semantics or writability are not confirmed.

Writable main entities (`switch.py:28`, `number.py:20`, `select.py:39`, `button.py:20`):

| Platform | Fields / actions | Behavior |
| --- | --- | --- |
| Switch | `isAutoStandby`, `swEps` | Sends 1/0; waits for telemetry to change displayed state. |
| Switch | `offGridDown`, `socForceChg` | Optimistic UI and cache update before publish. Force charging is binary, not a SOC target. |
| Switch | `isFollowMeterPw` | Optimistic; entity unavailable when received `workMode != 4`. Missing/invalid workMode does not enforce that restriction. |
| Number | `socChgLimit`, `socDischgLimit` | Defaults 50–100% and 5–49%, step 1; device-reported bounds override defaults. |
| Number | `defaultPw`, `maxOutPw`, `maxFeedGrid` | Optimistic; 0–200 W / 0–2500 W / 0–2500 W, all step 10. House AC output limit and public-grid export cap are separate. |
| Select | `autoStandby`; `workModel` | 0/1/2 standby enum; work modes 2/4/7/8. WorkModel writes patch both `workMode` and `workModel`. |
| Button | `reboot=1` | Main type=1/cmd=5 command. No execution acknowledgement tracking. |

`offGridTime`, capability bits and other raw configuration fields are read-only; a sensor name is not evidence of writability. Changelog reports offGridTime did not acknowledge writes. No pairing, provisioning, arbitrary service, cloud API or EMS scheduler is implemented.

## Subdevices

Current child classification is centralized in the standard-library-only
`devices/classification.py`. It returns one of expansion battery, CT,
SmartMeter, collector, plug or unknown, plus the established HTO907A, Shelly Pro
3EM and HTO910A subtype associations. Explicit contexts retain the existing
route differences: missing `devType` defaults to 6 in plug arrays and 2 in CT
arrays; collector arrays add no default; Type-102 point updates infer a plug
from switch/energy fields before considering phase-power fields for a
SmartMeter; Type-23 recognizes only `devType=1` as an expansion battery.

Arrays accepted: `plug/plugs/socket/sockets`, `ct/cts`, `collectors`. Each nonempty section merges by `deviceSn` or `sn`; missing entries and fields remain cached. Classification does not choose the cache/source array. Consequently, contradictory explicit metadata retains its prior behavior: the family follows `devType`/`subType`, while later entity reads still use the established family source array. This is characterized rather than standardized in this extraction.

| Class/model | devType / subType | Classification and measurements | Control / communications | Evidence |
| --- | --- | --- | --- | --- |
| BP2500 / expansion battery | 1 / sample 0 | Type-23 with non-system SN; separate `expansion_batteries[SN]`; `inEgy`, `outEgy` ×0.01 kWh. No individual instantaneous power or SOC entities. | Read-only; no commMode gate. | Explicit BP2500 upstream reports (README, changelog, calculation comment); synthetic type-23/null/availability tests. |
| Jackery SmartMeter 3P HTO907A | 3 / 5 | All devType=3 selects `ct_3phase`, reads lowercase phase totals and per-phase power/energy directly; 19 entities. | Read-only MQTT; commMode 1=lan, 2=cloud and commState displayed. Optional HTTP below. | README explicitly hardware tested; synthetic direct classifier and full discovery/entity snapshots cover this association. |
| Shelly Pro 3EM through Jackery | 3 / 2 | Same 19-entity direct-field group, not legacy CT phase selection. | Jackery MQTT only; no Shelly RPC/HTTP transport. | README explicitly hardware tested; `d99b8ca` introduces all-devType=3 grouping. Synthetic direct classifier and full discovery/entity snapshots cover subtype 2. |
| Jackery D0 reader HTO910A | 4 / 7 | `collectors` → collector group; import/export W, commState, commMode, IP (5). First usable collector is grid fallback after CT. | Read-only; communications displayed, not enforced as measurement freshness. | Named in source/README; synthetic direct classifier, discovery/entity and energy-source tests cover the software path. No explicit hardware-test certification found. |
| Standard CT | 2 / 1–5 and others | `ct` group (power, energy): subtype 1 selects A, 2 B, 3 C with A+B fallback, else total; energy may fall back to sole nonzero phase. | Read-only; attributes include commState and diagnostic hardware label. | Synthetic direct classifier, routing and discovery/entity snapshots; no new hardware evidence. |
| Other meter collector | 4 / not 7 | Legacy `ct` group in discovery, normally reads `cts`. | Read-only. | Synthetic devType=4 routing into cts, not real-device validation. |
| Smart plug (unnamed model) | 6 / unspecified | Power `outPw` (fallback `power`), energy `totalEgy` ×0.01 and switch. | Type=103 `sysSwitch`; HA switch blocks cloud/unknown modes, only mode 1 allowed. Telemetry still displayed in any mode. | Synthetic direct classifier, array/point, full discovery/entity, command and helper coverage. |
| Unknown subdevice types | unknown | Retained in accepted caches where applicable but do not create sensors or switches. Explicit unknown or string-valued types are not inferred from familiar fields. | Not treated as writable hardware. | Synthetic direct classifier, routing and discovery rejection coverage. |

Diagnostic `CT_SUBTYPE_MAP` labels are **not a classifier**: 1 Shelly Single Phase, 2 Shelly Three Phase, 3 Shelly 63A, 4 Eastron Single Phase (4002), 5 Eastron Three Phase (4003), 6 Jackery Wireless Smart Meter (US L1/L2 4007), 7 Jackery Smart Meter 3P (UK 4008). These named mappings alone do not prove those devices work. In particular subtype=5's diagnostic label differs from the HTO907A classification association, and subtype=7's label differs from HTO910A. This ambiguity is intentionally preserved pending device evidence.

Classification is independent of physical identity. Child device identifiers
remain scoped by SolarVault host plus child serial, and entity unique IDs also
include their established family. A subtype change updates the same physical
device association; identical child serials under different hosts remain
separate. The classifier does not migrate registries, choose entities, decide
availability, transform measurements or grant MQTT control.

Malformed or unhashable `devType` values are classified as unknown and the
static plug-switch filter rejects them without interrupting platform setup.
Only the established numeric plug type can create a writable plug switch.

## Availability and source behavior

Main timeout is 60 seconds, checked by the poll loop. However `_last_update_time` is set **before** SN filtering and JSON validation, so unrelated messages can postpone timeout. `_ever_received` becomes true before JSON validation. A 120-second never-received heuristic starts reauth; type-123/errorCode=401 also starts it once. Neither proves that a silent device rejected the token (`sensor.py:1421,1699,2190`).

Subdevice availability uses per-SN last-seen and 60-second startup grace; expansion battery energy remains available once seen regardless of age and is exempt from deletion. `_check_for_new_plugs` returns early if all lists are empty. Missing-list deletion timers are fed the **merged cache**, so ordinary omission/empty type-101 messages normally cannot remove an old cached device. In a message path, availability is then overwritten to true by sensor/plug updates from that same stale cache. Existing isolated availability tests do not cover that whole sequence (`sensor.py:1749,2639`; `switch.py:149`).

No per-measurement timestamp exists. A metadata-only cloud-mode message updates last-seen and can keep old measurements visible. `commState` does not consistently gate values. Calculation chooses first CT even without real measurement fields, then collector, then system fields; HTTP never participates in grid selection. See [protocol inventory](mqtt-protocol-inventory.md) for exact merge rules.

## Optional HTTP SmartMeter transport

Options flow edits token/topic prefix in entry data and stores `smartmeter_http_poll` (default false), `smartmeter_poll_interval` (default 10, accepted 2–60 seconds) in options (`config_flow.py:99`). No options update listener/reload is registered; startup alone creates the poll task. Manual reload may therefore be needed (also documented in README).

`sensor.py:2293–2393` selects the first cached type=3/subtype=5 meter with SN and `wip`. It GETs `http://{wip}/api/measurement` with HA aiohttp session, 5-second timeout, accepts HTTP 200 JSON without content-type enforcement, and creates 16 separate voltage/current/reactive/apparent power/power factor/frequency sensors after first success. Power factor scale is 0.001. No IP means a 30-second wait without aging existing measurements. Three consecutive ordinary HTTP failures mark sensors unavailable; successful numeric values recover them. JSON/type exceptions take the outer error path and do not increment that failure counter. Meter identity change and callback timing are not managed beyond one `_http_sm_sensors_created` flag.

**Verified interface defect:** registered HTTP sensors do not implement `_update_from_coordinator`, but `_distribute_data` invokes it on every registered entity. Thus a subsequent MQTT message can abort fan-out at the first HTTP sensor. This is recorded, not repaired, in this phase. Cancellation normally cancels/awaits both poll tasks; MQTT unsubscribe callbacks are discarded and `_subscribed` is not reset (`sensor.py:1363,1405`).
