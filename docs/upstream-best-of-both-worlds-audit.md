# Best-of-both-worlds upstream delta audit

Original audit date: **2026-09-21**. Community v2.5.0 refresh:
**2026-09-26**. This is a read-only source audit. No upstream commit was merged,
cherry-picked or copied, and no production or test file was changed.

## 1. Executive summary

The three repositories form the GitHub fork chain requested for this audit:

```text
Jackery-Official/jackery
  -> csoscd/ha-solarvault
    -> fred-head/ha-jackery-solarvault-ng
```

Git history gives two useful comparison boundaries. Community and Official
share `1f122f2`; after that point Official has 43 commits and Community has 87.
NG and Community share Community v2.4.0 at `183d74b`; Community has 11 later
commits. The commit counts are inventory only. The refreshed conclusions compare
behavior against NG foundation `7a9c252`, not SHA presence.

All Community v2.4.1 and v2.4.2 correctness changes are already equivalent or
superseded in NG. In particular, NG's merged P4.1 implementation replaces the
Community v2.4.2 "live always first" change with receipt-time arbitration.
Community v2.4.3 adds ability-bit gates for two writable entities and the read-only `wps`
storm-warning field. Community v2.5.0 additionally subscribes to `/alert` and
fires a `jackery_alert` Home Assistant event. That event path is a new
evidence-gated capability candidate rather than a high-confidence port: payload
semantics, lifecycle behavior and a stable public event contract need validation
before an NG-native implementation. The v2.5.0 typing changes are already
superseded by NG, while its battery statements are Community-claimed firmware
evidence for later cross-checking, not an immediate behavior change.

Official contains no checked-in tests, but its post-fork history exposed three
high-confidence, narrowly testable gaps that have since been implemented in NG:

1. exclude the configured host serial from child arrays, not only point updates;
2. accept host firmware from the top-level `softver` envelope form as well as
   `body.softver`;
3. isolate each type-100 child poll so a failure for devType 2 does not skip
   devTypes 3 and 6.

These were completed as regression-first semantic ports, not cherry-picks, so
Group A is now complete. Other Official and Community differences need hardware
evidence or separate policy audits: authoritative Type-101 list
replacement, generic devType 2/4 phase entities, CT-zero/commState logic,
`otherLoadPw` fallback, dynamic host model labels, and optimistic plug state.
Official's battery/home formulas, five-second polling, noisy protocol logging,
historical identity formats and documentation/release commits should not be
ported.

The audit is sufficiently complete to plan isolated investigation and port PRs.
It does not approve any candidate.

## 2. Audit foundation

The audit began on a clean `refactor/v3-foundation`. All remotes were fetched
with pruning before comparison.

| Repository/reference | SHA | Date | Meaning |
| --- | --- | --- | --- |
| NG `refactor/v3-foundation` | `7a9c25284e3020a590b8c101cdb5ab57d38faaff` | 2026-09-26 | Accepted foundation including P1-P3, P4.1 and completed Group A |
| Community `upstream-community/main` | `77d218f6f531c1b5cd0b2ae5b9f2edfe0c61879c` | 2026-09-23 | Community v2.5.0 |
| Official `upstream-official/main` | `af97223ff17fc8f14314cbc6da7213a5eee7004d` | 2026-07-22 | Official v2.0.0 documentation head |

Local and `origin/refactor/v3-foundation` both resolved to the accepted NG SHA,
with ahead/behind `0/0`. The refresh branch is
`docs/community-v250-audit-refresh`. The already configured upstream remotes were
not added or modified, and no push was made to either upstream.

The current NG comparison includes these relevant architectural facts:

- pure routing, normalization, command, classification and calculation modules;
- coordinator-owned cache, freshness, Type-106 and on-grid receipt evidence;
- transport-owned MQTT unsubscribe handles and separate SmartMeter HTTP health;
- host-scoped child identity and guarded registry migration;
- P3 diagnostics allowlisting and opt-in, read-only protocol discovery;
- 1,491 passing tests after Group A with 96.13% total coverage.

## 3. Repository and fork topology

GitHub metadata reports:

| Repository | GitHub `fork` | Parent | Source |
| --- | --- | --- | --- |
| `Jackery-Official/jackery` | false | none | none |
| `csoscd/ha-solarvault` | true | `Jackery-Official/jackery` | `Jackery-Official/jackery` |
| `fred-head/ha-jackery-solarvault-ng` | true | `csoscd/ha-solarvault` | `Jackery-Official/jackery` |

GitHub's parent/source metadata describes repository ancestry. Git `merge-base`
describes the last commit actually shared by two current histories. The latter
is the correct boundary for a commit delta, while the former explains why the
repositories appear in one fork network.

The heads are not linear descendants of one another after their fork points:

| Comparison | Left-only commits | Right-only commits |
| --- | ---: | ---: |
| NG foundation vs Community head | 83 | 11 |
| Community head vs Official head | 87 | 43 |

## 4. Fork point A: Official to Community

`git merge-base upstream-community/main upstream-official/main` yields:

| Property | Value |
| --- | --- |
| SHA | `1f122f223513006a3a4511835758dd7a467d6b90` |
| Author date | 2026-05-06 18:13:13 +08:00 |
| Message | `1. Fix the issue of duplicate entity names; 2. Fix the issue of some entities being unavailable;` |
| Parent | `3b562b03713b7e96ecd025545eb995b93ee9e5bc` |

The commit is contained by both current histories. Community's first unique
commit after it is `a947e43` (SolarVault 3 Pro Max fields and SmartMeter 3P
handling); Official's first unique commit is `12c2e7c` (its broad v2 rewrite).
This is therefore a reproducible Git boundary even though GitHub represents
Community as a fork of Official at the repository level.

Everything before `1f122f2` is shared history and is excluded from the Official
delta. Everything after it on Official is audited below; later Community work is
used only for the three-way cross-check.

## 5. Fork point B: Community to NG

`git merge-base refactor/v3-foundation upstream-community/main` yields:

| Property | Value |
| --- | --- |
| SHA | `183d74b7e042061ccb985ddc023b3cb7a085452e` |
| Author date | 2026-08-14 14:35:52 +02:00 |
| Message | `feat: merge v2.4.0 - Options Flow + SmartMeter HTTP polling` |
| Tag | Community `v2.4.0` |

This commit is the head of NG's original `main` and is contained by both NG and
Community. NG modernization and Community v2.4.1-v2.5.0 then diverge. It is the
precise boundary for the 11-commit Community delta.

## 6. Community delta inventory

The following table covers every commit in
`183d74b..upstream-community/main`. “Files” omits no changed production/test or
documentation area, but compresses long paths to basenames.

| Commit | Date | Files | Topic and actual change | NG status | Primary classification | Follow-up |
| --- | --- | --- | --- | --- | --- | --- |
| [`276abfc`](https://github.com/csoscd/ha-solarvault/commit/276abfcca5f915ed2d090a1d569f3810987a05e1) | 2026-09-16 | `manifest.json`, `sensor.py` | Changes the static plug filter from set membership to `devType == 6`; tracks HTTP sensor creation per SmartMeter serial instead of one global Boolean. | NG has the same equality rule, malformed-value regressions and stronger per-serial replacement/registry tests. | Superseded by NG | None. |
| [`db01e86`](https://github.com/csoscd/ha-solarvault/commit/db01e86121cc61928a4a5c027c94a82caca1c6c0) | 2026-09-16 | `sensor.py` | Resolves Type-23 expansion identity from `deviceSn` or `sn` and uses it for cache/freshness/discovery. | NG resolves one canonical serial with precedence and tests `sn`-only, empty and conflicting forms. | Already equivalent | None. |
| [`0b49875`](https://github.com/csoscd/ha-solarvault/commit/0b49875181b96e9454542de15c83a7acf440fd15) | 2026-09-16 | `sensor.py`, `tests/conftest.py` | Replaces permanent Type-106 field locks with a 60-second last-live map for 11 same-key power fields. | NG owns the same policy in `CoordinatorRuntimeState`; P4.1 additionally handles cross-alias on-grid receipt evidence. | Superseded by NG | None. |
| [`9e8da40`](https://github.com/csoscd/ha-solarvault/commit/9e8da40a4e1dadae2d5e8fd159077ded85311326) | 2026-09-16 | `.gitignore`, `number.py`, `sensor.py`, `switch.py`, two tests | Exact topic matching, valid-envelope liveness, structural array filtering, safe serials/numbers, owned unsubscribe callbacks, listener cleanup and child routing hardening. | NG has pure topic/envelope routing, transport-owned lifecycle, mutation-safe fan-out, bounded child classification and broader failure tests. | Superseded by NG | Individual Community tests need no direct port; NG coverage is stricter. |
| [`6365bf8`](https://github.com/csoscd/ha-solarvault/commit/6365bf8cebd790889061168101d80d8c646d1632) | 2026-09-16 | `CHANGELOG.md`, `README.md` | Documents v2.4.1. | Release documentation for another repository. | Irrelevant | None. |
| [`f040e40`](https://github.com/csoscd/ha-solarvault/commit/f040e40cfd965e1de22e013e2acccb69d80a59e7) | 2026-09-16 | no content change | v2.4.1 release/tag marker. | No behavior. | Irrelevant | None. |
| [`f355df8`](https://github.com/csoscd/ha-solarvault/commit/f355df8ac13248d09bed57ed1e3775753fa83759) | 2026-09-16 | `sensor.py` | Adds an assertion to narrow canonical child serial type for mypy. | NG's helper and branch narrowing pass both CI and HA-aware mypy without this assertion. | Already equivalent | None. |
| [`082340e`](https://github.com/csoscd/ha-solarvault/commit/082340e3e49be76f9283f74054cbd3049bde120a) | 2026-09-17 | `CHANGELOG.md`, `README.md`, `manifest.json`, `sensor.py` | Fixes [Issue 21](https://github.com/csoscd/ha-solarvault/issues/21) by making present live on-grid aliases unconditionally outrank Type-106 aliases. | NG P4.1 uses bounded receipt-time arbitration, preserves valid live zero and still permits sufficiently newer Type-106 evidence. | Superseded by NG | Do not port the simpler “live always first” rule. |
| [`4c80715`](https://github.com/csoscd/ha-solarvault/commit/4c807156ce5dd9cc9d35b828f38571d7d3c7fc2c) | 2026-09-17 | no content change | v2.4.2 release/tag marker. | No behavior. | Irrelevant | None. |
| [`020b370`](https://github.com/csoscd/ha-solarvault/commit/020b37010377ee858ec7c8336282e5b9a57bf591) | 2026-09-18 | README, manifest, number/sensor/switch, strings, DE/EN/FR, `test_v243_changes.py` | Gates `maxOutPw` on ability bit 9 and `socForceChg` on bit 11; adds `wps` storm-warning enum. Tests prove field/config and bit arithmetic, not HA lifecycle or hardware semantics. | NG exposes raw `ability` but does not gate the controls and does not expose `wps`. | Needs hardware evidence | Split into a capability-policy audit and a separate read-only `wps` sensor proposal; test firmware variation and identity/availability behavior. |
| [`77d218f`](https://github.com/csoscd/ha-solarvault/commit/77d218f6f531c1b5cd0b2ae5b9f2edfe0c61879c) | 2026-09-23 | `.gitignore`, README, manifest, number/sensor/switch, `conftest.py`, `test_v250_alert.py` | Adds an `/alert` subscription and `jackery_alert` event for flat/wrapped payloads; adds type annotations and config/unique-ID guards; documents claimed battery/BP2500 firmware findings; releases Community v2.5.0. | NG has no alert capability, but its transport/lifecycle boundaries require an NG-native design and validated payload/event semantics. NG already supersedes the typing changes. Battery statements are upstream evidence only; release/repository metadata is not portable. | Investigate further | Validate public payload semantics and the HA event contract before any alert proposal; cross-check battery claims independently; do not port typing or release metadata. |

## 7. Community semantic classification

The Community delta contains no missing high-confidence production fix after
completed Group A. Its distribution by primary classification is:

| Classification | Commits | Conclusion |
| --- | --- | --- |
| Already equivalent | `db01e86`, `f355df8` | Same behavior exists in current architecture. |
| Superseded by NG | `276abfc`, `0b49875`, `9e8da40`, `082340e` | NG solves the same failure with broader ownership/tests. |
| Needs hardware evidence | `020b370` | Capability bit meanings and `wps` usefulness need firmware evidence. |
| Investigate further | `77d218f` | The alert capability needs payload/event-contract evidence; the same commit's other parts are separately superseded, evidence-only or irrelevant. |
| Irrelevant | `6365bf8`, `f040e40`, `4c80715` | Documentation or empty release markers only. |

The v2.4.3 tests contain one useful test idea: exercise availability transitions
of existing writable entities when capability data is absent, malformed, loses
a bit, gains a bit, or arrives after entity setup. The upstream tests only assert
dictionary configuration and bit extraction, so they are not sufficient as an
NG test-only port.

### 7.1 Community v2.5.0 component classification

| Component | Classification | Reason | Follow-up |
| --- | --- | --- | --- |
| `/alert` subscription and `jackery_alert` event | Investigate further / evidence-gated feature | This is a new NG capability. Community tests demonstrate flat/wrapped payload handling and SN filtering, but not stable field semantics, HA event compatibility or NG transport lifecycle integration. | Validate public payload examples and define a bounded event contract; any later port must use NG's MQTT transport/lifecycle boundaries. |
| mypy/type cleanup | Already equivalent / superseded by NG | NG is mypy-clean and has stronger typed metadata, entity and coordinator contracts. | No code or test port. |
| Battery/BP2500 documentation | Evidence cross-check; no immediate code port | Community documentation attributes `batInPw`/`batOutPw` to the main unit rather than individual expansion batteries, describes BP2500 SOC as combined, and attributes Type-23 `inEgy`/`outEgy` to an onboard Coulomb counter. NG has not independently verified these claims. | Compare against sanitized hardware evidence before changing sensors, formulas or support claims. |
| Version, `.gitignore` and repository documentation | Irrelevant / repository-specific | Community release numbering and local repository exclusions do not change NG behavior. | No action. |

The Community handler subscribes to `hb/device/{SN}/alert`, accepts both flat
and `{"body": {...}}` payloads, and maps `alertId` and `recordTs` plus optional
`status`, `startTs`, `endTs`, and `manual` values into its event. These are
observed Community implementation details, not an accepted NG event contract.

## 8. Official delta inventory

Official reused the same generic commit message for most work. The “actual
change” column therefore comes from each diff, not from its subject. This table
covers every commit in `1f122f2..upstream-official/main`.

| Commit | Date | Files | Topic and actual change | NG status | Primary classification | Follow-up |
| --- | --- | --- | --- | --- | --- | --- |
| [`12c2e7c`](https://github.com/Jackery-Official/jackery/commit/12c2e7cb53fe550dcb87aec903148430a38944cb) | 2026-06-03 | integration core: init, flow, 5 platforms, sensor, strings, zh-Hans | Large v2 foundation: multi-entry identity/migration, host-specific topics, reauth, button/select, host/child metadata, entity definitions and routing changes. | Community later adopted most behavior; NG supersedes identity, routing and lifecycle. Atomic residuals are tracked below rather than porting this umbrella diff. | Superseded by NG | Never cherry-pick; use only as provenance for atomic candidates. |
| [`165b1a1`](https://github.com/Jackery-Official/jackery/commit/165b1a11070b2f68224b51a1abc39fcfc678ed96) | 2026-06-08 | component README | Adjusts dashboard/entity examples. | Repository-specific docs. | Irrelevant | None. |
| [`c35993e`](https://github.com/Jackery-Official/jackery/commit/c35993ef4e0d4cfe94a9e1c6ed0d8b386159c51d) | 2026-06-09 | README, `sensor.py`, `switch.py`, card YAML | Adds normalization, flat forms, generic child array/point merge, Type-23/101/102/106/107 paths, sensor tables and availability behavior. | NG contains extracted and tested equivalents, plus Community-only hardware families. | Superseded by NG | Retain as protocol-reference evidence only. |
| [`f808672`](https://github.com/Jackery-Official/jackery/commit/f808672ef91ec704b5a7537d43b1b146591b7865) | 2026-06-09 | Lovelace YAML | Adds a dashboard example. | No integration behavior. | Irrelevant | None. |
| [`d1f4f68`](https://github.com/Jackery-Official/jackery/commit/d1f4f68f78fc1388e47dcb5b6a316b38b9382ff9) | 2026-06-09 | sensor/switch/dashboard | Adds deduplicated subdevice aggregation, coordinator plug lookup/control validation, optimistic plug cache/distribution and switch-state presentation. | NG has cache lookup and entity-level commMode blocking, but coordinator direct calls can bypass it; NG deliberately keeps telemetry-confirmed plug state. | Port with NG adaptation | Audit coordinator boundary guard separately; do not import optimistic state or source priority. |
| [`246517b`](https://github.com/Jackery-Official/jackery/commit/246517b117637e80ee380e3a4e23ad480cb46ffb) | 2026-06-09 | `sensor.py`, `switch.py` | Temporarily changes type-103 wire field and optimistic state from `sysSwitch` to `switchSta`. | Official later reverts this in `1f308bb`; NG command tests require `sysSwitch`. | Irrelevant | Do not port. |
| [`66b9a7f`](https://github.com/Jackery-Official/jackery/commit/66b9a7f4cdcb9f1fdc9de77e694ff7578d3271dd) | 2026-06-09 | README, sensor, switch | Defines commMode 1/2, blocks MQTT plug control for non-local/unknown modes, and exposes diagnostic attributes. | NG has the transforms, HA error and entity guard with tests. | Already equivalent | Coordinator boundary remains the narrower `d1f4f68` candidate. |
| [`8417002`](https://github.com/Jackery-Official/jackery/commit/8417002e832af08da9ef277b6522738dc31c3224) | 2026-06-09 | sensor/switch/dashboard | Makes coordinator cache authoritative for plug mode/state and routes toggle through the same guard. | NG has `get_plug_item()`, merged entity view and guarded toggle/on/off. | Already equivalent | None. |
| [`5a18d53`](https://github.com/Jackery-Official/jackery/commit/5a18d53b22ac4ac3e8a17f17ea40a06ca07e87ea) | 2026-06-09 | dashboard YAML | Removes a duplicate dashboard line. | No integration behavior. | Irrelevant | None. |
| [`ea97d10`](https://github.com/Jackery-Official/jackery/commit/ea97d10883867a09f11c4804ebf930939bd953f4) | 2026-06-09 | README, sensor, dashboard | Adds Type-105 polling/106 handling, workModel alias, low-power status, on-grid/CT/link enums, `otherLoadPw`, `maxFeedGrid` and `funcEnable`. | Community/NG already expose these fields, commands and enum/bit semantics, with translations and tests. | Already equivalent | None. |
| [`73b1d2f`](https://github.com/Jackery-Official/jackery/commit/73b1d2fcc08071d158af4610df7682882adb5761) | 2026-06-09 | `sensor.py` | Reworks power presence, prefers Type-106 battery values, adds grid fallbacks and uses `otherLoadPw` when calculated home is zero. | NG intentionally uses tested whole-stack energy balance and P4.1 evidence; `otherLoadPw` fallback can overwrite valid zero. | Needs hardware evidence | Separate energy-policy audit with synchronized meter captures; do not port formulas wholesale. |
| [`3af71fd`](https://github.com/Jackery-Official/jackery/commit/3af71fd84808efe2cd3cdaab4ef1b1ccda3813ab) | 2026-06-09 | sensor, dashboard | Adds magnitude-based multi-source selection plus CT zero/phase fallback and commState usability rules. | NG rejects magnitude as freshness and already fixed its stale-zero failure with receipt evidence. `_grid_net_from_system()` remains intentionally unresolved. | Needs hardware evidence | Use as a candidate scenario set only; never port `_pick_best_power_net()` globally. |
| [`c84c866`](https://github.com/Jackery-Official/jackery/commit/c84c86676af9d0d49acd83770bddeecc1d07e331) | 2026-06-09 | switch/dashboard | Adds a persistent notification when plug MQTT control is blocked. | NG has the same user-visible guard and notification. | Already equivalent | None. |
| [`e130143`](https://github.com/Jackery-Official/jackery/commit/e1301438eab2374b5e5c8e17facf6564c1da4bf4) | 2026-06-11 | manifest | Changes version to `2.0.0-beta.1`. | Official release metadata. | Irrelevant | None. |
| [`05a8ef8`](https://github.com/Jackery-Official/jackery/commit/05a8ef8317a83b9ad11c7c4ee4dbb96da94914d8) | 2026-06-11 | manifest | Adds an invalid JSON comment and changes version to `v2.0-beta`. | Invalid/transient release metadata, later reverted. | Irrelevant | Do not port. |
| [`5fe1159`](https://github.com/Jackery-Official/jackery/commit/5fe115910d962f2a5e296a858dcd70517eefe42c) | 2026-06-12 | init, manifest, sensor, switch | Host-prefixes child IDs and makes Type-101 devType 2/6 lists authoritative replacements. | NG supersedes identity/migration. Authoritative replacement conflicts with tested partial-merge preservation. | Investigate further | Determine per-firmware membership semantics before any unbinding change. |
| [`55bfb2b`](https://github.com/Jackery-Official/jackery/commit/55bfb2b2e900bbd27b24f9ae1647b7c37462400f) | 2026-06-12 | `sensor.py` | Restricts host metadata capture to message types 2/23/25/106/107. | NG routing encodes the same message-type gate. | Already equivalent | None. |
| [`ef69587`](https://github.com/Jackery-Official/jackery/commit/ef6958778a47797180e168c2125a4b3191658458) | 2026-06-12 | `sensor.py` | Removes missing children immediately from HA after authoritative Type-101 category reports. | NG cannot safely infer unbinding from merged/partial reports and uses guarded removal. | Needs hardware evidence | Pair with `5fe1159` membership audit and registry fixture before considering. |
| [`d0e0c9f`](https://github.com/Jackery-Official/jackery/commit/d0e0c9fb08aea2041e07ebf7158dd952e55a8cc8) | 2026-06-12 | `sensor.py` | Refines metadata capture to host/system/missing body serials, blocking child contamination. | NG uses `is_host_message_body()` after owned topic/envelope validation and has direct regressions. | Already equivalent | None. |
| [`a88befc`](https://github.com/Jackery-Official/jackery/commit/a88befc86b12be99a5f0d85cfc14ad917e1a8fab) | 2026-06-12 | six integration files | English comment/docstring translation only; no executable semantic change. | No behavior. | Irrelevant | None. |
| [`6315207`](https://github.com/Jackery-Official/jackery/commit/6315207d7df65a554da0cadb8fc018927a91ea7e) | 2026-06-16 | `sensor.py` | Excludes the main host serial from child arrays/aggregation and labels host deviceType 3 as DIY3. | NG rejects host/system in point updates but does not filter host serials while merging arrays. | Worth porting | Regression-first manual port at the array admission boundary; preserve all child families and identity rules. |
| [`90c4414`](https://github.com/Jackery-Official/jackery/commit/90c44144855c83519e8c2fafa57c6024ff827361) | 2026-06-18 | sensor, switch | Introduces per-child last-seen, periodic child expiry, Type-123/401 reauth and prevents entity update from reviving availability. | NG has a single runtime owner, explicit freshness, Type-123 route and broader availability/reload tests. | Superseded by NG | Reauth completion remains a separate lifecycle candidate, not a port of this commit. |
| [`38f9f67`](https://github.com/Jackery-Official/jackery/commit/38f9f679de7ea2507839d7982e7c1b4a583e3e81) | 2026-06-18 | `sensor.py` | Switches two visible grid sensors from live aliases to Type-106 `gridInPw/gridOutPw` and changes icons. | NG exposes raw source fields separately and calculates with explicit source policy; changing existing entity source would be compatibility drift. | Superseded by NG | Do not rename or repoint existing entities. |
| [`66799f5`](https://github.com/Jackery-Official/jackery/commit/66799f57cc7aba93cd8d8cfdbe3c2de0fd4d1fcb) | 2026-06-18 | `sensor.py` | Comments out duplicate calculated AC-socket power entities. | NG has distinct signed EPS/raw definitions and tested transforms. | Superseded by NG | None. |
| [`c7894d3`](https://github.com/Jackery-Official/jackery/commit/c7894d327188248c4288425643836c8136c78a34) | 2026-06-22 | `sensor.py` | Adds CT subtype labels, total/phase forward/reverse power and total energies for generic CT devices; replaces zero totals with phase sums. | NG's devType 3 group is richer, but generic devType 2/4 retains a smaller two-entity contract. Zero replacement is not accepted policy. | Needs hardware evidence | Validate field casing/scaling and entity-ID migration separately for each CT family. |
| [`1f308bb`](https://github.com/Jackery-Official/jackery/commit/1f308bb8ceda52556a5e9a2b7dc6750c2d5b0f47) | 2026-06-22 | `sensor.py` | Restores type-103 command wire field `sysSwitch` and patches both switch aliases optimistically. | NG builder emits `sysSwitch`; it intentionally does not treat publish as confirmation. | Already equivalent | Do not import optimistic cache mutation. |
| [`e1604e8`](https://github.com/Jackery-Official/jackery/commit/e1604e8a149a1bcad888bd8aaa133740fefab552) | 2026-06-24 | init and five platforms | Expands host-prefixed unique-ID migration and dual main-device identifiers/via-device links. | NG has host-scoped IDs plus conflict-safe preflight and deliberately avoids unsafe/shared ownership changes. | Superseded by NG | Do not cherry-pick identity formats. |
| [`3878b4b`](https://github.com/Jackery-Official/jackery/commit/3878b4b59a1ad4fd6d0d473d46f4993818b885b5) | 2026-06-25 | `number.py` | Adds dynamic SOC bounds, narrows maxOutPw, restores unavailable entities and optimistically updates numbers. | Community and NG already implement dynamic bounds and explicit optimistic policies. | Already equivalent | None. |
| [`8ac1b40`](https://github.com/Jackery-Official/jackery/commit/8ac1b405c66cf6c61496e56754c5dc89e052dcec) | 2026-07-03 | number, sensor | Adds immediate startup poll, type-2 read-all-settings request and separates publish catches by request/category. | NG has type-2, throttled 105 and an intentional cadence, but one failed child devType currently skips later devTypes in the batch. | Port with NG adaptation | Isolate each type-100 publish while preserving `[2,3,6]`, pacing and 30-second Type-105 policy. |
| [`aac1022`](https://github.com/Jackery-Official/jackery/commit/aac1022eb03d9e4fe4f6f316de94e5ad47ec4533) | 2026-07-17 | README, sensor, switch | Removes several entities/calculated values and renames grid/EPS/CT entities into a forward/reverse schema. | Would break NG entity/history contracts and discard Community-only calculations. | Irrelevant | Do not port. |
| [`fa62f3c`](https://github.com/Jackery-Official/jackery/commit/fa62f3c3689aa5c0dac2f5f59cb1dc0c3a2692b4) | 2026-07-17 | README, sensor | Separates `soc` from `batSoc`, adds average SOC and stops summing missing CT energies. | NG already exposes `soc` separately as BMS SOC and preserves its documented CT-family policies. | Already equivalent | No duplicate sensor. |
| [`e5b3edd`](https://github.com/Jackery-Official/jackery/commit/e5b3edd573a631add8386093d52ac4509de89270) | 2026-07-22 | HA entity-list doc | Adds an entity inventory. | Documentation for Official's schema. | Irrelevant | Use only as reference evidence. |
| [`5aa5e37`](https://github.com/Jackery-Official/jackery/commit/5aa5e37deabf3e8897ed190feef06c88aa0f27fb) | 2026-07-22 | root README | Rewrites install/use/dashboard documentation. | Repository-specific documentation. | Irrelevant | None. |
| [`a2af2fe`](https://github.com/Jackery-Official/jackery/commit/a2af2fe224e4a93e43ebe113911e58be139a72c6) | 2026-07-22 | four images | Adds installation screenshots. | No integration behavior. | Irrelevant | None. |
| [`383a641`](https://github.com/Jackery-Official/jackery/commit/383a6418ec334e6b742babc3776ad7b2855e3c04) | 2026-07-22 | README | Minor English wording changes. | No integration behavior. | Irrelevant | None. |
| [`a128ccf`](https://github.com/Jackery-Official/jackery/commit/a128ccf8af8fc7039c2528cc7ba83fec2800ca93) | 2026-07-22 | manifest | Publishes version `2.0.0`. | Official release metadata. | Irrelevant | None. |
| [`f372a36`](https://github.com/Jackery-Official/jackery/commit/f372a36f29f5d481fe2c0a2fc5503699573c8a15) | 2026-07-22 | README/image rename | Fixes a screenshot filename/reference. | No integration behavior. | Irrelevant | None. |
| [`99de53c`](https://github.com/Jackery-Official/jackery/commit/99de53cf1ef46dee17ba26c779e2b02f3383ec0d) | 2026-07-22 | dashboard setup doc | Adds dashboard import instructions. | No integration behavior. | Irrelevant | None. |
| [`89ba6e3`](https://github.com/Jackery-Official/jackery/commit/89ba6e3422d8a4666356bff408cc1f5ee6d7e44f) | 2026-07-22 | README | Corrects a dashboard layout phrase. | No integration behavior. | Irrelevant | None. |
| [`a7b89a7`](https://github.com/Jackery-Official/jackery/commit/a7b89a7923c240c908d1cf5536e80f07fbac9894) | 2026-07-22 | README | Rewords the same dashboard sentence. | No integration behavior. | Irrelevant | None. |
| [`137f521`](https://github.com/Jackery-Official/jackery/commit/137f5219888b3e29df6f314826255d001b2642dc) | 2026-07-22 | entity reference and dashboard docs | Adds entity-ID reference and revises dashboard examples. | Official naming only. | Irrelevant | None. |
| [`854aba6`](https://github.com/Jackery-Official/jackery/commit/854aba6e9a8e60ec4bb1eb08f6871ecfacad0c38) | 2026-07-22 | README | Minor dashboard wording. | No integration behavior. | Irrelevant | None. |
| [`af97223`](https://github.com/Jackery-Official/jackery/commit/af97223ff17fc8f14314cbc6da7213a5eee7004d) | 2026-07-22 | README | Final punctuation/wording adjustment. | No integration behavior. | Irrelevant | None. |

## 9. Official protocol and hardware findings

### 9.1 New protocol knowledge after fork point A

| Finding | Official evidence | Community/NG state | Assessment |
| --- | --- | --- | --- |
| Host-specific status/event subscriptions | `12c2e7c` | Community and NG subscribe to the configured host, with wildcard only when no host is known; NG owns unsubscribe handles. | Already equivalent. |
| Type-23 literal host serial | `12c2e7c` route semantics | NG accepts missing, `system`, or configured host serial and separately handles expansion serial aliases. | Already equivalent with tests. |
| Top-level or body `softver` | Final Official `_capture_device_meta()` | NG accepts `body.softver` first and top-level `softver` as a fallback. | Closed by A2; body-first precedence is the NG compatibility contract. |
| Host-only metadata | `55bfb2b`, `d0e0c9f` | NG route plus `is_host_message_body()` is stricter. | Superseded. |
| Child point/array updates outside 101/102 | `c35993e` | NG generic routes merge arrays/points and refresh children under an explicit route contract. | Already equivalent. |
| Main serial filtered from child arrays | `6315207` | NG point path rejects it; array path does not. | High-confidence correctness gap. |
| Type-101 category replacement/unbinding | `5fe1159`, `ef69587` | NG preserves partial reports by merge. | Unresolved firmware semantic difference. |
| Per-child receipt freshness | `90c4414` | NG runtime state owns host/child clocks and entity fan-out cannot refresh them. | Superseded. |
| Per-category poll error isolation | final Official poll loop, refactored in `8ac1b40` | NG isolates 25/2/105 but groups child 2/3/6 in one `try`. | High-confidence lifecycle gap. |

### 9.2 Hardware and entity knowledge

Official does not add a newer SolarVault Pro/Pro Max model-code table after the
fork point. It maps top-level host `deviceType` values 1-4 to generic labels and
defines CT subtype labels 1-7. Community later adds the richer field evidence:
Pro Max fields, BP2500, HTO910A, HTO907A, Shelly Pro 3EM and expansion energy.
NG inherits and tests those Community families.

Official's generic CT group is still potentially useful for devType 2/4:
forward/reverse total and per-phase power plus total energies. It is not hardware
proof. Official has no tests or checked-in recorded payloads, replaces explicit
zero totals with phase sums, and changed the entity schema later in the same
series. Any adoption needs one sanitized fixture per subtype, scaling evidence,
and an entity-ID/history plan.

Official's expanded host labels (`Battery Pack`, `CT/Meter Collector/Meter`,
`DIY3`, `Meter Collector`) should not be interpreted as supported main-device
families. NG currently labels only verified host type 3 as DIY3 and keeps a
generic fallback. A label-only change would overstate support.

### 9.3 Correctness knowledge that should not be copied mechanically

- Official's CT logic can replace an explicit total zero with a non-zero phase
  sum and accept non-zero data while `commState` is offline. This may help some
  firmware, but it conflicts with NG's explicit-zero and freshness guardrails.
- Official's magnitude chooser treats the largest absolute power as best. P4.1
  proves magnitude is not freshness.
- Official prefers `batInPw/batOutPw` over Community's tested whole-stack energy
  balance and can use `otherLoadPw` when calculated home is zero. Both alter
  established NG formulas and require hardware evidence.
- Official's category-replacement Type-101 path historically had a startup
  missing-key failure when CT data arrived before plugs. Any later membership
  audit must retain an ordering regression even if implementation differs.

## 10. Official vs Community vs NG cross-check

| Topic | Official | Community | NG | Status |
| --- | --- | --- | --- | --- |
| Exact host topics | Added after A | Adopted before v2.4.0 | Present plus owned cleanup | In all; NG independently hardened |
| MQTT unsubscribe lifecycle | No complete owned transport | v2.4.1 stores callbacks | Transport-owned, failure-safe | NG independently improved |
| Type-23 host and child serials | Host serial accepted | v2.4.1 adds `sn` fallback | Both with canonical precedence | In all; NG broader |
| Type-106 live preference | Snapshot overwrites/magnitude formulas | 60-second same-key; v2.4.2 live alias always first | 60-second same-key plus P4.1 cross-alias receipts | Three implementations; NG evidence model wins |
| Host metadata scope | Host-message guard; top/body firmware | Host guard adopted; body firmware | Host guard; body-first with top-level fallback | In NG after A2; NG preserves established precedence |
| Main SN in child arrays | Filtered | Not explicitly filtered in merged arrays | Shared array-admission filter | In NG after A1 |
| Type-101 membership | Category replacement and immediate removal | Partial merge/cache preservation | Partial merge plus guarded identity/removal | Unresolved semantic difference |
| Generic child routing | Broad arrays/points | Added through upstream sync/hardening | Pure routing plus bounded classifier | In all; NG extracted |
| Generic CT phase entities | Ten Official entities for type 2/4 | Two legacy type-2/4; 19 richer type-3 | Same Community families, centrally classified | Official-only for legacy CT; hardware evidence needed |
| HTO907A / Shelly / HTO910A | Generic/partial CT handling | Dedicated groups | Dedicated groups plus HTTP transport tests | Community + NG |
| Expansion batteries | No dedicated discovery/entities | BP2500 Type-23 energy | Canonical serial, host identity and lifecycle tests | Community + NG |
| Alert topic/event | Not present in audited delta | v2.5.0 `/alert` plus `jackery_alert` | Not implemented | Community-only candidate; validate payload and public event contract first |
| Battery firmware claims | No equivalent checked-in evidence | v2.5.0 documents main-unit power, combined SOC and Type-23 energy claims | Existing behavior remains evidence-based and unchanged | Community documentation evidence; independent cross-check required |
| Plug commMode guard | Entity and coordinator boundary | Entity-level port | Entity-level transformed helper | Coordinator boundary still differs |
| Plug optimistic state | Publish patches cache and fans out | Telemetry-priority behavior | Publish does not imply execution | Intentional policy conflict |
| Poll child failure isolation | Each devType isolated | One grouped child loop | Per-category isolation with preserved cadence | In NG after A3 |
| Reauth | Official HA API plus form | Flow/init heuristic | Same plus tests, incomplete end-to-end completion | Manual lifecycle hardening candidate |
| Ability-bit entity gating | No v2.4.3 mapping | Bits 9/11 gate two controls | Raw ability only | Community-only; validate hardware |
| Storm warning `wps` | Not exposed | Read-only enum | Not exposed | Community-only; low operational value |
| Diagnostics/privacy | None | None | Nine-section allowlist and hardened HA endpoint | NG-only |
| Protocol discovery | None | None | Opt-in, bounded, memory-only | NG-only |
| Tests | None checked in | Broad synthetic suite | 1,491 tests, HA and privacy layers | NG independently improved |

## 11. Candidate port groups

### Group A: completed high-confidence ports

#### A1. Reject the host serial in child arrays

- **Source:** Official `6315207`.
- **Gap:** NG rejects host/system point updates but array merge can cache the
  configured host as a child and later reach discovery.
- **NG modules:** `sensor.py` child array admission; routing tests and child
  identity/discovery tests.
- **Benefit:** prevents a phantom self-child and registry pollution.
- **Risk:** low/medium; must cover plugs, CTs and collectors without changing
  partial merge semantics.
- **Hardware dependency:** no for the invariant; fixture evidence is still useful.
- **Port style:** manual semantic port; do not cherry-pick.
- **Acceptance:** host and `system` never enter any child cache/freshness/member
  set; valid children remain unchanged; no entity or device is created; point
  and array behavior agree.
- **Suggested PR:** one regression-first correctness PR.
- **Implementation follow-up:** A1 was implemented manually in NG with
  regression-first coverage across established array aliases and the shared
  admission boundary. No upstream commit was cherry-picked, no hardware evidence
  is required for this identity invariant, and cleanup of historical registry
  records is intentionally outside this change.

#### A2. Accept top-level host firmware metadata

- **Source:** Official final metadata helper after `12c2e7c`/`d0e0c9f`.
- **Gap:** NG reads `body.softver` only, although the validated envelope may carry
  host `softver` at top level.
- **NG modules:** coordinator metadata adapter and protocol contract tests.
- **Benefit:** correct read-only device-registry firmware display.
- **Risk:** low if host ownership/message-type guard remains first.
- **Hardware dependency:** no for parsing; one real trace would raise confidence.
- **Port style:** manual semantic port.
- **Acceptance:** top-level and body forms work; body precedence is explicit;
  child/foreign/malformed messages cannot update host metadata; no ID change.
- **Suggested PR:** metadata-only PR, separate from model-label expansion.
- **Implementation follow-up:** A2 was adapted manually from the Official
  metadata helpers around `12c2e7c`/`d0e0c9f` and implemented regression-first
  without cherry-picking. Parsing semantics require no hardware evidence. NG
  deliberately retains body-first precedence for compatibility, and the
  existing host/message-type ownership gates remain authoritative.

#### A3. Isolate type-100 child poll failures

- **Source:** Official poll loop, consolidated in `8ac1b40`.
- **Gap:** NG's single `try` around `[2,3,6]` stops later child categories after
  the first publish failure.
- **NG modules:** coordinator polling orchestration; command-contract tests.
- **Benefit:** one unsupported or transient child category does not suppress
  SmartMeter or plug polling in the same cycle.
- **Risk:** low/medium; error count/log volume and 0.5-second pacing must remain
  deterministic.
- **Hardware dependency:** no.
- **Port style:** manual semantic port.
- **Acceptance:** every category is attempted once despite one failure; current
  25/2/105 cadence, `[2,3,6]` order, token/body and cancellation semantics stay
  unchanged.
- **Suggested PR:** one polling failure-isolation PR.
- **Implementation follow-up:** A3 was adapted manually from Official `8ac1b40`
  and implemented regression-first without cherry-picking. Publish failures are
  isolated per child category and require no hardware evidence; poll order,
  cadence, payloads and cancellation semantics remain unchanged.

### Group B: port with NG adaptation

#### B1. Coordinator-level plug commMode guard

- **Source:** Official `d1f4f68`, refined by `66b9a7f`/`8417002`.
- **Gap:** NG entities block non-local control, but direct coordinator callers do
  not enforce the same contract.
- **Benefit:** future services/callers cannot bypass a known safety boundary.
- **Risk:** medium; the current missing-host silent return and tests are public
  internal behavior, and cache lookup may be temporarily incomplete.
- **Hardware dependency:** low; existing commMode evidence is sufficient for an
  audit, but command hardware tests are desirable.
- **Port style:** manual semantic port; explicitly exclude optimistic cache writes.
- **Acceptance:** all callers share one type-safe gate; local mode still publishes;
  cloud/unknown mode never publishes; entity notification behavior is unchanged.
- **Implementation follow-up:** B1 was manually adapted for NG from Official
  `d1f4f68`, refined by `66b9a7f`/`8417002`, without cherry-picking. The
  coordinator uses its current `get_plug_item()` view and the existing pure
  `plug_mqtt_control_allowed()` policy immediately before Type-103 construction.
  Missing-host calls intentionally retain NG's warning-and-return contract;
  entity notifications, transport failures and telemetry-confirmed plug state are
  unchanged. No hardware evidence is required to enforce this command boundary.

#### B2. Reauth lifecycle completion/API alignment

- **Source:** Official `12c2e7c`/`90c4414` and current HA lifecycle pattern.
- **Gap:** NG trigger and token-update form exist, but completion, removed entry,
  repeated trigger and reload/rejection journeys remain incompletely tested.
- **Benefit:** predictable recovery from token rejection and silent startup.
- **Risk:** medium due HA API evolution and lifecycle races.
- **Hardware dependency:** no for flow mechanics; token rejection hardware helps.
- **Port style:** manual NG lifecycle work, not code transplant.
- **Acceptance:** exactly one flow, safe missing-entry behavior, successful update
  and reload, no post-unload trigger, programming errors remain visible.

### Group C: hardware validation first

#### C1. Ability bits 9/11 and `wps`

- **Source:** Community `020b370`, citing an app decompile and observed ability
  values; tests cover bit arithmetic only.
- **Gap:** NG exposes raw `ability` but neither gates `maxOutPw`/`socForceChg` nor
  exposes `wps`.
- **Benefit:** avoids unsupported writes; optionally exposes cloud storm state.
- **Risk:** medium/high compatibility risk if absent/unknown bits hide established
  entities or firmware semantics differ.
- **Hardware dependency:** yes, across firmware/models.
- **Port style:** manual capability-model port; `wps` should be a separate PR.
- **Acceptance:** unknown capability is an explicit policy; availability recovers;
  identities/history stay stable; command publication is gated at the command
  boundary; fixture evidence cites hardware/firmware.

#### C2. Generic devType 2/4 phase entities

- **Source:** Official `c7894d3`.
- **Gap:** NG exposes only legacy selected power/energy for generic CT, while
  devType 3 has the rich 19-entity group.
- **Benefit:** more useful phase telemetry for verified legacy meters.
- **Risk:** high entity/scaling/history risk.
- **Hardware dependency:** yes for every subtype claimed.
- **Port style:** manual capability/entity addition; never replace current IDs.
- **Acceptance:** sanitized fixtures prove casing, direction and scale; entity
  migration/default visibility is defined; explicit zero is preserved.

#### C3. Authoritative Type-101 membership/unbinding

- **Source:** Official `5fe1159`/`ef69587`.
- **Gap:** NG partial merges cannot infer ordinary unbinding or stale registry
  cleanup from empty/omitted arrays.
- **Benefit:** automatic cleanup after genuine device removal.
- **Risk:** high; treating partial/empty reports as authoritative can remove valid
  entities and history.
- **Hardware dependency:** mandatory across firmware and category poll forms.
- **Port style:** investigation and fixture first; do not cherry-pick.
- **Acceptance:** authoritative marker/cadence is proven, startup order is safe,
  partial reports preserve children, registry ownership is preflighted.

#### C4. CT/system fallback formula differences

- **Source:** Official `73b1d2f`, `3af71fd`, `c7894d3`.
- **Gap:** semantic differences exist, not an established NG defect.
- **Benefit:** may improve some firmware when totals are absent/offline.
- **Risk:** high correctness risk; could reintroduce stale-zero and negative-home
  failures.
- **Hardware dependency:** mandatory synchronized meter/system captures.
- **Port style:** one root-cause audit per behavior.
- **Acceptance:** source/freshness contract precedes formulas; P4.1 and existing
  whole-stack regressions remain green.

### Group D: already covered or superseded

No action is needed for Community v2.4.1/v2.4.2, canonical Type-23 serials,
same-key Type-106 timeout, strict topic/envelope parsing, MQTT lifecycle,
SmartMeter replacement, malformed child handling, multi-entry identity,
availability ownership, generic routing, dynamic number bounds, Type-105/106/107,
funcEnable, host metadata guards, plug entity commMode guard, or the standby
home-power outcome. NG has equivalent behavior with stronger isolation/tests.

### Group E: investigate separately

- **Community v2.5.0 `/alert` and `jackery_alert`:** validate real public
  payload shapes, field meaning, lifecycle behavior and a stable HA event
  contract before proposing an NG-native transport integration. Do not copy the
  Community coordinator path into NG's transport abstraction.
- **Dynamic host model changes and deviceType 1/2/4 labels:** distinguish a
  metadata label from actual supported host hardware before changing registry
  model. A changed deviceType after setup also needs identity/diagnostics review.
- **Optimistic plug state and `switchSta`/`sysSwitch` priority:** establish device
  acknowledgement and telemetry ordering before changing NG's publish semantics.
- **YAML `async_step_import`:** Official has a step but no repository-level YAML
  schema/initiator proving a supported import path. Investigate only if a real
  import use case is requested.

### Group F: ignore

Ignore Official release/version churn, dashboard/screenshots, naming-only schema
rewrites, commented invalid manifest JSON, five-second/every-cycle polling,
per-message INFO logs, host-ID migration formats, duplicate calculated entity
removal and wholesale Official energy formulas. Also ignore Community release
markers and documentation-only v2.4.1/v2.4.2 commits.

## 12. Hardware-evidence requirements

| Candidate | Required evidence | Sensitive-data treatment |
| --- | --- | --- |
| Ability bits 9/11 | Multiple models/firmware, raw ability integer, whether app shows/executes each control | Alias device/child serials; retain only bounded semantic fields |
| `wps` storm warning | At least inactive/active observations and message type/cadence | Do not retain app/account/cloud payload context |
| Generic CT phase entities | Per subtype: devType/subType, direction, phase/total fields, unit scale, zero behavior | Remove serials, names, network values and topics |
| Type-101 membership | Poll request category, full/partial response distinction, repeated empty/omitted sequences, actual bind/unbind | Alias identities consistently across sequence |
| CT/system formula changes | Synchronized CT, system and reference-meter samples through import/export/zero/transitions | Store only sanitized power fields and relative times |
| Dynamic host deviceType | Multiple host messages and registry result across firmware/reload | Never publish real serial or firmware-linked owner data |

Code presence, app decompilation and one user's value are protocol evidence, not
hardware support certification.

## 13. Test ideas worth porting

| Test idea | Source | Why useful in NG | Port style |
| --- | --- | --- | --- |
| Later child polls continue after one category publish failure | Official final poll structure | Directly reproduces A3 and is independent of hardware | New NG regression, not upstream test copy |
| Host serial inside every child array alias | Official `6315207` | Proves no self-child cache/freshness/discovery/device creation | New parameterized routing transition |
| Top-level/body firmware matrix with child/foreign messages | Official metadata helper | Proves A2 without weakening host ownership | New protocol contract test |
| Capability absent/malformed/gain/loss across setup and reload | Community `020b370` concept | Upstream tests only bit math; NG needs HA entity lifecycle proof | New HA tests after policy decision |
| CT-only Type-101 as first child message | Observed Official startup failure | Prevents adoption of replacement logic that assumes `plugs` exists | Test-only prerequisite for C3 |
| Plug coordinator called outside entity path | Official coordinator guard | Proves no alternate caller bypasses commMode policy | Added by the completed B1 command-contract regression |
| Reauth removed/reloaded/repeated entry journey | Official API difference | Closes a known production-readiness gap | New HA config-flow/lifecycle suite |

Official has no checked-in tests to copy. Community's v2.4.3 test file is useful
as a list of bit examples, but its configuration assertions should not be ported
as a substitute for runtime tests.

## 14. Release and compatibility implications

| Candidate | Compatibility surface | Required release treatment |
| --- | --- | --- |
| Host-child array filter | Child/device registry only if current bad data already created a phantom entity | Add migration/cleanup decision before removing any existing registry record |
| Top-level firmware | Device registry metadata | Non-breaking; document source precedence |
| Poll error isolation | MQTT request cadence/logging | Non-breaking bugfix; verify no rate increase beyond attempted skipped polls |
| Plug coordinator guard | Writable command behavior | Behavior hardening; release note blocked modes and error semantics |
| Reauth lifecycle | Config-entry flow and HA API minimum | Validate supported HA versions and upgrade/reload path |
| Ability gates | Entity availability and writable capability | Potentially breaking for established entities; define fail-open/fail-closed and migration policy |
| `wps` | New sensor/translations | New capability; default visibility and schema must be explicit |
| Generic CT entities | Entity/device registry and recorder history | Additive only unless a deliberate, tested migration is approved |
| Type-101 unbinding | Device/entity registry deletion | High-risk behavior change; hardware fixtures and conflict-safe preflight mandatory |

No audited upstream commit justifies changing NG's minimum HA version,
manifest dependencies, diagnostics schema, identity format or supported-hardware
claims by itself.

## 15. Architecture guardrails

Every follow-up must preserve these established constraints:

1. one authoritative owner per cache, freshness and evidence state;
2. routing remains separate from calculation and entity creation;
3. transport remains separate from protocol semantics;
4. runtime state stays HA-independent where currently designed;
5. child identity remains host plus child serial with conflict-safe migration;
6. freshness never follows merely from cached value presence;
7. HTTP and MQTT values, health and lifecycle remain independent;
8. diagnostics remain explicit allowlist/alias output with no raw cache;
9. protocol discovery remains opt-in, read-only, bounded and memory-only;
10. no global mutable state or cross-entry cache;
11. expected external absence is handled narrowly and programming errors are not
    hidden by new blanket exception catches;
12. no upstream change is allowed to rebuild the coordinator monolith;
13. formula, source, identity and availability changes require dedicated
    regression-first PRs;
14. upstream code is evidence, not proof of correctness or cherry-pickability.

## 16. Proposed follow-up audits and port PRs

The previously proposed Group-A sequence was completed as separate A1, A3 and
A2 regression-first PRs. This refresh did not select a next major workstream;
B1 was selected later and is now complete. Remaining decision candidates include:

- an alert payload/event-contract evidence audit before any `/alert` feature;
- B2 reauthentication lifecycle design and HA tests;
- C1 capability evidence, with `wps` separate from writable gates;
- C3 membership semantics after real Type-101 sequences exist;
- C2/C4 hardware work, one meter family or formula question per audit.

Capability, entity and battery-semantics changes should wait for independently
reviewable evidence and a release/compatibility contract.

## 17. Explicitly superseded or no-action changes

- Community `082340e` is superseded by merged P4.1; strict live-alias priority is
  not the NG contract.
- Community v2.4.1's lifecycle, malformed-input, Type-23, Type-106 and HTTP
  replacement fixes are all covered by stronger NG owners and regressions.
- Community v2.5.0's mypy cleanup is superseded by NG's existing type contracts;
  its version, `.gitignore` and repository metadata are not portable behavior.
- Official identity changes are superseded by host-scoped, preflighted migration.
- Official Type-106 overwrite/magnitude selection is superseded by receipt
  evidence and must not replace NG source policy.
- Official generic routing and child freshness are already extracted and tested.
- Official battery/home formula branches are not accepted port candidates.
- Official entity renames/removals, dashboard assets and release metadata have no
  NG behavioral value.
- Official per-message INFO logging would increase noise and identifier exposure.
- Neither upstream has diagnostics/privacy/protocol-discovery work that should
  replace P3.

## 18. Candidate summary

| Candidate | Source | NG gap | Port style | Hardware needed | Risk | Suggested next step |
| --- | --- | --- | --- | --- | --- | --- |
| Host serial filter in child arrays | Official `6315207` | Closed by A1 | Manual semantic port | No | Low/medium | Implemented in NG |
| Top-level host `softver` | Official metadata helper | Closed by A2 with body-first precedence | Manual semantic port | No | Low | Implemented in NG |
| Child poll failure isolation | Official `8ac1b40` | Closed by A3 | Manual semantic port | No | Low/medium | Implemented in NG |
| Alert topic and HA event | Community `77d218f` | No NG `/alert` subscription or public event contract | Investigation first; later NG-native transport adaptation | Evidence first | Medium | Validate payload fields, lifecycle and event compatibility |
| Battery/BP2500 firmware claims | Community `77d218f` documentation | Claims are not independently verified by NG | Evidence cross-check only | Yes | Medium/high | Compare sanitized hardware evidence before behavior changes |
| Coordinator plug guard | Official `d1f4f68`, refined by `66b9a7f`/`8417002` | Closed by B1 | Manual semantic port | No | Medium | Implemented in NG |
| Reauth lifecycle completion | Official flow pattern | End-to-end recovery not proven | Manual NG adaptation | No/low | Medium | B2 HA lifecycle audit |
| Ability bits 9/11 | Community `020b370` | Unsupported controls may remain available | Manual capability port | Yes | Medium/high | Cross-firmware evidence audit |
| `wps` storm sensor | Community `020b370` | Read-only field not exposed | Manual additive port | Yes | Low/medium | Separate evidence/sensor proposal |
| Generic CT phase entities | Official `c7894d3` | Legacy type2/4 telemetry narrower | Manual additive port | Yes | High | One subtype fixture/audit |
| Type-101 unbinding | Official `5fe1159`/`ef69587` | Stale child cleanup uncertain | Investigation first | Yes | High | Membership semantics audit |
| CT/system formula variants | Official `73b1d2f`/`3af71fd` | Possible firmware-specific fallback gap | Do not cherry-pick | Yes | High | One physical scenario audit |
| Dynamic host labels | Official model map | NG labels only verified DIY3 host | Investigation first | Yes | Medium | Hardware support matrix evidence |

No candidate is a plausible direct cherry-pick. Upstream paths combine routing,
state, HA entities and transport inside `sensor.py`; NG's boundaries require
manual semantic ports. The only plausible test-only inputs are scenario ideas,
because Official has no tests and Community's relevant new tests do not exercise
HA behavior.

## 19. Open questions

1. Can maintainers provide sanitized Type-101 sequences proving when a category
   response is authoritative versus partial?
2. Which model/firmware combinations report ability bits 9/11, and does an absent
   bit mean unsupported, hidden, or not yet reported?
3. Does `wps` occur on local MQTT independently of cloud/app action, and is a
   default-visible entity useful?
4. Which generic devType 2/4 meters actually report per-phase forward/reverse
   fields and what are their scaling guarantees?
5. What is the supported HA version range for `ConfigEntry.async_start_reauth`
   versus the current flow-init approach?
6. Which publicly verifiable `/alert` payload forms and fields are stable enough
   for an NG event contract, and how should reload/unload be tested?
7. Can the Community v2.5.0 battery/BP2500 claims be independently confirmed by
   sanitized hardware evidence before changing NG behavior or support wording?
8. Should historical host-as-child registry records, if any, receive a separate
   cleanup after A1's prevention-only fix?

## 20. Decision answers

1. **Are there high-confidence changes NG still lacks?** No from the audited
   Group-A set: host-SN exclusion, top-level host firmware metadata and
   per-category child-poll isolation are implemented. Community v2.5.0 `/alert`
   is evidence-gated rather than a new Group-A port.
2. **Which changes need hardware tests first?** Ability gates, `wps`, generic CT
   phase entities, Type-101 unbinding, formula/CT-zero fallbacks and expanded host
   labels.
3. **Did Community miss Official functionality?** Historically yes: generic
   devType 2/4 phase entities, top-level firmware, host-SN array filtering and
   authoritative category replacement. NG has independently completed the
   bounded host-filter and firmware-metadata ports; phase entities and authoritative
   membership still need evidence.
4. **Are there post-fork Community fixes to port?** No ready high-confidence
   bugfix remains. Community v2.4.3 needs hardware evidence, while v2.5.0
   `/alert` needs a separate payload/event-contract investigation.
5. **What belongs before release/compatibility hardening?** Group A is complete.
   This refresh does not choose between release/lifecycle hardening and the
   remaining evidence audits; that is now a maintainer decision.
6. **What should deliberately not be ported?** Wholesale Official formulas,
   magnitude source selection, strict live-alias priority, optimistic plug cache,
   identity formats, five-second polling, INFO protocol logs, entity removals and
   repository-specific docs/releases.

**Audit conclusion:** yes, the source and semantic inventories are complete
enough to plan individual, narrowly scoped port or investigation PRs. No
upstream behavior is approved merely by appearing in a candidate group.
