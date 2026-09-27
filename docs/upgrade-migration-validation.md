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
- **[OPEN]**: no equivalent real installation, HACS operation or HA backup
  restore has been performed.

## Golden states

| Fixture | Devices | Representative entities |
| --- | ---: | --- |
| Official 2.0.0 | Main, Smart Plug, generic CT | Main SOC/EPS switch, plug power/switch, CT forward power |
| Community 2.5.0 | Main, Smart Plug, 3-phase meter, expansion battery, collector | Main SOC/EPS switch and one representative entity per child, plus plug switch |
| NG before host scope | Same selected device families as Community | Same selected identity surface as the pre-migration NG code |

The main-device surface includes both a sensor and a control platform. The
selected entities are given custom entity IDs and names. One child sensor
is disabled by the user, selected entities receive icons and areas, and devices
receive `name_by_user` and areas before migration.

## Official 2.0.0 -> NG

**Result: safe for the tested main and mapped Smart Plug identities after a
reproduced migration fix; one richer Official CT identity remains fail-closed.**

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
| Plug Device Registry ID | Existing `sub_{host}_{plug}` row | Same row, scoped NG identifier | Preserved in place |
| Plug entity IDs | User-customized IDs | Same | Preserved |
| Plug unique IDs | Official host-prefixed form | Canonical scoped NG form | Controlled migration |
| User names, disabled state, icon, area | Customized | Same | Preserved |
| Duplicates | One main, one plug | Same counts; no parallel entity | None |

The selected Official generic-CT entity uses `powertotalforward`. Current NG has
no proven one-to-one entity target for that field. Its record and device are
retained unchanged, discovery for that child is blocked, and a warning is
emitted. This is safer than inventing a mapping or creating a replacement.
Resolving that semantic gap is **[OPEN]** and requires a separate protocol/entity
decision.

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

The unsupported Official CT record also retains its original entity ID and its
history because migration fails closed without deleting or replacing it.

## Conflicts and duplicate prevention

A pre-existing target unique ID owned by another ConfigEntry blocks only the
affected child. The conflicting legacy row, user settings and history anchor
are retained, no foreign row is overwritten, and safe sibling migration
continues. Existing interrupted/resumable, ambiguous ownership, idempotency and
multi-entry tests remain part of the regression group.

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
recorder database image. A real HA backup/restore, actual HACS code switch and
rollback on an installation remain **[OPEN]**.

## Remaining real-world evidence

- Actual HACS switch from Official or Community to NG on a backed-up HA
  installation.
- Anonymized user registry and recorder exports covering more historical
  releases and customization patterns.
- A complete Home Assistant backup/restore including recorder data and HACS
  integration files.
- Verification of any desired mapping for richer Official-only CT entities.
- Rollback documentation tested through the user-facing Home Assistant/HACS UI.

Hardware is not required to establish registry identity, but these installation
operations remain necessary before claiming real-world upgrade safety.
