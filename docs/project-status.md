# Project status

SolarVault NG is an experimental, local-first Home Assistant integration under
active development. The maintained development branch is
`refactor/v3-foundation`; this page was created from foundation
`abe5201e93a46c39ae10f5b4bc7c9ee544fa7974`.

This is the public status entry point, not a second roadmap. The linked audits
and architecture documents remain authoritative.

| Status | Area | Summary |
| --- | --- | --- |
| Done | Foundation modernization | Phase 1/2 separated calculations, protocol normalization and routing, device classification, runtime state, commands, transports, discovery, and entity concerns while preserving compatibility. |
| Done | Phase 3 | Privacy-bounded Home Assistant diagnostics and opt-in, memory-only structural protocol discovery are complete. |
| Done | P4.1 correctness | Receipt-time arbitration now preserves a newer explicit live on-grid zero over an older Type-106 alias. |
| Done | Upstream audit | 10 Community and 43 Official delta commits were classified semantically; no upstream code was imported. |
| Current | High-confidence upstream ports | Three small candidates are ready for separate regression-first review: reject the host serial in child arrays, accept top-level host firmware metadata, and isolate type-100 child-poll failures. None is implemented yet. |
| Next | Release and lifecycle hardening | After the focused ports, likely work includes the release/upgrade contract, reauthentication and options reload, and real MQTT reconnect behavior. This order remains a maintainer decision. |

## Recently completed

- **Foundation refactoring (P1/P2):** cohesive pure and transport layers replaced
  much of the original `sensor.py` monolith. See the
  [refactoring roadmap](refactoring-roadmap.md) and
  [architecture](architecture.md).
- **Diagnostics and protocol discovery (P3.1-P3.5):** the diagnostics contract,
  passive observations, HA adapter, adversarial hardening, and opt-in structural
  discovery are complete. See the
  [diagnostics architecture](diagnostics-architecture.md).
- **Standby/live-zero correctness (P4.1):** the bounded, timestamp-aware fix is
  merged with focused regressions. See the
  [P4.1 audit](p4-standby-live-zero-audit.md) and
  [energy-source policy](energy-source-policy.md).
- **Best-of-both-worlds audit:** current Community and Official deltas are
  classified into port, adaptation, evidence, investigation, superseded, and
  no-action groups. See the
  [upstream delta audit](upstream-best-of-both-worlds-audit.md).

## Next

The immediate candidates are the three Group-A changes from the upstream audit.
Each should remain a separate, regression-first PR adapted to NG's architecture:

1. Prevent the configured host from entering child arrays, freshness, discovery,
   or registry state.
2. Accept host firmware metadata from the validated top-level envelope form with
   explicit precedence and host ownership.
3. Attempt every type-100 child category when one category publish fails, while
   preserving order, pacing, and cancellation behavior.

Release/compatibility hardening and lifecycle work are the likely following
tracks. The [Phase 3 closeout and Phase 4 decision basis](phase3-closeout-phase4-plan.md)
contains the decision matrix; this page does not select a full Phase 4 roadmap.

## Needs hardware evidence

| Topic | What is known | What is missing |
| --- | --- | --- |
| Ability bits 9/11 | Community code gates two writable controls by these bits. | Cross-model and cross-firmware evidence, including policy for absent or unknown capability data. |
| `wps` storm warning | Community exposes a read-only enum. | Local MQTT observations that establish meaning, cadence, and supported hardware. |
| Generic devType 2/4 phase behavior | Official exposes richer phase data for generic CT families. | Sanitized fixtures proving field casing, direction, scaling, and stable entity policy per subtype. |
| Type-101 unbinding | Official treats category arrays as authoritative replacements; NG preserves partial reports. | Firmware evidence that distinguishes complete membership snapshots from partial or empty reports. |
| CT/system formula variants | Official and NG use different source and fallback policies. | Synchronized physical measurements before changing `_grid_net_from_system()` or related formulas. |
| Golden fixtures and soak tests | Synthetic coverage is broad. | Sanitized hardware traces, a model/firmware matrix, broker/device reconnect runs, and multi-day reload/unload tests. |

Protocol discovery can help characterize safe structure, but it does not certify
hardware or automatically enable new devices.

## Investigation backlog

- Dynamic host-model labels and model changes after setup.
- Coordinator-level plug communication-mode enforcement; optimistic plug state
  and command acknowledgement/telemetry ordering remain separate concerns.
- Whether a supported YAML import path is actually needed.
- Deterministic precedence when top-level and body firmware values disagree.
- The separately deferred `_grid_net_from_system()` alias/source policy.
- Maintainability work such as removing the proven-unused `use_cts` fallback,
  correcting stale `maxOutPw` comments, narrowing coordinator APIs, and reducing
  remaining HA/coordinator coupling. These are tracked in the
  [Phase 4 decision basis](phase3-closeout-phase4-plan.md), not promoted to
  immediate feature work here.

## Production and release readiness

The integration has strong synthetic regression coverage, but broad production
recommendation still needs evidence and policy work:

- define the NG release, versioning, support, and upgrade/migration contract;
- complete and exercise the reauthentication lifecycle;
- apply options predictably through reload and prove partial-setup behavior;
- validate real MQTT disconnect/reconnect and long-running lifecycle behavior;
- test the declared Home Assistant version range;
- establish sanitized golden fixtures and a hardware/firmware matrix;
- decide whether command acknowledgement, timeout, and rollback warrant a
  dedicated workstream.

These are not all declared release blockers. Their impact and tradeoffs are
classified in the existing [decision matrix](phase3-closeout-phase4-plan.md#13-decision-matrix).

## Deferred and separate research

Cloud-independent onboarding and broader protocol/provisioning research remain
separate research tracks. They are not part of current production-readiness
work, and no private reverse-engineering details belong in this public status.

## Architecture guardrails

- Keep one authoritative owner for each runtime state.
- Keep transport, protocol, calculation, and Home Assistant concerns separated.
- Preserve the diagnostics allowlist, aliases, size bound, and privacy boundary.
- Keep protocol discovery opt-in, read-only, bounded, and memory-only.
- Keep child identity host-bound and migration conflict-safe.
- Determine freshness from accepted evidence rather than cache presence.
- Do not introduce global mutable runtime state.

See the [architecture](architecture.md),
[diagnostics architecture](diagnostics-architecture.md), and
[Phase 4 guardrails](phase3-closeout-phase4-plan.md#14-architecture-guardrails-for-phase-4)
for the full contracts.

## Key documents

| Topic | Authoritative detail |
| --- | --- |
| Architecture and extraction history | [Architecture](architecture.md), [refactoring roadmap](refactoring-roadmap.md) |
| Phase 3 and Phase 4 decision basis | [Phase 3 closeout](phase3-closeout-phase4-plan.md) |
| Diagnostics and structural discovery | [Diagnostics architecture](diagnostics-architecture.md) |
| P4.1 live-zero behavior | [P4.1 audit](p4-standby-live-zero-audit.md), [energy-source policy](energy-source-policy.md) |
| Upstream deltas and candidate groups | [Best-of-both-worlds audit](upstream-best-of-both-worlds-audit.md) |
| Test evidence and remaining blind spots | [Test coverage map](test-coverage-map.md) |
| User-facing capability and setup | [README](../README.md) |

