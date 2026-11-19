# Upgrade, migration and rollback validation

## Scope

This report validates persistent Home Assistant identity and history behavior
when existing `jackery` installations load SolarVault NG code. It does not
model a fresh installation and does not require a physical SolarVault.

| Route | Pinned source | Version |
| --- | --- | --- |
| Jackery Official -> NG | `Jackery-Official/jackery` `af97223ff17fc8f14314cbc6da7213a5eee7004d` | 2.0.0 |
| Community -> NG | `csoscd/ha-solarvault` `77d218f6f531c1b5cd0b2ae5b9f2edfe0c61879c` | 2.5.0 |
| Older NG -> current NG | `fred-head/ha-jackery-solarvault-ng` `ed89e745fd7ceab35a52593122f28969cafd3bba` | 2.4.0 manifest |
| Current NG | `7409e75e8b69e349d223755e16b9e9d0f2aac180` | pre-stable foundation |

The older NG pin is the last commit before host-scoped child identity migration
was introduced by `b5f00b3`. It therefore represents the exact global-child-ID
state that the current migration must accept.

## Method and evidence boundaries

`tools/generate_upgrade_fixtures.py` checks out or archives each exact source
commit into a temporary directory and executes that source's real entity
constructors under Home Assistant 2026.2.3. It emits small, deterministic JSON
snapshots under `tests/fixtures/upgrades/`; no upstream source is vendored. Each
fixture records its repository, commit, manifest version, HA version, generator,
generation method and source-file SHA-256.

All identifiers, tokens, names and areas are synthetic. The fixtures contain no
real serials, credentials, broker data, IP addresses or user data. The committed
snapshots are consumed offline; `python tools/generate_upgrade_fixtures.py
--check` verifies deterministic regeneration when the pinned Git objects are
available locally.

The fixtures are **upstream-constructor generated**, rather than handwritten
guesses. They are replayed into real Home Assistant Config Entry, Device
Registry and Entity Registry objects. The test then runs current NG migration
and, for representative entities, Home Assistant's SQLite recorder. MQTT is
mocked because this track tests persistence and identity rather than protocol or
hardware behavior.

Evidence labels in this report mean:

- **[UPSTREAM-CONSTRUCTOR-GENERATED TEST VERIFIED]**: the starting identity was
  emitted by code at the pinned upstream commit and migrated through real HA
  registries.
- **[RECORDER TEST VERIFIED]**: states were written before and after migration
  and queried from the HA recorder under the same entity ID.
- **[SEMANTIC SNAPSHOT RESTORE TEST VERIFIED]**: the complete selected
  ConfigEntry/registry semantics can be restored from the pre-upgrade fixture.
- **[REAL HA VERIFIED]**: observed on the separate HA OS installation below.
- **[REAL HA UPGRADE VERIFIED]**: the final uncommitted branch candidate was
  installed by manual code replacement over an existing Official 2.0.0
  ConfigEntry, completed setup and migration, and passed a second restart.
- **[REAL HA BACKUP RESTORE VERIFIED]**: the complete Pre-NG Official backup
  restored successfully on the separate HA OS installation before the final
  upgrade test.
- **[REAL HA REPRODUCED MIGRATION BUG]**: an Official registry identity was
  observed to remain orphaned while NG created a separate row.
- **[REAL HA COMPATIBILITY GAP]**: an Official entity was orphaned across a
  domain or behavior change and needs an explicit compatibility policy.
- **[OPEN]**: HACS switching, a Community 2.5.0 -> NG real upgrade, a longer
  MQTT/SolarVault soak, post-NG backup rollback and Production Go-Live remain
  open.

## Real Home Assistant upgrade runs

Environment: Home Assistant OS 18.3, Home Assistant 2026.10.4, Python 3.14.9
and HACS 2.0.5. The final run started from Official 2.0.0 at
`af97223ff17fc8f14314cbc6da7213a5eee7004d`, restored a complete Pre-NG backup,
installed the final uncommitted branch candidate by manually replacing the
integration code, and restarted Home Assistant. A second restart followed
without another restore or code change. No live registry exports, real serials,
credentials, IP addresses or private logs are included here.

**[REAL HA BACKUP RESTORE VERIFIED]**

- The complete Pre-NG Official 2.0.0 backup restored to the separate HA OS
  installation and provided the test's starting state.

**[REAL HA UPGRADE VERIFIED]**

- The Official ConfigEntry and main device survived code replacement.
- The Shelly/SmartMeter device migrated in place; no
  `identity_migration_blocked` warning remained.
- Reboot migrated in place and only one Restart button remained.
- Average SOC migrated in place to BMS SOC while preserving the original HA
  entity ID; only one BMS SOC entity remained.
- Auto Standby migrated in place; no orphaned Official Select or `_2` entity
  remained.
- The existing read-only Work Mode sensor remained active under its old entity
  ID, and the new NG Work Mode Select existed independently.
- Existing user entity settings remained intact and live MQTT telemetry was
  processed without a general setup or runtime failure.
- The second restart completed without creating duplicate devices or entities
  and without repeating a problematic migration.
- Jackery Device Registry deprecation warnings were absent on both restarts.

Earlier real code-replacement runs reproduced the Reboot, Average SOC, CT/Shelly
and Auto Standby identity gaps and the Work Mode sensor compatibility gap.
Those findings led to the migrations and conditional Legacy Work Mode bridge
described above and in the implementation sections below. The final candidate
passed the real upgrade checks listed here.

**[REAL HA REPRODUCED MIGRATION BUG]** Historical finding: Official Auto
Standby originally remained orphaned while NG created a separate Select. The
final candidate migrated it in place, as verified above.

**[REAL HA COMPATIBILITY GAP]** Historical finding: the Official Work Mode
sensor originally became orphaned across the `sensor` to `select` transition.
The final candidate kept the old read-only sensor active and added the NG
Select independently, as verified above.

**Expected / not a bug:** NG intentionally makes `isFollowMeterPw` unavailable
outside Work Mode 4. This workstream does not change that behavior.

**Compatibility Hardening:** the run exposed API deprecations:
`device_registry.async_get_device` (removal target 2027.8), deprecated registry
mapping access (2027.9), `DeviceEntry.config_entries` (2027.10) and `via_device=`
(2027.8). A central feature-detected compatibility layer now keeps HA 2025.8.0
support while using config-entry-scoped lookups, singular ownership and
`via_device_id` on HA 2026.8+. Focused automated tests pass against HA 2025.8.0
and the actual HA 2026.10.4 API. The final HA OS 2026.10.4 real run also
reported no Jackery-owned Device Registry deprecation warnings.

The final Official 2.0.0 -> NG manual code-replacement upgrade and Pre-NG full
backup restore are **[REAL HA UPGRADE VERIFIED]** and
**[REAL HA BACKUP RESTORE VERIFIED]**. The second restart confirmed idempotence.
This was not a HACS upgrade. Restoring a post-NG backup as rollback was not
tested. The Battery Count icon correction is UI-only, was made after the real
upgrade run, and is covered by its focused metadata test; it does not change
the migration or Device Registry path.

## Golden states

| Fixture | Devices | Representative entities |
| --- | ---: | --- |
| Official 2.0.0 | Main, Smart Plug, generic CT, Type 3 CT / Shelly | Average SOC, Reboot, EPS switch, plug power/switch, generic CT and ten Type 3 CT identities |
| Community 2.5.0 | Main, Smart Plug, 3-phase meter, expansion battery, collector | Main SOC/EPS switch and one representative entity per child, plus plug switch |
| NG before host scope | Same selected device families as Community | Same selected identity surface as the pre-migration NG code |

The main-device surface includes sensors and controls. Selected entities have
custom entity IDs, names and icons; user-disabled main and child entities plus
areas are represented, and devices receive `name_by_user` and areas before
migration.

## Official 2.0.0 -> NG

**Automated result: exact Official Reboot, Average SOC and Auto Standby
identities, Smart Plug identities and ten Type 3 CT identities migrate in
place. The Official Work Mode sensor remains a separate read-only entity only
when its exact registry ownership is proven. The generic Type 2 CT identity
without a proven NG target remains fail-closed.**

Official 2.0.0 emits host-prefixed child identifiers such as
`sub_{host}_{child}` and unique IDs such as
`jackery_{host}_plug_{child}_power`. The prior NG migration recognized the
Community global form but did not recognize this actual Official form. The
first regression expected the existing plug Device Registry row to become
`child:{host}:{child}`; before the fix it remained
`sub_{host}_{child}` and the linked entities were retained as unresolved.

Extending the same fixture to Official's real main EPS-switch constructor found
a second concrete gap: `jackery_{host}_main_swEps` remained unchanged while NG
would create `jackery_{host}_switch_swEps`. NG now migrates host-bound
`main_{key}` switch/number records to the platform-qualified ID in place, with
the existing target-conflict refusal preserved.

NG now recognizes the host prefix only when the same device's linked entity IDs
provide matching Official-format evidence. It then migrates known fields in
place. This avoids interpreting an arbitrary Community child serial that merely
starts with the host string. No record is deleted to complete the migration.

| Property | Before | After | Result |
| --- | --- | --- | --- |
| ConfigEntry ID / unique ID / data | Existing synthetic entry / host / token and topic | Same | Preserved |
| Main Device Registry ID | Existing row with host and entry identifiers | Same row, canonical host identifier | Preserved in place |
| Main EPS switch registry/entity ID | Existing Official row / customized entity ID | Same row and entity ID, platform-qualified unique ID | Preserved in place |
| Main Average SOC and Reboot | Existing Official rows / customized entity IDs | Same rows and IDs under current constructors | Preserved in place |
| Plug Device Registry ID | Existing `sub_{host}_{plug}` row | Same row, scoped NG identifier | Preserved in place |
| Plug entity IDs | User-customized IDs | Same | Preserved |
| Plug unique IDs | Official host-prefixed form | Canonical scoped NG form | Controlled migration |
| Type 3 CT Device and ten entity rows | Official `sub_{host}_{child}` / `ct` identities | Same rows under canonical child and SmartMeter identities | Preserved in place |
| User names, disabled state, icon, area | Customized | Same | Preserved |
| Duplicates | One row per selected identity | Same counts; no parallel entity | None |

The fixture preserves both Official CT shapes. The generic Type 2 CT record has
no proven one-to-one NG entity target; its row and device stay unchanged and
discovery for that child is blocked. For Official's persisted `Sub-device Type
3` record, the ten exact observed suffixes map to the current NG SmartMeter
constructor identities. The mapping requires the Official device identifier,
model/manufacturer, parent link, entry ownership and complete known entity set;
unknown fields or any conflict block the entire child plan.

Official Average SOC and Reboot mappings are exact and domain-specific. They
also require the same ConfigEntry and an exclusively owned main host device. An
occupied target is retained without changing either row.

Official Auto Standby is also a same-domain `select` migration. Its exact
`jackery_{host}_main_autoStandby` row is updated to the Unique ID emitted by the
current NG `JackeryAutoStandbySelect` constructor, after proving main-device
ownership and checking that the target is unoccupied. A target conflict retains
both records. The existing Entity Registry ID, HA entity ID, name, icon,
disabled state and area remain on the source row.

Work Mode cannot use an in-place Unique ID migration because Official exposed
it as a read-only `sensor`, while NG exposes a writable `select`. NG therefore
binds a read-only compatibility sensor to the exact existing Official sensor
row only when domain, platform, ConfigEntry, Unique ID and exclusive main-device
ownership all match. It reads normalized `workMode` from the existing
coordinator and adds no subscription or polling task. Fresh NG installations
do not get the Legacy sensor. A user-disabled Official row stays disabled.
Recorder tests cover pre-upgrade and post-upgrade states under the same entity
ID.

Evidence: **[UPSTREAM-CONSTRUCTOR-GENERATED TEST VERIFIED]** and, for the same
selected entity IDs, **[RECORDER TEST VERIFIED]**.

## Community 2.5.0 -> NG

**Result: safe under the tested conditions.**

Community 2.5.0 emits global child identifiers such as `sub_{child}` and IDs
such as `jackery_plug_{child}_power`. Current NG migrates the selected Smart
Plug, 3-phase meter, expansion battery and collector devices and entities to
host-scoped identities in place.

The ConfigEntry, Device Registry row IDs, Entity Registry row IDs, customized
entity IDs, names, disabled-by-user state, icons, `name_by_user` and areas are
unchanged. Re-running migration is idempotent. Exact pre/post registry counts
show no second ConfigEntry, main device, child device or selected entity.

Evidence: **[UPSTREAM-CONSTRUCTOR-GENERATED TEST VERIFIED]** and
**[RECORDER TEST VERIFIED]**.

## Older NG -> current NG

**Result: safe under the tested conditions.**

The selected older NG commit produces the global child identity surface that
predates current host scoping. The same four child families migrate in place,
retain all tested user customization, produce no duplicate records, and remain
unchanged on a second migration pass.

Evidence: **[UPSTREAM-CONSTRUCTOR-GENERATED TEST VERIFIED]** and
**[RECORDER TEST VERIFIED]**.

## Recorder continuity

For every route, representative main SOC, plug power and meter entities receive
a state before migration and a second state afterward. Both values remain
queryable from Home Assistant's SQLite recorder under the unchanged customized
entity ID. The Entity Registry row ID is unchanged and no `_2` replacement is
created. This is **[RECORDER TEST VERIFIED]**, not merely an entity-ID proxy.
The Official Work Mode compatibility sensor also retains both pre-upgrade and
post-upgrade states under its existing entity ID.

The generic Type 2 CT record retains its original entity ID and history because
migration fails closed without deleting or replacing it. Recorder tests also
write states before and after the Type 3 mapping for total import power, total
export power and total import energy under the same entity IDs.

## Conflicts and duplicate prevention

A pre-existing target unique ID owned by another ConfigEntry blocks the
affected child or exact main identity operation. The conflicting legacy row,
user settings and history anchor are retained, no foreign row is overwritten,
and safe sibling migration continues. Existing interrupted/resumable,
ambiguous ownership, idempotency and multi-entry tests remain part of the
regression group.

After safe migration, current NG setup and discovery reuse the same selected
registry rows. Tests compare registry IDs and exact isolated migration counts,
not only aggregate entity totals.

## Rollback and downgrade

### Code-only downgrade

**Result: not registry-safe.**

After NG scopes child identities, loading Official 2.0.0 or Community 2.5.0
constructors against that persistent state registers their older identity
namespace as additional Device and Entity Registry rows. This can split entity
IDs and recorder history. NG will not weaken its forward migration or delete
records to make an old integration understand the new namespace.

A future user-facing release procedure must therefore say: create a Home
Assistant backup before switching integration code; do not rely on a code-only
downgrade as rollback.

### Full-state restore

The test suite removes the migrated selected registry state and rebuilds the
complete pre-upgrade ConfigEntry/device/entity semantics from the pinned
fixture. Identifiers, user names, disabled state, icons and area assignments
match the saved snapshot. This is
**[SEMANTIC SNAPSHOT RESTORE TEST VERIFIED]**.

It is not a Home Assistant backup subsystem test and does not restore an actual
recorder database image. Separately, the Pre-NG Official full-backup restore is
**[REAL HA BACKUP RESTORE VERIFIED]**. A HACS code switch and rollback by
restoring a post-NG backup remain **[OPEN]**.

## Remaining real-world evidence

- Actual HACS switch from Official or Community to NG on a backed-up HA
  installation.
- A real Community 2.5.0 -> NG upgrade on a backed-up HA installation.
- A longer MQTT/SolarVault soak and Production Go-Live qualification.
- Anonymized user registry and recorder exports covering more historical
  releases and customization patterns.
- Rollback by restoring a post-NG Home Assistant backup, including its recorder
  data and integration files.
- Rollback documentation tested through the user-facing Home Assistant/HACS UI.

Hardware is not required to establish registry identity, but these installation
operations remain necessary before claiming real-world upgrade safety.
