# Diagnostics design (not implemented)

Neither C nor O provides diagnostics.py. Current troubleshooting relies on logs and entity attributes, including unsanitized plug raw_data. Source: C `sensor.py:2542,2798`, `switch.py:207`, pinned in [baseline](baseline.md). This proposal follows AGENTS.md and addresses specific missing visibility; it does not expose a protocol command interface.

Provide an async config-entry diagnostics function returning a JSON-safe snapshot. Device diagnostics can later select one child from the same snapshot. HA documents these entry points and its `async_redact_data` utility; it requires excluding sensitive data. Use the helper as a final defense after building an allowlisted snapshot. [HA diagnostics documentation](https://developers.home-assistant.io/docs/core/integration/diagnostics/).

## Snapshot fields

| Section | Proposed fields | Current evidence / instrumentation needed |
| --- | --- | --- |
| Version/context | integration manifest version, HA/Python versions, diagnostics schema version, configured transport flags, interval, pseudo entry ID | Version/options exist. Report package metadata separately if needed; pyproject version differs from manifest. |
| Host identity/capabilities | Per-download alias host_1, deviceType/model, firmware, observed known fields, supported entity groups, capability source (explicit/inferred) | `_device_type`, `_soft_ver`, SENSORS and cache exist. Field-presence capability evidence is not firmware support certification. |
| Main health | seconds since accepted message, startup age, ever_received, reauth requested, unavailable reason, state validity | Existing last-update/ever-received values are inaccurate for malformed/foreign traffic. Initially label their actual semantics; add accepted-message timestamp only through tested instrumentation. |
| MQTT | connected status if available from HA adapter, subscription active/count, expected redacted topic template, poll task state, last publish age, message/error counters by type | `_subscribed` currently means subscribe calls completed, not broker connected. No unsubscribe handles, per-type counters or publish outcome history yet. Never infer connectivity from this boolean. |
| Child health | child_1 alias, parent alias, source array, item devType/subType, diagnostic label, communication mode/state, last message age, per-measurement age/knownness, missing-since, availability reason | Last-seen/missing sets exist. No per-field timestamps now; distinguish unknown from zero age. Highlight cached power vs sparse cumulative energy. |
| HTTP health | enabled/target-discovered, endpoint reachable boolean (no address), timeout/interval, task state, last attempt/success age, consecutive failures, threshold, sensor-created count | Counter and last meter SN currently loop-local. Last success/status history requires bounded instrumentation; note no-IP waiting separately from HTTP failures. |
| Source selection | For grid/ongrid/battery/home: value, selected source alias and field names, direct/normalized/calculated flag, age if known, alternate candidate presence/rejection reason | No persistent provenance record now. Calculation must return observational trace in a later tested change, without changing selected values. Do not pretend HTTP is a grid source. |
| Entities | Counts by platform/group, unavailable counts/reasons, disabled counts if registry queried safely | Use counts and logical keys, not raw entity IDs/names. Distinguish entity availability from transport health. |
| Protocol metadata | Observed type counters; unknown type count, bounded list of safe field names/types, last parse-error category | New instrumentation needed. No raw payload/body/token, no messageId history or device timestamps revealing schedules. |
| Commands | Last command kind, sent/failed/optimistic state, elapsed age; confirmed only if future protocol correlation exists | Currently no command lifecycle state. Report confirmation unknown, not success. Avoid values that reveal schedules or identifiers. |

Unavailable information is `null`/`unknown`, not inferred healthy. Diagnostics must work before first receipt, during reauth, partial setup and after a transport failure. Reading diagnostics must not start polls, publish queries, mutate cache, rediscover devices or request credentials.

## Redaction contract

Always remove tokens, API keys, passwords, MQTT broker credentials, account/customer/user IDs, authorization headers, cookies/session IDs, Wi-Fi credentials, private keys/certificates, sensitive URLs and query strings. These may appear under unexpected casing or nested keys; a key blacklist alone is inadequate.

Also redact or replace serial numbers (`device_sn`, `deviceSn`, `sn`, child SNs), MAC/BSSID, hostnames, local/public IPs (`wip`, `eip`, mqtt_host), SSID (`wname`), user-assigned names (`name`, `scanName`), area/location, config-entry ID, device registry ID, entity unique ID and entity_id, and the configured topic prefix/full topics. Preserve topic **shape**, e.g. `{prefix}/device/{host}/status`. Do not emit raw exception strings containing an endpoint or authorization value.

Use per-download aliases consistently across host/child/source sections, including identifiers embedded as dictionary keys. Do not publish stable hashes of serials (they still permit correlation and guessing). Redact full serials by default; if troubleshooting ever requires partial serials, make that an explicit separate reviewed policy. Public model names, protocol field names and firmware versions may remain, subject to type/length allowlists.

Unknown data: preserve raw values internally where current behavior already does, but diagnostics should expose only bounded structural metadata with safe key syntax/length. Drop values and suspicious/dynamic key names; summarize counts for excess fields. Do not reuse `switch.extra_state_attributes['raw_data']` as a diagnostics payload.

## Size, testing and rollout

Proposed bounds (design choices, not current features): 50 message types, 50 unknown key descriptions, 100 child summaries and a 64 KiB serialized snapshot limit; include truncation counts. Prefer ages to exact timestamps. Start without any raw trace ring buffer; add opt-in trace only if bounded metadata proves insufficient.

Tests must inject distinct sentinel secrets into every nesting position and key, include numeric/lowercase/uppercase SNs, duplicate child SNs across entries, exceptions containing URLs, malformed payloads and absent runtime state. Assert no raw sensitive strings survive serialized output and snapshots do not mutate state or call transports. Cover real source precedence and unavailable reasons; redact before writing logs or fixtures. Validate the endpoint on the supported HA test version and avoid promising compatibility with the untested HACS minimum.
