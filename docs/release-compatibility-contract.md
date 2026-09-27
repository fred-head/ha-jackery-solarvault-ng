# Release and compatibility contract

## Status

SolarVault NG is an experimental, pre-stable custom integration. This contract
makes repository metadata and release operations consistent; it does not make
the integration production-proven and does not publish a release. Real
SolarVault/broker soak evidence, a sanitized hardware fixture matrix, and
upgrade testing from exported Home Assistant registries remain open.

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
| 2025.8.0 | Isolated import/API probe plus 17 focused config-flow, options, reauth, setup and unload tests using `pytest-homeassistant-custom-component` 0.13.269 | Required APIs, all integration-module imports, and the focused lifecycle block pass. |
| 2026.2.3 | Repository lock and complete quality suite | Current development reference: 1,529 tests pass with 96.50% statement coverage. |

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
history are intended to survive a reload or migration. Synthetic Home Assistant
tests cover in-place main and child unique-ID migration, conflict refusal,
interrupted migration recovery, idempotence, registry ownership, multi-entry
isolation, and recorder continuity.

The same tests give useful confidence for installations inherited from the
Community fork because NG retains the established domain and config-entry
shape. They do not prove every real upgrade path. The project has not yet run a
HACS upgrade and rollback against anonymized exported registries/backups from
each historical Community release. Ambiguous ownership continues to fail
closed rather than guessing, and no rollback guarantee beyond Home Assistant's
normal backup restore is claimed.

## Remaining evidence

- Real broker disconnect/reconnect with a SolarVault and long-duration soak.
- Sanitized hardware/firmware fixtures across the supported device matrix.
- Exported-registry HACS upgrade and rollback qualification.
- Periodic compatibility runs across more Home Assistant releases between the
  evidenced floor and current development reference.
- A maintainer decision on command acknowledgement, timeout, and rollback.

See the [project status](project-status.md),
[MQTT reconnect validation](mqtt-reconnect-validation.md), and
[Phase 3 closeout decision basis](phase3-closeout-phase4-plan.md) for the wider
production-readiness context.
