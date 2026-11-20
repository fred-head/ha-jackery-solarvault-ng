# Issue #58: Official child registry reconciliation plan

Status: implemented on `fix/issue-58-official-child-reconciliation`, 2026-11-20.
Automated validation results are recorded below. No new Marketplace release or
hardware upgrade test is claimed by this change.

Issue: <https://github.com/fred-head/ha-jackery-solarvault-ng/issues/58>

## Problem and evidence

Official 1.0.0 used `sub_<child>` device identifiers. Official 2.0.0 added
the host to entity unique IDs but did not migrate the old device identifiers.
Discovery could consequently create a second Jackery device for the same child.
The reported state contains an old Type 2 record with two already host-prefixed
CT entities and a Type 3 record with ten newer CT entities. Both have the same
Jackery config entry and host parent. The separate Shelly integration is not
part of the conflict.

The source change and conflicting registry state are verified in the issue.
The personal Official 1.0.0 -> Official 2.0.0 installation sequence is an
accepted reconstruction with the evidence limits described there.

NG currently groups both records under one child and refuses migration with
`duplicate-device-target`. Its existing Official upgrade fixture does not
represent this sequential-upgrade residue.

## Agreed behavior

1. Recognize this specific, proven Official residue before child discovery.
2. Migrate the active Type 3 device and its supported entities in place into
   the existing canonical NG namespace. Preserve its HA device ID, entity IDs,
   entity registry IDs, user settings and recorder continuity.
3. Retain the old device and its two entity records as historical inventory.
   Preserve their identities, customization and existing history. Do not
   automatically delete, merge or reassign them, disable user entities, or
   rewrite automations and dashboards.
4. Distinguish the retained historical device from active discovery candidates.
   It must neither block the active child nor be recreated as another active
   device. Protect its entities from unrelated identity migrations and cleanup.
5. Do not assign new measurements to the old sensors. Their historical subtype
   dependent semantics are not proven equivalent to the newer total sensors.
   The notice must explain that these old sensors will not receive new readings.
6. Remove the migration block and conflict warning only for the verified case.
   Unknown, shared, foreign or ambiguous records must still fail closed.

This deliberately retains two device cards until the user chooses to remove
the historical one. It is not a general device merge feature.

## User-visible marking and explanation

- Add an explicit HA label to the historical device, with suggested wording
  `Jackery: Altbestand – prüfen`. Preserve all existing labels.
- Optionally append an old-inventory marker to the integration-provided device
  name. Never overwrite a user-provided name. Exact wording and localization
  are implementation details; the visible marking must also work for devices
  with a custom name.
- Provide a one-time, dismissible notification linking to the historical and
  active device cards. Explain that an earlier Official update left duplicate
  Jackery records and NG has completed takeover of the active device.
- Ask the user to review references to the old sensors in automations,
  dashboards and external monitoring, and move them if necessary. Do not claim
  that all external references can be detected automatically.
- Explain that keeping the historical card is allowed, and that the user can
  delete it after checking. Deleting it also removes its associated entity
  registry entries; do not promise indefinite history access after deletion.
- Do not emit a recurring conflict warning for a successfully reconciled case.
  Persist notification acknowledgement so restart/reload does not repeatedly
  announce the same event. Clear an obsolete notice when its old device is gone.

## User-controlled deletion

Support removal of the verified historical device through the normal HA UI.
The current integration does not implement `async_remove_config_entry_device`;
the implementation must cover the supported HA device registry API versions.

Authorize removal using proven registry ownership and historical classification,
never a user-editable device name or label alone. Do not expose the active host,
active child or a foreign integration's device to this special removal path.
Deleting the historical device must leave the active device and its entities
intact. Restart, reload and later discovery must not recreate the old card.

## Recovery after RC1: no restore prerequisite

The intended supported paths include both:

- Official 1.0.0 -> Official 2.0.0 -> fixed NG release.
- Official 1.0.0 -> Official 2.0.0 -> NG 3.0.0-rc.1 with the reported block ->
  fixed NG release (for example RC2).

The current migration runs on every setup, before platform creation. For the
reported duplicate-device conflict it retains both affected device records and
their entities and vetoes that child's writes. The refusal is not a permanent
"migration completed" marker. A later release can therefore inspect and handle
the retained state on the next setup after updating and restarting HA.

The fix must use persisted registry evidence, not require a first-time Official
upgrade or gate recovery on a config-entry version change. Other children may
already have migrated successfully in RC1; preserve that work. Users must not
need to restore their pre-RC1 backup, uninstall NG, delete the config entry or
manually modify registries to recover this known case.

The regression suite exercises the RC1 refusal path followed by the new
migration on the retained state. This is not a released RC2 or a live Marketplace
upgrade test. Unexpected manual changes or additional conflicts
must retain the normal fail-closed behavior and actionable recovery guidance.

## Implementation boundaries

Extend the existing preflight/plan/apply migration incrementally. Prove exclusive
entry ownership, the same exact host parent, expected legacy/Official identities,
known linked entities and unoccupied canonical targets before applying changes.
Model strings and timestamps alone are insufficient evidence. Include supported
modern HA child registries, which may not retain model/manufacturer metadata.

The recognized state must remain recognizable after active identities become
canonical and discovery adds further supported NG entities. Make partial writes
resumable, and marking/notification idempotent. Do not weaken unrelated conflict
checks or change measurement semantics, source precedence or protocol handling.
Use sanitized diagnostic references; never disclose serials or credentials.

## Required validation before release

- Add a sanitized sequential-upgrade fixture with the two old, host-prefixed
  entities and ten newer entities on the separate same-child devices.
- Test direct Official -> fixed NG and, explicitly, RC1 refusal -> fixed NG.
  Capture the blocked state before applying the fix. Include already migrated
  safe siblings and assert that no backup restore or manual repair is needed.
- Verify active discovery and readings resume, the known conflict warning is
  absent, and no replacement entities or third device card are created.
- Verify retained device/entity IDs, custom names, labels, user settings and
  recorder history using real HA registries and recorder tests where applicable.
- Test repeated setup, restart, partial/interrupted migration, notification
  dismissal persistence, user deletion and subsequent discovery without revival.
- Test that ambiguous/foreign records remain untouched and blocked, and that
  the separate Shelly integration remains unchanged. Exercise supported legacy
  and modern HA registry shapes.
- Run focused checks during implementation and the full applicable project
  quality gates before release, using the persistent temporary/cache paths
  required by `AGENTS.md`.
- Update the changelog, upgrade/troubleshooting guidance and relevant maintainer
  references to describe the implemented and verified behavior.

## Automated validation, 2026-11-20

The implementation retains and labels historical inventory, migrates the active
meter, and provides localized notification and user-controlled deletion. The
per-entry store also prevents reactivating a historical card after the active
meter is unbound. Store IDs are hints that always require fresh registry
validation, including when a deletion request carries an older device snapshot.

| Check | Result |
| --- | --- |
| Before changes: full project suite, HA 2026.2.3 | 1,690 passed, 94.02% statement coverage |
| After changes: full project suite, HA 2026.2.3 | 1,721 passed, one expected modern-only skip, 94.13% statement coverage |
| Issue #58 and registry compatibility tests, HA 2025.8.0 / Python 3.13.5 | 39 passed, one expected modern-only skip |
| Same focused tests, HA 2026.10.4 / Python 3.14.10 | 39 passed, one expected legacy-only shared-ownership skip; includes real lightweight children with deprecation hooks failing on access |
| Ruff, mypy (37 modules), translation completeness and release contract | Passed |
| Hassfest, official HA 2026.10.4 scripts, all custom-integration checks | Passed; zero invalid integrations |
| HACS action | Pending CI: the configured Docker action cannot run locally because this user has no Docker-socket access and sudo requires a password |

Compatibility environments, upstream validator checkout, logs and test workspaces
are under `/home/fredmin/.cache/tmp`; uv downloads use `/home/fredmin/.cache/uv`.
The HA 2025.8 test environment uses `pycares<5` and wheel-compatible test-only
overrides `lru-dict==1.4.1` / `ciso8601==2.3.3`: the original pins require a C
compiler absent from this host. No project or production dependency was changed.

These are automated registry, runtime/platform and recorder checks. Neither a
new release nor a live Marketplace update on the maintainer's installation was
performed. The release manifest remains at RC1 until a separate release step.
