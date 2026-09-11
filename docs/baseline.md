# Phase 0/1 engineering baseline

Analysis date: **2026-09-11 (UTC)**. Scope: source analysis, existing checks and documentation only. The user request takes precedence over the broader future implementation milestone in [AGENTS.md](../AGENTS.md). In particular, `COMMUNITY_ONLY` is used instead of the policy's `LOCAL_ONLY` label. No Phase 2 implementation is included.

## Repository identity

| Role | Repository / ref | Exact commit |
| --- | --- | --- |
| Development | `origin`: `fred-head/ha-jackery-solarvault-ng`, branch `refactor/v3-foundation` | `183d74b7e042061ccb985ddc023b3cb7a085452e` |
| Community baseline (C) | `upstream-community`: `csoscd/ha-solarvault`, `main` | `183d74b7e042061ccb985ddc023b3cb7a085452e` |
| Official baseline (O) | `upstream-official`: `Jackery-Official/jackery`, `main` | `af97223ff17fc8f14314cbc6da7213a5eee7004d` |

At the start, tracked files were clean; the user-provided root `AGENTS.md` was untracked. It was read completely and left unchanged. All three remotes have the expected fetch and push URLs. Local `origin/HEAD` points to `origin/main`; both upstream default branches were verified as `main` using `git ls-remote --symref`. Both remote HEADs equal the local analysis refs, so fetching was unnecessary. No merge, reset, checkout, commit, push or remote reconfiguration was performed.

Community `v2.4.0` points directly to C (release published 2026-08-14); `v2.4.0-rc1` points to `2787acade83acbc6de89523bc96e49cbaafb94ca`. Official `v2.0.0` points to `99de53cf1ef46dee17ba26c779e2b02f3383ec0d` (release published 2026-07-22); O is a later main commit. Official `v2.0-beta` also points to O. Local tags mix upstream histories: notably local `v2.0.0` is the **community** tag, so it must not be used to identify the official release. Remote tag ownership was verified separately.

## Environment

| Item | Baseline |
| --- | --- |
| System and test Python | CPython 3.13.5, Linux; system command `python3` (`python` absent outside venv) |
| Requested Python | `.python-version`: 3.13; `pyproject.toml`: >=3.13; CI: 3.13 |
| Installed HA test dependency | Home Assistant 2026.2.3 |
| Test packages | pytest 9.0.0; pytest-homeassistant-custom-component 0.13.316; pytest-asyncio 1.3.0; pytest-cov 7.0.0 |
| Lint packages | Ruff 0.16.0; mypy 2.3.0 |
| Dependency manager | uv 0.12.3 (x86_64-unknown-linux-gnu) |
| Integration manifest version | Community 2.4.0; official 2.0.0 |
| Package metadata version | Community `pyproject.toml` still 2.0.0; not the HA integration version |
| Runtime dependency | HA MQTT integration; Python project declares paho-mqtt >=2.1.0, but integration publishes/subscribes through HA MQTT |
| HACS advertised minimum | `hacs.json`: HA 2024.1.0; **not verified** against this older HA version |
| Real hardware / broker | None connected or exercised during this analysis |

Dependencies were installed from the unchanged `uv.lock` using `uv sync --frozen`. Combined test/lint environment: `.venv`; separate CI-style lint environment: `/tmp/jackery-baseline/lint-venv`. The venv is ignored by Git. Test artifacts were moved out of the root; selected logs are retained under [baseline-evidence](baseline-evidence/).

## Evidence conventions

All `C sensor.py:NN` references mean `custom_components/jackery/sensor.py` at C; likewise other platform filenames. `O` means the same path at O. Tests refer to `tests/` at C. Source anchors remain valid while this documentation-only change leaves production and tests untouched.

Pinned trees: [community integration](https://github.com/csoscd/ha-solarvault/tree/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery), [official integration](https://github.com/Jackery-Official/jackery/tree/af97223ff17fc8f14314cbc6da7213a5eee7004d/custom_components/jackery), [community tests](https://github.com/csoscd/ha-solarvault/tree/183d74b7e042061ccb985ddc023b3cb7a085452e/tests).

Both complete Python implementations, configuration manifests, entity dictionaries, translation structure, READMEs and relevant history were inspected. Official has no test suite in its tree. The official snapshot was read from `git archive upstream-official/main` extracted under `/tmp`, not copied into production. Model claims from README/changelog are explicitly attributed; synthetic test success is not hardware certification. Findings labelled **source observation**, **probe**, **upstream report**, **unknown** or **proposal** should not be conflated.

Start with [the final report](phase-0-1-report.md), then consult the inventories and [check results](baseline-test-results.md).
