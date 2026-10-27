# Release and compatibility contract

## Status

SolarVault NG is an experimental, pre-stable custom integration. This contract
makes repository metadata and release operations consistent; it does not make
the integration production-proven and does not publish a release. A Pre-NG
Official full-backup restore and a manual Official 2.0.0 -> NG code-replacement
upgrade are verified on HA OS 18.3 / HA 2026.10.4, including the migration fixes
and a second restart. Actual HACS switching, a Community 2.5.0 real upgrade,
long-running SolarVault/broker soak, and rollback from a post-NG backup remain
open. The real evidence is detailed in the
[upgrade/migration validation](upgrade-migration-validation.md).

The compatibility audit used foundation
`529c14f49af7faa197004309d903201c760e398d`.

## Version authority

`custom_components/jackery/manifest.json` is the single authoritative source of
the integration release version used by Home Assistant and HACS. Its current
`2.4.0` value is retained in this hardening change; a future NG release changes
that value in a normal reviewed pull request before tagging.

`pyproject.toml` defines only the repository's Python test and maintenance
environment. Its project name ends in `-tooling` and its sentinel version is
`0.0.0`; neither value is an integration release version. `CHANGELOG.md` keeps
the release content under `[Unreleased]` until a separately reviewed version
change assigns it to a release.

## Home Assistant compatibility

The declared minimum is **Home Assistant 2025.8.0**. This is the first stable
Home Assistant version that provides every production API currently required
by NG, including the current
[Options Flow reload pattern](https://developers.home-assistant.io/docs/core/integration/options_flow/):

- `ConfigEntry.async_start_reauth(hass)`;
- `ConfigFlow._get_reauth_entry()`;
- `ConfigFlow.async_update_reload_and_abort(...)`; and
- `OptionsFlowWithReload`.

The boundary is evidence-based:

| Home Assistant | Evidence | Result |
| --- | --- | --- |
| 2025.7.0 | Isolated API probe on Python 3.13.5 | Negative boundary: `OptionsFlowWithReload` is absent. |
| 2025.8.0 | Isolated HA 2025.8.0 / Python 3.13.5 environment; 125 focused import, config-flow, migration, registry, setup, unload and reload tests using `pytest-homeassistant-custom-component` 0.13.269 | Minimum-version APIs, integration imports, legacy registry ownership, child parent links and lifecycle behavior pass. |
| 2026.2.3 | Repository lock and complete quality suite | Current development reference: 1,584 tests pass with 96.15% statement coverage. |
| 2026.10.4 | Isolated HA 2026.10.4 / Python 3.14.2 focused tests and HA OS 18.3 / Python 3.14.9 real upgrade test | Scoped lookups, singular ownership, parent IDs and migrations pass with deprecation hooks failing in tests. The manual code-replacement upgrade, Pre-NG full-backup restore and second restart reported no Jackery Device Registry deprecation warnings. |

The negative and positive API boundary was also checked directly against the
official Home Assistant Core
[`2025.7.0`](https://github.com/home-assistant/core/blob/2025.7.0/homeassistant/config_entries.py)
and
[`2025.8.0`](https://github.com/home-assistant/core/blob/2025.8.0/homeassistant/config_entries.py)
sources.

The 2025.8 test environment used the historically compatible
`pycares` 4.11.0 because resolving the old Home Assistant package against the
current unconstrained package index selected an incompatible future `pycares`
major. This is test-environment dependency drift rather than an integration
failure. Intermediate Home Assistant releases are inside the declared range but
are not each a separate full-suite CI target.

### Device Registry compatibility hardening

Home Assistant **2025.8.0 remains supported**. `hacs.json` continues to declare
`2025.8.0`; this work does not raise the minimum. Compatibility is selected by
API feature detection in `custom_components/jackery/registry_identity.py`, not
by scattered version checks.

On HA 2025.8, the adapter uses the globally keyed device lookup, the
`config_entries` ownership set, and the supported `via_device` DeviceInfo form.
Ownership remains exclusive: a shared device is not treated as owned by either
entry. On HA 2026.8 and newer, it uses config-entry-scoped main/child identifier
lookups, `config_entry_id`, filtered `async_get_devices(identifiers=...)` for
conflict checks, public registry collection iteration, and `via_device_id` with
the resolved Home Assistant parent device ID. Conflicting identifiers remain
visible across entries while each entry resolves only its own parent.

Automated compatibility validation covers the minimum legacy registry model
and the actual HA 2026.10.4 Device Registry API. The latter confirms the new
API path and child identity migration without the observed
`homeassistant.helpers.frame` warnings. The manual HA OS 2026.10.4 upgrade and
second-restart logs also contained no Jackery Device Registry deprecation
warnings. The compatibility hardening is therefore **automated verified** and
**real HA verified**; the minimum remains HA 2025.8.0.

## Python and reproducible tooling

Home Assistant determines the Python runtime of an installed custom
integration. Home Assistant 2025.8.0 itself
[requires Python 3.13.2 or newer](https://github.com/home-assistant/core/blob/2025.8.0/pyproject.toml),
so NG does not claim a stricter runtime requirement.

Repository tooling is narrower and reproducible: `.python-version` and CI pin
Python 3.13.5, `pyproject.toml` accepts Python `>=3.13.2,<3.14`, `uv.lock`
resolves the current HA 2026.2.3 test environment, and CI installs it with
`uv sync --frozen`. This tooling range is not a promise that users select their
own Home Assistant Python version.

## Release source

Only an exact commit on `main` may be tagged. Development may continue on
`refactor/v3-foundation`, but the selected release commit must first reach
`main` through a reviewed merge. This hardening work does not merge branches,
change the default branch, create a tag, or publish a release.

The release repository is always
`fred-head/ha-jackery-solarvault-ng`. Documentation and support requests also
belong to that repository. The Official and Community repositories remain
credited as project lineage; they are never release destinations for NG.

## Release procedure

1. Change the manifest version and move the intended changelog entries out of
   `[Unreleased]` in a normal pull request.
2. Merge the reviewed release commit to `main` and wait for that exact commit's
   `Validate` workflow to pass, including HACS and Hassfest validation.
3. Check out the exact `main` commit with a clean tree and run
   `./release.sh vX.Y.Z`.
4. Review the preflight result. The script deliberately creates no commit, tag,
   push, or GitHub release.
5. Create the annotated tag and GitHub release manually only after that final
   review.

`release.sh` fails closed when the repository, branch, working tree, remote
commit, manifest version, tag state, dependency lock, local gates, or GitHub CI
evidence is wrong. Existing tags are immutable: the supported procedure never
deletes or overwrites one. The legacy `prepare_release.sh` was removed because
it could stage unrelated files, push automatically, and replace tags.

## Upgrade contract

For upgrades within NG, existing config entries, host and child identifiers,
entity unique IDs, device associations, user registry settings, and recorder
history are intended to survive a reload or migration. The focused
[upgrade/migration validation](upgrade-migration-validation.md) now derives
sanitized golden identity states from the actual constructors at pinned
Official 2.0.0, Community 2.5.0 and pre-host-scope NG commits. It replays those
states through real HA registries and the SQLite recorder.

Under those tested conditions, Community 2.5.0 and the selected older NG state
migrate in place without duplicate devices/entities or loss of ConfigEntry,
registry-row, entity-ID, user customization or recorder continuity. Official
2.0.0 main sensor/control, known Smart Plug identities, Average SOC, Reboot,
Auto Standby and the ten observed devType=3 CT identities are covered by
in-place migration tests. Work Mode remains a separate read-only sensor only
for an exact existing Official registry row; a fresh NG install gets only the
writable select. The generic Type 2 CT field without a proven NG entity mapping
remains retained and blocked rather than guessed. Ambiguous ownership and
target conflicts continue to fail closed. The Official 2.0.0 code-replacement
upgrade, including Reboot, Average SOC, CT/Shelly, Auto Standby and Work Mode,
was verified on real HA after restoring a Pre-NG full backup. The restore and
the second HA restart were also verified; no HACS upgrade is claimed.

Code-only downgrade after NG migration is not registry-safe: older Official or
Community identity constructors can create parallel child records and split
history. A complete pre-upgrade backup is therefore the intended rollback
boundary. Semantic fixture restoration is tested, but the project has not yet
performed an actual HACS switch or restored a post-NG backup as a rollback on
an installation. A Pre-NG Official full-backup restore before the verified
upgrade did succeed. No broader rollback guarantee is claimed.

## Remaining evidence

- Real broker disconnect/reconnect with a SolarVault and long-duration soak.
- Sanitized hardware/firmware fixtures across the supported device matrix.
- Actual HACS upgrades and a Community 2.5.0 -> NG real upgrade; the tested
  Official 2.0.0 code-replacement path is not evidence for either route.
- Longer MQTT/SolarVault soak and rollback by restoring a post-NG Home
  Assistant backup.
- Periodic compatibility runs across more Home Assistant releases between the
  evidenced floor and current development reference.
- A maintainer decision on command acknowledgement, timeout, and rollback.

See the [project status](project-status.md),
[MQTT reconnect validation](mqtt-reconnect-validation.md), and
[Phase 3 closeout decision basis](phase3-closeout-phase4-plan.md) for the wider
production-readiness context.
