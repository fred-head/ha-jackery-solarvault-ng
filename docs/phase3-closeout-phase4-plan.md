# Phase 3 closeout and Phase 4 decision basis

Audit date: **2026-09-20**. Accepted foundation:
`2158a531be9790aa77ad234e9a4dbd52f6434ac8` on
`refactor/v3-foundation`.

This document is a technical closeout of P3.1 through P3.5 and a decision basis
for a future Phase 4. It does not authorize or schedule Phase 4 work. Findings
come from the current source, tests, Git history and freshly fetched configured
upstreams. No production or test code was changed for this audit.

## 1. Executive summary

SolarVault NG now has a substantially safer foundation than the community
v2.4.0 tree from which the modernization started. Protocol normalization,
routing, commands, device classification, energy calculations, MQTT mechanics,
HTTP request mechanics, runtime state, child membership decisions and
diagnostics have explicit boundaries. Multi-entry identity, migration,
freshness, MQTT unload/reload and SmartMeter replacement have extensive
regression coverage. Phase 3 adds a bounded, privacy-first Home Assistant
diagnostics endpoint and an opt-in, memory-only structural protocol discovery
mode without raw capture.

The current foundation is technically strong under synthetic tests: **1,442
tests pass with 96.09% statement coverage**, both mypy environments pass, and
Ruff, translations, compile and whitespace checks pass. This is not equivalent
to broad production proof. The suite has no recorded hardware fixtures, no live
broker or device run, and no SolarVault NG production soak. The README correctly
continues to describe the project as experimental.

Three issues should be resolved before a broad production recommendation:

1. The current calculation still reproduces the community v2.4.2 standby case:
   with live `inOngridPw=0` and stale `gridInPw=300`,
   `_effective_ongrid_net()` selects `300` instead of the live zero. The newer
   community tree fixes this. It needs an independent regression-first review in
   the NG source policy, not a blind cherry-pick.
2. No NG hardware/golden-fixture matrix proves the supported combinations and
   long-running lifecycle behavior. Existing hardware statements are inherited
   reports, not validation performed on this foundation.
3. Release and upgrade identity are not yet coherent for a stable NG release:
   the manifest remains `2.4.0`, still points documentation and issues to the
   community repository, and advertises Home Assistant 2024.1 through HACS even
   though this foundation is tested against the locked 2026-era environment.

Phase 4 therefore has several legitimate directions. Production evidence and
lifecycle hardening have the clearest immediate effect on safe daily use.
Capability expansion, command confirmation and cloud-independent onboarding
can be valuable, but each depends on hardware or protocol evidence that the
repository does not currently contain.

## 2. Accepted foundation

The audit began with a clean tree. Local and
`origin/refactor/v3-foundation` both resolved to the accepted SHA with ahead and
behind counts of zero. The five Phase 3 merges form one linear first-parent
sequence:

| Phase | Implementation | Foundation merge | Result |
| --- | --- | --- | --- |
| P3.1 Diagnostics contract | `89ff4c8` | `fb4fbfe` / PR 27 | Pure nine-section snapshot, allowlist, aliases and size bound |
| P3.2 Passive observability | `60215f6` | `d1450a8` / PR 28 | Per-coordinator protocol/HTTP observation without authority |
| P3.3 HA diagnostics | `b99d357` | `f470738` / PR 29 | Config-entry endpoint and read-only HA aggregation |
| P3.4 Adversarial hardening | `8dd88f9` | `e9fabab` / PR 30 | Privacy, mutation, determinism and size stress |
| P3.5 Protocol discovery | `136a828` | `2158a53` / PR 31 | Opt-in bounded structural observations, disabled by default |

Freshly fetched comparison references at audit time are:

| Reference | SHA | Interpretation |
| --- | --- | --- |
| Community `csoscd/ha-solarvault` `main`, tag `v2.4.3` | `020b37010377ee858ec7c8336282e5b9a57bf591` | Advanced beyond the original common v2.4.0 baseline |
| Official `Jackery-Official/jackery` `main` | `af97223ff17fc8f14314cbc6da7213a5eee7004d` | Unchanged from the Phase 0/1 reference pin |
| Original common community baseline | `183d74b7e042061ccb985ddc023b3cb7a085452e` | Starting point for the NG modernization |

## 3. Current architecture snapshot

### 3.1 Ownership inventory

| Area | Owner | Responsibility and dependencies | Maturity | Residual risk or debt |
| --- | --- | --- | --- | --- |
| Topic/envelope routing | `protocol/routing.py` | Exact topic parse, envelope validation, flat-body boundary and immutable route decision; standard library plus normalization | Mature under direct and transition tests | Unknown/generic messages remain intentionally permissive; no ordering or correlation |
| Normalization | `protocol/normalization.py` | Fixed aliases and flat-payload recognition; standard library only | Mature | Phase-key casing and route-specific null semantics remain separate contracts |
| Protocol commands | `protocol/commands.py` | Pure action topic and six outbound envelope builders | Mature for wire construction | No execution acknowledgement, retry or correlation semantics |
| Route application | `JackeryDataCoordinator` in `sensor.py` | Applies route decisions, child merges, Type-23/106 effects, discovery and fan-out | Strongly tested but coupled | Main cache and child-array policy still require coordinator knowledge |
| Runtime cache/freshness | `CoordinatorRuntimeState` | Main cache, host/child clocks, Type-106 evidence and source provenance; HA-independent | Mature for documented policy | No per-field freshness; compatibility properties expose mutable internals |
| Energy calculation | `calculations/energy_flow.py` | Pure source selection and derived energy flow | Broad synthetic coverage | Current v2.4.2 standby source-priority gap; no golden physical scenarios |
| Device classification | `devices/classification.py` | Route-aware family/model classification and static plug filter | Mature for known matrix | Several paths are heuristic; no generic capability model or dynamic reclassification |
| Child membership | `ChildDiscoveryState` in `discovery.py` | Known/expansion membership and missing timers; no HA objects | Unit-tested | Merged-cache semantics prevent ordinary empty/omitted reports from proving unbinding |
| MQTT transport | `transport/mqtt.py` | HA subscribe, publish, JSON and owned unsubscribe handles | Mature for mocked HA lifecycle | Broker connectivity/reconnect is delegated to HA and not exercised against a broker |
| MQTT lifecycle policy | Coordinator plus integration setup/unload | Locking, task start/stop, poll cadence and failure cleanup | Strong mocked lifecycle coverage | No live broker disconnect/reconnect or long-running soak evidence |
| SmartMeter HTTP request | `transport/smartmeter_http.py` | URL, timeout, request, status/JSON and numeric allowlist | Mature under synthetic transport tests | Target is an MQTT-learned private IP; no hardware/network matrix |
| SmartMeter HTTP policy | Coordinator | Target selection, cadence, failure threshold, replacement, entities and availability | Strong synthetic coverage | State/policy remains coordinator-coupled; options need reload to take effect reliably |
| Config and options flow | `config_flow.py` | Validates host/token input, prevents duplicate hosts, updates reauth tokens and stores HTTP/discovery options | Basic paths and option persistence tested | No update listener applies option changes automatically; complete reauth journey is unproven |
| HA setup and migration | `__init__.py`, `child_migration.py`, `identity.py` | Config validation, platform order, host/child registry migration and guarded cleanup | Extensive HA registry tests | Real exported registry snapshots and release-to-release upgrade runs are absent |
| Entity definitions | `entities/sensor_definitions.py` and platform modules | Static metadata and HA entities; pure transforms separated | Stable compatibility surface | Entities and tests still consume coordinator private fields; `sensor.py` owns entity classes |
| Reauthentication | Coordinator trigger plus `config_flow.py` | Type-123/401 and silence trigger, token update and reload helper | Basic path exists | Completion, removed-entry, repeat-trigger and token-rejection flows lack end-to-end coverage |
| P3.1 snapshot | `diagnostics_snapshot.py` | Versioned allowlist, aliases, JSON normalization and 64-KiB fail-closed budget | Adversarially hardened | Large explicit schema must be deliberately versioned when extended |
| P3.2 observation | `diagnostics_observation.py` | Fixed bounded route/error and HTTP observations | Mature and read-only | Broker connectivity and command outcomes deliberately remain unknown |
| P3.3 HA adapter | `diagnostics.py`, `diagnostics_adapter.py` | Entry-scoped read-only aggregation and HA endpoint | Strong privacy/side-effect tests | Adapter is large because it explicitly maps owners; do not replace with generic dumping |
| P3.5 discovery | `protocol_discovery.py` plus one coordinator hook | Per-coordinator bounded structural observation | Experimental developer feature, well bounded | First-observed retention is order-dependent after overflow by design |

### 3.2 Dependency direction

The pure layers are now one-way dependencies:

```text
Home Assistant setup/platforms
        -> coordinator orchestration
        -> protocol / calculation / classification / state decisions
        -> HA MQTT and aiohttp transport boundaries

HA diagnostics endpoint
        -> read-only diagnostics adapter
        -> explicit P3.1 input records
        -> pure P3.1 snapshot builder
```

The pure calculation, normalization, routing, command, classification,
coordinator-state, observation and protocol-discovery modules do not import Home
Assistant. The MQTT transport intentionally imports HA's MQTT API. Sensor
definitions import HA metadata types but no coordinator. The most visible
remaining reverse dependency is that platform modules and dynamic child entity
construction depend on `sensor.py`'s coordinator and entity classes.

### 3.3 Historical documentation status

Older documents remain valuable evidence but not every statement describes the
current foundation:

| Document | Current status |
| --- | --- |
| `docs/diagnostics-architecture.md` | Current normative Phase 3 contract; P3.1-P3.5 are implemented |
| `docs/architecture.md`, `docs/coordinator-state.md`, `docs/entity-boundaries.md` | Current implemented Phase 2 boundaries, with deliberately retained coupling |
| `docs/refactoring-roadmap.md` | Extraction history remains valid; Phase 0/1 baseline language is historical and Phase 4 is not selected |
| `docs/test-coverage-map.md` | Top chronology is current; the old behavior/gap table and 174-test index are Phase 0/1 evidence and are now labelled historical |
| `docs/phase-0-1-report.md`, `docs/baseline-test-results.md` | Historical baseline. HTTP dispatch, heartbeat filtering, Type-106, identity and MQTT lifecycle findings were subsequently fixed |
| `docs/current-capability-inventory.md` | Mixed historical/current inventory. Its opening classification matrix is useful; old line references and the stated HTTP dispatch/unsubscribe/heartbeat defects are superseded |
| `docs/multi-instance-identity.md` | PR2A/PR2B sections at the top are current; the later proposed, unimplemented historical section is superseded by the completed migration work |
| `docs/protocol-routing-commands.md`, `docs/energy-source-policy.md` | Current executable contracts where later follow-up notes explicitly supersede diagnostic baseline behavior |
| `docs/diagnostics-plan.md` | Explicitly superseded |
| `docs/logging-plan.md` | Design proposal; not implemented |

The Phase 0/1 five highest-risk areas now classify as follows:

| Original risk | Current disposition |
| --- | --- |
| HTTP listener breaks MQTT fan-out | Resolved with capability dispatch and mutation-safe iteration |
| Foreign/malformed traffic refreshes host; child stale values revive | Host defect and stale fan-out resolved; authoritative unbinding and per-field freshness remain open |
| Cross-entry child identity and unsafe migration | Resolved with host-scoped identities, preflight and conflict-safe migration under synthetic HA tests |
| Subscription leaks and failed-start cleanup | Resolved with transport-owned handles, serialized lifecycle and setup unwind tests |
| Type-106/source/routing uncertainty | Repeated snapshots and source freshness fixed and extracted; some firmware semantics and golden evidence remain open |

## 4. Capabilities after P1-P3

The current code supports the following behavior; this list is a software
contract, not a hardware certification:

- Config-entry setup for a host serial, token and topic prefix, with duplicate
  host prevention and malformed restored-config rejection.
- Entry-scoped MQTT status/event subscriptions and periodic local action polls.
- Exact host/topic ownership, JSON/envelope validation and handling for message
  types 2, 23, 25, 101, 102, 106, 107 and 123, plus the documented generic route.
- Seventy-five static main sensor definitions, five main switches, five numbers,
  two selects and one reboot button.
- Dynamic child groups: two plug sensors plus switch, two legacy CT sensors,
  nineteen devType-3 SmartMeter sensors, five collector sensors and two
  expansion-battery energy sensors.
- Sixteen optional local HTO907A HTTP measurement sensors with independent
  failure/recovery and replacement handling.
- Tested host-scoped child identities, guarded migration, multi-entry isolation,
  unload/reload cleanup, main/child freshness and source fallback.
- Exact construction of established main, child and poll commands. Publication
  success is not treated as device execution confirmation.
- Home Assistant config-entry diagnostics with nine stable root sections,
  snapshot-local aliases, entry-scoped registry aggregates and a hard 64-KiB
  UTF-8 JSON budget.
- Optional protocol discovery with bounded numeric/type/structure buckets,
  memory-only lifecycle and no raw field names or unknown scalar values.

The code does not provide cloud-free provisioning, SmartMeter pairing, BLE
bootstrap, schedules/tariff configuration, command acknowledgement tracking,
automatic support for unknown hardware, raw protocol capture or persistent
protocol discovery history.

## 5. Major improvements versus the earlier foundation

### 5.1 Measurable change

| Measure | Community v2.4.0 baseline | Accepted foundation | Meaning |
| --- | ---: | ---: | --- |
| Tests | 174 | 1,442 | Much broader behavior and failure-path characterization |
| Statement coverage | 60.78% | 96.09% | Stronger executed-code coverage, not hardware proof |
| Production Python modules | 7 | 30 | Cohesive protocol/state/transport/diagnostics boundaries exist |
| `sensor.py` lines | 2,913 | 1,789 | 1,124 lines removed from the monolith; orchestration/entities still remain |
| HA-aware mypy findings | 23 | 0 | Metadata and restored-config boundaries now type-check in the HA environment |
| Diagnostics endpoint | None | Config-entry diagnostics | Privacy-bounded support artifact available |

### 5.2 Concrete technical improvements

- **State ownership:** cache, host/child freshness, Type-106 evidence and source
  provenance moved into `CoordinatorRuntimeState`; compatibility properties are
  views of that owner rather than a second copy.
- **Routing clarity:** topic/envelope parsing and route decisions are pure.
  Coordinator order remains visible: validate ownership, parse, record activity,
  optionally observe, apply route, calculate, discover and fan out.
- **Transport lifecycle:** every MQTT unsubscribe handle is owned and released;
  partial startup, cancellation, repeated stop/restart and platform failure have
  direct regressions. HTTP request mechanics are separately testable.
- **Identity safety:** child identities are host-scoped. Migration pauses on
  ambiguous/shared/foreign records rather than deleting or guessing.
- **Freshness and availability:** foreign/malformed traffic no longer keeps a
  host alive; child freshness is per serial; stale cached fan-out cannot revive
  MQTT entities; HTTP health remains independent.
- **SmartMeter lifecycle:** HTTP sensors no longer break MQTT dispatch, meter
  replacement creates the right per-serial set, and old sources are retired.
- **Protocol robustness:** malformed arrays, serials, numeric control telemetry,
  unhashable `devType`, canonical plug aliases and Type-23 serial fallback have
  explicit regression coverage.
- **Energy/source behavior:** repeated Type-106 snapshots update after the live
  preference window; explicit zero is preserved; stale or measurement-less
  meter sources fall back; source decisions are observable.
- **Testability and typing:** pure modules have direct tests, HA registry and
  lifecycle tests use actual HA helpers, and both CI-style and HA-aware mypy pass.
- **Diagnostics/privacy:** the export begins with an allowlist, not a generic
  redactor. Canary tests cover pre-redaction and final output, mutable owner
  snapshots, multi-entry isolation and deterministic size limits.
- **Protocol discovery:** unknown structures can be counted without retaining
  raw payloads, keys or scalar values and without altering routing.

Claims that cannot be made from repository evidence are equally important:
there is no quantified runtime performance comparison, no long-duration broker
test, no new hardware certification and no proof that every inherited control
works across firmware variants.

## 6. Comparison with the current community and official references

### 6.1 Community fork

The project and `upstream-community/main` share the v2.4.0 ancestor
`183d74b`. The community tree is now v2.4.3 at `020b370`, so comparisons must be
dated to this audit rather than treating the original pin as current.

| Concern | NG foundation | Community v2.4.3 at audit time |
| --- | --- | --- |
| Architecture | Extracted protocol, calculation, state, discovery, transport and diagnostics layers | Primarily platform files with a large `sensor.py` |
| Robustness fixes from v2.4.1 | Equivalent or stricter local fixes exist for dispatch, host validation, malformed children, lifecycle, Type-106, Type-23 and SmartMeter replacement | Consolidated those fixes into v2.4.1 |
| Standby home-power fix | Not present; current helper reproduces the stale `gridInPw` priority case | Fixed in v2.4.2 by preferring present live `inOngridPw/outOngridPw` |
| Capability gating | Main controls remain created without `ability` suppression | v2.4.3 gates Force Charge and `maxOutPw` by capability bits |
| Storm warning field | Not exposed | v2.4.3 exposes `wps` as a read-only enum |
| Identity/migration | Host-scoped child identity and conflict-safe preflight | Does not contain the NG migration architecture |
| Diagnostics/discovery | P3 endpoint plus opt-in structural discovery | No equivalent P3 contract or endpoint |
| Tests | 40 test modules, 1,442 cases | Much smaller inherited suite plus v2.4.3 cases |
| Typing | CI and HA-aware environments pass | Current source was not revalidated in the NG HA-aware audit |
| CI | pytest, Ruff, mypy, translations, HACS and Hassfest workflow | Same broad workflow family |

The v2.4.2 change is a concrete correctness candidate. The v2.4.3 additions are
not automatically ports: capability-bit meaning and entity availability need
NG-specific compatibility and migration tests, and the cloud-controlled `wps`
field does not by itself improve local operation.

### 6.2 Official integration

The fetched official reference remains at the Phase 0/1 SHA. It continues to be
useful for message forms, device labels and protocol intent, but has no checked-in
test suite and differs in entity identity, source formulas, polling and
classification. Previously selected host-Type-23 and host-metadata guards are
already represented locally. Future comparison is worthwhile for newly observed
hardware, capability fields and protocol forms, never as a branch merge or
feature ranking.

## 7. Current production-readiness gaps

### Blocking before a broad production recommendation

| Finding | Evidence and effect |
| --- | --- |
| No NG hardware/golden validation | Every protocol playback is synthetic. Inherited reports exist, but this exact foundation has no device/broker soak or sanitized trace corpus |
| Known current upstream correctness delta | The v2.4.2 standby scenario is reproducible in NG and can make derived home power collapse toward zero when a stale Type-106 alias has larger magnitude |
| Release/upgrade contract not finalized | Manifest remains 2.4.0 and points at the community docs/issues; NG HACS/HA compatibility and upgrade path have not been declared and exercised as a release |

These block a general recommendation, not controlled developer testing.

### Important hardening

| Finding | Current evidence |
| --- | --- |
| Options reload | The options flow stores values but no update listener guarantees reload; HTTP and protocol discovery are read when a coordinator is constructed |
| Reauth completion | Trigger and token-update helper exist, but there is no full flow/reload/rejection/removed-entry regression |
| MQTT reconnect | HA owns reconnect behavior, but tests use an in-memory subscription model rather than an actual broker loss/recovery |
| Command failure semantics | Optimistic controls retain tentative cache/UI values after publish errors; no acknowledgement, timeout or rollback exists |
| Child unbinding/stale registry cleanup | Partial-merge semantics preserve children; empty/omitted Type-101 is not authoritative, so normal cache-fed reconciliation rarely proves removal |
| Supported HA range | Tests target the locked current environment; the advertised HACS minimum 2024.1.0 is not covered by a compatibility matrix |
| Capability gates | Current entities may expose controls unsupported by a device; community v2.4.3 supplies evidence but local policy is not decided |

### Useful improvement

- Truthful broker-connectivity diagnostics if HA exposes a stable entry-scoped
  signal; subscription-handle count must not be relabelled as connectivity.
- Transition-oriented, redacted and rate-limited logging from the existing
  unimplemented logging plan.
- Explicit release notes and support boundaries per tested hardware/firmware.
- A documented policy for old orphan entities and dynamic family changes that
  preserves history and never guesses registry ownership.

### Developer and maintainability

- `sensor.py` still owns coordinator policy and three entity classes. Platform
  code and tests use many private fields; an audit count found 331 direct
  `coordinator._...` references and 883 private-attribute references in tests.
  These numbers are coupling signals, not defects.
- The CI coverage floor remains 50%, far below the observed 96.09%, so CI would
  permit a large silent coverage regression.
- Diagnostics adapter and snapshot modules are intentionally explicit but large;
  future changes require schema discipline rather than generic abstraction.
- Historical comments and compatibility surfaces remain and should only be
  removed under an explicit support policy.

### Experimental or future

- New device types inferred from P3.5 observations.
- Command acknowledgement and protocol correlation requiring live evidence.
- Cloud-independent onboarding, BLE provisioning or SmartMeter pairing research.

## 8. Technical debt inventory

| Debt item | Current status | Phase 4 relevance |
| --- | --- | --- |
| Complete reauth workflow | Trigger/form exist; completion and failure lifecycle unproven | High for production hardening |
| `use_cts` constructor fallback | No production or test caller passes it; retained as an internal legacy fallback | Low-risk cleanup only after compatibility search |
| `maxOutPw` comments | `number.py` still says it moved to a select; sensor definitions mention a removed `JackeryMaxFeedInSelect` | Documentation/comment cleanup, no behavior change |
| Narrow coordinator APIs | Entities read `_data_cache`, identity, source and listener internals directly | High architectural leverage, medium/high regression risk |
| HA/coordinator coupling | Dynamic child entities, registry removal, HTTP policy and callbacks remain in `sensor.py` | Valuable only in small behavior-preserving slices |
| Hardware golden fixtures | No fixture directory or recorded sanitized payload corpus exists | High production evidence value; needs hardware contributors |
| Options application | No deterministic automatic reload hook | Small focused lifecycle candidate |
| Stale child cleanup | Membership owner exists, but cache merge is not an authoritative membership snapshot | Requires protocol evidence before behavior change |
| Command optimism | No pending-command owner, ack semantics or rollback | Separate protocol/hardware workstream |
| Compatibility aliases | Coordinator private properties re-expose the runtime owner; sensor definitions and helpers are re-exported | Intentional migration bridge; remove only with downstream policy |
| Old v2 migration paths | Obsolete-select and v2.0.1 residue cleanup still execute | Intentional until a minimum supported upgrade version is chosen |
| Logging plan | Proposed rate/privacy policy is unimplemented; some logs include serials or IPs | Useful independent hardening, especially for public bug reports |
| Project metadata | Manifest docs/issues and version still identify the community release line | Must be resolved for an NG release |
| Stale internal wording | P3.2 docstrings still refer to a “future” adapter although P3.3 exists | Low-priority source-comment cleanup; not changed by this audit |

No evidence was found that `CoordinatorRuntimeState` duplicates the cache: the
old coordinator names are compatibility views of the same objects. The old v2
migration paths are not dead code while upgrades from those releases remain in
scope. A repository-wide source/documentation search found no `TODO`, `FIXME` or
`HACK` markers; the debt above comes from executable behavior, tests, comments
and declared boundaries rather than marker collection.

## 9. Test and validation assessment

### 9.1 Strongly protected paths

- Pure normalization, routing, classification, commands and energy calculations.
- Ordered MQTT route transitions and cache/freshness effects.
- Type-106 live/snapshot arbitration and source fallback.
- MQTT subscribe/start/partial-failure/stop/reload and multi-entry isolation at
  the mocked HA boundary.
- SmartMeter HTTP decoding, failure threshold, recovery, target loss and
  replacement.
- Host/child identity migration, conflicts, interruption recovery and registry
  isolation using Home Assistant registries.
- Main/child availability and HTTP/MQTT health isolation.
- P3 diagnostics privacy, size, mutation, determinism, partial state and side
  effects.
- Protocol discovery bounds, disabled equivalence, privacy and reload reset.

### 9.2 Primarily unit-tested or simulated paths

- MQTT transport tests use mocked HA subscription/publication; no Mosquitto or
  reconnecting broker is involved.
- HTTP uses fake sessions/responses; no HTO907A endpoint is queried.
- Command tests prove bytes and local state transitions, not device execution.
- Energy and routing scenarios are synthetic dictionaries, not sanitized
  production traces.
- HA registry tests are substantial but use constructed registry states rather
  than exports from affected installations.

### 9.3 Blind spots hidden by 96.09% coverage

- Physical meaning and timing of fields across firmware versions.
- Device reconnect, broker restart, packet reordering and long outages.
- Complete options and reauth user journeys.
- HACS upgrade from a real community installation and rollback behavior.
- Home Assistant versions down to the advertised minimum.
- Authoritative child-unbinding semantics.
- Command rejection, delayed acknowledgement and contradictory telemetry.
- Performance and log volume during multi-day operation.

The suite also has high mock/fixture complexity around identity, diagnostics and
lifecycle. Many tests intentionally inspect private state to freeze behavior;
that is valuable for refactoring safety but makes API narrowing expensive. New
hardware fixtures should emphasize public route-to-entity outcomes rather than
copying that coupling.

## 10. Hardware and protocol readiness

| Hardware/path | Runtime implementation | Evidence level | Current claim limit |
| --- | --- | --- | --- |
| SolarVault 3 Pro Max | Main telemetry, derived flow and established controls | Inherited hardware reports plus broad synthetic NG tests | No NG full-firmware/hardware certification |
| SolarVault 3 | Generic main path and selected SOC behavior | Partial inherited report | Not an all-feature claim |
| Other SolarVault variants | Generic field-driven fallback | Little or no specific evidence | Heuristic compatibility only |
| HTO907A SmartMeter 3P | 19 MQTT sensors and optional 16 HTTP sensors | Inherited hardware report; synthetic full lifecycle | No current NG network/hardware run |
| Shelly Pro 3EM through Jackery | Same devType-3 MQTT group | Inherited hardware report; synthetic subtype-2 classification | No direct Shelly RPC transport |
| HTO910A D0 reader | Collector cache, five entities and grid fallback | Synthetic tests only | Software path, not hardware-certified |
| BP2500 | Two cumulative Type-23 energy sensors | Synthetic identity/freshness/entity tests | No per-battery power/SOC support |
| Smart Plug | Power, energy and guarded switch | Synthetic routing/entity/command tests | No live command acknowledgement proof |
| Generic CT devType 2/4 | Subtype-based selected phase/total fields | Synthetic compatibility path | Named subtype labels are not hardware support claims |
| Unknown hardware | Cache tolerance plus optional structural discovery | Privacy-bounded observation only | No automatic classification, entities or control |

Protocol discovery improves the evidence collection toolchain but does not
convert observations into device support. A hardware claim requires sanitized
fixtures, scaling/units, lifecycle and preferably real command evidence.

## 11. Cloud-dependency boundary

### Fully local at runtime

- Home Assistant receives and publishes through its configured MQTT broker.
- Routing, cache, calculations, entities, availability and diagnostics execute
  locally.
- Optional SmartMeter HTTP measurement calls use the meter's local IP and no
  cloud API.
- Protocol discovery is memory-only and performs no network operation beyond
  observing already accepted local MQTT messages.

### Still dependent on Jackery onboarding or cloud behavior

- The Jackery app is currently required to configure the device's MQTT broker
  and obtain the serial/token used by the integration.
- SmartMeter pairing/provisioning and recovery from cloud communication mode are
  not implemented locally.
- Tariff schedules, AI strategy details and some settings remain app/cloud-only.
- A device may switch SmartMeter communication to cloud mode, at which point
  local measurement fields can disappear even though the integration remains
  local.

There is no Jackery cloud API client in the runtime. The cloud boundary is
primarily bootstrap, pairing and features whose local commands are unknown, not
an ongoing integration-side telemetry dependency. Future cloud-independent work
would require separate research into provisioning, credentials/certificates,
BLE/bootstrap and pairing. None belongs in ordinary production hardening, and
private reverse-engineering findings must not be copied into public docs.

## 12. Candidate Phase 4 workstreams

These candidates are alternatives or composable tracks, not a selected roadmap.

### 12.1 Production evidence and release hardening

- **Problem:** a known standby calculation delta exists; release/version/support
  metadata and the HA compatibility claim are not aligned with NG.
- **Practical benefit:** removes known correctness uncertainty and creates a
  supportable installation/upgrade target.
- **Architecture:** calculation policy, manifest/release metadata, CI matrix and
  documentation.
- **Risk/size:** medium risk, medium scope; formula/source changes require strict
  regression isolation.
- **Prerequisites:** reproduce community v2.4.2 sequences in NG, decide supported
  HA versions, select release/version policy.
- **Hardware:** strongly desirable for standby validation; not required for
  metadata/CI work.
- **Possible PRs:** standby regression and fix; community v2.4.3 delta decision;
  HA version matrix; NG release metadata/docs.
- **Acceptance:** live-zero source priority is explicit; all historical energy
  scenarios pass; declared HA versions pass CI; manifest/support links/version
  identify the intended release; clean upgrade and rollback instructions exist.

### 12.2 Reauth, options and connection lifecycle completion

- **Problem:** options application and reauth completion are only partly covered;
  reconnect behavior is delegated to HA without broker-level evidence.
- **Practical benefit:** fewer manual reloads and more predictable recovery from
  credential, broker and HA lifecycle events.
- **Architecture:** config/options flow, setup update listener, coordinator
  lifecycle, HA MQTT integration boundary.
- **Risk/size:** medium risk, medium scope.
- **Prerequisites:** decide automatic reload semantics and identify a stable HA
  broker/connectivity test surface.
- **Hardware:** no for flow/reload; a local test broker is enough for reconnect;
  device helpful for token rejection.
- **Possible PRs:** options reload; completed reauth flow; broker restart harness;
  truthful connectivity diagnostics only after evidence.
- **Acceptance:** one reload per effective option change, no duplicate tasks or
  subscriptions, token update recovers or reports failure, removed entries do
  not start flows, broker restart restores one delivery path per entry.

### 12.3 Compatibility and migration qualification

- **Problem:** synthetic migration coverage is strong, but real community-fork
  registry snapshots, HACS upgrades and supported rollback windows are absent.
- **Practical benefit:** protects recorder history, custom names, disabled state
  and device cards for existing users.
- **Architecture:** identity, registry migration, config-entry versioning and
  release process.
- **Risk/size:** high regression impact, medium scope.
- **Prerequisites:** anonymized registry exports and an explicit oldest-supported
  version policy.
- **Hardware:** no; representative HA backups/registry fixtures are needed.
- **Possible PRs:** fixture format; v1/v2 snapshot playback; upgrade matrix;
  retirement policy for obsolete cleanup.
- **Acceptance:** before/after registry snapshots preserve IDs/settings/history,
  ambiguous ownership never mutates, interrupted upgrades resume, rollback
  limitations are documented.

### 12.4 Hardware golden fixtures and soak validation

- **Problem:** synthetic coverage cannot prove wire forms, scaling, cadence or
  firmware-specific behavior.
- **Practical benefit:** turns inherited support claims into reproducible NG
  evidence and lowers risk for every later protocol change.
- **Architecture:** test fixtures and scenario playback; production changes are
  not required initially.
- **Risk/size:** low code risk, medium/high collection effort.
- **Prerequisites:** hardware contributors, redaction rules and capture provenance.
- **Hardware:** yes, or sanitized captures from trusted users.
- **Possible PRs:** fixture schema/redactor guidance; one model per PR; startup,
  steady-state, grid flow, child loss/recovery and reload scenarios.
- **Acceptance:** fixtures contain no identifiers/secrets; playback asserts
  normalized cache, sources, entities and availability; each hardware claim cites
  a fixture/firmware/provenance level.

### 12.5 Command reliability and outcome tracking

- **Problem:** publish success is not device execution; optimistic controls can
  remain tentative after failure or absent telemetry.
- **Practical benefit:** clearer failures and safer writable entities.
- **Architecture:** command manager/state, protocol correlation and entity state
  policy.
- **Risk/size:** high risk, high scope.
- **Prerequisites:** hardware evidence for cmd107/message IDs and per-command
  confirmation semantics.
- **Hardware:** yes.
- **Possible PRs:** evidence/contract only; passive outcome observation; one
  command family; bounded timeout/rollback; diagnostics integration.
- **Acceptance:** sent/pending/confirmed/failed meanings are explicit, no false
  confirmation from unrelated telemetry, reload clears pending state, publish
  and rejection paths are tested on hardware-backed fixtures.

### 12.6 Capability model and hardware expansion

- **Problem:** entities are largely static; community v2.4.3 demonstrates
  capability-bit gates, while unknown types remain unsupported.
- **Practical benefit:** hides unsupported controls and enables evidence-based
  additions without model conditionals scattered across platforms.
- **Architecture:** classification/capability model, entity creation and migration.
- **Risk/size:** medium/high risk, medium/high scope.
- **Prerequisites:** capability-bit meaning by hardware/firmware and entity
  migration/default-visibility policy.
- **Hardware:** yes for capability claims.
- **Possible PRs:** v2.4.3 comparison tests; read-only capability mapping;
  gate one existing control; add one proven hardware family separately.
- **Acceptance:** absent capability cannot expose a writable control, unknown bits
  do not remove established entities, identity/history remain stable, every new
  capability has fixture evidence.

### 12.7 Coordinator API narrowing and focused debt cleanup

- **Problem:** entity classes and tests depend on coordinator internals; stale
  compatibility code/comments obscure current ownership.
- **Practical benefit:** easier later maintenance and smaller regression surface.
- **Architecture:** coordinator read APIs, entity adapters and retained migration
  shims.
- **Risk/size:** medium regression risk, divisible scope.
- **Prerequisites:** classify external compatibility surfaces and retain current
  entity identity/value tests.
- **Hardware:** no for mechanical API moves; golden fixtures improve confidence.
- **Possible PRs:** immutable/read-only cache views; child entity construction
  boundary; remove proven-dead `use_cts`; comment/docs cleanup; logging as its own
  behavior-neutral PR.
- **Acceptance:** no ID/value/timing change, dependency tests prevent reverse
  imports, private access falls measurably, one cohesive concern per PR.

### 12.8 Cloud-independent onboarding research

- **Problem:** broker provisioning, tokens and pairing still depend on the app.
- **Practical benefit:** possible operation without cloud-assisted bootstrap.
- **Architecture:** currently unknown; must remain outside the stable runtime
  until protocol and security boundaries are established.
- **Risk/size:** high risk, high and uncertain scope.
- **Prerequisites:** legal/security review, dedicated hardware, reproducible public
  evidence and separation from user credentials.
- **Hardware:** mandatory.
- **Possible PRs:** public research questions and isolated tooling policy before
  any production code; no raw secret capture or speculative commands.
- **Acceptance:** cannot be defined responsibly from current evidence. This is a
  reason to defer implementation, not to guess.

## 13. Decision matrix

Qualitative ratings describe the current evidence. “High” regression risk or
complexity is a warning, not a negative score.

| Workstream | User impact | Production-readiness impact | Regression risk | Complexity | Hardware dependency | RE dependency | Architectural leverage | Testability |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Production evidence/release | High: correct energy and install path | High | Medium | Medium | Medium | Low | Medium | High except physical confirmation |
| Reauth/options/reconnect | High during failures/config changes | High | Medium | Medium | Low/medium | Low | Medium | High with local broker/HA |
| Compatibility/migration | High for existing users | High | High | Medium | Low | Low | Medium | High with registry fixtures |
| Golden fixtures/soak | Indirect but broad | High | Low | Medium/high effort | High | Low | High | High once captures exist |
| Command outcomes | High for controls | Medium/high | High | High | High | High | High | Medium until semantics known |
| Capability/hardware expansion | Medium/high for affected models | Medium | Medium/high | Medium/high | High | Medium | High | Medium/high with fixtures |
| Coordinator/API debt | Low immediate user impact | Low/medium | Medium | Medium | Low | Low | High | High synthetically |
| Cloud-independent research | Potentially high | Low for current runtime | High | High/unknown | High | High | Unknown | Low initially |

### 13.1 What each strategic direction solves

| Direction | Solves | Does not solve | Missing prerequisite / likely effect |
| --- | --- | --- | --- |
| A. Production hardening first | Known calculation delta, release clarity, lifecycle evidence, operational confidence | New devices or cloud onboarding | Hardware/upgrade evidence; strongest near-term user trust effect |
| B. Technical debt first | Coupling, stale shims/comments, future change cost | Real-device uncertainty or command semantics | Compatibility policy; mainly maintainer benefit |
| C. Hardware/capabilities first | Unsupported devices and capability-gated UI | Upgrade/reconnect/release gaps | Captures and hardware; visible feature benefit with higher compatibility risk |
| D. Command/transport reliability first | Failure recovery and trustworthy controls | Device coverage or provisioning | Broker/hardware evidence and acknowledgement semantics |
| E. Cloud independence first | App/bootstrap dependency if research succeeds | Current release/migration and known runtime gaps | Major RE/security effort; uncertain benefit timeline |

The repository evidence supports choosing A, or pairing A with the test-only
parts of hardware fixtures, before high-uncertainty feature work. That is an
audit conclusion, not an approved Phase 4 roadmap.

## 14. Architecture guardrails for Phase 4

1. **One authoritative owner per state.** Do not reintroduce copied caches,
   freshness maps or global discovery/diagnostics state.
2. **P3 privacy boundary remains allowlist-first.** No raw cache, payload,
   registry object, state attributes, unknown keys/values or generic object dump
   may enter diagnostics.
3. **Protocol discovery remains read-only and opt-in.** It must never route,
   classify, create entities, persist observations or rescue malformed traffic.
4. **Child physical identity remains host plus child serial.** Family/capability
   changes must not silently create duplicate devices or orphan history.
5. **Freshness is separate from cached value.** Metadata, diagnostics and HTTP
   health must not make stale MQTT measurements current.
6. **HTTP and MQTT health remain isolated.** Neither transport may overwrite the
   other's values, counters, availability or lifecycle.
7. **Routing order stays explicit.** Topic/host ownership, JSON and envelope
   validation precede activity and structural observation; operational route
   application remains independent of diagnostics.
8. **Expected external states are handled narrowly; programming errors remain
   visible.** No blanket exception suppression to make lifecycle or discovery
   appear healthy.
9. **No generic raw-cache export or logging.** Debuggability must use bounded,
   semantic fields and safe transition logs.
10. **No global mutable state.** Multi-entry isolation applies to runtime,
    commands, diagnostics, migrations and any future health model.
11. **Source priority, formulas, IDs and public entity behavior change only in
    dedicated regression-first PRs.** Refactoring is not permission to alter
    protocol policy.

## 15. Questions for maintainer decision

1. Should the first Phase 4 deliverable be a production/release hardening series,
   beginning with the v2.4.2 standby regression and a supported HA/release policy?
2. Which real hardware and firmware combinations can provide sanitized golden
   captures and a multi-day broker/reload soak?
3. How long must direct upgrades from historical community v1/v2 registry states
   remain supported, and what is the oldest supported rollback target?
4. Is reliable command outcome tracking important enough to justify a dedicated
   hardware-backed workstream before capability expansion?
5. Should cloud-independent onboarding remain a later research track until the
   current runtime has a stable NG release, or is dedicated hardware/research
   capacity available now?

## 16. Open unknowns

- Whether Type-101 lists are authoritative membership snapshots for every
  supported firmware, and therefore when child removal is safe.
- Exact cmd107/message-ID acknowledgement and rejection semantics.
- Which NG-supported devices exhibit the v2.4.2 standby sequence and how quickly
  sources transition in real traffic.
- Capability-bit stability across models/firmware and whether absent bits mean
  hidden, unsupported or merely unreported.
- Real ordering/cadence of Type-23/101/102/106/107 payloads for each hardware
  family.
- Broker reconnect behavior across supported Home Assistant/MQTT versions.
- The oldest Home Assistant version compatible with the current Python/API use.
- Which onboarding/pairing steps are cloud-runtime dependencies versus one-time
  bootstrap dependencies on current firmware.

These unknowns should become evidence-gathering tasks or explicit non-support
statements before they become production behavior changes.
