# Devices and entities

This page describes the device paths and English entity names provided by the Jackery SolarVault NG integration. Home Assistant may also show the device name alongside an entity name. Home Assistant can display localized labels when another language is selected.

The integration currently supports English, German, and French.

The entities that appear depend on the connected devices, firmware, and values reported by each device. Some entities may remain unavailable if the device does not provide their data. This page documents implemented integration paths; it does not certify every device or firmware combination.

The source column lists the reported MQTT field or local HTTP field used by an entity. “Calculated” means the integration derives the value from other readings.

## Device overview

| Device or data path | Entities provided |
| --- | --- |
| SolarVault main unit | Battery, PV, grid connection, backup output, energy flow, status, network and configuration readings, plus the controls below. The current integration includes SolarVault 3 and SolarVault 3 Pro Max paths. |
| Jackery SmartMeter 3P (HTO907A) | Total and per-phase import/export power and energy, plus communication details. Optional local HTTP polling can add electrical measurements. |
| Shelly Pro 3EM connected through Jackery | The same three-phase entity set as the SmartMeter 3P when Jackery reports it as a supported meter. The integration reads it through Jackery; it does not connect to Shelly directly. |
| Jackery D0 Reader (HTO910A) | Aggregate grid import/export power and communication details, without a per-phase entity set. |
| CT meter sub-device | CT power and cumulative CT energy readings. |
| BP2500 expansion battery | Cumulative charge and discharge energy. This path does not expose separate live power or state-of-charge entities for the expansion battery. |
| Smart Plug sub-device | Power and energy readings, plus an on/off switch. The switch is available only in local/LAN communication mode. |

Child-device entities are created when the SolarVault reports the device. Available readings can vary with the connected device and firmware.

## SolarVault sensors

### Battery

| Entity name | Type | MQTT field / calculation | Meaning |
| --- | --- | --- | --- |
| Main battery state of charge | Sensor | <code>batSoc</code> | State of charge reported for the main SolarVault unit. |
| Main battery charging power | Sensor | <code>batInPw</code> | Current charging power of the main unit; expansion batteries are not included in this reading. |
| Main battery discharging power | Sensor | <code>batOutPw</code> | Current discharging power of the main unit; expansion batteries are not included in this reading. |
| Total battery charging power | Sensor | Calculated | Estimated charging power across the main unit and expansion batteries. |
| Total battery discharging power (calculated) | Sensor | Calculated | Estimated discharging power across the main unit and expansion batteries. |
| Battery temperature | Sensor | <code>cellTemp</code> | Battery cell temperature, converted to degrees Celsius. |
| Number of battery modules | Sensor | <code>batNum</code> | Number of battery units reported by the SolarVault. |
| Battery charging energy | Sensor | <code>batChgEgy</code> | Cumulative charging energy reported by the main unit. |
| Battery discharging energy | Sensor | <code>batDisChgEgy</code> | Cumulative discharging energy reported by the main unit. |
| Maximum battery charge | Sensor | <code>socChgLimit</code> | Current battery charge limit setting, shown as a percentage. A separate number entity can change this setting. |
| Minimum battery charge | Sensor | <code>socDischgLimit</code> | Current battery discharge limit setting, shown as a percentage. A separate number entity can change this setting. |
| Total state of charge | Sensor | <code>soc</code> | Battery-system state of charge reported by the BMS; the value can represent the combined system when multiple batteries are connected. |
| Battery status | Sensor | <code>batState</code> | Battery operating status reported by the device. |
| Net battery power (charging + / discharging −) | Sensor | Calculated | Whole-system battery power balance. Positive values mean charging; negative values mean discharging. |

### Solar (PV)

| Entity name | Type | MQTT field / calculation | Meaning |
| --- | --- | --- | --- |
| Total PV power | Sensor | <code>pvPw</code> | Combined power from the PV inputs. |
| Total PV energy | Sensor | <code>pvEgy</code> | Cumulative energy from the PV inputs. |
| PV1 power | Sensor | <code>pv1</code> | Current power at PV input 1. |
| PV1 energy | Sensor | <code>pv1Egy</code> | Cumulative energy at PV input 1. |
| PV2 power | Sensor | <code>pv2</code> | Current power at PV input 2. |
| PV2 energy | Sensor | <code>pv2Egy</code> | Cumulative energy at PV input 2. |
| PV3 power | Sensor | <code>pv3</code> | Current power at PV input 3. |
| PV3 energy | Sensor | <code>pv3Egy</code> | Cumulative energy at PV input 3. |
| PV4 power | Sensor | <code>pv4</code> | Current power at PV input 4. |
| PV4 energy | Sensor | <code>pv4Egy</code> | Cumulative energy at PV input 4. |
| PV charging power limit | Sensor | <code>pvMaxChgPower</code> | Maximum PV charging power reported by the device. |

### Grid connection and home consumption

| Entity name | Type | MQTT field / calculation | Meaning |
| --- | --- | --- | --- |
| Energy to home grid | Sensor | <code>inOngridPw</code> | Power at the SolarVault's OnGrid connection. Despite the entity name, this is not whole-home grid import. |
| Energy from home grid | Sensor | <code>inOngridEgy</code> | Cumulative energy at the SolarVault's OnGrid connection. |
| Power to home grid | Sensor | <code>outOngridPw</code> | SolarVault AC output power at the OnGrid connection; this is not the same as export to the public grid. |
| SolarVault on-grid output energy | Sensor | <code>outOngridEgy</code> | Cumulative energy at the SolarVault's OnGrid AC output. |
| Home-grid power limit | Sensor | <code>maxOutPw</code> | Device-reported limit for the SolarVault's OnGrid AC output. |
| Home consumption (calculated) | Sensor | Calculated | Estimated home consumption based on available meter and SolarVault power readings. Without a meter, SolarVault AC output is used as an estimate. |
| Public-grid net power (import + / export −) | Sensor | Calculated | Grid import minus export. Positive values mean import; negative values mean export. The calculation uses available meter readings when present. |
| CT import energy | Sensor | <code>inCtEgy</code> | Cumulative CT import energy reported by supported firmware. |
| CT export energy | Sensor | <code>outCtEgy</code> | Cumulative CT export energy reported by supported firmware. |
| Home consumption (device estimate) | Sensor | <code>otherLoadPw</code> | Estimate of other home loads reported by the SolarVault. |
| Grid AC input power | Sensor | <code>gridInPw</code> | AC input power reported for the grid side. |
| Grid AC output power | Sensor | <code>gridOutPw</code> | AC output power reported for the grid side. |
| Grid-side input power | Sensor | <code>inGridSidePw</code> | Separate reading for input power on the grid side. |
| Grid-side output power | Sensor | <code>outGridSidePw</code> | Separate reading for output power on the grid side. |
| Public-grid export limit | Sensor | <code>maxFeedGrid</code> | Public-grid export limit reported by the device. A separate number entity can change this setting. |

The SolarVault's OnGrid readings describe power and energy at its own AC
connection. They do not represent whole-home grid import or export. For
whole-home readings, use a supported meter such as the SmartMeter 3P or D0
Reader.

### Backup output (EPS)

| Entity name | Type | MQTT field / calculation | Meaning |
| --- | --- | --- | --- |
| Backup output power | Sensor | <code>swEpsOutPw</code> − <code>swEpsInPw</code> | Net power at the backup/EPS output, calculated as output power minus input power. |
| Backup output energy | Sensor | <code>outEpsEgy</code> | Cumulative energy at the backup/EPS output. |
| Backup input power | Sensor | <code>swEpsInPw</code> | Current input power for the backup/EPS path. |
| Backup input energy | Sensor | <code>inEpsEgy</code> | Cumulative input energy for the backup/EPS path. |
| Backup power status | Sensor | <code>swEpsState</code> | Operating status of the backup/EPS path as reported by the device. |
| Backup power switch | Sensor | <code>swEps</code> | Reported on/off state of the backup switch. A separate switch entity controls it. |

### Cumulative energy flows

These readings show cumulative energy assigned to each path by the SolarVault.

| Entity name | Type | MQTT field / calculation | Meaning |
| --- | --- | --- | --- |
| Backup-to-battery energy | Sensor | <code>acOtBatEgy</code> | Cumulative energy from the AC path into the battery. |
| PV-to-battery energy | Sensor | <code>pvOtBatEgy</code> | Cumulative PV energy charged into the battery. |
| PV-to-backup energy | Sensor | <code>pvOtAcEgy</code> | Cumulative PV energy routed to the AC/backup path. |
| PV-to-home-grid energy | Sensor | <code>pvOtOngridEgy</code> | Cumulative PV energy assigned to the OnGrid path. |
| Home-grid-to-backup energy | Sensor | <code>ongridOtAcLoadEgy</code> | Cumulative energy from the grid/OnGrid path to the AC load. |
| Battery-to-backup energy | Sensor | <code>batOtAcEgy</code> | Cumulative battery energy routed to the AC/backup path. |
| Battery-to-home-grid energy | Sensor | <code>batOtGridEgy</code> | Cumulative battery energy assigned to the grid path. |
| Home-grid-to-battery energy | Sensor | <code>ongridOtBatEgy</code> | Cumulative grid energy charged into the battery. |
| Backup-to-home-grid energy | Sensor | <code>acOtOngridEgy</code> | Cumulative energy from the AC path toward the OnGrid connection. |

### Status, network, and device readings

| Entity name | Type | MQTT field / calculation | Meaning |
| --- | --- | --- | --- |
| Inverter input power | Sensor | <code>stackInPw</code> | Power at the input of the inverter stack. |
| Inverter output power | Sensor | <code>stackOutPw</code> | Power at the output of the inverter stack. |
| Ethernet connected | Sensor | <code>ethPort</code> | Whether the Ethernet port is reported as connected. |
| Wi-Fi signal strength | Sensor | <code>wsig</code> | Wi-Fi signal strength in dBm. |
| Wi-Fi name | Sensor | <code>wname</code> | Name of the connected Wi-Fi network. |
| Ethernet IP address | Sensor | <code>eip</code> | IP address of the Ethernet interface. |
| Wi-Fi IP address | Sensor | <code>wip</code> | IP address of the Wi-Fi interface. |
| Device capabilities | Sensor | <code>ability</code> | Capabilities reported by the device as a bitmask. |
| Function flags | Sensor | <code>funcEnable</code> | Function bitmask; decoded flags are also available as state attributes. |
| Device status | Sensor | <code>stat</code> | General device status. The integration displays recognized statuses in English, such as Normal, Waiting, Alarm, Fault, Standby, Low Power, or Fast charging. |
| Home-grid connection status | Sensor | <code>ongridStat</code> | Connection status of the OnGrid path. |
| CT connection status | Sensor | <code>ctStat</code> | Connection status of the CT/meter. |
| Grid meter connection | Sensor | <code>gridSate</code> | Grid-meter link status reported by the device. |
| Inverter standby limit | Sensor | <code>maxInvStdPw</code> | Device-reported standby power limit for the inverter. |
| Grid-side standby limit | Sensor | <code>maxGridStdPw</code> | Device-reported standby power limit on the grid side. |
| Energy plan output power | Sensor | <code>energyPlanPw</code> | Power value reported for the energy plan. |
| Standby power threshold | Sensor | <code>standbyPw</code> | Power threshold used for standby operation. |
| System output power limit | Sensor | <code>maxSysOutPw</code> | Device-reported power limit at the system output. |
| System input power limit | Sensor | <code>maxSysInPw</code> | Device-reported power limit at the system input. |
| Grid outage switchover time (s) | Sensor | <code>offGridTime</code> | Reported duration or switchover time for off-grid operation, in seconds. |

## SolarVault controls

Controls are available only where supported by the connected device and
firmware. Read-only sensors can report the current value of a setting that also
has a separate control entity.

| Entity name | Control type | MQTT setting / command | Meaning |
| --- | --- | --- | --- |
| Automatic standby mode | Select | <code>autoStandby</code> | Selects the automatic standby behavior: Invalid, Standby, or On. |
| Operating mode | Select | <code>workModel</code> | Selects Self-Consumption, Custom, Tariff Mode, or AI Mode. |
| Set charge limit | Number | <code>socChgLimit</code> | Sets the battery charge limit. The default range is 50–100%; device-reported bounds can override it. |
| Set discharge limit | Number | <code>socDischgLimit</code> | Sets the battery discharge limit. The default range is 5–49%; device-reported bounds can override it. |
| Default output power | Number | <code>defaultPw</code> | Sets default output power for Custom mode. |
| Maximum power to home grid | Number | <code>maxOutPw</code> | Sets the SolarVault OnGrid AC output limit. This is separate from the public-grid export limit. |
| Maximum export to public grid | Number | <code>maxFeedGrid</code> | Sets the public-grid export limit. This is separate from the SolarVault OnGrid AC output limit. |
| Automatic standby allowed | Switch | <code>isAutoStandby</code> | Enables or disables automatic standby. |
| Backup power switch | Switch | <code>swEps</code> | Turns the backup/EPS output on or off. |
| Grid outage fallback | Switch | <code>offGridDown</code> | Enables or disables the grid-outage fallback. |
| Forced charging | Switch | <code>socForceChg</code> | Enables or disables forced charging. |
| Follow meter | Switch | <code>isFollowMeterPw</code> | Makes output power follow the meter. This control is available in Custom mode. |
| Restart | Button | <code>reboot=1</code> | Sends a restart request to the main SolarVault. |

## SmartMeter 3P and Shelly Pro 3EM

The supported three-phase meter paths expose the following entities. Power
totals are summed across phases. The cumulative phase energy readings are
separate per-phase totals; do not add them to the total energy reading.

| Entity name | Type | MQTT field | Meaning |
| --- | --- | --- | --- |
| Total grid import power | Sensor | <code>tPhasePw</code> | Summed current grid import power across the phases. |
| Total grid export power | Sensor | <code>tnPhasePw</code> | Summed current grid export power across the phases. |
| L1 import power | Sensor | <code>aPhasePw</code> | Current grid import power on phase L1. |
| L2 import power | Sensor | <code>bPhasePw</code> | Current grid import power on phase L2. |
| L3 import power | Sensor | <code>cPhasePw</code> | Current grid import power on phase L3. |
| L1 export power | Sensor | <code>anPhasePw</code> | Current grid export power on phase L1. |
| L2 export power | Sensor | <code>bnPhasePw</code> | Current grid export power on phase L2. |
| L3 export power | Sensor | <code>cnPhasePw</code> | Current grid export power on phase L3. |
| Total grid import energy | Sensor | <code>tPhaseEgy</code> | Cumulative grid import energy across the phases. |
| Total grid export energy | Sensor | <code>tnPhaseEgy</code> | Cumulative grid export energy across the phases. |
| L1 import energy | Sensor | <code>aPhaseEgy</code> | Cumulative grid import energy on phase L1. |
| L2 import energy | Sensor | <code>bPhaseEgy</code> | Cumulative grid import energy on phase L2. |
| L3 import energy | Sensor | <code>cPhaseEgy</code> | Cumulative grid import energy on phase L3. |
| L1 export energy | Sensor | <code>anPhaseEgy</code> | Cumulative grid export energy on phase L1. |
| L2 export energy | Sensor | <code>bnPhaseEgy</code> | Cumulative grid export energy on phase L2. |
| L3 export energy | Sensor | <code>cnPhaseEgy</code> | Cumulative grid export energy on phase L3. |
| SmartMeter communication mode | Sensor | <code>commMode</code> | Communication mode displayed as LAN or Cloud. |
| SmartMeter communication status | Sensor | <code>commState</code> | Online/offline status of the meter. |
| SmartMeter IP address | Sensor | <code>wip</code> | IP address reported for the SmartMeter. |

## Other sub-device entities

### CT meter

| Entity name | Type | MQTT field | Meaning |
| --- | --- | --- | --- |
| CT power | Sensor | <code>phasePw</code> | Power reading from the CT sub-device. The direction depends on the connected meter type. |
| CT energy | Sensor | <code>phaseEgy</code> | Cumulative energy reading from the CT sub-device. |

### Jackery D0 Reader (HTO910A)

| Entity name | Type | MQTT field | Meaning |
| --- | --- | --- | --- |
| D0 meter import power | Sensor | <code>inPw</code> | Grid import power reported by the D0 meter. |
| D0 meter export power | Sensor | <code>outPw</code> | Grid export power reported by the D0 meter. |
| D0 meter communication status | Sensor | <code>commState</code> | Online/offline communication status. |
| D0 meter communication mode | Sensor | <code>commMode</code> | Communication mode displayed as LAN or Cloud. |
| D0 meter IP address | Sensor | <code>wip</code> | IP address reported for the meter reader. |

### Smart Plug

| Entity name | Type | MQTT field / command | Meaning |
| --- | --- | --- | --- |
| Smart plug power | Sensor | <code>outPw</code> (fallback: <code>power</code>) | Current output power of the plug. |
| Smart plug energy | Sensor | <code>totalEgy</code> | Cumulative energy measured by the plug. |
| Switch smart plug | Switch | State: <code>sysSwitch</code> (fallback: <code>switchSta</code>); command: <code>sysSwitch</code> | Turns the plug on or off. The integration permits control only in local/LAN communication mode. |

### BP2500 expansion battery

| Entity name | Type | MQTT field | Meaning |
| --- | --- | --- | --- |
| Charged energy | Sensor | <code>inEgy</code> | Cumulative charging energy for this expansion battery. |
| Discharged energy | Sensor | <code>outEgy</code> | Cumulative discharging energy for this expansion battery. |

## Optional SmartMeter HTTP entities

Enable **Poll SmartMeter via HTTP** in the integration options to request these
additional readings from a compatible SmartMeter 3P over the local network.
They appear after a successful HTTP response.

| Entity name | Type | Local HTTP field | Meaning |
| --- | --- | --- | --- |
| L1 voltage | Sensor | <code>volt1</code> | Voltage on phase L1. |
| L2 voltage | Sensor | <code>volt2</code> | Voltage on phase L2. |
| L3 voltage | Sensor | <code>volt3</code> | Voltage on phase L3. |
| L1 current | Sensor | <code>curr1</code> | Current on phase L1. |
| L2 current | Sensor | <code>curr2</code> | Current on phase L2. |
| L3 current | Sensor | <code>curr3</code> | Current on phase L3. |
| L1 reactive power | Sensor | <code>rep1</code> | Reactive power on phase L1. |
| L2 reactive power | Sensor | <code>rep2</code> | Reactive power on phase L2. |
| L3 reactive power | Sensor | <code>rep3</code> | Reactive power on phase L3. |
| L1 apparent power | Sensor | <code>ap1</code> | Apparent power on phase L1. |
| L2 apparent power | Sensor | <code>ap2</code> | Apparent power on phase L2. |
| L3 apparent power | Sensor | <code>ap3</code> | Apparent power on phase L3. |
| L1 power factor | Sensor | <code>fact1</code> | Power factor on phase L1. |
| L2 power factor | Sensor | <code>fact2</code> | Power factor on phase L2. |
| L3 power factor | Sensor | <code>fact3</code> | Power factor on phase L3. |
| Grid frequency | Sensor | <code>freq</code> | Measured grid frequency. |
