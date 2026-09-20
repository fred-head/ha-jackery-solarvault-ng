# Phase 3 diagnostics architecture

## 1. Foundation baseline

This document is the binding technical basis for Phase 3. It was audited
against `refactor/v3-foundation` at
`ccaa100bbbea88d3d01904d7548aaf934c1b9a07`. The accepted Phase 2/2.5
architecture is a constraint, not a subject of this phase.

P3.3 adds a config-entry-only `diagnostics.py` endpoint on top of the P3.1
snapshot builder and P3.2 observation record. The integration retains distinct
owners for protocol/runtime state, child membership, transport mechanics and
Home Assistant effects. Diagnostics observes those owners without consolidating
or moving their state.

The Home Assistant integration currently stores entry runtime data in
`hass.data[DOMAIN][entry_id]`, not `ConfigEntry.runtime_data`. A later
diagnostics adapter must follow the repository's implemented setup boundary; a
runtime-data migration is outside Phase 3.

The current Home Assistant diagnostics contract supports a config-entry
function in `diagnostics.py` and optionally a device function. Home Assistant's
redaction helper is useful as a final defense, but it does not replace the
allowlist defined here. See the
[Home Assistant diagnostics documentation](https://developers.home-assistant.io/docs/core/integration/diagnostics/).

## 2. Goals and non-goals

Phase 3 diagnostics must provide a bounded, deterministic and JSON-serializable
snapshot that helps users and maintainers understand:

- integration and entry lifecycle state;
- host and child communication freshness;
- configured and active transport lifecycles;
- protocol cache shape and source-selection evidence;
- child membership and classification;
- SmartMeter MQTT and HTTP health;
- aggregate Home Assistant entity/device health;
- fixed, safe reason codes for degraded state.

The snapshot must be safe to attach to a public issue by default. Creating it
must be observational: it must not publish MQTT, make HTTP requests, start a
poll, run discovery, write entity state, mutate a registry, start reauth or
change any runtime collection.

Phase 3 diagnostics does not:

- redesign coordinator, runtime-state or discovery ownership;
- change routing, freshness, availability or source priority;
- add command acknowledgement or broker-connectivity semantics;
- expose a protocol command interface;
- dump raw cache, payload, config-entry, entity-state or registry objects;
- certify hardware capabilities from field presence;
- implement a permanent MQTT trace or packet capture;
- replace the separate logging policy;
- reopen Phase 2/2.5 architectural decisions.

## 3. Current state owners

### 3.1 Ownership inventory

"Authoritative" below means authoritative for the integration's current
runtime decision, not an assertion that the device or network has a particular
physical state.

| Owner | Current information | Nature | Diagnostics use | Redaction or later observation need |
| --- | --- | --- | --- | --- |
| `CoordinatorRuntimeState.data_cache` | Main raw/normalized keys, derived calculation keys, child containers, expansion-battery map and optimistic control writes | Authoritative current integration cache, but heterogeneous and not a message log | Read only through explicit semantic selectors and bounded structural counts | Never export the mapping, arbitrary keys or raw child dictionaries |
| `CoordinatorRuntimeState.last_update_time`, `start_time`, `ever_received` | Accepted host-topic activity and coordinator start reference | Authoritative communication freshness | Export non-negative ages, stale decision and ever-received flag | Never export absolute timestamps |
| `CoordinatorRuntimeState.subdevice_last_seen` | Last accepted activity per validated child serial | Authoritative child communication freshness, not per-measurement freshness | Join through child aliases and export age/availability | Serial keys require aliases; do not imply every cached measurement is fresh |
| `CoordinatorRuntimeState.power_live_seen` | Preferred live field to message-type/receipt-time evidence | Authoritative Type-106 arbitration evidence | Summarize only the fixed preferred-field set and ages | No arbitrary keys; no absolute timestamps |
| `CoordinatorRuntimeState.power_106_samples` | Most recent Type-106 value/time for preferred fields | Authoritative snapshot evidence | Report presence and age for fixed fields; numeric sample values are not needed in the default export | Copy first; no raw mapping |
| `CoordinatorRuntimeState.energy_sources` | Calculation-owned source-decision metadata | Derived current source provenance | Export a schema-checked semantic summary, currently the `grid` decision | Accept only fixed source/reason enums and finite numeric/count fields |
| `ChildDiscoveryState.known_children` | Children for which dynamic discovery has registered membership | Authoritative in-memory discovery membership | Build the child identity universe and membership flags | Serial values become snapshot-local aliases |
| `ChildDiscoveryState.expansion_batteries` | Once-discovered expansion membership | Authoritative discovery policy input | Export boolean/family information and the retained-freshness policy | Serial values become aliases |
| `ChildDiscoveryState.missing_since` | Missing-list timers | Authoritative current removal-timer state, derived from reconciliation policy | Export age and due/not-due semantic state | Serial keys require aliases; absolute timestamps are forbidden |
| Coordinator host fields | `_device_sn`, `_device_type`, `_soft_ver`, configured topic/token/host inputs | Current host identity and captured metadata | Export host alias, identity origin, validated device type/model and a bounded firmware value | Never export serial, token, MQTT host or topic prefix; firmware is untrusted text |
| Coordinator reauth and migration fields | `_reauth_started`, `_child_migration` | Current HA workflow guard and child-identity safety result | Export guard boolean and aggregate conflict counts/categories | Do not export entry/entity IDs, serials, protected sets or existing hash references |
| Coordinator listener/callback fields | `_sensors`, dynamic-add callbacks | HA runtime references, not the full entity registry | At most aggregate callback-capability/listener counts for consistency checks | Never serialize entities, listener keys, unique IDs or callback objects |
| Coordinator task/lifecycle fields | `_data_task`, `_smartmeter_http_task`, `_subscribed`, `_poll_105_counter`, lifecycle lock | Application lifecycle and scheduling state | Export normalized task/lifecycle enums and configured cadence | `_subscribed` means startup completed, not broker connected; lock/counter internals are not exported |
| Coordinator HTTP creation state | `_http_sm_sensor_sns_created` | Set of meter serials whose HTTP entity sets were created | Export alias count/list and duplicate-prevention state | Serial values require the same child alias map |
| MQTT transport | Per-instance unsubscribe callbacks and their count | Authoritative ownership of active HA MQTT listener handles | Export owned-handle count only | Handles are not connectivity, broker health or successful subscription delivery |
| SmartMeter HTTP transport | Injected session and one call's URL/status/data result | Request-local mechanics only | No transport object or response is exported | URL/status are not persistently observable; never retain or export URL/IP/raw data |
| P3.2 diagnostics observation state | Selected HTTP target, attempt/success times, consecutive failures, bounded outcome/replacement/health and bounded protocol counters | Passive per-coordinator mirror of existing transitions with no operational authority | Copy the immutable observation snapshot into explicit P3.1 inputs | Never export request data, exception text, raw message types or identities; the target identifier enters only the shared alias relation |
| Config entry | Configuration data/options, entry state, source and title | HA configuration truth | Export only schema-derived booleans, bounded interval and safe entry-state enum | Never copy `entry.data`/`entry.options`; omit title, IDs and all raw strings |
| HA entity registry/state machine | Entry-owned entity records, disabled status and current HA states | Authoritative HA registration/state view | Aggregate counts by fixed platform and availability bucket | IDs, unique IDs, names, areas, state attributes and values are not exported |
| HA device registry | Entry-owned main/child device records and relationships | Authoritative HA device registration view | Aggregate device counts/roles only | Never export device IDs, identifiers, names, areas or `via_device` identifiers |

### 3.2 Corrected assumptions from the Phase 0/1 plan

The earlier plan predates several accepted fixes and extractions. Phase 3 uses
these current facts:

- host activity and `ever_received` advance only after exact topic ownership and
  a structurally accepted JSON envelope; malformed JSON and foreign host topics
  do not refresh the host;
- MQTT unsubscribe callbacks are retained by `JackeryMqttTransport`, unwound on
  partial start and attempted exactly once on stop;
- `_subscribed` records successful coordinator application startup only and must
  never be labeled broker connectivity;
- runtime state already persists Type-106 live/snapshot evidence and selected
  energy-source metadata;
- runtime cache/freshness and child discovery membership have separate
  Home-Assistant-independent owners;
- HTTP and MQTT entity health are isolated, and MQTT fan-out deliberately skips
  HTTP-only listeners;
- HTTP replacement serials receive distinct entity sets and old meter entities
  remain registered but unavailable;
- child freshness is communication freshness, not field-level measurement age;
- P3.2 passively mirrors the HTTP failure counter, selected meter and bounded
  outcome/health transitions without changing the poll loop's authority;
- P3.2 provides fixed-cardinality route/error counters and an unknown-message
  count; command outcome history and broker-connection state remain unavailable.

## 4. Diagnostics data contract

### 4.1 Contract rules

The root object has exactly these stable logical sections:

```text
integration
host
transport
protocol
freshness
children
smartmeter
entities
health
```

Every field is explicitly declared by the snapshot schema. Missing information
uses `null`, an empty collection or the fixed enum `unknown`; it is never guessed
as healthy. Booleans and numbers keep their types. Non-finite numbers are
rejected. Absolute wall-clock times are converted to rounded, non-negative ages.

Implementation class names, private attribute names, callback objects and task
representations are not contract fields. A future internal rename should require
only an input-adapter change, not a diagnostics schema change.

### 4.2 Section contract

| Section | Purpose and source of truth | Allowed fields | Derived fields | Explicitly forbidden |
| --- | --- | --- | --- | --- |
| `integration` | Manifest plus HA/config-entry adapter | diagnostics schema version; manifest version; HA/Python versions; fixed entry-state enum; booleans for configured host/token/custom topic/legacy MQTT host; HTTP enabled; bounded poll interval; snapshot truncation counters | `identity_mode` as `configured`, `adopted` or `unknown`; configuration-presence booleans | Entry data/options dump, title, entry ID, unique ID, source data, tokens, topic prefix value, host value |
| `host` | Coordinator metadata and runtime state | alias `host`; safe numeric device type; code-owned model label; bounded firmware value; cache initialized flag | identity origin; fixed capability-presence tokens derived only from known fields | Host serial, network names/addresses, raw metadata, inferred hardware certification |
| `transport` | Coordinator lifecycle/tasks and MQTT handle count | MQTT lifecycle enum, owned subscription count, poll-task enum, HTTP-task enum, fixed QoS/retain facts, configured cadence and timeout | consistency flags such as `running_without_owned_subscriptions` | Broker URL/host, topic/prefix, callbacks, task repr, exception text; any claim that handles imply broker connectivity |
| `protocol` | Allowlisted views of runtime cache/evidence | bounded known semantic measurement values; known/unknown field counts; child-container counts; Type-106 evidence presence/ages; fixed route/error counters when later observed; energy-source metadata | semantic cache-shape flags and source status | `_data_cache`, raw wire keys not in the schema, raw payload/body, arbitrary unknown keys/values, message IDs, device timestamps |
| `freshness` | Runtime clocks plus discovery timers | host age/stale/ever-received; per-child alias, activity age, availability, missing age and retention policy | fixed availability and missing-state reason codes using existing timeout policy | Absolute timestamps, per-field age claims, serial-keyed mappings |
| `children` | Discovery membership joined to allowlisted cache classification | child alias; fixed family/model enums; numeric `devType`/`subType` when type-safe; fixed cache-container tokens; known/expansion flags; communication mode/state when type-safe | deterministic family and safe measurement-presence flags | Serial, name/scanName, IP, complete child dictionary, arbitrary metadata, writable capability inferred from unknown types |
| `smartmeter` | Child classifications, HTTP options/task and passive HTTP observation | MQTT SmartMeter aliases/count; HTTP enabled/task; target alias; created-set aliases/count; interval/timeout/threshold; last attempt/success ages; failure count; fixed last-outcome enum | `target_discovered`, source replacement state and bounded HTTP health status | IP, URL, serial, raw response, HTTP entity values, exception text; claim that an HTTP task or created entity means reachable |
| `entities` | HA entity/device registries and state machine, scoped to the config entry | aggregate counts by fixed platform; disabled count; `available`/`unavailable`/`unknown` state counts; device counts by host/child role; runtime-listener counts by fixed callback capability | mismatch counts between registry and runtime registrations | Entity/device/registry IDs, unique IDs, names, areas, state values, attributes, `raw_data` |
| `health` | Pure summary derived from the other sections | overall fixed enum; sorted fixed reason-code list; reauth guard; migration block-all flag, blocked-child count and conflict-category counts | `ok`, `degraded`, `unavailable` or `unknown` from documented reason precedence | Free-form reason text, exception strings, credentials, identities, claims of command confirmation or broker connectivity |

### 4.3 Semantic protocol fields

The default export may include a deliberately small numeric measurement set to
make source and formula failures diagnosable. The contract uses semantic names,
not a raw cache copy. Initial candidates are solar power, main battery charge and
discharge power, grid import/export power, EPS input/output power, and the
derived grid, battery and home net values. Each selector must accept only a
finite numeric value and must preserve zero.

Child entries expose whether known power/energy fields are present, not their
complete values. HTTP measurements remain entity-owned and are not copied into
the default diagnostics export. Expanding either allowlist requires a reviewed
schema change and full-output privacy tests.

The current energy-source record permits only:

- source: `cts`, `collectors`, `system` or `unavailable`;
- non-negative activity age or `null`;
- non-negative `skipped_stale` and `skipped_missing` counts;
- a code-owned reason enum derived from the current fixed reason text.

Arbitrary mappings added to `energy_sources` in the future do not automatically
become diagnostics fields.

### 4.4 Observation availability

P3.2 supplies bounded passive observations to the P3.3 adapter. Fields without
an authoritative owner remain `unknown`/`null`; the endpoint does not synthesize
them:

| Desired field | P3.3 status and source |
| --- | --- |
| HTTP last attempt/success age | Available from the coordinator HTTP-observation record |
| HTTP consecutive failures and last outcome | Available from the coordinator HTTP-observation record |
| HTTP last status category | Available as the bounded P3.2 outcome category |
| Accepted route/error counters | Available from the HA-independent protocol-observation record |
| Unknown-message count | Available as a count from the protocol-observation record; no raw type string |
| MQTT broker connectivity | `unknown`; the integration owns no stable public connection state |
| Publish/command outcome history | Omitted; the transport retains no outcome state or correlation |

## 5. Privacy, redaction and aliasing

### 5.1 Allowlist first

The builder constructs a new object from declared fields. It must never sanitize
an arbitrary object and then assume the remainder is safe. Home Assistant's
`async_redact_data` may be applied to the completed allowlisted object as a final
defense only.

The following handling is mandatory:

| Data class | Rule |
| --- | --- |
| Tokens, passwords, credentials, API keys, authorization/cookies, private keys/certificates | Never copy, compare only for a boolean such as `token_configured` when useful |
| Host and child serials | Replace with one snapshot-local alias map; never expose full, partial or hashed serials |
| Config-entry IDs and unique IDs | Never export; use no persistent entry alias |
| Entity, device and registry IDs | Use internally only for scoped lookups; export counts, never identifiers |
| Entity IDs and entity unique IDs | Never export, including dictionary keys |
| IP addresses, MAC/BSSID and hostnames | Never export or partially redact |
| MQTT topics and topic prefixes | Never export configured values; at most emit the constant shape `{prefix}/device/{host}/status|event` |
| SSIDs and network names | Never export |
| User-defined device/entity names, `name`, `scanName`, area/location | Never export |
| URLs and query strings | Never export, including HTTP measurement URLs |
| Exception text | Never export; map only at the catch site to fixed code-owned categories |
| Raw MQTT/HTTP payloads and cache dictionaries | Never export |
| `extra_state_attributes["raw_data"]` and all entity attributes | Never use as diagnostics input |
| Firmware string | Accept only a short, conservative version-token form; otherwise use `null` plus a fixed invalid-value flag |
| Model/family/source/status strings | Accept only code-owned enum values, never arbitrary protocol strings |

### 5.2 Snapshot-local aliases

Alias assignment occurs before any section is built:

1. The active host is always `host`.
2. Collect child serials from copied discovery membership, copied freshness keys,
   allowlisted child containers, expansion membership and HTTP creation/target
   state.
3. Sort the raw serials only in memory and assign `child_001`, `child_002`, ... .
4. Reuse that same alias everywhere in `freshness`, `children`, `smartmeter`,
   source metadata and health summaries.
5. Discard the reverse map before returning the snapshot.

Aliases are deterministic for identical input within a snapshot. They are not
persisted and are not intended to remain stable after membership changes or
reload. A stable hash is prohibited because it enables correlation and can make
guessable serials recoverable. If a malformed record has no validated serial,
it contributes only to aggregate counts and receives no identity alias.

### 5.3 Unknown and untrusted data

- Unknown values never pass through, even when their key resembles a known key.
- Unknown keys are counted only after comparison with a maintained known-field
  set. Their raw names are not exported.
- Strings of unknown origin are omitted. Code-owned enums are emitted from a
  closed mapping, not by stringifying the input.
- Type mismatches increment a bounded invalid-value count; their values and
  exception text are dropped.
- Booleans are not accepted as numeric protocol measurements.
- NaN, infinity and values outside a field's documented representation are
  rejected.
- Collections are copied before iteration. Sets become sorted lists; mappings
  receive new string keys from the output schema only.
- The builder must not call a generic `default=str` JSON fallback.

### 5.4 Bounds

Initial contract limits are:

- 100 child summaries, with total and omitted counts;
- 50 route/message counter buckets;
- 100 structural protocol-observation buckets;
- 64 characters for any permitted untrusted string;
- 64 KiB for compact UTF-8 JSON of the complete result.

All truncation is deterministic and is reported through aggregate counts in
`integration`. If fixed collection limits are insufficient to stay under 64
KiB, the builder drops lower-priority detail in this order: protocol observation
details, children beyond the retained summary count, then per-platform entity
detail. It retains schema/version, host/transport/freshness/health summaries and
all truncation counters. It never truncates a secret into a supposedly safe
fragment.

## 6. Snapshot architecture

### 6.1 Pure layer

A later `diagnostics_snapshot.py` should contain only standard-library code:

```text
copied owner views + one supplied now value
                  |
                  v
        typed SnapshotInput records
                  |
                  v
     alias assignment and allowlisted selectors
                  |
                  v
      bounded JSON-safe diagnostics dictionary
```

The pure builder:

- accepts already copied primitive collections and a caller-supplied clock;
- has no `HomeAssistant`, config-entry, coordinator, entity or transport import;
- never awaits and never retains a reference to input collections;
- calculates all ages from one `now` value;
- returns only dictionaries, lists, strings, finite numbers, booleans and null;
- sorts every unordered collection and reason list;
- enforces the contract and output-size budget;
- produces identical output for identical input and `now`.

The input model is intentionally separate from the output schema. It may reflect
current owners, while the output remains stable if private runtime fields move or
are renamed later.

#### P3.1 concrete contract decisions

P3.1 implements the pure boundary in
`custom_components/jackery/diagnostics_snapshot.py`. The module uses only the
Python standard library and exposes frozen, typed input records plus
`build_diagnostics_snapshot(inputs, *, now)`. It has no coordinator, transport,
protocol or Home Assistant runtime import. The returned dictionary has exactly
the nine sections in section 4.1; fields that require P3.2 observation remain
`unknown`, `null` or an empty fixed counter mapping.

The firmware/version validator accepts 1 to 32 ASCII characters from
`A-Z`, `a-z`, `0-9`, `.`, `+` and `-`, requires the first character to be
alphanumeric, at least one digit and at least one version separator (`.`, `+` or
`-`). Values outside that deliberately narrow token form become `null` with
`firmware_valid: false`; a missing value uses `null` for both fields. This rejects
spaces, paths, URLs and undelimited serial-like strings without introducing a
general string sanitizer.

The alias universe is the union of validated identifiers supplied through child
summaries, child freshness, MQTT SmartMeter membership and HTTP target/created
state. The host identifier is removed from that universe. Remaining raw values
are sorted only in local memory and assigned `child_001`, `child_002`, ... in one
shared namespace, including SmartMeters. Duplicate identities therefore reuse
one alias across all sections. No raw-to-alias mapping is returned or retained.

P3.1 retains at most 100 aliases in ascending alias order and enforces a 64 KiB
compact UTF-8 JSON limit. Protocol observation detail is currently the mandated
empty/neutral P3.2 placeholder, so there is no observation detail to discard.
If the fixed child cap is still too large, aliases are removed deterministically
from the end; per-platform entity and listener detail is removed next. Aggregate
counts and truncation metadata remain. The builder fails closed rather than
returning an over-budget object if the fixed core alone cannot fit.

### 6.2 Runtime collection

Snapshot collection runs on Home Assistant's event-loop thread and makes a
best-effort point-in-time copy without awaiting between owner reads. It must:

- shallow/deep copy only the collections required by the allowlist;
- never expose a live set/list/dict through an input record;
- tolerate an entity unregistering or a task completing after the copy;
- avoid the coordinator lifecycle lock, because diagnostics must not delay start
  or stop and does not need a transactionally atomic runtime view;
- label internally inconsistent best-effort observations with fixed consistency
  flags instead of mutating state to repair them.

No snapshot accessor may trigger `_find_smartmeter_ip_and_sn`, discovery,
calculation, availability writes or transport methods if doing so has side
effects. Pure classification and fixed-field selection over copied data are
allowed.

### 6.3 Passive observation state

Information missing today must be added later only as bounded observation state.
Recording may occur at existing decision points, but must not alter their
conditions or ordering. The observation record stores timestamps, counts and
fixed enums, never payloads, URLs, IPs, serials outside the owner that already
requires them, or exception strings.

HTTP observation remains coordinator policy because the coordinator owns target
selection, failures, threshold and replacement behavior. MQTT subscription
handle count remains transport-owned. Protocol route/error counters may live in
a small Home-Assistant-independent observation record; they do not belong in
the raw cache and must not turn routing into a diagnostics concern.

### 6.4 P3.2 passive observability decisions

P3.2 composes one standard-library-only `DiagnosticsObservationState` into each
`JackeryDataCoordinator`. It is separate from `CoordinatorRuntimeState`, because
cache, freshness and source evidence remain operational runtime truths while the
new record contains only diagnostic history. The state is created and discarded
with its coordinator; there is no module-global state, persistence or transfer on
reload. Stop/unload does not synthesize HTTP or protocol observations.

The coordinator exposes `diagnostics_observation()`, which returns frozen records
and sorted tuples copied from all mutable counter mappings. P3.3 may translate
that view into the P3.1 input records without reaching into private dictionaries.
The HTTP target identifier in this internal view exists only to join the selected
meter to P3.1's snapshot-local alias map. It is not export-safe and must never be
returned directly by a Home Assistant diagnostics endpoint.

SmartMeter HTTP request outcomes are classified at the transport result boundary
as `success`, `timeout`, `client_error`, `http_status_error`, `invalid_json` or
`invalid_payload`. The coordinator additionally records `no_target` and
`unexpected_error`; the initial value is `unknown`. Only the fixed code is stored.
URLs, IP addresses, response bodies and exception text remain request-local. The
observation mirrors the poll loop's existing consecutive-failure counter after
each iteration, its current target, last attempt/success receipt timestamps and
the last target-selection transition (`initial`, `unchanged` or `replaced`).
`healthy`, `degraded`, `unavailable` and `unknown` are diagnostic summaries of
that mirrored counter and outcome. The operative three-failure threshold remains
the unchanged local poll-loop decision and never reads observation state.

Protocol counters use only these fixed accepted-route buckets:
`type_23`, `type_101`, `type_102`, `type_106`, `type_107`, `type_123`,
`generic_known` (currently types 2 and 25), and `generic_unknown`. An accepted
route increments only after route application, calculations, discovery and
entity fan-out complete. `unknown_message_count` increments with a successfully
handled `generic_unknown` route and never stores the raw message type. Fixed
error buckets are `invalid_topic`, `foreign_host`, `invalid_json`,
`invalid_envelope` and `handler_error`; each is recorded at the existing
rejection/failure boundary. Counters saturate at 2,147,483,647 and their key
cardinality cannot grow.

P3.1 now accepts these fixed counter and HTTP-observation values through explicit
allowlisted input fields and converts receipt timestamps to ages using the one
supplied snapshot clock. No production code invokes the snapshot builder yet;
P3.3 remains responsible for constructing the complete input and exposing the HA
endpoint. MQTT broker connectivity remains `unknown`: subscription ownership,
application lifecycle and `_subscribed` are still not connectivity evidence.

## 7. Home Assistant integration boundary

The later `diagnostics.py` should be a thin adapter:

```text
HA ConfigEntry and hass.data runtime lookup
        +
entry-scoped entity/device registry aggregates
        +
manifest and HA version metadata
        |
        v
copied SnapshotInput
        |
        v
pure snapshot builder
        |
        v
final allowlisted/redacted diagnostics dictionary
```

The first endpoint should be config-entry diagnostics only. Home Assistant uses
entry diagnostics as the fallback from a device page when no device-specific
function exists, so a device endpoint is not required to make the initial
feature useful. Device diagnostics may be added later only if it can filter the
same snapshot without exposing registry identifiers or creating a second
contract.

Registry queries belong exclusively in this HA adapter. The pure layer receives
aggregate counts and fixed state buckets, not registry entries. The adapter must
scope every query to the config entry and must not scan/export unrelated entries.

The adapter must work for a loaded entry with no accepted message, partial child
state, reauth requested and degraded transports. If the coordinator is absent
because setup did not complete or the entry is unloaded, it returns a minimal
safe snapshot with fixed `runtime_unavailable` health, not a stack trace or raw
entry data.

### 7.1 P3.3 Home Assistant adapter decisions

P3.3 implements Home Assistant's current config-entry diagnostics signature:

```python
async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry)
```

The public function in `diagnostics.py` loads only the integration manifest
version, resolves the entry-scoped coordinator through the repository's existing
`hass.data[DOMAIN][entry_id]` boundary, reads one snapshot clock and invokes
`build_diagnostics_snapshot()` exactly once. The larger explicit owner mapping
lives in `diagnostics_adapter.py`; it is read-only Home Assistant adapter code,
not a state owner or a second serialization layer. The completed P3.1 dictionary
receives Home Assistant's key-based redaction helper only as a final defense.

The adapter copies fixed fields from `CoordinatorRuntimeState`,
`ChildDiscoveryState` and the P3.2 immutable observation snapshot. It supplies
only the P3.1 semantic measurement allowlist, fixed cache/container counts,
Type-106 evidence, grid-source metadata, child summaries and freshness inputs.
The internal host, child and selected HTTP target identifiers are passed only as
P3.1 input relations; P3.1 remains the sole aliasing boundary. The raw cache,
complete child dictionaries, topics, network addresses, HTTP data, exception
text and entity attributes are never inputs.

Entity and device registry reads use the current entry-scoped Home Assistant
helpers. Output contains only total and fixed-platform entity counts, disabled
count, normalized `available`/`unavailable`/`unknown` counts, host/child device
counts, fixed runtime-listener capability counts and the sensor registration
mismatch count. Entity IDs are used transiently only to retrieve a state; the
adapter reads only its normalized state string and never reads attributes,
including `raw_data`. Registry IDs, identities, names, labels and areas are not
passed to P3.1.

Coordinator application state is normalized from the config-entry state and
the existing `_subscribed` application flag. MQTT and HTTP tasks become only
`absent`, `cancelled`, `done` or `running`; task/coroutine representations,
exception objects and function names are never inspected. MQTT owned-handle
count remains transport-owned evidence and is not broker connectivity. Broker
connectivity therefore remains `unknown`.

Runtime receipt and freshness values use the foundation's wall-clock
`time.time()` basis. The endpoint reads that clock once after manifest loading
and supplies the same value to every age decision and the P3.1 builder. An
unloaded or partially initialized entry uses explicit neutral inputs and
`runtime_unavailable` without catching unexpected programming errors. P3.3 adds
no polling, refresh, discovery, registry mutation, task creation, device-specific
endpoint or protocol-discovery behavior.

### 7.2 P3.4 adversarial hardening decisions

P3.4 exercises the complete adapter and pure builder with canaries in config,
coordinator metadata, runtime/cache state, child discovery, HTTP target
relations, device/entity registries, areas, labels, HA states and attributes.
The compact P3.1 result is verified before Home Assistant key redaction as well
as after the public endpoint returns. Both results exclude every raw identity,
registry ID and canary, confirming that P3.1 remains the privacy boundary and
HA redaction remains defense in depth.

The largest fixed-contract stress case supplies 2,000 valid 256-character child
identifiers, maximal child details, every semantic measurement, Type-106 field,
route/error counter, registry aggregate and maximum-length version token. The
deterministic result is 61,018 UTF-8 bytes, below the 65,536-byte limit. It keeps
the first 100 sorted snapshot-local aliases and records 1,900 omissions. Child,
freshness and SmartMeter alias references are removed together. The established
priority remains authoritative: remove aliases from the end, then omit optional
per-platform/listener entity detail, then fail closed if the fixed core alone
cannot fit. Host, transport, protocol, freshness, health and truncation metadata
remain present.

Alias tests cover empty and overlong identifiers, Unicode, duplicates,
host/child collisions, shared Child/SmartMeter relations, reversed input order
and consecutive independent snapshots. Invalid identifiers are ignored, the
host identity is excluded from the child namespace, duplicates reuse one alias,
and every snapshot starts again at `child_001`; no alias map is retained.

The HA adapter now takes immediate built-in shallow copies of the coordinator
cache, discovery sets/timers, freshness map, HTTP-created set, listener map and
protocol/source evidence. Child lists, expansion mappings and allowlisted child
payload views are likewise copied before iteration. This prevents normal
collection mutation from changing owner state through diagnostics or raising a
changed-size iteration error. Registry helper results were already converted to
tuples, and disappearing entity states remain an `unknown` aggregate. No lock is
added: reads across distinct owners remain a best-effort, non-transactional
snapshot, and unexpected programming errors continue to propagate.

Registry stress uses 300 entry-owned plus 300 foreign entities and 100
entry-owned plus 100 foreign devices. Only requested-entry aggregates affect the
result, which remains below 5 KiB regardless of registry object detail. A
separate endpoint case joins 1,000 discovery identities, including 500 retained
expansion batteries, while preserving the 100-alias and 64-KiB bounds.

Side-effect tests retain active tasks and compare cache, freshness, source,
discovery, missing-timer and observation owners before and after the call. No
publish, poll, discovery, reauth, registry write, entity write, task creation or
task cancellation occurs. P3.4 adds no protocol discovery, persistence, broker
connectivity, command outcome tracking or device diagnostics.

## 8. Diagnostics versus protocol discovery

### 8.1 Standard diagnostics

Standard diagnostics is always safe-by-default output for users, support and
public issue reports. It contains current bounded semantic state and health. It
does not contain raw protocol values beyond the small numeric allowlist, unknown
field names, payload fragments or a traffic history.

### 8.2 Protocol discovery mode

Protocol discovery is a later, separate, explicitly enabled developer feature.
It may observe:

- counts of unknown MQTT message-type categories;
- counts of unknown numeric `devType`/`subType` combinations;
- unknown-field counts at fixed structural paths;
- observed JSON primitive/container type signatures;
- occurrence count and first/last-seen ages;
- bounded differences from known structural schemas.

It must not become a raw MQTT capture. Its observation point is after host-topic
ownership is established and as much structural validation as the category
allows. Rejected input may increment a fixed parse/error category, but its text or
bytes are discarded immediately.

Unknown message types that are safe integers may be bucketed numerically.
Arbitrary string/object message types are bucketed by primitive type, not value.
Unknown field names receive ephemeral local aliases inside a structural
signature; raw names are not stored or exported. Unknown scalar values are never
stored. Serial-like fields, credentials, network fields and dynamic strings are
always represented only by type/presence.

Discovery observations are memory-only, bounded, reset on reload and disabled by
default. Enabling them must be an explicit option and must not change routing,
cache merging, entity discovery, logs or command behavior. A future export may
add a versioned `protocol.discovery` object only when enabled; it must pass the
same complete-output canary and size tests as standard diagnostics.

## 9. Test strategy

### 9.1 Snapshot contract tests

- assert the exact root sections and versioned field schema;
- assert JSON serialization without custom encoders;
- assert deterministic output for identical inputs and clock;
- assert zero is preserved and NaN/infinity are rejected;
- mutate the result and prove runtime/input collections are unchanged;
- mutate runtime/input collections after construction and prove an existing
  snapshot is unchanged;
- cover empty, startup, stale, recovery, reauth, child-removal-timer, expansion
  retention, HTTP disabled and runtime-unavailable states.

### 9.2 Privacy and redaction tests

Inject distinct canaries into configuration, mapping keys and values, nested
lists, child records, registry records, names, IDs, URLs, exception text and
entity attributes, including at minimum:

```text
SUPER_SECRET_TOKEN_123
192.0.2.123
PRIVATE_SSID_CANARY
SERIAL_SECRET_CANARY
```

Serialize the complete final output and assert that no canary or encoded/partial
variant occurs anywhere, including dictionary keys. Also assert that raw serial
hashes, entity IDs, topic prefixes and URL components are absent. Testing only
individual redaction helpers is insufficient.

### 9.3 Side-effect tests

Patch/count the actual MQTT publish/subscribe boundary, HTTP session/request
boundary, poll sender, discovery callbacks, entity `async_write_ha_state`, reauth
flow and entity/device registry mutation methods. Snapshot collection must call
none of them. It must leave caches, freshness clocks, membership sets, task
references, listener maps and registry contents equal to pre-snapshot copies.

### 9.4 Size and malformed-data tests

- more than 100 children and all supported families;
- large known and unknown cache collections;
- malformed/unhashable metadata and nested containers;
- unknown child/message types and very long strings/keys;
- duplicate serials across cache containers;
- missing runtime owner, missing registry records and entities removed during a
  best-effort snapshot;
- exact 64 KiB output enforcement and deterministic omitted counts.

### 9.5 HA adapter tests

- invoke the real config-entry diagnostics function for loaded, unloaded and
  partially initialized entries;
- use multiple config entries and prove registry/runtime aggregation is scoped;
- include disabled entities and devices without current state;
- prove device-page fallback needs no separate device contract;
- validate the installed HA diagnostics function signature and final redaction
  defense;
- rerun lifecycle, HTTP, freshness, discovery, identity/migration and full
  regression suites after passive observation hooks are added.

## 10. Phase 3 implementation plan

The original four-PR hypothesis is split into five PRs. The additional passive
observability PR is required because HTTP health and protocol counters are not
currently readable state. Combining those mutations with the pure serializer or
HA endpoint would blur both review and rollback boundaries.

### P3.1 - Diagnostics contract and pure snapshot layer

**Goal:** implement the versioned output model, snapshot input records,
snapshot-local aliasing, allowlisted selectors and deterministic bounds without a
Home Assistant endpoint.

**Scope:** new HA-independent `diagnostics_snapshot.py`; schema constants; pure
contract/privacy/copy/serialization/size tests based on synthetic owner views.

**Non-scope:** coordinator instrumentation, `diagnostics.py`, registry access,
network calls, protocol discovery, entity changes.

**Acceptance:** exact contract tests pass; full-output canaries are absent;
identical input/clock produces identical output; result is JSON-safe, <=64 KiB
and cannot mutate inputs; module imports only the standard library.

**Dependency:** this architecture document only.

### P3.2 - Passive runtime observability

**Goal:** make required HTTP health and bounded protocol/lifecycle facts readable
without changing operational decisions.

**Scope:** a small HA-independent observation record; updates at existing
coordinator HTTP/routing decision points; read-only copied views from runtime,
discovery and transport owners; fixed outcome/error enums; snapshot integration
tests over real state transitions.

**Non-scope:** HA diagnostics endpoint, registry aggregation, raw payload or
exception retention, source/freshness policy changes, broker connectivity,
command tracking, protocol discovery signatures.

**Affected modules:** likely `coordinator_state.py`, a new observation module,
minimal coordinator call sites in `sensor.py`, and narrowly scoped read views in
`transport/mqtt.py` if count/state normalization cannot stay in the adapter.

**Acceptance:** existing routing, HTTP replacement/failure/recovery, lifecycle,
freshness and source tests remain identical; new tests prove counters mirror
existing transitions and observation cannot influence them; no identifier or raw
data is retained.

**Dependency:** P3.1.

### P3.3 - Home Assistant diagnostics integration

**Goal:** expose config-entry diagnostics through the official HA entry point and
add safe entry-scoped registry/state aggregates.

**Scope:** `diagnostics.py`; runtime lookup through the implemented `hass.data`
boundary; config-presence/version metadata; registry aggregate adapter; final
redaction defense; HA endpoint tests.

**Non-scope:** device-specific endpoint, runtime-data migration, system-health
integration, polls/requests, registry writes, raw state values and attributes.

**Acceptance:** loaded/unloaded/partial and multi-entry tests pass; no IDs or
canaries appear in the full serialized endpoint output; no side-effect boundary
is called; official function signature matches the supported HA test version.

**Status:** completed by the config-entry endpoint and read-only HA adapter
described in section 7.1. Device diagnostics, broker-connectivity inference and
protocol discovery remain out of scope.

**Dependency:** P3.1 and P3.2.

### P3.4 - Diagnostics adversarial hardening

**Goal:** close privacy, mutation, concurrency, size and malformed-data gaps found
against the complete HA endpoint.

**Scope:** expanded canary matrix, fuzz-like malformed structures, collection
copy tests, deterministic truncation, multi-instance isolation, side-effect spies
and documented contract corrections if evidence requires them.

**Non-scope:** new diagnostics categories, protocol discovery, logging redesign,
runtime behavior changes.

**Acceptance:** complete-output privacy assertions pass for keys and values;
64 KiB and collection limits hold under adversarial input; snapshot leaves all
owners unchanged; full repository gates are green.

**Status:** completed by the endpoint and contract stress matrix described in
section 7.2. One live-collection iteration defect was corrected with local
copies at the existing P3.3 adapter boundary. The contract and observation
owners remain unchanged, and P3.5 is still separate.

**Dependency:** P3.3.

### P3.5 - Opt-in protocol discovery mode

**Goal:** add bounded structural observations for reverse engineering without raw
traffic capture.

**Scope:** explicit disabled-by-default option; memory-only observation state;
safe type/signature counters, first/last ages and overflow counts; separate
export section when enabled; privacy/size/lifecycle tests.

**Non-scope:** raw MQTT storage, packet export, unknown-field values, automatic
entity creation, new commands, routing/classification changes and persistent
cross-reload identity.

**Affected modules:** protocol observation model, narrow routing/coordinator
observation hooks, options flow/translation only as required for opt-in, snapshot
contract extension and tests.

**Acceptance:** disabled mode has no observation/output overhead beyond a fixed
flag; enabled mode remains bounded and contains no canaries/raw identifiers;
routing/cache/entity results are byte-for-byte or semantically identical to mode
off; unload/reload clears observations.

**Dependency:** P3.4.

## 11. Open decisions and assumptions

The following decisions must be resolved in their named PR, with tests, before
expanding scope. The P3.1 decisions are resolved in section 6.1, the P3.2
ownership, counter and HTTP-outcome decisions in section 6.4, and the P3.3
adapter decisions in section 7.1. P3.3 deliberately leaves broker connectivity
`unknown` and exposes config-entry diagnostics only; subscription handles are
not connectivity evidence and no device-specific contract was justified.

- **P3.5:** the exact user-facing opt-in and reload behavior must follow the
  existing options lifecycle; protocol discovery must remain disabled by default
  and memory-only.

Assumptions are deliberately narrow: the HA event loop gives the collector a
non-awaiting best-effort copy window; wall-clock receipt timestamps remain the
accepted foundation behavior; and field-level freshness is unavailable unless a
later, separately reviewed state policy introduces it. None of these assumptions
permits diagnostics to rewrite runtime state.
