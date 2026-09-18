# HA-aware typing audit

Baseline: `9b3476ad95d779d80c837e8d2d3bde1413ddce0c`. Reproduced from a
`git archive` snapshot with the installed HA environment and
`mypy --no-incremental custom_components/jackery/`: 23 errors in four files.
Audit completed before corrective production edits. Line numbers below refer
to that baseline. These are 23 diagnostics, not 23 demonstrated runtime bugs.

| # | File:line / original diagnostic | Root cause and possible runtime types | Attempt in de87833 / assessment | Classification / corrective direction |
| --- | --- | --- | --- | --- |
| 1 | __init__.py:186 token Any or None → str [arg-type] | ConfigEntry values are not validated on restore; str, missing/None or malformed objects possible | cast(str): no validation, rejected | UNVALIDATED_RUNTIME_VALUE: validate setup boundary; preserve optional None token semantics |
| 2 | __init__.py:187 mqtt_host Any or None → str [arg-type] | Current config flow omits this legacy field; str or None expected, malformed objects possible | cast(str): incorrectly claims a required string | OPTIONAL_NARROWING: type legacy field as optional and validate when present |
| 3 | __init__.py:187 device_sn Any or None → str [arg-type] | Flow requires str; restored entries may be malformed; existing missing-host adoption must remain | cast(str): unsafe before migration | UNVALIDATED_RUNTIME_VALUE: validate before migration; preserve absent/empty host behavior |
| 4 | switch.py:89 PlugSwitch → MainSwitch [arg-type] | List legitimately contains both SwitchEntity subclasses | list[SwitchEntity]: accurate, retain | UNION_NARROWING: explicit common base |
| 5 | sensor.py:724 object.items [attr-defined] | Child group is dict[str, child metadata]; inference collapses heterogeneous metadata | nested Any cast hides field types, rejected | REAL_TYPE_BUG: declare child metadata TypedDict at source |
| 6 | sensor.py:764 object.items [attr-defined] | Expansion group has the same metadata schema | nested Any cast rejected | REAL_TYPE_BUG: typed child groups |
| 7 | sensor.py:1171 object.get [attr-defined] | Main sensor metadata, json_key is str or None | Any cast rejected | REAL_TYPE_BUG: main metadata TypedDict |
| 8 | sensor.py:1199 object not indexable [index] | unit is str enum/string or None | Any cast rejected | REAL_TYPE_BUG: typed unit field |
| 9 | sensor.py:1200 object not indexable [index] | icon is str | Any cast rejected | REAL_TYPE_BUG: typed icon field |
| 10 | sensor.py:1201 object not indexable [index] | device_class is SensorDeviceClass or None | Any cast rejected | REAL_TYPE_BUG: typed device_class field |
| 11 | sensor.py:1202 object not indexable [index] | state_class is SensorStateClass or None | Any cast rejected | REAL_TYPE_BUG: typed state_class field |
| 12 | sensor.py:1207 object.get [attr-defined] | options is optional list[str] | Any cast rejected | REAL_TYPE_BUG: typed options field |
| 13 | sensor.py:1208 object not indexable [index] | options is list[str] when present | Any cast rejected | REAL_TYPE_BUG: typed options field |
| 14 | sensor.py:1240 object.get [attr-defined] | json_key is str or None; existing truthiness check narrows | Any cast rejected | REAL_TYPE_BUG: typed json_key field |
| 15 | sensor.py:1273 object.get [attr-defined] | value_map is optional dict[int, str] | Any cast rejected | REAL_TYPE_BUG: typed value_map field |
| 16 | sensor.py:1281 object.get [attr-defined] | scale is optional numeric, default 1 | Any cast rejected | REAL_TYPE_BUG: typed numeric scale |
| 17 | sensor.py:1284 object.get [attr-defined] | unit is str or None | Any cast rejected | REAL_TYPE_BUG: typed unit field |
| 18 | sensor.py:1298 object.get [attr-defined] | raw_key derives from str or None json_key | Any cast rejected | REAL_TYPE_BUG: typed json_key field |
| 19 | sensor.py:1385 optional unique_id → str [arg-type] | Constructor always assigns child_unique_id returning str; HA base permits None | conditional silently skips registration for None | OPTIONAL_NARROWING: declare constructor-established nonoptional attribute |
| 20 | sensor.py:1388 optional unique_id → str [arg-type] | Same constructor guarantee on removal | conditional skips removal for None | OPTIONAL_NARROWING: same nonoptional declaration |
| 21 | number.py:81 object → float [arg-type] | Static min values are numbers; dict inference includes strings/bools | float-or-str cast unsupported by source schema | REAL_TYPE_BUG: number metadata TypedDict |
| 22 | number.py:82 object → float [arg-type] | Static max values are numbers | same cast rejected | REAL_TYPE_BUG: typed numeric max |
| 23 | number.py:83 object → float [arg-type] | Static step values are numbers | same cast rejected | REAL_TYPE_BUG: typed numeric step |

Classification totals: 17 REAL_TYPE_BUG (declaration defects, not demonstrated
runtime failures), 3 OPTIONAL_NARROWING, 1 UNION_NARROWING and 2
UNVALIDATED_RUNTIME_VALUE. No finding has evidence of an HA stub defect.

## Every broad typing shortcut in the attempted commit

The two child-group casts, setup-loop cast, main `_config` cast and sub-entity
`_sensor_config` cast all concern repository-owned static metadata. None is
unconstrained. Per-field TypedDict declarations represent the values more
accurately than unions for entire dictionaries, protocols, runtime guards or
boundary validation. No new Any return/parameter annotation was introduced;
the imported Any already existed. Existing dynamic MQTT/cache/hass.data typing
is outside this correction; it must not be widened to hide metadata errors.
The three numeric casts likewise need source declarations, not assertions.
All four string casts (including the extra topic_prefix cast) need removal.
Topic prefix must be a string; optional token/legacy MQTT host and host adoption
must not be coerced into literal 'None' or otherwise change identity.

## Framework boundaries

ConfigEntry's generic data mapping does not guarantee strings on restore.
Validate before migration, platform forwarding or subscriptions, without
logging values. The schema normally provides token/device_sn and defaults the
topic prefix, but mqtt_host is intentionally absent. Registry lookup guards,
typed transport callbacks/tasks, existing per-entry hass.data storage and
platform callback ownership need no changes for these findings. The switch
list uses the actual HA base class; the entity unique ID has a stronger local
constructor guarantee than HA's optional base attribute. No stub ignore is
necessary for either case.

## Final disposition

| Original findings | Applied correction | Remaining diagnostics |
| --- | --- | --- |
| 1 | Read token as object, validate str or None before setup; coordinator matches the command builders' existing optional-token contract | 0 |
| 2 | Read mqtt_host as object and validate str or None; declare the unused legacy field optional | 0 |
| 3 | Validate a present device_sn as str before migration; missing key still passes None for host adoption, empty string remains empty | 0 |
| 4 | Declare list[SwitchEntity] for the actual mixed subclass collection | 0 |
| 5, 6 | Declare child/HTTP metadata fields in ChildSensorConfig and type the nested group dictionary | 0 |
| 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18 | Declare MainSensorConfig fields at the source, retaining values and lookup behavior | 0 |
| 19, 20 | Declare the constructor-assigned _attr_unique_id as str; retain unconditional registration and removal | 0 |
| 21, 22, 23 | Declare numeric min/max/step in NumberConfig; a NumberBounds view preserves the existing empty fallback for unknown keys | 0 |

All 23 original diagnostics are eliminated by these declarations and validated
narrowing, with no new casts or ignores relative to foundation. Five broad
metadata casts, three numeric casts and four unchecked string casts from
de87833 were removed. Two pre-existing assignment ignores became unnecessary
after explicitly declaring numeric/textual entity state (`float | str | None`).
That declaration also prevents the HA-free CI environment from inferring the
state solely from its first numeric assignment. This is accurate local typing,
not an HA stub exception. Existing dynamic payload handling is not rewritten.

There are **zero remaining HA/stub limitations among these 23 findings**.
The 17 REAL_TYPE_BUG entries are metadata declaration defects, not 17 runtime
crashes. Four diagnostics concern safe Optional/union declarations. Two concern
unvalidated runtime config; nine new malformed-input cases demonstrate the
shared boundary defect (including topic_prefix beyond the original diagnostics).

### Runtime evidence and scope

The 12 tests in `test_typing_boundaries.py` were run against the extracted,
unchanged foundation: **9 failed, 3 passed**. Three serial cases reproduced
`AttributeError` in migration; six other invalid configurations incorrectly
completed setup with mocked transport start. After correction all pass.
The three compatibility cases preserve absent fields, optional None values,
empty strings, explicit strings, the default topic and wildcard host topics.
Invalid present serial None is rejected rather than failing at `.strip()`;
missing serial still remains None. No string coercion is introduced, and the
error log contains no field values. Normal identity, routing, command, source,
availability and transport behavior are unchanged.

The metadata dependency test now permits only standard-library `typing` in
addition to its two original HA metadata imports. All metadata dictionary
values remain unchanged. Registry/task/callback behavior and hass.data storage
were reviewed but required no additional edits for this correction.

### Quality gate

The complete diff against foundation has no new broad Any annotations/casts,
unchecked string casts, identity conversions or broad ignores. ConfigEntry
inputs are explicitly object until validated. The protocol helper's host type
is now str or None to express the existing adoption state; its body is unchanged.
No unrelated cleanup or Phase 3 implementation is included.

### Final validation (2026-09-18)

| Gate / command | Result |
| --- | --- |
| Foundation snapshot: installed HA mypy `--no-incremental custom_components/jackery/` | 23 diagnostics reproduced in 4 files |
| Foundation snapshot: `pytest tests/test_typing_boundaries.py -q --no-cov --tb=line --show-capture=no --timeout=30` | 9 expected failures, 3 passes |
| Focused pytest: typing boundaries, sensor definitions, MQTT lifecycle, multi-instance identity, SmartMeter HTTP, commands, sub-device entities, v2.3 controls (`--no-cov --timeout=30`) | 369 passed |
| `.venv/bin/pytest tests/ -q --timeout=30 --tb=short` | 1,343 passed; 94.30% coverage; no skips/xfails |
| `.venv/bin/ruff check custom_components tests` | Passed |
| `.venv/bin/python tools/check_translations.py` | de/en/fr passed |
| `/tmp/jackery-baseline/lint-venv/bin/mypy --no-incremental custom_components/jackery/` | Passed, 25 files |
| `.venv/bin/mypy --no-incremental custom_components/jackery/` | Passed, 25 files; original 23 eliminated, zero remaining/new diagnostics |
| `git diff --check` | Passed |

The full-suite count increases by the 12 boundary cases, not by tests of type
annotations. Coverage's small increase includes executable TypedDict class
declarations; it is not evidence of broader runtime feature coverage.

PR #21 is technically ready for review outside draft after this correction.
It is deliberately left as a draft and not merged. There is no remaining
typing blocker in this audit; the separate final foundation/Phase 3 gate has
not been performed or approved by this PR.
