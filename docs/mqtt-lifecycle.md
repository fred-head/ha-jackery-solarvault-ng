# MQTT subscription lifecycle

Scope: `fix/mqtt-lifecycle-cleanup`, based on merged PR2B foundation `3006414`.
Production changes stay in coordinator start/stop and integration setup/unload.
No transport module extraction or protocol, command, identity/migration,
energy-flow, source-priority or availability-policy changes are included.

## Audit and reproduced failures

There were exactly two subscription calls, both in
`JackeryDataCoordinator.async_start`: `{prefix}/device/+/status` and
`{prefix}/device/+/event`, QoS 1. Both passed the same local callback, which invokes
the coordinator's real `_handle_message`. That handler already rejects topics
belonging to other hosts and accepts relayed children on the configured host's
topics. No other production subscription path was found.

The installed Home Assistant MQTT API (`mqtt/client.py:async_subscribe`) returns
a synchronous, no-argument cleanup callback. Its client removes the particular
listener and clears its topic matcher cache; broker unsubscription is managed by
HA with regard to any remaining listeners. Both returned handles were discarded.
Stop only cancelled the MQTT/HTTP polling tasks and never reset `_subscribed`.
Consequently, unload left MQTT callbacks referencing the old coordinator, and
reload added another pair of listeners. Concurrent start could also overwrite
the task reference after starting duplicate tasks.

Startup caught and logged every ordinary exception without propagating it or
releasing earlier subscriptions. A failure in the second subscription therefore
left the first listener active while integration setup could report success.
Integration setup also lacked cleanup for already-forwarded platforms.

Regression tests were added before production edits: the initial 13 cases failed,
with an additional teardown error exposing the orphan task from concurrent start.
The tests subsequently corrected fixture ordering because HA's first domain
setup automatically loads other already-registered entries; entries are now
registered in the intended order. Failed-entry retries use HA's `async_reload`.
Five further cases cover cancellation and errors during cleanup and actual reload.

## Ownership and successful lifecycle

Each coordinator owns `_mqtt_unsubscribers` and an `asyncio.Lock` serializing
start/stop. There is no global subscription state. Each cleanup handle is retained
immediately after the corresponding subscribe completes, so zero, partial and
full subscription sets are valid states.

Configured entries subscribe to `{prefix}/device/{host}/status` and
`{prefix}/device/{host}/event`, still with QoS 1 and default decoding. This matches
the handler's existing host acceptance rule and includes host-relayed child
reports. The existing empty-host wildcard fallback remains for coordinators
without a configured serial. Payload parsing and routing are unchanged.

Setup forwards platforms first, preserving PR2A's discovery callback ordering,
then starts the coordinator. After subscriptions, the existing MQTT poll task and
optional per-entry HTTP task start. `_subscribed` is set only after startup work
finishes. Repeated or concurrent start while running creates no additional work.

Stop clears the callback list and `_subscribed` before invoking all detached
handles. It then cancels and awaits both owned polling tasks. Repeated stop invokes
no old handle again. Completed task objects remain referenced as before; a later
successful start replaces them. Integration unload also unloads the platforms,
allowing entities to unregister, then removes successful runtime data from
`hass.data`. Reload obtains a fresh coordinator and a fresh pair of subscriptions.
One entry never cancels another entry's callbacks or HTTP task.

## Failure and cancellation behavior

If subscription creation or later synchronous startup work fails, the coordinator
releases every acquired subscription and any tasks it started, then propagates
the original exception. Cancellation of a partially completed start follows the
same cleanup path and propagates cancellation. If cleanup also fails, its
`ExceptionGroup` preserves the startup exception as context.

Integration setup explicitly stops the failed coordinator and unloads any
forwarded platforms; successful platform cleanup removes its runtime data.
It does not depend on a later unload of an entry that never finished loading.
HA can retry an ordinary failed setup using its normal reload flow. Registry
records are not deleted or remigrated by this lifecycle cleanup.

Each unsubscribe is attempted even if another raises. Cleanup exceptions and
ordinary task-shutdown errors are collected and raised as an `ExceptionGroup`
after the other resources have been attempted. They are never silently swallowed.
Expected cancellation of owned tasks is distinguished from cancellation of the
caller. Integration unload attempts platform cleanup in `finally`, including when
coordinator cleanup raises.

An unsubscribe callback that raises before removing its listener cannot be
assumed to have succeeded. There is no invented retry or access to HA's private
subscription storage. Failed callbacks are not invoked twice, because their
side effects may already have happened. HA reports an unload exception as
`FAILED_UNLOAD`, which requires restarting HA rather than ordinary unload retry.
The failed runtime remains available in `hass.data`; entity platforms and other
callbacks/tasks have still been cleaned up where their cleanup succeeded.
Only normal successful unload is reported as successful.

## Regression scope and limits

`tests/test_mqtt_lifecycle.py` runs actual coordinator methods, real HA config
entry setup/unload/reload and entity platform registration. A fake MQTT boundary
retains callbacks and models per-listener unsubscribe; messages pass through
those registered callbacks into the real parser/cache handler. Assertions cover
delivery counts, stale coordinator inactivity, listener counts, both entry orders,
three successive reload cycles, HTTP task isolation, partial subscription failure,
later startup failure, cancellation, concurrent start/stop, platform setup failure
and cleanup errors. The existing HTTP test mock now returns a synchronous
unsubscribe callback, matching HA's API; its health assertions are unchanged.

This is not a live broker disconnect/reconnect or wire-level unsubscribe test.
HA owns connection reconnection, retained delivery and broker subscription
aggregation. No new retries, broker client or reconnection policy were introduced.
Errors inside already-running polling loops retain their existing handling.
HTTP replacement-meter creation, options-triggered reload policy, command
confirmation, protocol/classification changes, energy/source/Type-106 work and
architectural extraction remain separate tasks. MQTT 60-second freshness, HTTP's
three-failure policy and PR2B's persistent identities/migrations are unchanged.

## Validation

Tests use the existing Python 3.13/Home Assistant environment outside the sandbox,
as in earlier baseline runs, due to the documented sandbox teardown limitation.
The foundation's **475 tests at 86.32%** remain green; the final suite has
**493 passing tests at 86.52%** statement coverage, including **18 new lifecycle
cases**. There are no skips, xfails or new warnings in the final run.

| Command/check | Result |
| --- | --- |
| `.venv/bin/pytest tests/test_mqtt_lifecycle.py -q --no-cov --timeout=30 --tb=short` before production edits | 13 failed, 1 teardown error; leak/failure evidence described above. |
| Same lifecycle command on final code | 18 passed. |
| `.venv/bin/pytest tests/test_mqtt_lifecycle.py tests/test_mqtt_routing.py tests/test_config_flow.py tests/test_multi_instance_identity.py tests/test_child_identity.py tests/test_child_migration.py tests/test_migration.py tests/test_availability_freshness.py tests/test_subdevice_availability.py tests/test_smartmeter_http.py -q --no-cov --timeout=30 --tb=short` | 359 passed. |
| `COVERAGE_FILE=/tmp/mqtt-lifecycle.coverage .venv/bin/pytest tests/ -q --timeout=30 --tb=short` | 493 passed, 86.52% coverage. |
| `.venv/bin/ruff check custom_components/jackery/ tests/` | Passed. |
| `python3 tools/check_translations.py` | Passed: de/en/fr. |
| `/tmp/jackery-baseline/lint-venv/bin/mypy custom_components/jackery/` | Passed, 9 source files, matching CI's lint-only environment. |
| `.venv/bin/mypy custom_components/jackery/` | The same 23 known HA-aware findings in 4 files; normalized message text and multiplicities match the PR2B baseline exactly. |
| `git diff --check`, new-file whitespace checks and production diff review | Passed; changes confined to lifecycle setup/stop and subscription bookkeeping. |
| `command -v docker` | Unavailable; local HACS/Hassfest not run. CI definitions unchanged. |
