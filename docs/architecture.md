# Implemented architecture

This document describes only code that exists on the current branch. The
incremental target and risk order remain in [refactoring-roadmap.md](refactoring-roadmap.md).

## Current dependency direction

```text
Home Assistant platform entities
             ↓
sensor.py coordinator and runtime state
             ├──→ protocol/normalization.py ──→ Python standard library
             ├──→ devices/classification.py ──→ Python standard library
             └──→ calculations/energy_flow.py ──→ Python standard library
```

`sensor.py` still owns MQTT/HTTP interaction, routing, cache and freshness state,
entity classes, discovery and coordinator lifecycle. Identity construction and
registry migration already live in `identity.py` and `child_migration.py`.

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
precedence or build commands. Those responsibilities remain in `sensor.py`.

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

The extractions do not alter formulas, raw-cache retention, source priority,
zero/null handling, alias precedence or retention, the flat-status whitelist,
device-family precedence, child freshness, the 50 W anomaly branches, Type-106
precedence, entity IDs or entity metadata. The exact energy behavior and known limits are defined in
[energy-source-policy.md](energy-source-policy.md).
