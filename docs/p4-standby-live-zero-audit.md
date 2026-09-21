# P4.1 Standby / Live-Zero root-cause audit

Audit date: **2026-09-21**. Accepted foundation:
`69914f8e4a00d1150ae823ad9c0ccf59751298ac` on
`refactor/v3-foundation`.

This is an analysis and design record. It does not contain or authorize a
production fix, regression test, fixture or upstream port. All payloads below
are synthetic and use non-identifying placeholders.

## 1. Executive summary

The reported standby failure is reproducible through the real topic, envelope,
route, cache, calculation and entity fan-out path. An older Type-106
`gridInPw=300` remains in the incremental cache. A later Type-2 message correctly
stores explicit `inOngridPw=0` and `outOngridPw=0`, but the two field families
coexist because they are distinct raw protocol evidence.

The first wrong decision is in
`calculations.energy_flow._effective_ongrid_net()`. It presents the cached
Type-106 net and the newer live on-grid net as equal candidates to
`_pick_best_power_net()`. That helper deliberately removes every zero whenever
any non-zero candidate exists, then selects the largest absolute magnitude. It
therefore returns the older `300`, despite the valid newer live zero. With a
current meter grid net of `300`, `home = grid_net - ongrid_net` becomes `0`
instead of `300`.

This is not a general falsy-value merge bug. Zero survives parsing, validation,
cache merge, battery calculation and entity conversion. The loss occurs later
in source arbitration. The receipt-time maps used for the existing bounded
Type-2-versus-Type-106 policy do not cover `gridInPw/gridOutPw`,
`inOngridPw/outOngridPw` or `inGridSidePw/outGridSidePw`, so the selector cannot
recover message order or age from the merged cache.

Community v2.4.2 fixes the observed sequence with strict field priority for
`inOngridPw/outOngridPw`. That is a useful source observation, but copying it
unchanged would make any cached live field authoritative indefinitely and would
treat malformed non-null live values as zero. The preferred NG design is a
narrow receipt-time-aware arbitration for the on-grid semantic value, owned by
`CoordinatorRuntimeState` and using the existing 60-second live preference.
Raw values remain untouched and the formula remains unchanged.

The root cause is sufficiently understood for a focused regression-first fix
PR. The remaining hardware questions affect validation breadth, not the known
software failure or the proposed bounded contract.

## 2. Foundation

The audit gate passed before the audit branch was created:

- working tree clean;
- local and `origin/refactor/v3-foundation` both at
  `69914f8e4a00d1150ae823ad9c0ccf59751298ac`, ahead/behind `0/0`;
- merge commit `69914f8` contains the Phase-3 closeout audit;
- P3.1 through P3.5 are recorded as complete;
- the closeout identifies this standby/live-zero case as a production-readiness
  finding.

The audit branch is `audit/p4-standby-live-zero`. The last P3.5-only foundation
`2158a531be9790aa77ad234e9a4dbd52f6434ac8` is its first-parent ancestor, not
the branch base.

Read-only upstream references were freshly fetched:

| Reference | SHA | Relevant state |
| --- | --- | --- |
| Community `csoscd/ha-solarvault` | `020b37010377ee858ec7c8336282e5b9a57bf591` | v2.4.3; contains the v2.4.2 fix commit `082340e` |
| Official `Jackery-Official/jackery` | `af97223ff17fc8f14314cbc6da7213a5eee7004d` | Retains the magnitude-based helper |

No upstream commit was merged, cherry-picked or copied.

## 3. Reproduction

### 3.1 Minimal routed sequence

The smallest useful reproduction has two accepted host messages. The second
message includes a current CT value so the grid source and the on-grid port
value are independent, as they are in the reported symptom.

| Receipt time | Message | Relevant body | Meaning |
| ---: | --- | --- | --- |
| `1000` | Type 106 | `gridInPw=300`, `gridOutPw=0`, `pvPw=0` | Older full-state on-grid/system candidate |
| `1011` | Type 2 | `inOngridPw=0`, `outOngridPw=0`, `pvPw=0`, CT import `300` | Newer explicit live zero plus current whole-site grid import |

After the Type-2 message, the actual coordinator state is:

```text
gridInPw                 300
gridOutPw                  0
inOngridPw                 0
outOngridPw                0
selected grid source     cts
calc_grid_net_power      300
calc_home_power            0   <- wrong
calc_batt_net_power        0   <- correct
```

The registered `grid_net_power`, `home_power` and `battery_net_power` entities
receive `300`, `0` and `0` respectively, proving that the wrong derived cache
value reaches normal fan-out.

At receipt time `1030`, a later Type-106 snapshot with `gridInPw=0` and
`gridOutPw=0` makes both candidates zero. The unchanged CT remains fresh, so the
derived values become grid `300`, home `300`, battery `0`. This demonstrates the
usual recovery event: a subsequent snapshot that ceases to conflict. With the
normal 10-second poll loop and Type-105 request every third cycle, that is
normally around the next approximately 30-second full-state response. The bug
can persist longer if the conflicting snapshot value repeats; repeated live
zero messages alone do not repair it.

### 3.2 Reproduction method

The reproduction used an unversioned Python command with:

- a real `JackeryDataCoordinator`;
- the production `_handle_message()` topic/envelope path;
- production routing, normalization, runtime state and calculations;
- real `JackerySensor` instances with only `async_write_ha_state` mocked;
- a fixed `time.time()` source.

It created no repository file and made no network or device request.

## 4. Current data flow

The relevant runtime path is:

```text
owned topic
  -> parse_envelope()
  -> record_host_activity(time.time())
  -> _apply_message_route()
     -> Type 106: _handle_type106()
        -> normalize_payload_fields()
        -> CoordinatorRuntimeState.merge_type106_snapshot()
     -> Type 2: _merge_normalized_cache()
        -> normalize_payload_fields()
        -> CoordinatorRuntimeState.merge_main_payload()
  -> _calculate_energy_flow(merged cache)
     -> select_grid_source()
     -> calculate_energy_flow()
        -> _effective_ongrid_net()
        -> home/grid/battery formulas
  -> _distribute_data()
```

### 4.1 Cache and evidence behavior

`merge_type106_snapshot()` records snapshot samples and applies live protection
only for `_TYPE106_LIVE_PREFERRED`. That set contains eleven battery, PV, EPS
and stack fields. It does not contain any of the six grid/on-grid candidate
fields.

`merge_main_payload()` does preserve a finite numeric live zero for protected
fields: `_power_sample(0)` returns `0.0`, and the field receives live evidence.
For the on-grid fields, however, the same message only updates the raw cache.
Consequently, after the reproduction:

```text
power_live_seen    contains pvPw only
power_106_samples  contains pvPw only
energy_sources     says grid source = cts
```

There is no receipt metadata for either the live on-grid pair or the Type-106
grid pair. `energy_sources["grid"]` correctly describes the CT selected for
whole-site grid power; it is not provenance for the separate on-grid-port
candidate.

### 4.2 Calculation behavior

`_field_present()` correctly considers zero present. `_safe_float()` converts
the two valid zero fields to `0.0`. `_effective_ongrid_net()` constructs:

```text
Type-106 grid pair:  300 - 0 = 300
live on-grid pair:     0 - 0 =   0
```

`_pick_best_power_net([300, 0])` first builds the non-zero list `[300]` and
returns `300`. Message order is already lost; the same merged dictionary yields
the same result regardless of which message was newer.

`select_grid_source()` independently and correctly selects the current CT net
of `300`. The formula then computes:

```text
home = grid_net - ongrid_net = 300 - 300 = 0
```

Battery net does not use `_effective_ongrid_net()`. It uses the raw live
`inOngridPw/outOngridPw` pair directly, so it remains correct in the minimal
case.

## 5. Timeline / state transition

| Step | Raw cache | Receipt evidence | Selected grid source | Effective on-grid | Derived result |
| --- | --- | --- | --- | ---: | --- |
| Startup | Empty | None | unavailable | `0` default | grid unavailable, home `0` |
| Type 106 at `1000` | `gridIn=300`, `gridOut=0` | No on-grid evidence recorded | system `300` | `300` | grid `300`, home `0` |
| Type 2 at `1011` | Adds live `in/outOngrid=0/0`; old grid pair retained | Still no on-grid evidence | CT `300`, age `0` | **`300`** | grid `300`, home **`0`** |
| Repeated live zero | Live keys rewritten with zero | Still no on-grid evidence | CT remains selected | **`300`** | Defect persists |
| Type 106 zero at `1030` | Replaces grid pair with `0/0` | Still no on-grid evidence | CT `300`, age `19` | `0` | grid `300`, home `300` |

Host freshness is updated by each accepted envelope. It says the host is alive;
it does not say which cached field is current. Child freshness says the CT is
current. Neither can order the two host candidate pairs.

All runtime clocks in this path use local receipt `time.time()`. Wire `ts` and
message IDs have no verified common sample-time semantics and are deliberately
not used. A focused fix can stay in this existing time domain.

## 6. Root cause

Given a cached Type-106 `gridInPw/gridOutPw` non-zero pair and a later accepted
Type-2 `inOngridPw/outOngridPw` pair whose valid net is zero,
`CoordinatorRuntimeState` stores both raw pairs but records no per-source
receipt evidence for them. `calculate_energy_flow()` then calls
`_effective_ongrid_net()`, which treats the temporally different pairs as
equal candidates. `_pick_best_power_net()` excludes zero whenever any non-zero
candidate exists and therefore selects the older Type-106 net. The stale
on-grid value remains authoritative for `calc_home_power`, causing
`grid_net - ongrid_net` to collapse to zero until another candidate changes.

The defect is broader than truthiness but narrower than the whole calculation:

- zero is not lost during parsing or cache merge;
- source age/order is unavailable at the selector;
- magnitude is incorrectly used as a proxy for source quality;
- the first incorrect value is `ongrid_net`, before the home formula and entity
  fan-out.

The same selector also lets any smaller-magnitude newer live value lose to a
larger older candidate. Zero makes the problem deterministic and visible in
standby; it is not the only possible magnitude conflict.

## 7. Zero vs missing vs stale semantics

| Semantic state | Required meaning | Current representation | Current result |
| --- | --- | --- | --- |
| Missing / never seen | Source provides no candidate | Key absent or null; `_field_present()` false | Correctly omitted |
| Explicit zero | Valid measured no-flow | Finite numeric zero in cache; field present | Preserved, but loses to every non-zero candidate |
| Non-zero | Valid measured directional flow | Finite numeric value in cache | Considered; largest magnitude wins |
| Stale | Previously valid but superseded/expired evidence | Value remains in cache | Indistinguishable because these fields have no receipt evidence |
| Invalid | Non-null non-numeric/non-finite input | `_safe_float()` returns zero while `_field_present()` remains true | Can be mistaken for explicit zero in this helper |

The current code can distinguish missing from explicit zero, and the shared
protected-field policy can distinguish current live from later snapshots for
eleven other fields. It cannot distinguish current, stale and invalid on-grid
candidates sufficiently for this arbitration.

A zero becomes stale because of its source receipt history, never because its
magnitude is zero. Consistent with the existing protected-field policy, a new
live observation receives bounded preference. A snapshot received within the
60-second live window is suppressed for selection; it must not become active
later merely because a timer elapsed. A newly received valid snapshot after the
window may replace the stale live candidate. An older snapshot must never be
resurrected over a newer live value.

## 8. Affected fields / blast radius

| Semantic value | Live source | Type-106/fallback source | Calculation/entity | Same bug possible? |
| --- | --- | --- | --- | --- |
| On-grid port net | `inOngridPw/outOngridPw` | `gridInPw/gridOutPw`; also grid-side pair | `calc_home_power`; no-meter home fallback | **Confirmed** for home power and Entity fan-out |
| Whole-site grid net | CT/collector or `inGridSidePw/outGridSidePw` | `gridInPw/gridOutPw` | `calc_grid_net_power`, then home | Same magnitude mechanism is synthetically reproducible for host fallbacks and is already characterized, but it is a separate policy without hardware proof |
| Grid anomaly correction | Current selected grid plus raw `inOngridPw` | Effective on-grid candidate | May overwrite `calc_grid_net_power` in the existing <=50 W branch | Theoretical shared path; the explicit-zero reproduction does not enter this branch |
| Total battery net | Raw `pvPw`, live on-grid pair and EPS pair | No effective-on-grid selector | Battery net/charge/discharge entities | **Not affected** by this selector; reproduction remains correct |
| Solar power | Live/shared `pvPw` | Type-106 same-key snapshot | Solar and battery balance | **Not affected**; existing bounded same-key evidence preserves zero |
| EPS power | Live/shared EPS fields | Type-106 same-key snapshot | EPS and battery balance | **Not affected**; separate bounded same-key evidence |
| Main battery/stack raw power | Live/shared same keys | Type-106 same keys | Raw main/stack entities | **Not affected** by `_effective_ongrid_net()` |
| Raw grid/on-grid entities | Their respective raw keys | Their respective raw keys | `grid_import_power`, `grid_in_power`, grid-side diagnostic entities | No arbitration; they intentionally expose distinct cached protocol evidence |

`_pick_best_power_net()` is shared by `_grid_net_from_system()`. P4.1 must not
silently change that second policy while fixing the confirmed on-grid-port
selection. Its stale-host-alias case needs its own hardware evidence and
regression-first decision.

## 9. Existing test gap

The relevant existing test selection passes **277 tests**, but none expresses
the complete failing contract:

- `TestEffectiveOngridNet.test_type106_zero_does_not_mask_type2_reading`
  tests old/snapshot zero against live non-zero. It freezes the original reason
  for magnitude selection, not the inverse live-zero sequence.
- `_pick_best_power_net([0, 170]) == 170` explicitly says zero must not mask a
  reading, but supplies no source identity or receipt time.
- the protected-field matrix verifies live zero versus Type 106 only for the
  eleven `_TYPE106_LIVE_PREFERRED` same-key fields; the grid/on-grid aliases are
  absent from that matrix.
- energy-balance tests provide one coherent message/state at a time. They do
  not retain an older conflicting alias across messages.
- alias tests prove that normalization preserves explicit zero, but do not run
  the derived formulas.
- `test_system_magnitude_and_cached_source_limitation` deliberately freezes an
  older `gridInPw=900` winning over a newer grid-side zero for the separate
  system fallback. It does not assert live on-grid priority or Home Power.
- no current test combines Type 106 -> Type 2 live zero -> current CT source ->
  calculation -> registered Home Power entity.
- current provenance assertions cover CT/collector/system selection, not the
  internal on-grid-port source.

Thus the suite proves each surrounding mechanism while leaving the temporal
cross-alias composition untested. High statement coverage executes the lines;
it does not supply the missing state sequence.

The audit ran:

```text
pytest -q test_energy_source_policy.py test_calculate_energy_flow.py
          test_energy_flow_module.py test_upstream_sync.py
          test_coordinator_state_transitions.py --no-cov
277 passed
```

The first sandbox run entered the known HA/asyncio teardown hang and was
stopped. The identical local run outside that restriction completed in 0.82 s.

## 10. Community-v2.4.2 history

The magnitude helper and multi-source `_effective_ongrid_net()` entered the
community line in `ad738cc` (`feat: upstream sync v2.0.0`) and shipped in the
v2.3.x line. Its stated goal was the opposite ordering: prevent a Type-106 zero
from hiding a live non-zero Type-2 value. The common v2.4.0 ancestor
`183d74b` already contains that behavior.

NG inherited the behavior from its starting foundation. Commit `86efbe3`
extracted it into `calculations/energy_flow.py` without semantic change. NG did
not lose an existing fix during refactoring.

The community project later added commit
`082340e3e49be76f9283f74054cbd3049bde120a`, released in v2.4.2. It changes only
the relevant priority concept:

1. if `inOngridPw/outOngridPw` is present, return that net, including zero;
2. otherwise consider grid-side fields;
3. use `gridInPw/gridOutPw` as the final fallback.

That commit documents the approximately 11-second live cadence and 30-second
snapshot cadence. It contains production/docs/version changes but no dedicated
regression test for the failing message sequence. The current official
reference still uses magnitude selection. These are reference facts, not
authority to port either implementation.

## 11. Correct behavior contract

The focused fix should establish this contract for a **validated on-grid
semantic candidate** while leaving raw cache fields and other source policies
unchanged:

1. A valid newly received live pair wins immediately over an older Type-106
   pair, including when the live net is exactly zero.
2. A valid Type-106 pair is used at startup when no live evidence exists.
3. Missing, null or invalid live input does not manufacture zero and does not
   establish live preference.
4. A Type-106 observation received within the existing 60-second live
   preference does not replace live selection.
5. A newly received valid Type-106 observation after that bounded window may
   replace a live candidate that has not been refreshed.
6. An already suppressed older snapshot is not replayed merely because wall
   time later passes the boundary; replacement requires new evidence, matching
   the current same-key policy.
7. A newer valid live observation recovers immediately from a selected
   snapshot.
8. Non-zero -> zero and zero -> non-zero transitions within one source both
   follow receipt order; magnitude has no quality meaning.
9. Grid-side and Type-106 fallback ordering outside the confirmed live
   preference remains unchanged in P4.1.
10. Host timeout and entity availability remain independent of field/source
    arbitration.

The required order matrix is therefore:

| Sequence | Expected selection |
| --- | --- |
| Startup, Type 106 only | Type 106 |
| Type 106 -> valid live zero | Live zero |
| Type 106 -> valid live non-zero | Live |
| Live -> Type 106 inside 60 s | Live |
| Live -> newly received Type 106 after 60 s | Type 106 |
| Newer live -> older cached Type 106 | Live |
| Stale live with no newer fallback evidence | Retain live until new evidence or host unavailability; do not resurrect older data |
| Live non-zero -> live zero | Live zero |
| Live zero -> live non-zero | Live non-zero |
| Invalid/missing live -> Type 106 | Type 106 |

This is not “zero always wins.” It is validated source evidence plus bounded
receipt-time priority.

## 12. Candidate fixes

### A. Strict field priority, matching community v2.4.2

- **Files/functions:** `_effective_ongrid_net()` in
  `calculations/energy_flow.py` plus direct/integration tests.
- **State change:** none.
- **Behavior:** use `inOngridPw/outOngridPw` whenever non-null keys exist; retain
  current fallback logic otherwise.
- **Advantages:** smallest production diff; fixes the known sequence; easy to
  test; formula and routing unchanged.
- **Risks:** cache presence becomes an unbounded freshness proxy. A live field
  can remain preferred indefinitely while other host traffic and Type-106
  snapshots continue. Current `_safe_float()` also turns malformed non-null
  live values into zero. It cannot satisfy stale-live -> newer-Type-106
  semantics without an explicit policy that live fields are permanently
  authoritative.

### B. Bounded receipt-time on-grid arbitration

- **Files/functions:** `CoordinatorRuntimeState` receipt evidence,
  coordinator merge adapter, a small pure on-grid selection input/helper in
  `calculations/energy_flow.py`, and focused tests.
- **State change:** yes, but metadata only. Add per-coordinator receipt evidence
  for the semantic live and Type-106 on-grid candidates, or extend the existing
  power evidence maps with an equally explicit contract. Do not copy raw values.
- **Behavior:** validate at least one finite directional sample, preserve zero,
  record local receipt time, and apply the existing inclusive 60-second live
  preference. Pass the selected net/source into the pure calculation.
- **Advantages:** satisfies the complete ordering contract, separates freshness
  from cache presence, preserves raw evidence and reuses the accepted runtime
  owner/timebase.
- **Risks:** larger than the community patch; partial directional updates and
  exact evidence-map shape need explicit tests. Diagnostics must not infer or
  export new raw data.
- **Testability:** high with the fixed clock and current routed coordinator
  fixtures.

### C. Canonicalize or delete competing cache fields

- **Files/functions:** route/cache merge.
- **State change:** no explicit timestamp, but destructive cache mutation.
- **Behavior:** overwrite/delete the older alias when another source arrives.
- **Risks:** destroys useful raw protocol evidence, still cannot decide stale
  order after partial messages, changes raw entities and diagnostics, and
  couples routing to formulas.
- **Decision:** reject. It violates the canonical raw-state and ownership
  guardrails.

## 13. Preferred minimal fix

Candidate B is the smallest fix that satisfies the full contract requested for
P4.1. Candidate A is mechanically smaller but does not distinguish current from
stale live data and therefore leaves a predictable mirror-image defect.

The implementation PR should remain narrow:

1. `CoordinatorRuntimeState` owns only receipt metadata for two semantic
   candidate families; no duplicate power value is introduced.
2. Known live routes record/clear live evidence only when an on-grid directional
   field is actually observed and validated.
3. Type 106 records snapshot evidence only when its relevant pair is observed
   and validated.
4. A pure selector resolves one `net/source` decision from raw cache plus that
   evidence, using the existing 60-second inclusive preference.
5. `calculate_energy_flow()` consumes that explicit decision; the home,
   battery, grid and anomaly formulas remain unchanged.
6. `_grid_net_from_system()` and its characterized host-magnitude policy remain
   untouched.

This needs a small state-contract extension, not a new state owner. It should
not add polling, tasks, diagnostics state, persistence or field-level freshness
for unrelated protocol data.

## 14. Regression test plan

### Core regression

- route Type 106 `gridIn/out=300/0` at `t0`;
- route Type 2 `in/outOngrid=0/0` plus current CT import `300` at `t0+11`;
- assert selected on-grid source is live and net is zero;
- assert grid `300`, home `300`, battery `0`;
- register real main entities and assert fan-out exposes those values.

### Direction and expiry matrix

- Type 106 -> live zero: live wins immediately.
- Live non-zero -> Type 106 inside 60 seconds: live remains selected.
- Live -> newly received Type 106 at exactly 60 seconds: live remains selected,
  matching the inclusive current policy.
- Live -> newly received Type 106 after 60 seconds: Type 106 wins.
- Older Type 106 -> newer live: live wins regardless of magnitude.
- A suppressed snapshot does not activate later without a new snapshot.

### Missing, invalid and recovery

- missing/null live differs from explicit zero and falls back;
- malformed, boolean and non-finite live samples do not establish evidence;
- stale non-zero -> live zero -> later live non-zero recovers on both transitions;
- only Type 106 at startup remains supported;
- zero and non-zero partial-direction cases preserve the established absent
  opposite-direction default.

### No behavior drift

- existing non-zero live scenarios retain values;
- PV, EPS, battery/stack same-key Type-106 protection is unchanged;
- CT/collector/system grid-source priority is unchanged;
- the existing `_grid_net_from_system()` magnitude characterization remains
  unchanged;
- entity IDs, availability and raw diagnostic entities are unchanged.

At least one test must use `_handle_message()` and real `JackerySensor` fan-out;
direct selector tests alone are insufficient.

## 15. Golden fixture candidate

The first high-value sanitized hardware fixture would capture one standby entry
and recovery cycle:

1. Type 101 membership for a meter, if needed to establish the child;
2. a current Type 102 or accepted meter update showing whole-site import;
3. Type 106 with a non-zero grid alias;
4. approximately 11 seconds later, Type 2/25 live on-grid zero;
5. the next Type-106 response showing whether the snapshot converges;
6. a later live non-zero recovery transition.

Preserve message types, relative receipt intervals, relevant numeric directions
and structural location. Replace host and child serials with stable fixture
aliases; remove token, topic, event/message IDs, absolute timestamps, firmware
metadata, network/Wi-Fi fields and unrelated unknown values. Do not publish a
raw capture.

Playback should assert raw cache preservation, candidate source/provenance,
grid/home/battery derived values, entity fan-out, availability and recovery.
The fixture must record hardware model and firmware provenance separately
without customer identifiers.

## 16. Architecture guardrails

The preferred design passes the Phase-3 guardrails:

- `CoordinatorRuntimeState` remains the single owner of runtime receipt
  evidence.
- Raw protocol values remain intact; selected/derived state does not replace
  them.
- Freshness is explicit metadata, not inferred from magnitude or key presence.
- Source priority is a small named contract and uses the existing local receipt
  timebase.
- Routing order and exception behavior remain unchanged.
- The calculation layer stays HA-independent and accepts an explicit decision.
- Diagnostics and Protocol Discovery gain no operational authority or reverse
  dependency.
- No global state, task, persistence, network operation or generic formula
  redesign is introduced.
- IDs, registry relationships, translations, availability and HTTP/MQTT
  isolation remain outside the change.

Candidate A conflicts with the freshness guardrail unless permanent live-field
authority is explicitly accepted as protocol policy. Candidate C conflicts with
raw-state preservation and is rejected.

## 17. Open questions

The following questions should be answered by hardware evidence where possible,
but do not prevent a bounded software fix for the reproduced sequence:

1. Do all supported firmwares emit both live directions together, or can the
   pair be updated one direction at a time?
2. Can Type 2/25 live on-grid reports stop while Type 106 and unrelated host
   traffic continue, and is 60 seconds the correct shared preference window?
3. Are `inGridSidePw/outGridSidePw` ever the freshest on-grid-port source, or
   should their existing fallback position remain purely compatibility policy?
4. Which hardware families exhibit the observed standby sequence, and does the
   next Type-106 response always converge?
5. Should on-grid source metadata eventually become a safe diagnostics enum and
   age? That is useful observability, but it is not required for the P4.1 fix.
6. The separate `_grid_net_from_system()` stale-host-alias characterization is
   the same magnitude mechanism. It needs its own evidence and must not be
   changed incidentally in P4.1.

**Audit conclusion:** yes, the root cause and required state transitions are
understood well enough to implement a narrow, regression-first P4.1 fix. The
fix should use bounded receipt evidence rather than copy the upstream strict
presence rule blindly.
