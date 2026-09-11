# Baseline checks and results

Analysis date 2026-09-11 UTC; commits and environment: [baseline](baseline.md). Production code, tests, pyproject.toml and uv.lock were not changed. No device or live MQTT broker was contacted. Log evidence: [baseline-evidence](baseline-evidence/).

## Results

| Check | Exact command | Result / classification |
| --- | --- | --- |
| Dependency setup | `UV_CACHE_DIR=/tmp/jackery-uv-cache uv sync --frozen --group test --group lint` | Initial sandbox download failed DNS resolution at files.pythonhosted.org; **environment/setup failure**. Same command outside sandbox completed. Lockfile unchanged. |
| Full tests (initial) | `.venv/bin/pytest tests/ -v` | Collected 174, first 3 passed, stalled during teardown; interrupted (exit130), no valid coverage result from this attempt. **Environment/setup failure**, not failed assertions. |
| Timeout diagnostic | `.venv/bin/pytest tests/ -v --timeout=30` inside sandbox | Timeout during teardown, thread stack includes pycares `_run_safe_shutdown_loop`; subsequent tests proceeded intermittently, then interrupted (exit130). No repo edit. |
| Full tests (authoritative local run) | `.venv/bin/pytest tests/ -v --timeout=30` outside sandbox | **174 passed in 2.98s**, exit0. Statement coverage **60.78%**, threshold 50% passed. [Full log](baseline-evidence/pytest.txt). Only sandbox boundary/timeout changed, no tests suppressed. |
| Ruff | `.venv/bin/ruff check custom_components/jackery/` | **PASS**, exit0; [log](baseline-evidence/ruff.txt). No --fix used. |
| mypy with HA installed | `.venv/bin/mypy custom_components/jackery/` | **23 errors in 3 files**, exit1; [full findings](baseline-evidence/mypy-with-ha.txt). Existing typing defects under combined dependency environment; see below. |
| CI-style lint-only setup | `UV_CACHE_DIR=/tmp/jackery-uv-cache UV_PROJECT_ENVIRONMENT=/tmp/jackery-baseline/lint-venv uv sync --frozen --group lint` | PASS, same lock, separate environment (runtime paho + lint group, no HA test group). |
| CI-style mypy | `/tmp/jackery-baseline/lint-venv/bin/mypy custom_components/jackery/` | **PASS**, exit0, 7 files; [log](baseline-evidence/mypy-lint-only.txt). Matches repository's separate lint job dependency scope. |
| Translations | `python3 tools/check_translations.py` | **PASS**, de/en/fr have all base leaf keys; [log](baseline-evidence/translations.txt). Not a translation-quality review or Hassfest replacement. |
| Hassfest local attempt | `docker run --rm -v /home/fredmin/projects/ha-jackery-solarvault-ng:/github/workspace:ro ghcr.io/home-assistant/hassfest` | **Environment/setup failure**: docker command absent (127). No local validator result. |
| HACS local attempt | `docker run --rm -e INPUT_CATEGORY=integration -e INPUT_COMMENT=false -v /home/fredmin/projects/ha-jackery-solarvault-ng:/github/workspace:ro ghcr.io/hacs/action:main` | **Environment/setup failure**: docker absent (127). Does not establish complete local Actions/GitHub context. No comment or external write was made. |
| Existing baseline CI | `gh run list --repo csoscd/ha-solarvault --limit 5 --json databaseId,headSha,conclusion,url`; `gh run view 31801070343 --repo csoscd/ha-solarvault --json jobs,headSha,url,conclusion` | Read-only query outside sandbox after sandbox API connection failure. **PASS historically at exact C SHA**: Tests, Lint, HACS and Hassfest all succeeded. [Job/step evidence](baseline-evidence/upstream-ci.json). This is not a fresh validation of fork metadata. |
| Release script syntax | `bash -n release.sh prepare_release.sh` | PASS. Scripts read completely but **not executed**: they alter versions/tags, push and create releases. Their independent validation commands are covered here. |
| Whitespace / unchanged tracked tree | `git diff --check`; `git diff --exit-code HEAD -- custom_components/jackery tests pyproject.toml uv.lock .github/workflows/validate.yml` | PASS. Additional untracked documentation checks described below. |
| Coverage extraction | `.venv/bin/python -m coverage json -o /tmp/jackery-baseline/results/coverage.json` | PASS; read-only analysis of authoritative test coverage. Root .coverage subsequently moved to /tmp. |

The configured workflow is [.github/workflows/validate.yml](../.github/workflows/validate.yml). It runs pytest, Ruff, mypy, translation completeness, HACS and Hassfest; it does not configure formatter, Markdown lint or separate build checks. Its commands `uv run pytest tests/ -v`, `uv run ruff check ...`, `uv run mypy ...` were executed via the installed venv binaries to keep the frozen combined environment stable. The shell's `python` alias was absent, so the translation command used `python3` instead.

The current [Hassfest action definition](https://raw.githubusercontent.com/home-assistant/actions/master/hassfest/action.yml) invokes its Docker image; [HACS action](https://raw.githubusercontent.com/hacs/action/main/action.yml) is Docker-based and has comment output enabled by default, so the attempted local command explicitly disabled comments. Historical exact-C validation: [Validate job](https://github.com/csoscd/ha-solarvault/actions/runs/31801070343/job/94768919465), HACS/Hassfest success 2026-08-14. Moving action references and Docker tags are not pinned in repository CI.

## Coverage interpretation

| Module | Statements | Missed | Rounded coverage |
| --- | --- | --- | --- |
| __init__.py | 87 | 19 | 78% |
| button.py | 28 | 2 | 93% |
| config_flow.py | 51 | 20 | 61% |
| number.py | 82 | 2 | 98% |
| select.py | 99 | 30 | 70% |
| sensor.py | 1078 | 478 | 56% |
| switch.py | 156 | 69 | 56% |
| Total | 1581 | 620 | 61% (60.78% exact report) |

No pre-existing pytest assertion failures were observed in the successful run. Main MQTT startup, polling/publishing, HTTP, dynamic child creation, options and completed reauth are largely unexecuted. High percentage for number/button mostly means constructors ran, not that commands were transmitted. See [test map](test-coverage-map.md) for every test and critical gaps.

## mypy discrepancy

With HA installed, sensor.py has 19 findings (heterogeneous config dictionaries inferred as object, optional config strings passed to str parameters, optional unique_id used for registration); switch.py has one mixed entity list type finding; number.py has three object-to-float findings. These are **actual pre-existing typing findings** in that environment, not introduced documentation regressions. Their exposure depends on the dependency environment: same mypy 2.3.0 and same source pass in the separate lint-only environment with missing HA imports ignored. This explains why the existing CI-style check can be green without proving HA-aware type correctness. Runtime impact of each individual typing error has not been established; do not label all 23 as runtime bugs or silence them by weakening mypy.

## Source-confirmed behavior probes

For accurate baseline classification, the following small in-memory probe was executed with `.venv/bin/python -` from the repository root (no network or added test files). It uses real production classes and synthetic identifiers; it does not validate real hardware semantics:

```python
import json
from unittest.mock import patch
from custom_components.jackery.sensor import (
    JackeryDataCoordinator, JackerySmartMeterHttpSensor,
    SMARTMETER_HTTP_SENSOR_CONFIGS,
)
from tests.conftest import FakeMqttMsg

c = JackeryDataCoordinator(None, "hb", "testtoken", "localhost", "MAIN")
with patch("custom_components.jackery.sensor.time.time", return_value=123456):
    c._handle_message(FakeMqttMsg("hb/device/OTHER/status", "{}"))
print("wrong_SN_heartbeat", c._last_update_time, "cache", c._data_cache)
c._handle_message(FakeMqttMsg("hb/device/MAIN/status", json.dumps({
    "type": 23, "body": {"deviceSn": "MAIN", "pvEgy": 123},
})))
print("main_SN_type23_pvEgy", c._data_cache.get("pvEgy"))
for value in [100, 200]:
    c._handle_message(FakeMqttMsg("hb/device/MAIN/event", json.dumps({
        "type": 106, "body": {"pvPw": value},
    })))
print("two_type106_pvPw", c._data_cache["pvPw"])
s = JackerySmartMeterHttpSensor(
    "METER", "frequency", SMARTMETER_HTTP_SENSOR_CONFIGS["frequency"], c, "ENTRY",
)
c.register_sensor("http_METER_frequency", s)
try:
    c._distribute_data({})
except Exception as exc:
    print("http_dispatch", type(exc).__name__, str(exc))
print("empty_CT_grid_available", c._calculate_energy_flow({"cts": [{}]})["grid_available"])
```

Observed output:

```text
wrong_SN_heartbeat 123456 cache {}
main_SN_type23_pvEgy None
two_type106_pvPw 100
http_dispatch AttributeError 'JackerySmartMeterHttpSensor' object has no attribute '_update_from_coordinator'
empty_CT_grid_available True
```

HTTP interface mismatch and foreign-SN heartbeat are **repository defects** established by source and probes. Main-SN type23 loss is a compatibility gap against O. 106 freeze and empty-CT availability are established C behavior; desired policy needs separate regression design and device evidence. Further source-observed risks (cached data reviving unavailable entities, unsubscribe omission, collector migration) are documented without claiming automated regression protection or verified hardware consequences.

## Scope verification

### Official startup probe

Executed `/home/fredmin/projects/ha-jackery-solarvault-ng/.venv/bin/python -` with working directory `/tmp/jackery-baseline/official` (the O archive). This imports **Official**, without altering either implementation:

```python
import json
from types import SimpleNamespace
from custom_components.jackery.sensor import JackeryDataCoordinator
c = JackeryDataCoordinator(None, "hb", "testtoken", "localhost", "MAIN")
c._handle_message(SimpleNamespace(
    topic="hb/device/MAIN/event",
    payload=json.dumps({"type": 101, "body": {"devType": 2, "cts": [
        {"deviceSn": "METER", "devType": 3, "tPhasePw": 50},
    ]}}),
))
print("official_first_CT_known", sorted(c._known_plugs))
print("official_first_CT_derived_present", "calc_home_power" in c._data_cache)
print("official_first_CT_cache_keys", sorted(c._data_cache))
```

Observed: error log `Error handling message: 'plugs'`; known list `[]`, derived present `False`, cache keys `['cts']`. **Official repository defect**: category2-first full report hits an uninitialized plugs key before discovery. This was a one-off baseline probe, not a port or a new test-suite addition.

### Final documentation and source checks

All 14 requested Markdown files exist, generated entity table contains all runtime dictionary definitions, and the complete test index contains all 174 source test cases. Local Markdown file links and pinned source line ranges were checked; Python files and tracked baseline inputs were byte-compared to HEAD. New Markdown/text files were checked for trailing whitespace. Only documentation created by this task remains untracked alongside the user-supplied AGENTS.md. No tests were edited, checks disabled, runtime behavior changed, branch merged or feature ported.
