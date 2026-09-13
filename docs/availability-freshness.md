# Availability and freshness audit

## Current state ownership

The Phase 2 state extraction stores host/child activity in the per-coordinator,
Home-Assistant-independent `CoordinatorRuntimeState`. It owns the exact
60-second host/child freshness comparisons and the startup grace calculation.
The coordinator supplies whether a child is a discovered expansion battery, so
the existing once-seen cumulative-energy exception is unchanged.

The state object returns decisions only. The coordinator still schedules timer
checks, changes entity `_attr_available`, writes HA state, maintains discovery
and missing/deletion sets, and removes registry objects. The calculation adapter
uses the same state answer and activity age for grid-source eligibility. Raw
cached values remain present when a source expires. HTTP health and failure
counters remain entirely separate from MQTT runtime state.

Reload creates a new runtime state; cache, activity timestamps, live/snapshot
evidence and source metadata never persist across coordinator instances.

The subsequent [energy/source policy](energy-source-policy.md) also applies the
existing child timeout to CT/collector selection. Incoming MQTT and the existing
timer reevaluate derived grid/home values; no remaining grid source makes the
grid entity unavailable. EPS null becomes unavailable without interrupting
fan-out. HTTP health, host/child timeouts and cumulative battery exceptions
remain intact. Per-measurement expiry beyond the eleven Type-106 preference
fields is not introduced; metadata-only child activity remains a known limit.

Scope: `fix/availability-freshness`, starting from the HTTP/MQTT dispatch fix
(`61b0f8c`). This is a correctness audit, not the architectural extraction.
All scenarios use synthetic data, not captured hardware traffic.

## Observed behavior before production changes

| Scope | Existing rule | Weakness to reproduce |
| --- | --- | --- |
| Host MQTT | Coordinator `_last_update_time`, initialized at construction; timeout strictly greater than 60 seconds. All registered entities are marked offline by the request loop. | Timestamp advances before topic SN and JSON validation. HTTP entities are included in host timeout. |
| Child MQTT | `_subdevice_last_seen[SN]`; arrays (101/102), points (102), expansion statistics (23). Startup grace for unseen children is strictly less than 60 seconds. Other children expire when age exceeds 60 seconds. | Checks run only during discovery on incoming messages with nonempty cached lists. Subsequent cached fan-out restores availability. Ordinary child statistics do not refresh last-seen. |
| Expansion energy | Once seen, cumulative energy remains valid without a time limit; never removed by the missing-list timer. | Host timeout currently also marks these counters unavailable. Preserve the documented cumulative-counter exception. |
| Membership | Nonempty child lists merge by SN; omitted children and empty lists retain cache. Missing-list removal uses the merged cache and a separate strictly greater than 60-second timer. | Whether 101 is authoritative membership is unresolved. Do not change list/deletion semantics. |
| HTTP | Separate update callback; three consecutive failed requests mark values unavailable; next numeric reading restores availability. Values remain cached. | JSON/type errors bypass failure counting; no-IP discovery waits indefinitely without counting failure. Host/child MQTT health checks also touch HTTP entities. |
| HTTP timing | Option defaults to 10 seconds, configured range 2–60 seconds; request timeout 5 seconds; no address retries every 30 seconds. Counter is local to one polling task. | Cancellation during the outer error-handler sleep bypasses trailing cleanup. |
| Reauthentication | Never-received hint after more than 120 seconds; explicit type123/401 also triggers it. | `_ever_received` is set before JSON validation. |

The request loop waits 2 seconds initially, sends a batch, then checks health and
sends another batch. Normal batches include three 0.5-second child-poll waits;
the next iteration follows a 10-second sleep. Timeouts therefore take effect on
the next loop check, not through an exact 60-second alarm. There is no separate
coordinator `available` property: the coordinator writes entity availability.
Main sensors, switches, selects and numbers generally restore availability from
their cached fields; follow-meter retains its work-mode restriction. The reboot
button does not register for coordinator updates and has no telemetry health gate.

## Identity and source contracts to preserve

Both wildcard subscriptions enter `_handle_message`. The topic identifies the
SolarVault host. Child SNs in type23 statistics, type101 arrays and type102 points
identify children relayed by that host; these are legitimate host activity.
Payload `deviceSn` is not a general host identity field. Do not require every
payload SN to match the host, or change main-SN type23 routing in this task.

Freshness is per host and per child communication, not per cached measurement.
Metadata-only child reports currently refresh child activity even in cloud mode;
`commState` is not a universal availability gate. The intended lifetime of an
omitted field is ambiguous. Keep that policy and characterize it with tests.
HTTP does not participate in energy-flow source selection. Cached CT/collector
priority and type106 protected fields remain outside this change.

## Confirmed defects and implementation

Regression tests ran against unchanged production code first: 33 MQTT/child cases
and six HTTP cases failed; the original 183-test suite passed at 68.86% coverage.
Fifteen additional cases subsequently reproduced missing activity updates for
child arrays in already-supported system/fallback messages. A separate regression
also reproduced the old HTTP meter remaining healthy after the selected SN changed.

All production changes are local to `sensor.py`:

- Match the complete MQTT topic with a literal prefix, reject foreign host SNs,
  and validate the JSON object/body shape before setting heartbeat/ever-received.
  Preserve flat-body reconstruction, permissive unknown-type handling and relayed
  children. Null-body 101 remains ignored.
- Reuse the existing child availability rules in a small coordinator method,
  called by both discovery and the existing request timer. Guard MQTT fan-out
  against stale child cache updates. No new scheduler, subscription or task.
- Timestamp ordinary child statistics actually merged by type23. Timestamp only
  child-array members present in accepted system/fallback bodies (2, 25, 106, 107,
  unknown types). Array merge/replacement behavior is unchanged.
- Exclude HTTP registration keys from child MQTT health changes and exclude
  HTTP-only callbacks from host timeout. Preserve once-seen expansion counters
  across host silence as required by their cumulative-energy exception.
- Treat invalid JSON, non-object responses and responses without any recognized
  numeric measurement as failed HTTP attempts. Use the existing counter for loss
  of address after a meter has been found. Keep HTTP errors distinct from
  unexpected programming errors; no new blanket exception handler was added.
- Invalidate the previous HTTP source and reset the source's failure count when
  the selected meter SN changes. Cancellation during request, normal delay or
  unexpected-error backoff reaches the existing unavailable cleanup.

These changes correct the existing health contracts without changing entity
identity, energy calculations, source preference, commands or module boundaries.
Timeouts preserve cached values and registrations; valid reports restore existing
entities automatically. Listener collections are snapshotted where callbacks can
remove registrations.

## Effective freshness rules

| Source | Freshness / expiry | Recovery |
| --- | --- | --- |
| Main MQTT | Matching host topic and decoded object body (including reconstructed flat/empty body); child relays count as host activity. Offline when age **>60 s** on the next request-loop check. | Valid host-topic message distributes the merged cache; field-specific entity rules still apply. |
| Ordinary child MQTT | Per-SN accepted array/point/statistics activity; offline when age **>60 s**, through either incoming fan-out or periodic check. Unseen startup grace **<60 s**. | A report for that child refreshes its timestamp and existing entity state. Other children keep their own timestamps. |
| Expansion energy | After first type23 report, cumulative counters do **not expire**, even during host silence. Never subject to the ordinary missing-list deletion timer. | Later type23 readings update the retained counter. |
| SmartMeter HTTP | At least one recognized field convertible to float makes a successful source poll. First two consecutive failed attempts preserve availability; the **third** marks entities unavailable. Missing address counts at the existing **30 s** discovery cadence. | A successful source poll resets failures; each entity requires its own numeric field to restore availability. MQTT cannot change HTTP health. |
| HTTP stop / selected SN change | The previous HTTP source becomes unavailable immediately; values remain cached. | A numeric HTTP reading for that same SN restores its existing entities. |

HTTP interval remains **10 s by default**, options **2–60 s**, with **5 s** request
timeout. A failure count is not an exact elapsed-time TTL: request durations add
to the interval. Address loss expires on the third missing-address check (two
30-second waits after the first check). Startup without a discovered meter does
not create a failure warning or fresh state. The MQTT timer cadence and **120 s**
reauthentication hint are unchanged.

## Ambiguities and intentionally deferred work

- Freshness means communication/source activity, not per-field measurement age.
  A metadata-only child report can retain old measurements; a successful partial
  HTTP response can omit a field indefinitely. Both policies are characterized
  by tests, not silently replaced with invented per-field lifetimes.
- Type101 membership completeness is unresolved. Omissions/empty arrays retain
  children and timestamps, so absent children expire but are not destroyed by
  ordinary merged-list reports. Generic system messages retain their existing
  shallow-array replacement semantics and existing missing-list removal behavior.
- The topic remains the host authority. A different body SN on a generic system
  message is accepted as before and explicitly characterized: body ownership
  cannot be inferred uniformly from the supported child message forms. This does
  not permit another host's topic to refresh this coordinator.
- Child freshness does not change cached CT/collector energy-source priority or
  type106 protected-field lifetime. `commMode`/`commState` are not new measurement
  gates. Follow-meter's work-mode restriction remains tested and unchanged.
- The reboot button remains outside coordinator health registration. No new
  availability policy for command-only entities was invented.
- MQTT unsubscribe handles, resetting `_subscribed`, options-triggered reload,
  partial startup cleanup and the global `_http_sm_sensors_created` flag remain
  later lifecycle work. The latter still limits automatic entity creation for a
  replacement meter; this fix only retires the previous source's health. Existing
  registration/unregistration, duplicate-start prevention and HTTP cancellation
  are tested, but a full HA reload/MQTT subscription cleanup is not claimed.
- Existing wall-clock timestamps are retained; no monotonic-clock migration or
  comprehensive malformed-protocol schema validation is introduced.

## Regression coverage and validation

`tests/test_availability_freshness.py` uses real coordinator/entity constructors,
registration hooks, MQTT decoding/cache merging/fan-out and the real request loop.
Only HA state writes, network boundaries and clock/sleep are replaced. Cases cover
host and two-instance isolation, literal topics, invalid envelopes, host controls,
CT type2, legacy type4, HTO907A, Shelly type3/subtype2, HTO910A, plugs/switches,
expansion counters, list omission, recovery, repeat checks and listener removal.
`tests/test_smartmeter_http.py` runs the real HTTP loop across failures, partial
responses, address loss, meter changes and cancellation, in addition to the prior
HTTP/MQTT dispatch tests.

Explicitly protected: **foreign host messages**, **main stale/recovery**,
**child stale/recovery**, **HTTP stale/recovery**, and **MQTT/HTTP freshness
isolation**, including HTTP and MQTT entities sharing the same meter SN.

Final validation (2026-09-11, Python 3.13.5): **260 passed**, **79.34%** coverage,
compared with **183 passed**, **68.86%** before this change. **77 new cases**:
65 in `test_availability_freshness.py` and 12 added to the existing HTTP module.

| Command | Result |
| --- | --- |
| `.venv/bin/pytest tests/ --ignore=tests/test_availability_freshness.py -q --timeout=30` (before HTTP test additions/production edits) | Baseline: 183 passed, 68.86% coverage. |
| `.venv/bin/pytest tests/test_availability_freshness.py -q --no-cov --timeout=30` (first regression run before production edits) | 33 failed, 10 passed; reproduced baseline defects. |
| `.venv/bin/pytest tests/test_smartmeter_http.py -q --no-cov --timeout=30` (first HTTP regression run before production edits) | 6 failed, 14 passed. |
| `.venv/bin/pytest tests/test_availability_freshness.py tests/test_subdevice_availability.py tests/test_smartmeter_http.py tests/test_mqtt_routing.py tests/test_upstream_sync.py tests/test_subdevice_entity.py tests/test_config_flow.py tests/test_switch_select_cache.py -q --no-cov --timeout=30` | 186 passed; subsequent payload-SN characterization and HTTP meter-change test also pass in the final full suite. |
| `.venv/bin/pytest tests/ -q --timeout=30` | Final: 260 passed in 3.20 s, 79.34% coverage; includes all required routing, HTTP, subdevice, multi-instance-relevant, config-flow and migration tests. |
| `.venv/bin/ruff check custom_components/jackery/ tests/test_availability_freshness.py tests/test_smartmeter_http.py` | Passed. |
| `python3 tools/check_translations.py` | Passed for de/en/fr. |
| `/tmp/jackery-baseline/lint-venv/bin/mypy custom_components/jackery/` | Passed, seven source files. |
| `.venv/bin/mypy custom_components/jackery/` | 23 existing HA-aware findings in three files. Exact finding text matches the recorded baseline after normalizing line numbers; no new findings. |
| `git diff --check` | Passed. |
| `command -v docker` | Docker absent; local Hassfest/HACS remain unavailable as in the baseline. No new remote CI run is claimed. |

The first sandboxed pytest attempt encountered the previously recorded pycares
teardown timeout. Authoritative baseline, regression and final results above were
obtained outside that sandbox with the same dependencies and tests, without
disabling assertions or changing CI configuration.
