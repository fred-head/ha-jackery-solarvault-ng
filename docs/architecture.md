# Implemented architecture

This document describes only code that exists on the current branch. The
incremental target and risk order remain in [refactoring-roadmap.md](refactoring-roadmap.md).

## Current dependency direction

```text
Home Assistant platform entities
             ↓
sensor.py coordinator and runtime state
             ├──→ protocol/routing.py ──→ protocol/normalization.py
             │                                  ↓
             │                         Python standard library
             ├──→ protocol/normalization.py ──→ Python standard library
             ├──→ devices/classification.py ──→ Python standard library
             └──→ calculations/energy_flow.py ──→ Python standard library
```

`sensor.py` still owns MQTT/HTTP interaction, route application, cache and
freshness state, entity classes, discovery and coordinator lifecycle. Identity
construction and registry migration already live in `identity.py` and
`child_migration.py`.

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

The coordinator consumes those decisions and still owns every runtime effect:

| `_handle_message` responsibility | Current owner and category |
| --- | --- |
| 1. Topic validation | `protocol.routing.parse_topic`; pure routing |
| 2. Host serial validation/adoption | Topic extraction is pure; rejection and adoption are coordinator state |
| 3. Payload decoding | `protocol.routing.parse_envelope`; protocol structure |
| 4. Body reconstruction/normalization | Flat reconstruction is `protocol.normalization` via routing; field aliases remain applied at cache merge |
| 5. Malformed-array sanitization | `protocol.routing`; pure copied structural validation |
| 6. Host freshness | Coordinator state |
| 7. Device metadata capture | Routing supplies the eligibility decision; coordinator mutates metadata/registry state |
| 8. Message-type routing | `protocol.routing.route_message_type`; pure routing |
| 9. Main cache mutation | Coordinator state |
| 10. Child cache mutation | Coordinator state, using `devices.classification` for family decisions |
| 11. Type-106 live/snapshot arbitration | Coordinator state |
| 12. Reauthentication | Routing recognizes Type 123; coordinator owns the HA action and guard |
| 13. Energy calculation | Coordinator adapter calls `calculations.energy_flow` after route mutation |
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
are composed above it in `protocol.routing`; runtime effects remain in
`sensor.py`.

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
coordinator always supplies its freshness-aware selection during production
message processing and timer reevaluation.

The coordinator's `_calculate_energy_flow` method remains as a narrow adapter.
It applies `normalize_payload_fields`, translates
its child last-seen state into `SourceFreshness`, calls the pure calculation
functions, stores source observability metadata and retains the existing error
log/fallback boundary.

Type-106 live/snapshot maps and receipt-time policy remain in `sensor.py` because
they are cache/state-transition responsibilities. HTTP health, MQTT lifecycle,
entity availability and state writes also remain there. The calculation package
does not decide whether a Home Assistant entity is available.

## Preserved contract

The extractions do not alter message routing, formulas, raw-cache retention,
source priority, zero/null handling, alias precedence or retention, the
flat-status whitelist, device-family precedence, child freshness, the 50 W
anomaly branches, Type-106 precedence, entity IDs or entity metadata. The exact
energy behavior and known limits are defined in
[energy-source-policy.md](energy-source-policy.md).
