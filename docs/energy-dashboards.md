# Energy dashboards

There is no single dashboard layout that every SolarVault installation needs.
Use the Home Assistant cards you like, arrange them for your household, and add
custom cards only if they provide a view you want. This guide helps you choose
the right Jackery readings; the examples are optional starting points.

For the complete entity list and device-specific notes, see
[Devices and entities](devices-and-entities.md). Entity IDs depend on your
Home Assistant entity registry and may differ from the examples here. Select
the actual entities shown under **Settings → Devices & services → Jackery** or
in **Developer Tools → States**. You can also use the entity picker in the
dashboard editor.

## Choose entities for a live power-flow view

Power-flow cards normally display current power in watts (W). These readings
are useful starting points:

| Dashboard role | Entity to use | Notes |
| --- | --- | --- |
| Solar production | **Total PV power** | Combined PV input. PV1–PV4 power readings are individual inputs; do not add them to Total PV power. |
| Whole-home grid import/export | **Total grid import power** and **Total grid export power** from a supported SmartMeter 3P; D0 Reader import/export power readings | These are the meter's total directional readings. If you use a Shelly Pro 3EM, use the import and export entities from Home Assistant's Shelly integration for your dashboard. |
| Grid flow as one signed value | **Public-grid net power (import + / export −)** | Positive means import; negative means export. It uses the grid source selected by Jackery SolarVault NG. For a Shelly Pro 3EM, prefer the direct Shelly import/export entities. |
| Battery charging/discharging | **Total battery charging power** and **Total battery discharging power (calculated)** | These represent the calculated battery-system flow. The main-unit charging and discharging readings do not include expansion batteries. |
| Battery flow as one signed value | **Net battery power (charging + / discharging −)** | Positive means charging; negative means discharging. Check the card's sign convention before using it. |
| Home load | **Home consumption (calculated)** | An estimate derived from available meter and SolarVault readings, not a direct whole-home meter measurement. |
| Battery level | **Total state of charge** | The reported BMS state of charge may represent the combined system when multiple batteries are connected. **Main battery state of charge** refers to the main unit. |

The SolarVault's **Energy to home grid**, **Power to home grid**, and related
OnGrid readings describe the SolarVault's own AC connection. They are not
whole-home public-grid import or export. Do not use them as a substitute for a
whole-home meter in a grid-flow card. Without a supported whole-home meter, you
can omit the grid node or use a signed net reading only if your card supports
that representation. The home-consumption value may be an estimate as well.

When a Shelly Pro 3EM is connected to the SolarVault, Jackery SolarVault NG may
also expose the readings relayed by the SolarVault. For dashboard grid import
and export, prefer the Shelly entities provided directly by Home Assistant's
Shelly integration.

## Optional example: Energy Flow Card Plus

[Energy Flow Card Plus](https://github.com/flixlix/energy-flow-card-plus) is a
third-party Home Assistant custom card. It is not included with Jackery SolarVault
NG. Install and configure it separately, then replace every example entity ID
below with the matching entity from your Home Assistant instance. Adapt the
layout and options to your preference and the card version you have installed.

```yaml
type: custom:energy-flow-card-plus
entities:
  solar:
    entity: sensor.replace_with_total_pv_power
    name: Solar
  grid:
    entity:
      consumption: sensor.replace_with_total_grid_import_power
      production: sensor.replace_with_total_grid_export_power
    name: Grid
  battery:
    entity:
      consumption: sensor.replace_with_total_battery_charging_power
      production: sensor.replace_with_total_battery_discharging_power
    state_of_charge: sensor.replace_with_total_state_of_charge
    name: Battery
  home:
    entity: sensor.replace_with_home_consumption_calculated
    name: Home
```

The grid entries in this example require a supported meter that reports both
import and export. For a Shelly Pro 3EM, select its direct Shelly integration
entities, not the Shelly sub-device entities exposed by Jackery SolarVault NG.
If your meter exposes only a signed net value, use a card configuration that
accepts signed grid power instead of mapping that value to both directional
fields.

## Home Assistant Energy dashboard and cumulative readings

The built-in Home Assistant Energy dashboard uses cumulative energy readings
in kilowatt-hours (kWh), rather than instantaneous power readings in watts.
History and statistics cards can display either kind of measurement. For the
Energy dashboard, choose entities such as **Total PV energy** and the **Total
grid import energy** / **Total grid export energy** reported by a supported
whole-home meter. These entities are distinct from the SolarVault's OnGrid
energy readings.

Some additional cumulative readings are available, including battery charging
and discharging energy. These are device-reported counters; expansion batteries
may expose their own counters. Counters can describe different parts of the
system, so do not add them together unless their measurement boundaries are
known. For the same reason, do not add a meter's total energy reading to its
per-phase readings.

See Home Assistant's [Energy documentation](https://www.home-assistant.io/dashboards/energy/)
for dashboard setup and supported sensor requirements. The available entities
depend on the connected device and firmware.

## Match the card to the measurements

- Use W power sensors for live flow diagrams, gauges, and current-value cards.
- Use kWh cumulative energy sensors for daily totals, long-term statistics, and
  Energy dashboard configuration.
- Prefer the total PV reading for overall solar production; use the separate
  PV1–PV4 readings when you want to compare inputs.
- Use whole-home meter readings for whole-home grid flow. SolarVault OnGrid
  readings describe a different electrical boundary.
- Check whether a card expects separate positive import/export values or one
  signed value. Jackery's **Public-grid net power** uses positive for import;
  **Net battery power** uses positive for charging.
- Treat **Home consumption (calculated)** as an estimate. It may differ from a
  dedicated home meter or the SolarVault's separate device estimate.

If a value is missing or unexpected, check whether the connected device reports
that measurement and whether its entity is available. See
[Troubleshooting](troubleshooting.md) for meter and entity checks.
