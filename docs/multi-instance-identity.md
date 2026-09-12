# Multi-instance identity audit

## PR2A status — identity and migration safety

**Public entity unique-ID formats: unchanged. Public device identifier formats:
unchanged. Duplicate child serials across hosts remain unsupported.** PR2A does
not implement the proposed `jackery_child:` namespace. The audit/design below is
historical evidence from baseline `00ecba9`, committed as `5b9563f`; its failing
results describe that baseline, not the current merge-target suite.

### Fixed in PR2A

- Preserve collector, SmartMeter, battery, plug and CT child IDs, including numeric,
  lowercase and underscore-containing serials and historical `SmartMeter`/`Battery`
  prefixes. Prefer the existing device link; without one, preserve recognized
  child families. Exact legacy main sensor keys still migrate. If a key could be
  both main and child (e.g. `jackery_ct_import_energy`), an absent device link is
  insufficient evidence: retain it and warn instead of guessing.
- Check migration targets globally by HA's `(entity domain, integration platform,
  unique ID)` using the entity registry API. Different domains/platforms do not
  conflict. Retain **both** records on actual target conflicts, even within one
  entry: matching IDs alone do not prove either record has dispensable history
  or user settings. Foreign targets no longer raise a migration `ValueError`.
- Only migrate exclusively owned main devices; preserve both devices on a target
  conflict and keep unrelated identifiers during an in-place migration. Skip
  entity migration on foreign/shared associated devices. Host metadata writes
  also require exclusive ownership. These checks protect migration/update paths;
  they do not resolve HA's creation-time merging of unscoped child devices.
- Child deletion requires exclusive config-entry ownership. Foreign/shared
  matches remain intact, including local listeners when deletion is refused.
  Same-entry deletion and rediscovery still work. Registry ownership is checked
  around the unchanged global `sub_{serial}` lookup.
- Listener matching uses the entity's exact stored `_plug_sn` or `_sm_sn`, so a
  serial inside another serial, the host ID or an unrelated ID component cannot
  remove that listener. HTTP keeps its separate health path.
- Create one coordinator in integration setup before forwarding platforms; start
  MQTT/HTTP only after forwarding has installed both dynamic callbacks. Sensor
  setup consumes that existing object. Sensor-first, controls-first and ordinary
  concurrent forwarding now produce all five platforms, in either host order.
  Unload clears entity registrations and stops polling; reload creates a fresh
  coordinator with the same public IDs. No coordinator module was extracted.
- Keep only the documented obsolete-select cleanup in the select domain, and
  known v2.0.1 main-sensor residue cleanup in the sensor domain. Unknown residue
  names and wrong-domain records remain intact.

### Classification of every original audit test (60 cases)

Names below are from `tests/test_multi_instance_identity.py` at `5b9563f`.
Parameter subsets are explicit where one function spans classifications.

| Original test / parameter subset | Cases | Classification | PR2A disposition |
| --- | ---: | --- | --- |
| `test_platform_setup_order_does_not_drop_controls` | 1 | PR2A | Retained; extended to three forwarding modes. |
| `test_two_hosts_all_platforms_and_reload_isolation` | 2 | ALREADY_PASSING | Retained; extended to three forwarding modes and exact ID sets. |
| `test_distinct_children_with_overlapping_metadata`, collector in both host orders | 2 | PR2A | Retained; collector reload now preserves registry identities. |
| Same test, other six child configurations in both host orders | 12 | ALREADY_PASSING | Retained unchanged. |
| `test_duplicate_child_serial_unique_ids_are_host_scoped`, all seven configurations | 7 | PR2B | Assertions preserved verbatim in future-test source. |
| `test_duplicate_plug_switch_unique_id_is_host_scoped` | 1 | PR2B | Same. |
| `test_http_unique_ids_differ_but_devices_must_also_be_separate` | 1 | PR2B | Same; HTTP entity IDs differ, devices still collide. |
| `test_duplicate_child_discovery_does_not_claim_other_host`, both orders | 2 | PR2B | Same. |
| `test_child_cleanup_cannot_delete_another_entries_device` | 1 | PR2A | Retained; foreign device protected. |
| `test_child_migration_preserves_identity`, uppercase serial with lowercase smartmeter/battery/ct/plug prefix | 4 | ALREADY_PASSING | Retained unchanged. |
| Same test, other 17 prefix/serial combinations | 17 | PR2A | Retained unchanged; IDs now preserved. |
| `test_legacy_migration_is_entry_scoped_and_idempotent`, both orders | 2 | ALREADY_PASSING | Retained unchanged. |
| `test_migration_conflict_is_scoped_to_entity_domain` | 1 | PR2A | Retained unchanged. |
| `test_main_device_migration_cannot_rewrite_foreign_device` | 1 | PR2A | Retained; bidirectional/shared cases added separately. |
| `test_migration_target_owned_by_other_entry_is_not_claimed`, both entries | 2 | PR2A | Retained unchanged. |
| `test_existing_cleanup_policy_is_scoped_and_idempotent`, both entries | 2 | NEEDS_REVIEW → PR2A | Original tests passed but required deleting conflicting source records. Now explicitly assert source preservation while still checking documented obsolete cleanup and entry isolation. |
| `test_meters_and_plugs_reappear_without_changing_ownership`, both orders | 2 | ALREADY_PASSING | Retained unchanged. |

Totals: **25 PR2A, 11 PR2B, 22 ALREADY_PASSING, 2 NEEDS_REVIEW** (both review
cases resolved above). All 49 applicable original cases remain in the active
suite; extensions add coverage rather than skipping failed assertions.

The 11 PR2B cases are stored unchanged in
[future-tests/pr2b-child-identity.py.txt](future-tests/pr2b-child-identity.py.txt).
The `.py.txt` file is a documented test design artifact, deliberately outside
pytest collection. Reinsert its functions into the original test module in
PR2B; its header lists the shared helpers/imports. No `xfail`, skip marker or
weakened duplicate-isolation assertion was added. The original baseline evidence
remains below and in commit `5b9563f`.

Additional PR2A tests cover unlinked historical children, exact ID formats,
ambiguous CT identity, both directions of device ownership, shared/foreign device
and entity targets, domain/platform isolation, guarded obsolete cleanup, exact
listener serials, plug/CT/SmartMeter deletion and rediscovery, HTTP/MQTT shared
registry protection, and HTTP polling across reloads. Three old availability mocks
now supply the `_plug_sn` attribute real entities already have; their health
assertions are unchanged. The older `test_main_sensor_gets_sn_prefix` now seeds an
unloaded entry so it tests real in-place migration rather than accidental orphan
removal; `test_conflict_records_preserved` explicitly tests the revised conflict
policy.

### Deferred to PR2B

**The principal unresolved defect is global child identity:** MQTT child entity
IDs and `sub_{serial}` device identifiers still omit the host. The same child
serial under two hosts therefore still collides; exclusive-owner cleanup guards
do not provide duplicate-serial isolation or prevent HA creation-time merging.

PR2B must cover host-scoped child entity identity, host-scoped child device
identity, duplicate child serial isolation, migration from old child identities,
already-shared historical-device conflict handling, interrupted migration,
recorder/entity continuity validation, and HTTP/MQTT shared-device migration.
The proposed migration design below remains unimplemented. No automatic history
split, reassignment or conflict-record deletion is introduced by PR2A.

MQTT unsubscribe callbacks are still not retained (pre-existing lifecycle issue).
The new setup-order tests mock the broker and prove coordinator/polling/entity
lifecycle, not broker subscription cleanup. Failed or partial MQTT subscription
startup and the broader transport lifecycle refactor remain separate work.
Existing replacement-meter HTTP discovery policy is also unchanged.

### PR2A validation (2026-09-12 UTC)

Python 3.13.5, existing locked HA test environment. The initial sandbox test run
stalled and was interrupted, as in the documented baseline; pytest runs below
used the approved sandbox exception. No broker/hardware was contacted.

| Command/check | Result |
| --- | --- |
| `.venv/bin/pytest tests/test_multi_instance_identity.py tests/test_migration.py -q --no-cov --timeout=30 --tb=short` before production edits, after PR2B separation/conflict-test correction | **28 failed, 27 passed**, reproducing the safety defects against baseline production. |
| Expanded regression run before production edits | **71 failed, 33 passed, 35 setup/teardown errors**; the new lifecycle assertions additionally expose starting the coordinator before both platform callbacks exist. |
| `.venv/bin/pytest tests/test_multi_instance_identity.py -k 'ambiguous_unlinked or device_link_disambiguates' -q --no-cov --timeout=30 --tb=short` before the ambiguity guard | **1 failed, 2 passed**; unlinked CT identity was guessed incorrectly. |
| `.venv/bin/pytest tests/test_multi_instance_identity.py tests/test_migration.py -q --no-cov --timeout=30 --tb=short` after fixes, before the final shared HTTP/MQTT case | **110 passed**. |
| `.venv/bin/pytest tests/test_multi_instance_identity.py tests/test_migration.py tests/test_config_flow.py tests/test_subdevice_entity.py tests/test_subdevice_availability.py tests/test_availability_freshness.py tests/test_smartmeter_http.py tests/test_mqtt_routing.py -q --no-cov --timeout=30 --tb=short` | **240 passed**. |
| `.venv/bin/pytest tests/ -q --timeout=30 --tb=short` on final code | **365 passed**, **84.32%** statement coverage; no skipped or expected-failure tests. Includes **105 PR2A identity cases** and the 260 existing tests. |
| `.venv/bin/ruff check custom_components/jackery/ tests/` | Passed. |
| `python3 tools/check_translations.py` | Passed: de/en/fr. |
| `/tmp/jackery-baseline/lint-venv/bin/mypy custom_components/jackery/` | Passed, seven source files; baseline-consistent CI environment. |
| `.venv/bin/mypy custom_components/jackery/` | **23 existing diagnostics**, now in four files. The three optional constructor-argument findings moved from sensor setup to integration setup. Message multiplicities match the baseline exactly after removing paths/line numbers; no additional findings. |
| `git diff --check` and new-file whitespace check | Passed. |
| Compare PR2B future-test source with `git show 5b9563f:tests/test_multi_instance_identity.py` | Deferred assertion block matches byte-for-byte. |
| `command -v docker` | Unavailable; local HACS/Hassfest could not run. CI validator definitions unchanged. |

The first full run exposed two old availability mocks missing the stored serial;
these were corrected to match real entities without changing their availability
assertions. No unrelated failing check was disabled. Production changes are
limited to `custom_components/jackery/__init__.py` and `sensor.py`; supporting
changes cover tests, this report, the future-test artifact, inventory/coverage/map
status notes and `CHANGELOG.md`.

## Historical Phase 0/1 follow-up audit

Scope: `fix/multi-instance-identity`, baseline `00ecba9`. Synthetic data only.
Audit completed on 2026-09-12 UTC and originally paused at the user's Step 11
boundary without production changes. All "current"/"failing" descriptions below
refer to that original audit baseline; PR2A status and validation supersede them.

## Current identity model (before production changes)

`E` is a Home Assistant config entry ID, `H` the configured SolarVault serial,
`C` a child serial, and `K` the existing entity field/description key.
Config flow version is **1**. Its unique ID is the trimmed submitted host serial;
entry data retains the submitted string. Runtime constructors usually use that
stored string, falling back to `E` when empty. These are distinct identities.

| Family | Entity unique ID | Device identifier | Parent |
| --- | --- | --- | --- |
| Main sensor (all definitions) | `jackery_{H}_{K}` | `(jackery, H)` | None |
| Main switches, including optimistic/follow-meter | `jackery_{H}_switch_{K}` | `(jackery, H)` | None |
| Main numbers | `jackery_{H}_number_{K}` | `(jackery, H)` | None |
| Main selects | `jackery_{H}_auto_standby_select`, `jackery_{H}_work_mode_select` | `(jackery, H)` | None |
| Reboot button | `jackery_{H}_reboot` | `(jackery, H)` | None |
| Expansion battery (type 1) | `jackery_battery_{C}_{K without underscores}` | `(jackery, sub_{C})` | `(jackery, H)` |
| CT (type 2 and legacy type 4) | `jackery_ct_{C}_{K without underscores}` | same child format | same parent format |
| HTO907A / Shelly Pro 3EM (type 3, subtype 5 / 2) | `jackery_smartmeter_{C}_{K without underscores}` | same child format | same parent format |
| HTO910A collector (type 4 / subtype 7) | `jackery_collector_{C}_{K without underscores}` | same child format | same parent format |
| Plug / unknown-type discovery fallback | `jackery_plug_{C}_{K without underscores}` | same child format | same parent format |
| Plug switch | `jackery_plug_{C}_switch` | same child format | same parent format |
| SmartMeter HTTP | `jackery_{H}_http_sm_{C}_{K}` | same child format | same parent format |

All entities are added through their platform's config-entry callback. Registry
ownership is the actual `config_entry_id`; it is not encoded in child MQTT IDs.
Home Assistant keys entities by entity domain, integration platform and unique ID,
not by config entry. Device identifiers are global to the integration domain.
`via_device` is a relationship, not part of the identifier. Entity IDs are assigned
by HA from names/translations and registry reuse; no explicit entity-ID assignment
exists in the integration. User names and disabled settings live in the registry.

The serial determines child identity, while classification determines its MQTT
entity prefix. Changing the advertised name does not change identity; changing
classification on a later reload can change that prefix. No child number, select
or button exists. HTTP shares the MQTT meter device intentionally.

## Registration, lookup and lifecycle

`hass.data[DOMAIN][E]` holds one coordinator per entry. Caches, discovery sets,
last-seen maps and listener maps are instance attributes. No shared child cache
or classification dictionary was found. Static main entity keys are local to the
coordinator; dynamic child sensors register by unique ID, plug switches by their
own local key, HTTP by `http_{C}_{K}`.

Discovery uses a per-coordinator set of child serials. Repeated reports do not
recreate entities. Type101 omission retains cached children; other existing
replacement paths can start the missing-child deletion timer. Expansion batteries
are exempt. Cleanup globally looks up `(jackery, sub_{C})` and removes the device
without checking config-entry ownership. Listener cleanup also uses substring
matching rather than exact stored child identity. Host metadata updates globally
look up `(jackery, H)`. MQTT unsubscribe callbacks are not retained; reload registry
tests with a mocked broker do not establish subscription cleanup.

## Existing migration rules

There is no versioned `async_migrate_entry`. `_migrate_unique_ids` runs on every
setup, before platform forwarding. Its source entity list is entry-scoped.

- `jackery_{main_sensor_key}` becomes `jackery_{H}_{main_sensor_key}`.
- `jackery_main_{field}` becomes host-scoped `switch_` / `number_`, selected by
  entity domain; other domains receive the generic host prefix.
- `jackery_{E}_{suffix}` becomes `jackery_{H}_{suffix}`.
- Lowercase `smartmeter_`, `battery_`, `plug_`, `ct_` prefixes are preserved only
  when the next character is uppercase. Collector and numeric/lowercase child
  serials are not protected. The comment mentioning historical capitalized
  `SmartMeter` / `Battery` prefixes does not match the case-sensitive check.
- Already host-prefixed `main_*` residue is deleted (documented v2.0.1 bug).
- Already host-prefixed `max_feed_in_select` is deleted (v2.3.2 replacement).
- An old source is deleted when its target unique ID exists in this entry.
  This comparison ignores entity domain/platform. A target belonging to another
  config entry is not detected by this set.
- The old `(jackery, E)` main device gets identifier `(jackery, H)` through a
  global lookup without an ownership check or an explicit target-conflict plan.

Updating an entity's unique ID in place can retain its entity ID and registry
settings. Existing deletion branches do not preserve that source registry entry;
this audit must not be interpreted as a guarantee of recorder history recovery.

## Collision boundary

Distinct child serials should coexist even with identical names, classification
and keys. Identical child serials under distinct hosts collide for every MQTT
child family; HTTP unique IDs differ but the device identifier still collides.
Claiming a child for the first host to load would make ownership order-dependent.
Adding an ownership check only during deletion would not prevent creation-time
merging or entity registration rejection.

The task explicitly says to stop and provide a migration design if a clean fix
requires changing public identity formats across many entity classes. A complete
fix affects every MQTT child sensor family, plug switches and the shared HTTP/MQTT
device identifier. Regression evidence and a concrete design follow below before
any such production change is made.

## Confirmed regression evidence

`tests/test_multi_instance_identity.py` adds 60 cases. The final run against
unchanged production code has **24 passing and 36 failing cases**. Failures are
ordinary assertions/errors, not skipped tests or expected-failure markers.

| Finding | Evidence | Consequence |
| --- | --- | --- |
| All child MQTT families lack host scope | Seven all-definition sensor cases plus the plug switch case fail ID disjointness | Same child SN produces identical IDs for different hosts. Different type3 subtypes do not distinguish SmartMeter/Shelly identity. |
| Duplicate child discovery depends on host order | Both discovery-order cases fail the second host's child entity count | HA rejects the already-registered child entities; the second host does not get its own children. This test does not claim MQTT-only duplicate discovery itself changes the existing device parent. |
| HTTP device identity still collides | All 16 HTTP unique IDs differ across hosts, but real device-registry creation returns the same device ID | Unique entity IDs alone do not provide device separation. HA's device creation can add another entry to the shared device. |
| Cleanup can delete a foreign child | A coordinator with no ownership removes B's real plug device via its global serial lookup | B's registry snapshot changes. Config-entry scoping is required even if future IDs become host-scoped. |
| Child migration misclassifies legitimate IDs | 17 preservation cases fail; 4 existing uppercase/lowercase-prefix cases pass | Collector IDs and lowercase/numeric child serials receive an erroneous host prefix. Historical capitalized prefixes mentioned in source comments are also misclassified. |
| Collector reload creates replacement registry entities | Both order cases initially create separated collectors, then fail identity snapshots after reload/rediscovery | Migration rewrites IDs that constructors still generate in their old form. This fragments entity continuity even with distinct child serials. |
| Migration conflict detection ignores HA entity domain | A switch's target-looking UID causes deletion of a sensor's old registry entry | HA permits the same UID in different entity domains; the migration's string-only set incorrectly treats it as a collision. This is a synthetic restored/conflicting-registry edge case, not a claim current constructors emit that switch UID. |
| Old-device migration ignores ownership | A restored `(jackery, A.entry_id)` device owned by B is renamed during A's migration | B's identifier changes despite entry-scoped entity enumeration. |
| Foreign entity target aborts migration | Both entry directions raise HA `ValueError` on an already-used target UID | Foreign entities are not overwritten, but the migration lacks a controlled conflict path and cannot complete setup safely. |
| Platform startup order drops controls | An explicit controls-before-sensor test fails the five-platform assertion | Controls return early when sensor setup has not created the coordinator. Real unconstrained initial test runs also exhibited this ordering failure. |

The first unconstrained run had variable failures because platform forwarding
runs concurrently. To isolate identity behavior, the normal setup fixture calls
the **real HA forwarding function** for sensor first, then the remaining platforms.
The separate startup-order regression reverses those batches. All registry calls,
platform constructors, dynamic additions, migration, MQTT decoding, registration,
unload and reload are real. MQTT readiness/subscription and the periodic network
poll loop are replaced; no broker or hardware is contacted. A passing reload test
therefore establishes registry/coordinator isolation under the stated setup order,
not production subscription cleanup or guaranteed concurrent startup.

## Proposed migration design — not implemented

### Identity and duplicate-child policy

Use **host plus child serial** for the integration's child identity. If two hosts
report the same child SN, expose two host-owned representations; do not infer that
the reports describe a single physical device or automatically transfer ownership.
This policy follows the requested order-independent isolation. Actual hardware
re-pairing semantics remain unknown. Keep main-device IDs and HTTP entity unique
IDs unchanged for existing valid configurations.

A concrete collision-resistant candidate namespace is:

| Item | Proposed value |
| --- | --- |
| Child device identifier | `(jackery, child:{encoded_H}:{encoded_C})` |
| Child MQTT sensor unique ID | `jackery_child:{encoded_H}:{encoded_C}:{existing_family}:{existing_safe_key}` |
| Plug switch unique ID | `jackery_child:{encoded_H}:{encoded_C}:plug:switch` |
| HTTP entity unique ID | Existing `jackery_{H}_http_sm_{C}_{K}` |
| All child `via_device` | Existing `(jackery, H)` |

Encode serial components with percent encoding (`urllib.parse.quote(value,
safe="")`), so literal colons and percent signs cannot make the component boundary
ambiguous. Do not lowercase serials or infer their allowed alphabet. The reserved
`jackery_child:` prefix must be recognized before the old generic migration.
Preserve existing family/key tokens; this is an identity migration, not a
classification or measurement redesign. Names, translations, entity domains,
units, default enablement and HTTP/MQTT device grouping remain unchanged.

### Ownership preflight and migration sequence

1. Before platform forwarding, enumerate only this entry's entity records. Resolve
   the host from its persisted configuration/config-entry identity, and build a
   complete source-to-target plan without mutating either registry. Whitespace
   mismatch between stored and trimmed SN is a separate legacy ambiguity: account
   for both explicitly or stop that entry; do not silently normalize runtime IDs.
2. Identify children using their existing device identifiers, entity ownership
   and parent relationship. Match known family/key formats, including collector,
   numeric/lowercase SNs and documented historical capitalized prefixes. Do not
   split arbitrary serials at underscores or use uppercase as the discriminator.
   An entity without reliable device association needs an unambiguous legacy
   match; otherwise leave it untouched and report the conflict.
3. A legacy device can be updated in place only when it belongs exclusively to
   the intended config entry and its parent/child evidence agrees. Check target
   devices globally, but never claim one owned by another entry. For a shared or
   inconsistently owned legacy device, stop the affected entry before mutation
   and report the exact conflict. Do not choose a winner from setup order or the
   most recently assigned `via_device`.
4. Check entity targets by `(entity domain, integration platform, unique ID)` in
   the global registry. A target in another config entry is a conflict, not an
   orphan to delete. A target already created during a partial migration must
   agree with the same source ownership. If both old and new records exist, do
   not delete either merely because the UID matches: user customization/history
   may be attached to the older record. Retain the existing narrowly documented
   obsolete-entity cleanup separately, restricted to the correct entry/domain.
5. Update each exclusively owned device's identifier **in place**, preserving
   its registry ID, area, labels and user name. Remove its old unscoped identifier
   rather than retaining it as an alias, which would reintroduce global merging.
   Retain the same main-device relationship. Update each source entity with
   `async_update_entity(..., new_unique_id=...)`; preserve its `entity_id`, registry
   ID, device association and user settings. HTTP entity UIDs need no change.
6. Make each step idempotent and recognize partially completed migrations. HA's
   entity and device registries are not a single transaction. A restart between
   writes must resume from the plan's validated ownership, never delete unknown
   residual records. If a config-entry migration version is introduced, advance
   it only after all required operations succeed; keep legacy compatibility for
   older registry states and add explicit interrupted-migration tests.
7. Constructors, discovery and cleanup must switch to the same new identifier in
   that release. Keep the changes in the existing modules. Cleanup must verify
   config-entry ownership before removal, and listener matching should use the
   entity's exact child SN rather than substring matches.

For example, `jackery_smartmeter_METER01_power` owned by host `SOLARVAULT_A`
would become `jackery_child:SOLARVAULT_A:METER01:smartmeter:power` on the **same**
entity record. The exclusively owned device `(jackery, sub_METER01)` would gain
the new identifier `(jackery, child:SOLARVAULT_A:METER01)` on the **same** device
record. An independently reporting `SOLARVAULT_B` would get its own namespace.

Already shared historical devices require an explicit resolution design beyond
the automatic exclusive-owner path. Entity `config_entry_id` is useful evidence,
but cannot recover measurements previously mixed into one history. No automated
history split, device deletion or reassignment is proposed here. Preserving IDs
in the unambiguous path avoids unnecessary recorder discontinuity; a real
recorder/statistics migration test is still required before claiming that path
fully validated.

### Small prerequisite fixes that do not require new public IDs

The child-prefix preservation, domain-aware conflict comparison and device
ownership checks can be fixed independently with their failing tests. The
platform-order defect can be addressed by ensuring sensor setup completes before
dependent platform setup, without extracting a coordinator module. These narrow
changes alone would **not** meet duplicate-child isolation. None has been applied
in this audit, to keep the requested migration-review boundary explicit.

## Coverage status and unresolved cases

| Requested check | Status |
| --- | --- |
| Two simultaneous SolarVault entries | Tested with real loaded entries, both host orders. |
| Main-device separation | Passing for all five platforms under deterministic sensor-first setup; inverse platform order has a separate failing regression. |
| Child-device separation | Distinct serials tested for CT types 2/4, HTO907A, Shelly, collector, plug and battery; collector reload fails. Simultaneous SmartMeter plus plug per host also passes. |
| Duplicate / overlapping metadata | Identical name/type/subtype/key with distinct serials tested; duplicate serial cases expose the failures above. |
| Unique-ID collision resistance | All main platforms separated; every child sensor definition and plug switch tested and currently colliding for duplicate SNs. All HTTP UID definitions are disjoint, but device IDs collide. |
| Migration idempotence | Passing legacy main/control/device and existing cleanup cases, both migration orders; child preservation fails for the documented forms. No new-format migration exists yet. |
| Cross-entry migration isolation | Passing ordinary two-entry migrations and cleanup; foreign-device ownership and foreign-target conflict cases fail. |
| Unload/reload isolation | Main and non-collector distinct children pass with mocked transport and ordered platforms. Collector reload fails; actual MQTT unsubscribe remains unverified. |
| Replacement / rediscovery | Plug disappearance/reappearance and same-SN metadata changes retain registry identity; a different meter creates new entities while the old meter is retained under existing merged-list policy. |

Unresolved: historical devices already shared across entries; interrupted migration
and target reconciliation; actual recorder/statistics continuity; class changes
for an unchanged child SN; malformed/restored config entries with ambiguous host
SNs; substring-based listener cleanup; MQTT subscription retention after unload;
HTTP's per-coordinator one-time entity creation flag for a replacement meter.
No automatic unpair/re-pair cleanup policy is invented. Existing availability,
source-priority, energy and command behavior is untouched.

## Validation and changed files

Python 3.13.5; HA test environment from the existing lockfile. Commands below were
executed from the repository root. Pytest used the same sandbox exception as the
previous audits after the baseline run inside the sandbox stalled in pycares
teardown and was interrupted. Assertions and CI configuration were not disabled.

| Command | Result |
| --- | --- |
| `.venv/bin/pytest tests/ -q --timeout=30` before adding tests | **260 passed**, 79.22% coverage. |
| `.venv/bin/pytest tests/test_multi_instance_identity.py -q --no-cov --timeout=30 --tb=short` | **24 passed, 36 failed**; all failures expose unchanged production behavior. |
| `.venv/bin/pytest tests/ -q --timeout=30 --tb=short` | **284 passed, 36 failed**, 83.86% coverage. All 260 pre-existing tests pass, including migration, config flow, entity/subdevice, availability/freshness, HTTP and MQTT routing. |
| `.venv/bin/ruff check custom_components/jackery/ tests/test_multi_instance_identity.py` | Passed. |
| `python3 tools/check_translations.py` | Passed: de/en/fr. |
| `/tmp/jackery-baseline/lint-venv/bin/mypy custom_components/jackery/` | Passed, seven source files. |
| `.venv/bin/mypy custom_components/jackery/` | 23 pre-existing errors in three files; exact output matches `docs/baseline-evidence/mypy-with-ha.txt` after line-number normalization. |
| `git diff --check` and new-file whitespace check | Passed. |
| `command -v docker` | Docker absent; local Hassfest/HACS unavailable as before. |

Changed files: this audit/design, `tests/test_multi_instance_identity.py`, and
links to this evidence in `docs/entity-inventory.md`, `docs/refactor-map.md` and
`docs/test-coverage-map.md`. No production files, identity formats or migrations
were changed. `CHANGELOG.md` is deliberately unchanged because no user-visible
fix has been implemented. This is an audit/design checkpoint with failing
regressions, **not a completed or merge-ready bugfix**.
