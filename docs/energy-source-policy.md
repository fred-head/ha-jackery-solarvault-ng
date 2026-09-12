# Energy and measurement-source contract

Investigation base: foundation `0673a49a17fe2195fa2f74189b60e697745f57f2`.
This document separates inspected implementation, regression expectations and
unverified firmware semantics. All new playback tests are **synthetic**. No
sanitized recorded MQTT fixture files exist in this checkout.

## Field inventory

`H` below means normalized top-level `_data_cache`: type 2, 25, 106, 107,
host-addressed 23, and the permissive generic status route can merge these keys.
This is an accepted-code-path inventory, not a claim that every firmware emits
every key on every route. Missing incremental fields retain cached values.
`C` means `cts[]`, `D` means `collectors[]`, `P` means `plugs[]`/`plug[]`:
101/102 merge by child serial; 23 patches existing children; host/generic arrays
replace their respective lists. Expansion counters use `expansion_batteries[SN]`
from type 23. Unknown raw fields remain cached but do not create entities.

| Raw fields | Source/cache; alias | Consumers / HA sensor keys |
|---|---|---|
| `pvPw` | SolarVault H; scalar or dictionary `pvPw`, `w`, `power` | `solar_power`; total battery balance |
| `pv1`, `pv2`, `pv3`, `pv4` | SolarVault H; scalar or same dictionary keys | `solar_power_pv1`…`4`; **not summed** as fallback for pvPw |
| `batInPw`, `batOutPw` | Main battery H; no alias | `battery_charge_power`, `battery_discharge_power`; not total-stack balance |
| `stackInPw`, `stackOutPw` | Inverter stack H; semantics unresolved | `stack_in_power`, `stack_out_power`; not battery balance |
| `inOngridPw`, `outOngridPw` | Host on-grid port H | `grid_import_power`, `grid_export_power`; battery balance, on-grid candidate and anomaly rules |
| `gridInPw`, `gridOutPw` | Host system H; `gridBuyPw`, `gridSellPw` normalize respectively | system diagnostic sensors, on-grid candidate, system grid fallback |
| `inGridSidePw`, `outGridSidePw` | Host system H | grid-side diagnostic sensors; system grid and on-grid candidates |
| `swEpsInPw`, `swEpsOutPw` | Host EPS H | `eps_input_power`; `eps_output_power` is out minus in; battery balance |
| `otherLoadPw` | Host H | `other_load_power`; deliberately not a home-calculation fallback |
| `tPhasePw`, `tnPhasePw`; `a/b/cPhasePw`, `an/bn/cnPhasePw` | SmartMeter/CT C; uppercase first-letter aliases `TphasePw`, `TnphasePw`, `AphasePw` etc. for calculation | grid calculation totals, then phase sums; 3-phase entity totals and L1/L2/L3 directional power |
| `phasePw`, `phaseEgy` | Legacy CT C; entity selects configured phase from reported phase fields | legacy CT power/energy; phasePw alone is not a whole-house grid measurement |
| `inPw`, `outPw` | Meter collector D | collector import/export entities and grid fallback |
| `outPw` (`power` fallback), `totalEgy` | Smart plug P | plug power/energy; not household-load formula inputs |
| `batChgEgy`, `batDisChgEgy` | Host H | battery charge/discharge energy |
| `pvEgy`, `pv1Egy`…`pv4Egy` | Host H | solar total/channel energy |
| `inOngridEgy`, `outOngridEgy`, `inEpsEgy`, `outEpsEgy` | Host H | grid import/export and EPS input/output energy |
| `acOtBatEgy`, `pvOtBatEgy`, `pvOtAcEgy`, `pvOtOngridEgy` | Host H | AC→battery, PV→battery/AC/grid energy |
| `ongridOtAcLoadEgy`, `batOtAcEgy`, `batOtGridEgy`, `ongridOtBatEgy` | Host H | grid→AC load, battery→AC/grid, grid→battery energy |
| `inCtEgy`, `outCtEgy`, `acOtOngridEgy` | Host H | CT import/export, AC→grid energy |
| `tPhaseEgy`, `tnPhaseEgy`, `a/b/cPhaseEgy`, `an/bn/cnPhaseEgy` | SmartMeter C | total/per-phase directional energy, ×0.01 kWh |
| `inEgy`, `outEgy` | Expansion battery, type 23 | expansion charge/discharge energy, ×0.01 kWh; cumulative availability exception retained |
| `volt1/2/3`, `curr1/2/3`, `rep1/2/3`, `ap1/2/3`, `fact1/2/3`, `freq` | SmartMeter HTTP response; entity-owned state, not H/C | supplemental voltage, current, reactive/apparent power, PF (×0.001), frequency; **no active grid power** |
| `calc_home_power`, `calc_batt_net_power`, `calc_grid_net_power` | Derived cache | `home_power`, `battery_net_power`, `grid_net_power` |
| `total_battery_charge_power`, `total_battery_discharge_power` | Derived cache | same-named sensor keys, unsigned split of total battery balance |

Energy counters do not enter instantaneous W calculations. All listed host
energy counters scale by 0.01 kWh, as do plug and legacy CT counters. Host and
child entity conversion/scaling is preserved; [entity-inventory.md](entity-inventory.md)
provides the complete entity-key mapping. Power limit/status fields (`maxOutPw`,
`maxFeedGrid`, `energyPlanPw`, `standbyPw`, `pvMaxChgPower`, `maxSysInPw`,
`maxSysOutPw`, `maxInvStdPw`, `maxGridStdPw`, `batSoc`, `soc`, `ctStat`,
`gridSate`, `ongridStat`) are retained/exposed as configured, not alternate
measurements in the energy balance.

HTO907A and Shelly Pro 3EM both use the devType-3 MQTT meter path. Legacy CT
devType 2 and other CT devType 4 share calculation fields where reported.
HTO910A (devType 4/subType 7) is a collector in `collectors`, not a PV or battery
source. No model name establishes a separate precedence rule.

## Baseline and historical evidence

Before this fix, CT selection read only `cts[0]`, used truthiness for uppercase
aliases, and manufactured zero phase sums from missing values. Thus an empty
CT blocked a usable collector/system source. CT/collector selection ignored
the established child timeout, even after child entities became unavailable.
Raw host candidates also persist indefinitely while any host/relayed traffic
keeps the coordinator alive; candidate magnitude is not a freshness measure.

Commit `80435856b48eba1a05c8186df140ac2eb2ffc172` documents the original
Type-106 protection: ~30-second polled snapshots displaced fresher ~11-second
Type-2 battery readings. Its key-existence guard accidentally protected even
values first supplied by 106 and null seeds forever. Simply deleting that guard
would restore the original race.

## Type-106 policy

The corrected contract uses a bounded preference for valid live host fields.
For the eleven protected keys (`batInPw`, `batOutPw`, `pvPw`, `pv1`…`pv4`,
`swEpsInPw`, `swEpsOutPw`, `stackInPw`, `stackOutPw`), an accepted live update
has preference for **60 seconds inclusive**, using the existing timeout.
After that window a newly received 106 may replace it. Repeated 106-only
updates replace one another; snapshots cannot renew a live preference.
Unrelated traffic cannot renew another field's preference. A live zero is
valid; a live null releases that field's preference. Incoming null remains raw
null when accepted and never creates a permanent lock.
Finite numbers and numeric strings are accepted; booleans, non-numbers and
non-finite values cannot establish a live preference. Dictionary validation uses
the first non-null PV alias. This is narrow power validation, not a general
validator for every numeric protocol field.

This is a local receipt-time policy, **not a measured firmware timestamp
guarantee**. The bounded preference is a conservative inference combining the
documented snapshot race and existing 60-second timeout. Envelope timestamps
and message IDs have no verified common units, ordering or sample-time contract;
they are not used to invent one. Later 2/107 (and ordinary 25 host status) wins
immediately. Host 23 has the same accepted-cache semantics. Unknown generic
routes continue to merge but do not establish a known-live preference.

## Grid and solar source policy

Select the first usable, non-expired CT/SmartMeter in array order, then the first
usable, non-expired collector, then existing host system candidates. Serialled
children use the existing child last-seen timeout (available through 60s).
Serial-less generic measurements retain their historical acceptance; their
age is unknown. Do not infer offline status from unverified commState values.
Recovery returns to the preferred meter, including a reported zero. Keep raw
arrays when a source is skipped.
Selection is reevaluated on received MQTT messages and the existing polling
timer (normally every 10 seconds), without new tasks/subscriptions. Between
messages, only changed grid/home derived entities are updated. With no usable
grid source, the grid entity becomes unavailable while retaining its last
value internally. Whole-host timeout still takes precedence over timer updates.

Within CT fields, uppercase alias has priority when non-null, including zero;
then lowercase. Totals precede phase sums; sum phases only if a total is
absent/null and at least one phase measurement exists. An absent opposite
direction contributes zero. Metadata alone is not a zero measurement. Collector
inPw/outPw uses the same non-null presence rule.

System grid fallback retains maximum absolute net among grid-side and gridIn/Out
pairs; on-grid port alone does not establish a whole-house grid measurement.
The on-grid estimate independently retains maximum magnitude among gridIn/Out,
inOngrid/outOngrid and grid-side pairs. Ties preserve existing order. This policy
is inherited deliberately, **not** generalized to CT versus system sources.
Its historical goal was to avoid snapshot zero masking a live host alias.
Conflicting host aliases still need device evidence before changing priority.

Solar balance uses pvPw, never an invented channel sum. For dictionaries,
prefer first non-null pvPw/w/power, including zero. Battery raw main-unit and
stack sensors remain separate from the derived total battery flow.

## Formulas and intentional limits

Positive net grid means import; positive battery net means charge.
`battery_net = PV + inOngridPw - outOngridPw - swEpsOutPw + swEpsInPw`.
Charge/discharge are `max(net, 0)` / `max(-net, 0)`.
`grid_net = meter_import - meter_export`, or selected system net.
`home = max(0, grid_net - ongrid_net)`; with no grid source,
`home = max(0, -ongrid_net)` and grid net is unavailable.

Existing anomaly branches remain: when grid buy is below on-grid charge by at
most 50W, grid net becomes the on-grid estimate; positive grid buy under that
condition yields home=0. For positive buy and a larger deficit, home becomes
charge-buy. This includes a zero-grid/≤50W edge case that needs hardware evidence;
zero is authoritative at source selection, but this later correction can change
the derived value. Missing/null scalar inputs retain the existing zero calculation
default; this is not a claim that the device measured zero.
The EPS output entity reports unavailable for an explicitly null/invalid input
direction and recovers on valid data; it cannot abort fan-out to later entities.
Missing EPS keys retain the previous zero-default behavior.

The community comment records a parallel app/MQTT comparison on 2026-08-04:
the total-stack balance matched within 13W while main-only batInPw differed by
200–300W with BP2500 charging. This is historical source evidence, not a new
hardware validation performed in this task.

## HTTP and freshness boundaries

HTTP supplies 16 supplemental electrical sensors, no active power or energy
source for these formulas. There is therefore no HTTP→MQTT grid-power failover
to implement. HTTP polling, three-failure health threshold, independent recovery
and task lifecycle remain unchanged. MQTT cannot refresh HTTP state/counters;
HTTP cannot refresh child MQTT activity. Zero HTTP values remain valid.

Child freshness is activity age, not each measurement's age. A metadata-only
child update can keep cached power selected; host alias power can persist under
unrelated host traffic. These remaining limitations are explicitly characterized
in tests. Per-field TTL for all firmware measurements and replacement of the
host magnitude policy require reporting-cadence and alias evidence first.
No source disappearance is inferred solely from an omitted incremental field.
Legacy single-phase CT entity alias/phase-selection quirks remain unchanged;
the corrected CT alias precedence here describes the whole-house calculation.
Energy counter scaling and cumulative retention have not changed.

## Internal observability and lifecycle

`_power_live_seen` stores accepted live type/receipt time for at most eleven
keys. `_power_106_samples` retains the latest raw 106 value and receipt time for
the same bounded set, including suppressed snapshots; it is not replayed later
without a new message. These maps and the selected cache permit comparison of
live versus snapshot power without exposing new HA entities.
`_energy_sources['grid']` gives source label (`cts`, `collectors`, `system`,
`unavailable`), selected child activity age, counts skipped for stale/missing
power and the selection reason. Unknown age is explicitly null, including
host system candidates. The metadata is per coordinator, has no entity
references or serials in source labels, and does not change HTTP health.
No persistent storage, registry, command, subscription or polling-task ownership
changes were made. Existing unload/reload and identity regression gates remain.

## Upstream comparison

Fetched references: official `af97223ff17fc8f14314cbc6da7213a5eee7004d`,
community `183d74b7e042061ccb985ddc023b3cb7a085452e`.

| Topic | Classification | Decision |
|---|---|---|
| Community 106 key-existence guard | SAME (baseline defect) | Keep live preference, bound it; repeated snapshots update |
| Official unconditional normalized 106 merge | DIFFERENT_BUT_AMBIGUOUS | Does not preserve documented live/snapshot race protection |
| Official CT extraction checks actual phase presence | OFFICIAL_BETTER_SUPPORTED | Adopt presence distinction, independently regression tested |
| Official substitutes phases for total zero, requires commState for zero | DIFFERENT_BUT_AMBIGUOUS | Preserve reported total zero; do not infer quality from magnitude |
| Community collector fallback | COMMUNITY_BETTER_SUPPORTED | Preserve, apply existing child health |
| Official battery uses raw batIn/Out preferentially | COMMUNITY_BETTER_SUPPORTED | Preserve community total-stack formula and documented BP2500 evidence |
| Official home export reversal / otherLoadPw fallback | COMMUNITY_BETTER_SUPPORTED | Preserve local sign, clamp and no-meter regression behavior |
| Host candidate magnitude selection | SAME mechanism / NEEDS_REAL_DEVICE_EVIDENCE | Characterize conflict and stale-alias limitation, no new priority guess |
| Wire timestamps and snapshot age | NEEDS_REAL_DEVICE_EVIDENCE | Local receipt time only |

## Verification

Regression tests are added before production changes. The protected-field matrix
replaces the previous frozen-value diagnostic with corrected expectations;
history above preserves the defect evidence. Validation results and final
results are recorded below.

- Before production edits: energy/protocol regression run **164 failed, 238 passed**
  (`/tmp/energy-baseline.log`): permanent 106 guard, absent timeout, CT presence/
  alias selection and nested PV zero failures.
- Before timer/EPS edits: **4 failed, 4 passed**
  (`/tmp/energy-timer-baseline.log`): stale derived grid/home entities and EPS
  null interrupting later entity updates.
- Corrected initial targeted energy/protocol/calculation run: **424 passed**.
- First full run: **1,069 passed, 92.52% coverage**. Final gates below also
  include added source-observability, malformed-power and route-boundary tests.

Final validation (2026-09-12):

| Command | Result |
|---|---|
| `.venv/bin/pytest -q tests/test_energy_source_policy.py tests/test_protocol_contract.py tests/test_calculate_energy_flow.py --no-cov` | 424 passed before the last additional boundary cases |
| `COVERAGE_FILE=/tmp/energy-final.coverage .venv/bin/pytest -q tests/` | **1,081 passed, 92.57% coverage**, 22.95s; 219 more cases than foundation |
| `.venv/bin/ruff check custom_components/jackery/ tests/test_energy_source_policy.py tests/test_protocol_contract.py tests/test_availability_freshness.py tests/conftest.py` | Passed |
| `.venv/bin/python tools/check_translations.py` | de/en/fr passed |
| `/tmp/jackery-baseline/lint-venv/bin/mypy custom_components/jackery/` | CI-compatible environment: passed, 9 source files |
| `.venv/bin/mypy custom_components/jackery/` | HA-aware environment: 23 existing findings in 4 files; normalized comparison to `/tmp/protocol-finalize-mypy-ha.log` has no additions or removals |
| `git diff --check` | Passed |

The full suite includes protocol/classification/command, MQTT routing/lifecycle,
availability, SmartMeter HTTP, subdevice/entity, identity/migration, recorder,
config flow and earlier formula regressions. Tests run outside the restricted
sandbox to avoid the established HA teardown hang. Final output is in
`/tmp/energy-full-final.log`; coverage is in `/tmp/energy-final.coverage`.
Hassfest/HACS Docker actions were not run locally (Docker unavailable).

Changed files: production `custom_components/jackery/sensor.py` only; tests
`test_energy_source_policy.py`, `test_protocol_contract.py`,
`test_availability_freshness.py`, constructor-equivalent metadata in `conftest.py`;
this policy, MQTT inventory, capability inventory, availability report, protocol
report, coverage map, refactor map, upstream feature matrix and `CHANGELOG.md`.

Safe mechanical extraction can now preserve an explicit tested contract. This
is not evidence that all firmware source semantics are settled: host alias
priority, metadata-only freshness, the ≤50W correction, and snapshot wire
timestamps remain open. Do not redesign them during extraction. No hardware
compatibility claim or automatic start of the next roadmap item is implied.
