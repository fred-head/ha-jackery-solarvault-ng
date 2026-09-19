# Phase 0/1 analysis report

**The baseline is established; no architectural refactor or feature port was performed.** Community/development commit: `183d74b7e042061ccb985ddc023b3cb7a085452e`; Official commit: `af97223ff17fc8f14314cbc6da7213a5eee7004d`. Both upstream main branches were verified against remote HEADs. Analysis date: 2026-09-11 UTC. [Repository/environment baseline](baseline.md).

## Deliverables

| File | Purpose |
| --- | --- |
| [baseline.md](baseline.md) | SHAs, remotes, releases, versions, evidence conventions |
| [baseline-test-results.md](baseline-test-results.md) | Exact checks, results, classifications and reproducible probes |
| [current-capability-inventory.md](current-capability-inventory.md) | Devices, supported groups, controls, availability and HTTP |
| [mqtt-protocol-inventory.md](mqtt-protocol-inventory.md) | Types, shapes, cache effects and every action publish path |
| [entity-inventory.md](entity-inventory.md) | Every sensor definition, all controls, metadata, IDs and migration |
| [test-coverage-map.md](test-coverage-map.md) | Behavior map, ranked gaps and complete 174-test source index |
| [upstream-feature-matrix.md](upstream-feature-matrix.md) | Scoped SAME/COMMUNITY_ONLY/OFFICIAL_ONLY/DIFFERENT/UNKNOWN comparison |
| [upstream-port-candidates.md](upstream-port-candidates.md) | Per-behavior assessment; nothing ported |
| [refactor-map.md](refactor-map.md) | Responsibilities, callers, shared state, tests and extraction risk |
| [architecture-plan.md](architecture-plan.md) | Minimal staged target modules and data ownership |
| [refactoring-roadmap.md](refactoring-roadmap.md) | Small phases, invariants, tests, acceptance and rollback |
| [diagnostics-plan.md](diagnostics-plan.md) | Historical Phase 0/1 proposal; now redirects to the binding [Phase 3 diagnostics architecture](diagnostics-architecture.md) |
| [logging-plan.md](logging-plan.md) | Existing weaknesses, levels, context and noise control |
| [phase-0-1-report.md](phase-0-1-report.md) | This review entry point |

Six supporting evidence files are in [baseline-evidence](baseline-evidence/): pytest, Ruff, mypy-with-HA, mypy-lint-only, translations and exact-SHA upstream CI job/step results. Existing docs, production files, tests and AGENTS.md were not edited.

## Validation outcome

- Full suite: **174 passed**, **60.78%** statement coverage; 50% configured threshold passed. Initial sandbox runs stalled in teardown; unchanged suite passed outside sandbox in 2.98 seconds.
- Ruff and de/en/fr translation completeness: **passed**.
- Mypy: **passed in CI-style lint-only environment**; **23 existing findings with HA installed**. Both outcomes are retained, not presented as an unqualified green type baseline.
- Local HACS/Hassfest attempts: **blocked by missing Docker**. Both validators passed in the inspected upstream CI run at the exact community SHA; this is historical evidence, not a newly executed fork validation.
- Shell syntax and documentation/source consistency checks: passed. No production behavior changed; no tests changed; no upstream merge occurred.

## Strengths and community behavior worth preserving

The community has explicit synthetic regressions for whole-stack battery power, phase-balanced home consumption and nonnegative clamping, partial CT/plug cache preservation, key aliases, selected zero values and ID migrations. Per-entry coordinators and host-based main IDs support multiple main devices. Sensor metadata scales energy consistently and provides translated names.

Community-only behavior includes 19-entity devType3 SmartMeter handling (HTO907A and README-tested Shelly Pro 3EM), HTO910A collector cache/entities/grid fallback, BP2500 type23 energy retention, optional 16-sensor HTTP telemetry, work-mode/force-charge/follow-meter controls, optimistic cache patches, and type106 overwrite protection. Some are well-tested; HTTP, collectors and actual discovery are not. Hardware-test claims come from upstream README/comments, not hardware exercised here.

Official adds useful guardrails: correctly ordered host heartbeat filtering, literal main-SN type23 support, host-scoped metadata, child main-SN exclusion, broader generic child routing, coordinator plug guards, host-specific topics, and periodic child availability ownership. Its generic CT types expose additional phase fields. It also has incompatible full-list replacement, IDs, battery/source formulas and home-power branches; these must not be transplanted wholesale.

## Five highest-risk areas

1. **MQTT/HTTP fan-out and lifecycle.** HTTP sensors register in `_sensors` but lack `_update_from_coordinator`; next MQTT distribution raises. Both upstreams discard MQTT unsubscribe callbacks. Optional HTTP and reload have no direct test coverage.
2. **Freshness and availability.** Foreign-SN traffic refreshes C heartbeat; malformed traffic can suppress the reauth hint. Child metadata refreshes last-seen while old measurements survive, and entity updates can undo the stale flag. Missing-device deletion operates on a retained cache.
3. **Energy source meaning and precedence.** Raw main battery vs calculated whole stack, unit AC port vs public grid, first CT vs collector/system, empty CT and contradictory zero totals, plus 106 protected fields that can freeze on repeated snapshots. Official formulas produce different results on existing community regressions.
4. **Identity migration and multi-instance children.** Destructive orphan/residue cleanup is only partly tested; collector/numeric/lowercase child IDs are not protected by the existing heuristic. Official child/main_ formats conflict with C migration and could fragment history.
5. **Protocol routing, classification and commands.** Main-SN type23 loss, child metadata contamination, multiple inconsistent classification paths, subtype label ambiguity and untested outgoing envelopes. Command confirmation semantics remain unknown.

These risks are traceable to exact functions in the inventories and to the small reproducible probes in the check report. They are not introduced by this documentation.

## Recommended implementation work

**First task:** add a regression exercising an HTTP sensor registered alongside MQTT entities, then fix only the dispatch mismatch in a small bugfix PR. Verify subsequent MQTT updates reach all intended recipients and HTTP measurements retain their independent health behavior. Do not begin transport extraction in the same PR.

Next add the HIGH regression scenarios in the test map, especially two-host heartbeat/availability, complete migration snapshots, 106 ordering and collector/Shelly/whole-stack fixtures. Separate correctness changes from structural extraction and keep raw/history contracts intact.

**First refactoring PR:** extract pure payload normalization/flat helpers into protocol/normalization.py with old-path re-exports. **Second refactoring PR:** extract energy calculation helpers into calculations/energy_flow.py, preserving wrapper, input mutation and all state results. Normalization first avoids a calculation→sensor import. Subsequent parser, transport and coordinator phases follow the reversible roadmap.

## Unresolved protocol questions

Whether type101 is complete authoritative membership per query/firmware; correct interpretation of subtype across CT/Shelly/HTO models; phase-total zero vs contradictory phases; measurement freshness during cloud mode; meaning and cadence of 106 power snapshots; soc average/BMS semantics; type23 host forms; whether body.cmd107 reliably acknowledges writes and how messageId/eventId correlate; safe generic-message child handling. No invented command, polling probe against a real device or firmware assumption was used to resolve these.

## Do not change yet

- Do not rename entities, change unique IDs/device identifiers or copy Official migration formats without complete before/after registry evidence.
- Do not replace total battery/home/grid calculations or source precedence with Official rules. Preserve raw values and separate physical boundaries.
- Do not remove children on empty/partial type101 reports until membership semantics are established across actual devices.
- Do not collapse all devType/subType rules into a speculative hardware taxonomy; retain Shelly type3, HTO collectors and expansion handling independently.
- Do not treat MQTT publish as execution acknowledgement, add retries with unknown command idempotency, or expose speculative writable fields.
- Do not promote HTTP into grid fallback or interpret metadata-only cloud messages as fresh measurements without a tested source policy.
- Do not claim all-model hardware support or HA 2024.1 compatibility from one synthetic HA 2026.2.3 suite.

The current phase ends here for review. Broader AGENTS.md implementation milestones (ports, diagnostics endpoint, decomposition, new fixtures) remain **future work**, as required by the user's explicit Phase 0/1-only restriction.
