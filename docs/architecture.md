# Implemented architecture

This document describes only code that exists on the current branch. The
incremental target and risk order remain in [refactoring-roadmap.md](refactoring-roadmap.md).

## Current dependency direction

```text
Home Assistant platform entities
             ├──→ entities/sensor_definitions.py ──→ HA metadata/constants
             ├──→ entities/transforms.py ──→ Python standard library
             ↓
sensor.py coordinator orchestration, entities and HA effects
             ├──→ coordinator_state.py ──→ Python standard library
             ├──→ protocol/commands.py ──→ Python standard library
             ├──→ protocol/routing.py ──→ protocol/normalization.py
             │                                  ↓
             │                         Python standard library
             ├──→ protocol/normalization.py ──→ Python standard library
             ├──→ devices/classification.py ──→ Python standard library
             ├──→ calculations/energy_flow.py ──→ Python standard library
             ├──→ transport/mqtt.py ──→ Home Assistant MQTT API
             └──→ transport/smartmeter_http.py ──→ aiohttp
```

`sensor.py` still owns HTTP polling and health policy, route application, entity
classes, discovery, availability side effects and coordinator lifecycle.
Low-level MQTT interaction lives in `transport/mqtt.py`; low-level SmartMeter
request and response validation live in `transport/smartmeter_http.py`. Ephemeral cache,
freshness and source evidence live in `coordinator_state.py`. Identity
construction and registry migration live in `identity.py` and
`child_migration.py`.

## Setup and entity boundary

Integration setup creates and stores the coordinator before forwarding all five
platforms, then starts runtime transports only after the sensor and switch
platforms install their dynamic-add callbacks. Platform modules retain static
entity construction. Coordinator discovery retains the decision and current
construction path for dynamic children and HTTP sensors. Entity lifecycle hooks
retain listener registration and removal.

Declarative main, child and HTTP sensor metadata now lives in
`entities/sensor_definitions.py`. Migration reads those keys directly without
loading `sensor.py`; historical imports from `sensor.py` remain compatibility
re-exports. Pure Smart Plug communication-mode conversion lives in
`entities/transforms.py` and is consumed directly by the switch platform. The
complete ownership inventory and intentionally retained coupling are in
[entity-boundaries.md](entity-boundaries.md).

## Protocol command builders

`custom_components/jackery/protocol/commands.py` builds the established action
topic and plain Python envelopes for main controls, plug controls and type
2/25/100/105 requests. Explicit timestamps and message IDs keep the builders
deterministic. The module uses only the Python standard library and never calls
Home Assistant, MQTT, coordinator, entity, calculation, classification or state
APIs.

The coordinator still checks for a host serial, generates wall-clock timestamps
and random message IDs, serializes JSON, publishes with QoS 0/retain false and
owns logging and error boundaries. It also retains poll cadence/order/sleeps and
all optimistic cache behavior. The extraction adds no acknowledgement,
correlation, retry or rollback semantics. Control tokens remain conditional on
truthiness, while request envelopes always contain the token key, including for
empty or null values.

## MQTT transport

Each coordinator creates one `JackeryMqttTransport`. It calls the Home Assistant
MQTT API for QoS-1 subscriptions, retains each synchronous unsubscribe callback
immediately, serializes outbound mappings with the existing `json.dumps`
boundary and publishes with QoS 0/retain false. Partial subscribe failure removes
already-created listeners. Stop detaches all handles before invoking them,
attempts every callback and reports collected failures, making repeated stop
idempotent and keeping config entries isolated.

The coordinator still decides when to start and stop, supplies the exact status
and event topics and raw-message callback, owns the lifecycle lock and
`_subscribed` state, creates/cancels polling and HTTP tasks, builds commands,
chooses action topics and preserves all log severities and error boundaries.
Poll cadence/order/sleeps, routing, state, freshness, reauth and optimistic
updates remain outside transport. The HTTP polling loop is still coordinator
owned; no generic transport interface was introduced.

## SmartMeter HTTP transport

`SmartMeterHttpTransport` receives Home Assistant's shared aiohttp session and
owns the exact `/api/measurement` URL, GET request, five-second timeout, status
capture, JSON decoding and the existing minimum-success check. The coordinator
passes the established measurement keys, so the transport does not import entity
definitions. A successful body remains a dictionary containing at least one
configured value accepted by `float()`.

MQTT-cache target discovery, options, the polling task and cadence, the
three-failure health threshold, recovery, replacement-meter handling, sensor
creation and entity fan-out remain coordinator policy. The transport holds no HA
entity or coordinator reference and never creates its own HTTP session. The
single per-coordinator `_http_sm_sensors_created` flag still means a replacement
meter does not automatically receive a second entity set; that existing limit is
unchanged.

## Coordinator runtime state

`custom_components/jackery/coordinator_state.py` provides one
`CoordinatorRuntimeState` per coordinator. It owns the main/child protocol cache,
host and child activity timestamps, Type-106 live/snapshot evidence and selected
energy-source metadata. It applies main-payload and Type-106 cache transitions
and answers host/child freshness questions. It imports only the Python standard
library and holds no Home Assistant objects.

The coordinator continues to decide when a route is applied and prepares
normalized/validated values. It also owns discovery membership and missing-child
timers because those transitions directly create or remove entities and registry
objects. Entity availability writes, MQTT/HTTP lifecycle, reauth, device metadata,
identity and migration stay outside runtime state. Existing private cache and
freshness attributes are compatibility views of the same state, not duplicate
storage. The complete field inventory and reset contract are in
[coordinator-state.md](coordinator-state.md).

## Protocol routing package

`custom_components/jackery/protocol/routing.py` owns the pure structural edge of
inbound MQTT routing. `parse_topic()` recognizes only the exact escaped
`{root}/device/{serial}/status|event` shape. `parse_envelope()` decodes JSON,
rejects unsupported envelope/body shapes, reconstructs the established flat
body and sanitizes known child-array containers without mutating caller data.
`route_message_type()` returns an immutable `RoutingDecision` containing the raw
message type, its `MessageRoute`, and the existing host-metadata and generic-child
refresh flags. `TopicInfo` and `ParsedEnvelope` carry the other validated values.
The module imports only the Python standard library and
`protocol.normalization`.

The processing pipeline divides those decisions and effects as follows:

| `_handle_message` responsibility | Current owner and category |
| --- | --- |
| 1. Topic validation | `protocol.routing.parse_topic`; pure routing |
| 2. Host serial validation/adoption | Topic extraction is pure; rejection and adoption are coordinator state |
| 3. Payload decoding | `protocol.routing.parse_envelope`; protocol structure |
| 4. Body reconstruction/normalization | Flat reconstruction is `protocol.normalization` via routing; field aliases remain applied at cache merge |
| 5. Malformed-array sanitization | `protocol.routing`; pure copied structural validation |
| 6. Host freshness | `CoordinatorRuntimeState`; coordinator schedules availability effects |
| 7. Device metadata capture | Routing supplies the eligibility decision; coordinator mutates metadata/registry state |
| 8. Message-type routing | `protocol.routing.route_message_type`; pure routing |
| 9. Main cache mutation | Main and Type-106 transitions use `CoordinatorRuntimeState`; child placement remains coordinator logic |
| 10. Child cache mutation | Storage is runtime state; coordinator owns route-specific merges using `devices.classification` |
| 11. Type-106 live/snapshot arbitration | `CoordinatorRuntimeState`, supplied with coordinator policy constants and normalized values |
| 12. Reauthentication | Routing recognizes Type 123; coordinator owns the HA action and guard |
| 13. Energy calculation | Coordinator adapter calls `calculations.energy_flow`; source metadata is stored in runtime state |
| 14. Discovery | Coordinator and platform lifecycle |
| 15. Entity fan-out | Coordinator and entity lifecycle |
| 16. Logging/error containment | Coordinator; JSON errors intentionally propagate to its topic-aware warning |

This is a partial routing extraction. It does not introduce a protocol state
machine or move state transitions into the pure module. The post-route order
remains calculation, child discovery/synchronization, then entity fan-out.

## Device classification package

`custom_components/jackery/devices/classification.py` owns the established
child-device family decisions. `classify_device()` returns an immutable result
containing the effective `devType`, family and, where the existing subtype rules
identify one, the HTO907A, Shelly Pro 3EM or HTO910A model association. Explicit
contexts preserve the different defaults used by plug arrays, CT arrays,
Type-102 point updates, Type-23 child statistics and discovery.

The classifier imports only the Python standard library and never mutates its
input. It also owns the existing static plug-switch filter and the diagnostic CT
subtype label table. The label table remains descriptive metadata rather than a
hardware classifier.

Routing and cache placement remain in `sensor.py`: the same payload can retain
different behavior when its array location contradicts its `devType`. Entity
group selection, entity construction, source-array lookup, communication-mode
control policy, field transforms, physical identity and registry migration also
remain outside the classifier. Child identity continues to use host plus child
serial independently of family or subtype, so a later subtype change does not
create a second physical device.

## Protocol normalization package

`custom_components/jackery/protocol/normalization.py` owns the established
`gridBuyPw` to `gridInPw`, `gridSellPw` to `gridOutPw` and `workModel` to
`workMode` aliases. It also reconstructs a body from the existing flat-status
whitelist and removes the established envelope metadata keys. Both functions
make shallow copies, preserve original and unknown wire fields and import only
the Python standard library.

The module does not parse JSON, validate topics or hosts, select a message route,
classify devices, merge state, advance freshness, apply Type-106 live/snapshot
precedence or build commands. Structural JSON/topic parsing and route selection
are composed above it in `protocol.routing`; cache/source evidence is stored in
`coordinator_state.py`, while orchestration and HA effects remain in `sensor.py`.

## Energy calculation package

`custom_components/jackery/calculations/energy_flow.py` owns calculation-specific
numeric handling, CT/SmartMeter and collector extraction, the existing host
candidate rules, grid-source selection and all derived energy-flow formulas.
It imports only the Python standard library. It does not know about Home
Assistant entities, MQTT, config entries, registries, coordinator tasks or
protocol envelope types.

`select_grid_source(data, child_freshness)` accepts ordinary raw/cache mappings
after protocol alias normalization. The optional freshness mapping contains
availability and activity age prepared by the coordinator. It returns an
immutable `GridSourceSelection` with directional buy/sell values and the existing
source-decision metadata. Selection does not mutate raw input.

`calculate_energy_flow(data, grid_source)` accepts a mutable, normalized state
dictionary and an optional selection. It preserves the established internal
contract by adding/updating these keys in the same dictionary and returning that
same object:

- `calc_home_power`
- `calc_batt_net_power`
- `total_battery_charge_power`
- `total_battery_discharge_power`
- `grid_available`
- `calc_grid_net_power`

When no explicit grid selection is supplied, it selects from the data without a
runtime freshness constraint. This supports direct deterministic tests. The
coordinator always supplies the runtime state's freshness-aware selection during
production message processing and timer reevaluation.

The coordinator's `_calculate_energy_flow` method remains as a narrow adapter.
It applies `normalize_payload_fields`, translates
its child last-seen state into `SourceFreshness`, calls the pure calculation
functions, stores source observability metadata in runtime state and retains the
existing error log/fallback boundary.

Type-106 live/snapshot maps and receipt-time transitions live in
`coordinator_state.py`; the coordinator supplies the established field set,
60-second window and accepted-message receipt time. HTTP health, MQTT lifecycle,
entity availability and state writes remain in `sensor.py`. The calculation
package does not decide whether a Home Assistant entity is available.

## Preserved contract

The extractions do not alter message routing, formulas, raw-cache retention,
source priority, zero/null handling, alias precedence or retention, the
flat-status whitelist, device-family precedence, child freshness, the 50 W
anomaly branches, Type-106 precedence, entity IDs or entity metadata. The exact
energy behavior and known limits are defined in
[energy-source-policy.md](energy-source-policy.md).
