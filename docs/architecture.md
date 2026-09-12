# Implemented architecture

This document describes only code that exists on the current branch. The
incremental target and risk order remain in [refactoring-roadmap.md](refactoring-roadmap.md).

## Current dependency direction

```text
Home Assistant platform entities
             ↓
sensor.py coordinator and runtime state
             ↓
calculations/energy_flow.py
             ↓
Python standard library
```

`sensor.py` still owns MQTT/HTTP interaction, protocol normalization, cache and
freshness state, entity classes, discovery and coordinator lifecycle. Identity
construction and registry migration already live in `identity.py` and
`child_migration.py`.

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
It applies the existing `_normalize_payload_fields` protocol aliases, translates
its child last-seen state into `SourceFreshness`, calls the pure calculation
functions, stores source observability metadata and retains the existing error
log/fallback boundary.

Type-106 live/snapshot maps and receipt-time policy remain in `sensor.py` because
they are cache/state-transition responsibilities. HTTP health, MQTT lifecycle,
entity availability and state writes also remain there. The calculation package
does not decide whether a Home Assistant entity is available.

## Preserved contract

The extraction does not alter formulas, raw-cache retention, source priority,
zero/null handling, alias precedence, child freshness, the 50 W anomaly branches,
Type-106 precedence, entity IDs or entity metadata. The exact behavior and known
limits are defined in [energy-source-policy.md](energy-source-policy.md).
