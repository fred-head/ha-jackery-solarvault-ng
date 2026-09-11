# Logging design (not implemented)

Current source and versions: [baseline](baseline.md). C mostly logs startup/discovery at INFO and detailed 106/107 traffic at DEBUG. O logs each 101/106 at INFO and more command detail; that is not a behavior to port. This design preserves runtime behavior while making failures attributable without exposing identifying payloads.

## Observed weaknesses

- `sensor.py:1421` catches all handler errors with one message, without stable stage/type/category fields; a malformed child/entity failure looks like a general MQTT error and can stop fan-out.
- `sensor.py:2173` catches calculation errors and returns the dict, potentially retaining old derived values; the log does not describe which source could not be calculated.
- `sensor.py:1749` emits discovery/removal messages using raw SN; setup/config-flow logging includes SN and topic prefix. Registry migration logs print full unique/entity IDs.
- Type107 DEBUG logs include full body (`sensor.py:1527`); HTTP DEBUG logs include endpoint URL/IP (`sensor.py:2338`). Turning on DEBUG can therefore expose customer identifiers, network configuration or unexpected payload secrets.
- Main offline has no transition log (`sensor.py:2183`), child offline may repeat per entity/check; recovery visibility is inconsistent. HTTP warns only at exactly the third ordinary failure and does not explicitly log recovery.
- Polling failures can warn every cycle and broad errors recur without throttling. Reboot logs command sent without execution confirmation. There are no unknown-type counters or provenance summaries.
- Plug raw_data is exposed as a state attribute (`switch.py:207`), a separate diagnostics/privacy concern that log redaction alone cannot fix.

## Level and event policy

| Event | Level | Safe context and repetition rule |
| --- | --- | --- |
| Normal setup / stop | INFO | Entry alias, integration version, configured transports; one event per lifecycle. |
| MQTT subscribe/ready | INFO | Host alias and topic template; actual connection vs subscribed state distinguished. |
| Device discovery | INFO | Host/child aliases, devType/subType, selected group; once per discovery transition. Field/capability details DEBUG. |
| Recovery | INFO | Source alias, outage age, restored entity count, prior failure category; once per recovery. |
| Availability transition | INFO | Source/child alias, reason (no initial data, timed out, communication mode, HTTP threshold), age; one event per device transition, not per sensor. |
| MQTT transient disconnect/publish failure | WARNING | Operation/message kind, source alias, exception category; first failure, then bounded periodic summary. Expected reconnect progress DEBUG. |
| Setup cannot operate / unrecoverable task failure | ERROR | Stage, exception category and remediation relevant to actual failure; deduplicated. Include sanitized traceback only if it cannot reveal payload/URL secrets. |
| Protocol malformed message | WARNING for first occurrence or burst summary; DEBUG detail | Type/shape/error category, not raw body. Rate-limit repeated invalid traffic; don't reclassify it as valid freshness. |
| Unknown message type / key | DEBUG | Numeric type, safe structural key metadata/count; aggregate repeated observations. Unknown does not mean fault. |
| Command publish | DEBUG | Command name/type/field keys, host/child alias and sent/failed state; never token, raw payload or full topic. No INFO per switch/slider operation. |
| Reboot request | INFO optional | Explicitly say requested/submitted, never reboot confirmed without evidence. |
| Reauth requested | WARNING | Explicit rejection vs silence heuristic, alias and elapsed age; once per guard transition, no credentials. |
| HTTP ordinary transient failure | DEBUG | Response status/timeout category; no endpoint/IP or exception text containing it. |
| HTTP failure threshold reached | WARNING | Meter alias, count, unavailable transition; once, then summary. HTTP recovered INFO. |
| Source selection change | DEBUG | Measurement/group, old/new source kinds and reason; no per-message identical choices. A persistent loss of all usable sources is an availability transition. |
| Registry migration | INFO summary, DEBUG per-item redacted detail | Counts per migration rule, collision/deletion category; never raw unique IDs/SNs. Unexpected conflict WARNING with safe aliases. |

Use lazy formatting (`logger.debug('... %s', value)`) and consistent context fields such as entry alias, child alias, operation, message_type, source_kind, reason. A small shared redaction/context helper is justified only when used across transport/coordinator; do not introduce an external structured logging framework.

## Rate limits and protocol trace

Suggested policy: first degraded-event warning immediately, identical warnings summarized at most once per 60 seconds, recovery resets suppression. Normal INFO is limited to lifecycle/discovery/health transitions. Counters should make suppression visible in diagnostics without retaining message contents. These limits are design proposals and need tests, not claims about current behavior.

DEBUG can contain field names, selected numeric measurement values where safe, transformations, routing decisions, command keys and timeout reasoning. Raw packet dumps require a distinct opt-in trace mode, disabled by default and redacted before output. Do not enable raw trace just by setting ordinary DEBUG. Never dump an unknown dict as a convenience fallback.

Acceptance tests: repeated 101/106 messages produce no INFO; repeated failures emit one initial warning plus bounded summary; recovery emits one transition; foreign-device traffic does not acquire current-host context; injected secrets in payloads/topics/exceptions never appear at any level. Logging changes are an independent PR after behavioral coverage; they must not silently alter availability or source choice.
