# Upstream synchronization ledger

## Type-23 canonical child serial hardening — 2026-09-14

Classification: local correctness fix (`FIX_NOW`); no upstream feature port.

Relevant: expansion-battery recognition already accepted `deviceSn` or `sn`,
but host routing and subsequent cache/freshness writes still used `deviceSn`
directly. An `sn`-only report was therefore merged as host data, while an empty
`deviceSn` plus valid `sn` created an empty child identity.

Ported as: no port. The coordinator now resolves the existing canonical serial
once and uses it consistently for Type-23 expansion cache, freshness and
discovery. Existing `deviceSn` precedence and host routing remain intact.

Tests: direct serial precedence/malformed/host/cache/freshness/entity matrix and
Home Assistant registry identity across repeated reloads.

## Protocol/command audit — 2026-09-12

Fetched `upstream-official/main` at `af97223ff17fc8f14314cbc6da7213a5eee7004d`
and `upstream-community/main` at `183d74b7e042061ccb985ddc023b3cb7a085452e`.
Both remain equal to the Phase 0/1 source pins. No branch merge/cherry-pick or
bulk feature port was performed. Decisions are in
[the current feature matrix](upstream-feature-matrix.md).

Upstream commit: `12c2e7c` (present in the pinned Official source)

Repository: `Jackery-Official/jackery`

Classification: isolated correctness fix

Relevant: actual host serial in type23 statistics was not recognized locally.

Already implemented: no; the regression failed on foundation `016f849`.

Ported as: local type23 main-branch condition includes configured host SN.

Tests: `test_23_host_statistics_and_metadata`, host/topic matrix; expansion
null/identity/freshness regression suites retained.

Notes: a later local hardening fixes empty `deviceSn` only when a valid fallback
`sn` identifies an expansion battery. A lone empty serial and
collector-statistics routing remain deferred.
Source: [Official handler at audited SHA](https://github.com/Jackery-Official/jackery/blob/af97223ff17fc8f14314cbc6da7213a5eee7004d/custom_components/jackery/sensor.py#L1149).

Upstream commit: `d0e0c9f` (present in the pinned Official source)

Repository: `Jackery-Official/jackery`

Classification: isolated host-metadata ownership fix

Relevant: type23/101/102 child metadata could overwrite host firmware/model locally.

Already implemented: no; three child-message cases failed on foundation `016f849`.

Ported as: capture only selected host message types with missing/system/host deviceSn.

Tests: `test_child_metadata_cannot_contaminate_host`,
`test_only_host_body_metadata_updates_registry`, invalid-model conversion case.

Notes: preserve local first-valid numeric model and body-only firmware semantics;
do not port Official model table, registry identifiers or metadata replacement.
Source: [Official metadata guard at audited SHA](https://github.com/Jackery-Official/jackery/blob/af97223ff17fc8f14314cbc6da7213a5eee7004d/custom_components/jackery/sensor.py#L1124).

Malformed child structures, unknown automatic plug creation and invalid control
telemetry guards are independently reproduced local hardening, not upstream ports.
