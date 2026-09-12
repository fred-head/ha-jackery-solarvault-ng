# Entity inventory

The subsequent [multi-instance identity audit](multi-instance-identity.md) adds
real registry regressions for child collisions, collector reload and unsafe
migration/cleanup cases. Its migration design is proposed, not implemented; the
baseline formats below remain the production contract. PR2A now protects child
IDs and registry ownership and removes the platform-order dependency. The migration
heuristic described below is historical; see the audit's PR2A status for corrections.

## Entity identity and lifecycle contract

Main sensors: `jackery_{main_sn}_{sensor_id}`; main switches: `jackery_{main_sn}_switch_{field}`; numbers: `jackery_{main_sn}_number_{field}`. Main identity falls back to entry ID where constructor code says so. Select suffixes are `auto_standby_select` / `work_mode_select`; reboot suffix `reboot`.

Child sensors: `jackery_{device_name_lower}_{child_sn}_{key_without_underscores}`, where device name is battery, collector, smartmeter (devType=3), ct, or plug. Child switch: `jackery_plug_{child_sn}_switch`. HTTP: `jackery_{main_sn}_http_sm_{meter_sn}_{sensor_key}`. MQTT child unique IDs and device identifiers lack main SN; HTTP IDs include it. Thus main-device multi-instance support does not imply isolation when the same child SN appears under two hosts. Source: C `sensor.py:2437,2564,2852`; platform constructors.

Migration (`__init__.py:17`) preserves recognized lowercase-prefix child IDs only when the following SN starts uppercase; prefixes are smartmeter/battery/plug/ct, **not collector**. It prefixes old main sensors, chooses switch/number suffix from entity platform, translates entry-ID controls, removes conflicting old orphans and already-prefixed `main_*` residue, removes `max_feed_in_select`, and migrates the old entry-ID device identifier to host SN. Collector/numeric-or-lowercase SN preservation is not covered and can be misclassified. Do not import official host-prefixed child IDs or `main_*` controls: they conflict with this migration policy.

No disabled-by-default settings are declared for any platform. Device class/state class are absent for writable entities except reboot's restart device class. Initial numbers and HTTP sensors explicitly start unavailable; other classes largely inherit HA availability and update when data appears. Reboot is not registered for coordinator offline updates. Known entities with missing fields often retain state/availability; no per-field freshness exists.

## Writable entities

All main controls associate with `(jackery, main_sn)` and use MQTT type=1/cmd=5; the plug uses type=103. All are enabled by default. See [MQTT inventory](mqtt-protocol-inventory.md) for envelopes and response limitations.

| Entity field / key | Platform | Unit / limits | Source / optimistic behavior | Source location |
| --- | --- | --- | --- | --- |
| isAutoStandby | switch | none, 0/1 | Cached same field; no optimistic update | `switch.py:28,226` |
| swEps | switch | none, 0/1 | Cached same field; no optimistic update | `switch.py:28,226` |
| offGridDown | switch | none, 0/1 | UI + same cache key patched before publish | `switch.py:284` |
| socForceChg | switch | none, 0/1 | UI + same cache key patched before publish | `switch.py:28,284` |
| isFollowMeterPw | switch | none, 0/1 | Above plus workMode=4 availability condition | `switch.py:300` |
| socChgLimit | number | %, 50–100, step 1 | MQTT confirmed value; minSocChg/maxSocChg override bounds | `number.py:20,140` |
| socDischgLimit | number | %, 5–49, step 1 | MQTT confirmed value; minSocDischg/maxSocDischg override bounds | `number.py:20,140` |
| defaultPw | number | W, 0–200, step 10 | Optimistic integer write and cache | `number.py:20,178` |
| maxOutPw | number | W, 0–2500, step 10 | Optimistic integer write and cache | `number.py:20,178` |
| maxFeedGrid | number | W, 0–2500, step 10 | Optimistic integer write and cache | `number.py:20,178` |
| autoStandby | select | invalid=0, standby=1, on=2 | Reads/writes autoStandby; optimistic cache patch | `select.py:25,99` |
| work_mode | select | self_consumption=2, custom=4, tariff=7, ai=8 | Reads workMode; writes workModel and patches both aliases | `select.py:33,158` |
| reboot | button | restart device class | Sends reboot=1; no command-state entity | `button.py:36` |
| plug switch | switch | none, 0/1; child device | Read sysSwitch before switchSta (opposite Official); writes sysSwitch, no optimistic state patch; commMode=1 required at entity boundary | `switch.py:99,149,171` |

## Source selection, duplicate representations and deprecated entities

Main `battery_charge_power`/`battery_discharge_power` use raw batInPw/batOutPw; total battery charge/discharge and battery_net_power derive the whole-stack balance `pvPw + inOngridPw - outOngridPw - swEpsOutPw + swEpsInPw`. Despite its docstring, the calculation does not prefer raw batInPw for total battery power. `stackInPw/stackOutPw` are separately reported fields, not substituted into that formula (`sensor.py:1997`).

`grid_import_power`/`grid_export_power` use inOngridPw/outOngridPw (unit's AC port), whereas `grid_in_power`/`grid_out_power` use gridInPw/gridOutPw (also alias-normalized from gridBuyPw/gridSellPw), and grid_side_* uses inGridSidePw/outGridSidePw. These are exposed separately. Grid net selects first cached CT, then first collector with inPw/outPw, then largest-magnitude system-field candidate. It excludes inOngridPw/outOngridPw from the last fallback; no HTTP candidate exists. `grid_available` is an internal flag, not an entity. OnGrid port calculation chooses largest absolute net among reported port pairs, not the newest source. Empty CT data can count as available; timestamps/commState are not consulted.

`home_power` uses grid net minus selected port net with two charging discrepancy branches (50 W threshold), then clamps to >=0; without grid source it uses max(0,-port net). otherLoadPw remains a separate raw entity, not a home fallback. Main `grid_net_power` retains its last value if computed value is None (tested). EPS output is bidirectional `swEpsOutPw - swEpsInPw` even though table source is swEpsOutPw; missing operands default to zero. `eps_input_power` separately repeats the input component. PV1–4 dict values select pvPw, w, power in that order; generic scaling handles scalar values. `battery_soc` uses batSoc while `bms_soc` uses soc; official labels soc Average SOC. Do not rename either without verifying meaning/history.

Read-only max_output_power, soc_charge_limit, soc_discharge_limit, max_feed_grid_power and eps_switch duplicate fields represented by writable entities. Raw status/options and units remain compatibility contracts. Main/child/CT-port energy totals may describe different boundaries; never sum them merely because they are all kWh. Legacy CT per-subType selection and phase energy fallback are separate from direct lowercase SmartMeter reads. HTTP's 16 sensors supplement MQTT (no power-source precedence implemented).

The work_mode read-only sensor and socForceChg number are absent from current definitions. maxOutPw moved from select to number and obsolete max_feed_in_select is explicitly removed by migration. There is no corresponding cleanup for every historical work_mode/socForceChg entity. Source comments in number.py still mention a maxOutPw select although final code creates a number; dictionary/constructor behavior takes precedence over those stale comments.

Baseline and evidence notation: [baseline](baseline.md). Tables enumerate runtime dictionaries at C, with source anchors for every definition. All rows below are **read-only sensor entities**, enabled by default (no integration override), with no explicit entity category. All main sensors belong to the main SN device; each child group belongs to `sub_{child_sn}` via the main device. HTTP sensors belong to the same meter device as MQTT sensors. A dash means absent/None metadata.

## Sensor definitions

Main and child MQTT values come from the merged coordinator cache. HTTP values come directly from `/api/measurement`, never the MQTT cache. Derived main fields and exceptions are described below; scale 1 means no generic multiplier.

### main (75)

| Logical key | Source / normalized key | Unit | Device class | State class | Scale / mapping |
| --- | --- | --- | --- | --- | --- |
| [battery_soc](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L62) | `batSoc` | % | battery | measurement | 1 |
| [battery_charge_power](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L70) | `batInPw` | W | power | measurement | 1 |
| [battery_discharge_power](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L78) | `batOutPw` | W | power | measurement | 1 |
| [total_battery_charge_power](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L86) | `total_battery_charge_power` | W | power | measurement | 1 |
| [total_battery_discharge_power](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L94) | `total_battery_discharge_power` | W | power | measurement | 1 |
| [battery_temperature](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L102) | `cellTemp` | °C | temperature | measurement | 0.1 (entity transform) |
| [battery_count](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L110) | `batNum` | — | — | measurement | 1 |
| [battery_charge_energy](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L119) | `batChgEgy` | kWh | energy | total_increasing | 0.01 |
| [battery_discharge_energy](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L128) | `batDisChgEgy` | kWh | energy | total_increasing | 0.01 |
| [solar_power](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L139) | `pvPw` | W | power | measurement | 1 |
| [solar_energy](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L147) | `pvEgy` | kWh | energy | total_increasing | 0.01 |
| [solar_power_pv1](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L156) | `pv1` | W | power | measurement | 1 |
| [solar_energy_pv1](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L164) | `pv1Egy` | kWh | energy | total_increasing | 0.01 |
| [solar_power_pv2](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L173) | `pv2` | W | power | measurement | 1 |
| [solar_energy_pv2](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L181) | `pv2Egy` | kWh | energy | total_increasing | 0.01 |
| [solar_power_pv3](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L190) | `pv3` | W | power | measurement | 1 |
| [solar_energy_pv3](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L198) | `pv3Egy` | kWh | energy | total_increasing | 0.01 |
| [solar_power_pv4](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L207) | `pv4` | W | power | measurement | 1 |
| [solar_energy_pv4](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L215) | `pv4Egy` | kWh | energy | total_increasing | 0.01 |
| [grid_import_power](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L226) | `inOngridPw` | W | power | measurement | 1 |
| [grid_import_energy](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L234) | `inOngridEgy` | kWh | energy | total_increasing | 0.01 |
| [grid_export_power](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L243) | `outOngridPw` | W | power | measurement | 1 |
| [grid_export_energy](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L251) | `outOngridEgy` | kWh | energy | total_increasing | 0.01 |
| [max_output_power](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L260) | `maxOutPw` | W | power | measurement | 1 |
| [eps_output_power](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L270) | `swEpsOutPw` | W | power | measurement | 1 |
| [eps_output_energy](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L278) | `outEpsEgy` | kWh | energy | total_increasing | 0.01 |
| [eps_input_power](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L287) | `swEpsInPw` | W | power | measurement | 1 |
| [eps_input_energy](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L295) | `inEpsEgy` | kWh | energy | total_increasing | 0.01 |
| [eps_state](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L304) | `swEpsState` | — | — | — | 1 |
| [eps_switch](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L312) | `swEps` | — | — | — | 1 |
| [soc_charge_limit](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L322) | `socChgLimit` | % | — | measurement | 1 |
| [soc_discharge_limit](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L330) | `socDischgLimit` | % | — | measurement | 1 |
| [home_power](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L356) | `calc_home_power` | W | power | measurement | 1 |
| [battery_net_power](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L364) | `calc_batt_net_power` | W | power | measurement | 1 |
| [grid_net_power](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L372) | `calc_grid_net_power` | W | power | measurement | 1 |
| [ac_to_battery_energy](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L381) | `acOtBatEgy` | kWh | energy | total_increasing | 0.01 |
| [pv_to_battery_energy](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L390) | `pvOtBatEgy` | kWh | energy | total_increasing | 0.01 |
| [pv_to_ac_energy](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L399) | `pvOtAcEgy` | kWh | energy | total_increasing | 0.01 |
| [pv_to_grid_energy](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L408) | `pvOtOngridEgy` | kWh | energy | total_increasing | 0.01 |
| [grid_to_ac_load_energy](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L417) | `ongridOtAcLoadEgy` | kWh | energy | total_increasing | 0.01 |
| [battery_to_ac_energy](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L426) | `batOtAcEgy` | kWh | energy | total_increasing | 0.01 |
| [battery_to_grid_energy](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L435) | `batOtGridEgy` | kWh | energy | total_increasing | 0.01 |
| [grid_to_battery_energy](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L444) | `ongridOtBatEgy` | kWh | energy | total_increasing | 0.01 |
| [ct_import_energy](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L453) | `inCtEgy` | kWh | energy | total_increasing | 0.01 |
| [ct_export_energy](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L462) | `outCtEgy` | kWh | energy | total_increasing | 0.01 |
| [ac_to_grid_energy](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L471) | `acOtOngridEgy` | kWh | energy | total_increasing | 0.01 |
| [stack_in_power](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L482) | `stackInPw` | W | power | measurement | 1 |
| [stack_out_power](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L490) | `stackOutPw` | W | power | measurement | 1 |
| [bms_soc](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L500) | `soc` | % | battery | measurement | 1 |
| [battery_state](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L510) | `batState` | — | — | — | 1 |
| [ethernet_connected](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L520) | `ethPort` | — | — | — | 1 |
| [wifi_signal](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L528) | `wsig` | dBm | signal_strength | measurement | 1 |
| [max_inverter_standby_power](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L538) | `maxInvStdPw` | W | power | measurement | 1 |
| [max_grid_standby_power](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L546) | `maxGridStdPw` | W | power | measurement | 1 |
| [wifi_ssid](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L556) | `wname` | — | — | — | 1 |
| [ethernet_ip](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L564) | `eip` | — | — | — | 1 |
| [wlan_ip](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L572) | `wip` | — | — | — | 1 |
| [device_capability](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L580) | `ability` | — | — | — | 1 |
| [func_enable](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L590) | `funcEnable` | — | — | — | 1 |
| [device_status](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L600) | `stat` | — | enum | — | {0: 'normal', 1: 'waiting', 2: 'alarm', 3: 'fault', 4: 'standby', 5: 'low_power'} |
| [ongrid_status](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L610) | `ongridStat` | — | enum | — | {0: 'disconnected', 1: 'connected'} |
| [ct_status](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L620) | `ctStat` | — | enum | — | {0: 'disconnected', 1: 'connected'} |
| [grid_meter_link](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L630) | `gridSate` | — | enum | — | {0: 'not_linked', 1: 'linked'} |
| [other_load_power](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L642) | `otherLoadPw` | W | power | measurement | 1 |
| [grid_in_power](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L650) | `gridInPw` | W | power | measurement | 1 |
| [grid_out_power](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L658) | `gridOutPw` | W | power | measurement | 1 |
| [grid_side_in_power](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L666) | `inGridSidePw` | W | power | measurement | 1 |
| [grid_side_out_power](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L674) | `outGridSidePw` | W | power | measurement | 1 |
| [energy_plan_power](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L682) | `energyPlanPw` | W | power | measurement | 1 |
| [standby_power](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L690) | `standbyPw` | W | power | measurement | 1 |
| [pv_max_charge_power](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L698) | `pvMaxChgPower` | W | power | measurement | 1 |
| [max_system_output_power](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L706) | `maxSysOutPw` | W | power | measurement | 1 |
| [max_system_input_power](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L714) | `maxSysInPw` | W | power | measurement | 1 |
| [off_grid_time](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L722) | `offGridTime` | s | — | — | 1 |
| [max_feed_grid_power](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L733) | `maxFeedGrid` | W | power | measurement | 1 |

### plug (2)

| Logical key | Source / normalized key | Unit | Device class | State class | Scale / mapping |
| --- | --- | --- | --- | --- | --- |
| [power](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L747) | `outPw` | W | power | measurement | 1 |
| [energy](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L755) | `totalEgy` | kWh | energy | total_increasing | 0.01 |

### ct (2)

| Logical key | Source / normalized key | Unit | Device class | State class | Scale / mapping |
| --- | --- | --- | --- | --- | --- |
| [power](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L767) | `phasePw` | W | power | measurement | 1 |
| [energy](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L775) | `phaseEgy` | kWh | energy | total_increasing | 0.01 |

### ct_3phase (19)

| Logical key | Source / normalized key | Unit | Device class | State class | Scale / mapping |
| --- | --- | --- | --- | --- | --- |
| [import_total](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L789) | `tPhasePw` | W | power | measurement | 1 |
| [export_total](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L797) | `tnPhasePw` | W | power | measurement | 1 |
| [import_l1](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L805) | `aPhasePw` | W | power | measurement | 1 |
| [import_l2](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L813) | `bPhasePw` | W | power | measurement | 1 |
| [import_l3](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L821) | `cPhasePw` | W | power | measurement | 1 |
| [export_l1](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L829) | `anPhasePw` | W | power | measurement | 1 |
| [export_l2](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L837) | `bnPhasePw` | W | power | measurement | 1 |
| [export_l3](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L845) | `cnPhasePw` | W | power | measurement | 1 |
| [import_energy_total](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L853) | `tPhaseEgy` | kWh | energy | total_increasing | 0.01 |
| [export_energy_total](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L862) | `tnPhaseEgy` | kWh | energy | total_increasing | 0.01 |
| [import_energy_l1](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L871) | `aPhaseEgy` | kWh | energy | total_increasing | 0.01 |
| [import_energy_l2](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L880) | `bPhaseEgy` | kWh | energy | total_increasing | 0.01 |
| [import_energy_l3](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L889) | `cPhaseEgy` | kWh | energy | total_increasing | 0.01 |
| [export_energy_l1](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L898) | `anPhaseEgy` | kWh | energy | total_increasing | 0.01 |
| [export_energy_l2](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L907) | `bnPhaseEgy` | kWh | energy | total_increasing | 0.01 |
| [export_energy_l3](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L916) | `cnPhaseEgy` | kWh | energy | total_increasing | 0.01 |
| [comm_mode](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L926) | `commMode` | — | enum | — | ['lan', 'cloud']; offset=1 |
| [comm_state](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L936) | `commState` | — | enum | — | ['offline', 'online'] |
| [ip_address](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L945) | `wip` | — | — | — | 1 |

### collector (5)

| Logical key | Source / normalized key | Unit | Device class | State class | Scale / mapping |
| --- | --- | --- | --- | --- | --- |
| [import_power](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L962) | `inPw` | W | power | measurement | 1 |
| [export_power](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L969) | `outPw` | W | power | measurement | 1 |
| [comm_state](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L976) | `commState` | — | enum | — | ['offline', 'online'] |
| [comm_mode](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L983) | `commMode` | — | enum | — | ['lan', 'cloud']; offset=1 |
| [ip_address](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L991) | `wip` | — | — | — | 1 |

### expansion_battery (2)

| Logical key | Source / normalized key | Unit | Device class | State class | Scale / mapping |
| --- | --- | --- | --- | --- | --- |
| [charge_energy](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L1000) | `inEgy` | kWh | energy | total_increasing | 0.01 |
| [discharge_energy](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L1009) | `outEgy` | kWh | energy | total_increasing | 0.01 |

### http_smartmeter (16)

| Logical key | Source / normalized key | Unit | Device class | State class | Scale / mapping |
| --- | --- | --- | --- | --- | --- |
| [voltage_l1](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L1107) | `volt1` | V | voltage | measurement | 1 |
| [voltage_l2](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L1108) | `volt2` | V | voltage | measurement | 1 |
| [voltage_l3](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L1109) | `volt3` | V | voltage | measurement | 1 |
| [current_l1](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L1110) | `curr1` | A | current | measurement | 1 |
| [current_l2](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L1111) | `curr2` | A | current | measurement | 1 |
| [current_l3](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L1112) | `curr3` | A | current | measurement | 1 |
| [reactive_power_l1](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L1113) | `rep1` | var | reactive_power | measurement | 1 |
| [reactive_power_l2](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L1114) | `rep2` | var | reactive_power | measurement | 1 |
| [reactive_power_l3](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L1115) | `rep3` | var | reactive_power | measurement | 1 |
| [apparent_power_l1](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L1116) | `ap1` | VA | apparent_power | measurement | 1 |
| [apparent_power_l2](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L1117) | `ap2` | VA | apparent_power | measurement | 1 |
| [apparent_power_l3](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L1118) | `ap3` | VA | apparent_power | measurement | 1 |
| [power_factor_l1](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L1119) | `fact1` | — | power_factor | measurement | 0.001 |
| [power_factor_l2](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L1120) | `fact2` | — | power_factor | measurement | 0.001 |
| [power_factor_l3](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L1121) | `fact3` | — | power_factor | measurement | 0.001 |
| [frequency](https://github.com/csoscd/ha-solarvault/blob/183d74b7e042061ccb985ddc023b3cb7a085452e/custom_components/jackery/sensor.py#L1122) | `freq` | Hz | frequency | measurement | 1 |
