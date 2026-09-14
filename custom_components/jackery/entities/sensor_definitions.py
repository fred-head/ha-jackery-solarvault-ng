"""Declarative sensor metadata for Jackery Home Assistant entities."""

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    UnitOfApparentPower,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfReactivePower,
    UnitOfTemperature,
    UnitOfTime,
)

__all__ = [
    "CT_STATUS_MAP",
    "DEVICE_STATUS_MAP",
    "FUNC_ENABLE_BITS",
    "GRID_METER_LINK_MAP",
    "ONGRID_STATUS_MAP",
    "SENSORS",
    "SMARTMETER_HTTP_SENSOR_CONFIGS",
    "SUBDEVICE_SENSORS",
]

# ENUM value → option-key maps for status sensors (Ü5/Ü6 from upstream v2.0.0)
DEVICE_STATUS_MAP: dict[int, str] = {
    0: "normal", 1: "waiting", 2: "alarm", 3: "fault", 4: "standby", 5: "low_power",
}
ONGRID_STATUS_MAP: dict[int, str] = {0: "disconnected", 1: "connected"}
CT_STATUS_MAP: dict[int, str] = {0: "disconnected", 1: "connected"}
GRID_METER_LINK_MAP: dict[int, str] = {0: "not_linked", 1: "linked"}

# 传感器配置
SENSORS = {
    # 电池相关
    "battery_soc": {
        "json_key": "batSoc",
        "name": "Battery SOC",
        "unit": PERCENTAGE,
        "icon": "mdi:battery-50",
        "device_class": SensorDeviceClass.BATTERY,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "battery_charge_power": {
        "json_key": "batInPw",
        "name": "Main Unit Charge Power",
        "unit": UnitOfPower.WATT,
        "icon": "mdi:battery-charging",
        "device_class": SensorDeviceClass.POWER,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "battery_discharge_power": {
        "json_key": "batOutPw",
        "name": "Main Unit Discharge Power",
        "unit": UnitOfPower.WATT,
        "icon": "mdi:battery-minus",
        "device_class": SensorDeviceClass.POWER,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "total_battery_charge_power": {
        "json_key": "total_battery_charge_power",
        "name": "Total Battery Charge Power",
        "unit": UnitOfPower.WATT,
        "icon": "mdi:battery-charging",
        "device_class": SensorDeviceClass.POWER,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "total_battery_discharge_power": {
        "json_key": "total_battery_discharge_power",
        "name": "Total Battery Discharge Power",
        "unit": UnitOfPower.WATT,
        "icon": "mdi:battery-minus",
        "device_class": SensorDeviceClass.POWER,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "battery_temperature": {
        "json_key": "cellTemp",
        "name": "Battery Temperature",
        "unit": UnitOfTemperature.CELSIUS,
        "icon": "mdi:thermometer",
        "device_class": SensorDeviceClass.TEMPERATURE,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "battery_count": {
        "json_key": "batNum",
        "name": "Battery Count",
        "unit": None,
        "icon": "mdi:battery-multiple",
        "device_class": None,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    # 电池能量统计
    "battery_charge_energy": {
        "json_key": "batChgEgy",
        "name": "Battery Charge Energy",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "icon": "mdi:battery-plus",
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "scale": 0.01,
    },
    "battery_discharge_energy": {
        "json_key": "batDisChgEgy",
        "name": "Battery Discharge Energy",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "icon": "mdi:battery-minus",
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "scale": 0.01,
    },

    # 太阳能
    "solar_power": {
        "json_key": "pvPw",
        "name": "Solar Power",
        "unit": UnitOfPower.WATT,
        "icon": "mdi:solar-power",
        "device_class": SensorDeviceClass.POWER,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "solar_energy": {
        "json_key": "pvEgy",
        "name": "Solar Energy",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "icon": "mdi:solar-power",
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "scale": 0.01,
    },
    "solar_power_pv1": {
        "json_key": "pv1",
        "name": "Solar Power PV1",
        "unit": UnitOfPower.WATT,
        "icon": "mdi:solar-panel",
        "device_class": SensorDeviceClass.POWER,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "solar_energy_pv1": {
        "json_key": "pv1Egy",
        "name": "Solar Energy PV1",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "icon": "mdi:solar-panel",
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "scale": 0.01,
    },
    "solar_power_pv2": {
        "json_key": "pv2",
        "name": "Solar Power PV2",
        "unit": UnitOfPower.WATT,
        "icon": "mdi:solar-panel",
        "device_class": SensorDeviceClass.POWER,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "solar_energy_pv2": {
        "json_key": "pv2Egy",
        "name": "Solar Energy PV2",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "icon": "mdi:solar-panel",
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "scale": 0.01,
    },
    "solar_power_pv3": {
        "json_key": "pv3",
        "name": "Solar Power PV3",
        "unit": UnitOfPower.WATT,
        "icon": "mdi:solar-panel",
        "device_class": SensorDeviceClass.POWER,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "solar_energy_pv3": {
        "json_key": "pv3Egy",
        "name": "Solar Energy PV3",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "icon": "mdi:solar-panel",
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "scale": 0.01,
    },
    "solar_power_pv4": {
        "json_key": "pv4",
        "name": "Solar Power PV4",
        "unit": UnitOfPower.WATT,
        "icon": "mdi:solar-panel",
        "device_class": SensorDeviceClass.POWER,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "solar_energy_pv4": {
        "json_key": "pv4Egy",
        "name": "Solar Energy PV4",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "icon": "mdi:solar-panel",
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "scale": 0.01,
    },

    # 电网相关
    "grid_import_power": { # Grid -> System (outOngridPw)
        "json_key": "inOngridPw",
        "name": "Grid Import Power",
        "unit": UnitOfPower.WATT,
        "icon": "mdi:transmission-tower-import",
        "device_class": SensorDeviceClass.POWER,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "grid_import_energy": {
        "json_key": "inOngridEgy",
        "name": "Grid Import Energy",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "icon": "mdi:transmission-tower-import",
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "scale": 0.01,
    },
    "grid_export_power": { # System -> AC bus / home (outOngridPw); NOT net export to public grid
        "json_key": "outOngridPw",
        "name": "OnGrid AC Output Power",
        "unit": UnitOfPower.WATT,
        "icon": "mdi:transmission-tower-export",
        "device_class": SensorDeviceClass.POWER,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "grid_export_energy": {
        "json_key": "outOngridEgy",
        "name": "Grid Export Energy",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "icon": "mdi:transmission-tower-export",
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "scale": 0.01,
    },
    "max_output_power": {
        "json_key": "maxOutPw",
        "name": "Max Output Power (OnGrid)",
        "unit": UnitOfPower.WATT,
        "icon": "mdi:speedometer",
        "device_class": SensorDeviceClass.POWER,
        "state_class": SensorStateClass.MEASUREMENT,
    },

    # EPS (离网输出)
    "eps_output_power": {
        "json_key": "swEpsOutPw",
        "name": "EPS Output Power",
        "unit": UnitOfPower.WATT,
        "icon": "mdi:power-plug",
        "device_class": SensorDeviceClass.POWER,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "eps_output_energy": {
        "json_key": "outEpsEgy",
        "name": "EPS Output Energy",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "icon": "mdi:power-plug",
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "scale": 0.01,
    },
    "eps_input_power": {
        "json_key": "swEpsInPw",
        "name": "EPS Input Power",
        "unit": UnitOfPower.WATT,
        "icon": "mdi:power-plug",
        "device_class": SensorDeviceClass.POWER,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "eps_input_energy": {
        "json_key": "inEpsEgy",
        "name": "EPS Input Energy",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "icon": "mdi:power-plug",
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "scale": 0.01,
    },
    "eps_state": {
         "json_key": "swEpsState",
         "name": "EPS State",
         "unit": None,
         "icon": "mdi:power-settings",
         "device_class": None,
         "state_class": None, # 1-Normal, 0-Abnormal
    },
    "eps_switch": {
         "json_key": "swEps",
         "name": "EPS Switch Status",
         "unit": None,
         "icon": "mdi:toggle-switch",
         "device_class": None,
         "state_class": None, # 1-On, 0-Off
    },

    # Limits & Settings & Status
    "soc_charge_limit": {
        "json_key": "socChgLimit",
        "name": "SOC Charge Limit",
        "unit": PERCENTAGE,
        "icon": "mdi:battery-arrow-up",
        "device_class": None,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "soc_discharge_limit": {
        "json_key": "socDischgLimit",
        "name": "SOC Discharge Limit",
        "unit": PERCENTAGE,
        "icon": "mdi:battery-arrow-down",
        "device_class": None,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    # "is_auto_standby": {
    #     "json_key": "isAutoStandby",
    #     "name": "Auto Standby Allowed",
    #     "unit": None,
    #     "icon": "mdi:power-sleep",
    #     "device_class": None,
    #     "state_class": None, # 1-Allowed, 0-Not Allowed
    # },
    # "auto_standby_status": {
    #     "json_key": "autoStandby",
    #     "name": "Auto Standby Mode",
    #     "unit": None,
    #     "icon": "mdi:power-sleep",
    #     "device_class": None,
    #     "state_class": None, # 0-Invalid, 1-Sleep/Off, 2-On
    # },

    # Calculated Sensors
    "home_power": {
        "json_key": "calc_home_power",
        "name": "Home Power",
        "unit": UnitOfPower.WATT,
        "icon": "mdi:home-lightning-bolt",
        "device_class": SensorDeviceClass.POWER,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "battery_net_power": {
        "json_key": "calc_batt_net_power",
        "name": "Battery Net Power",
        "unit": UnitOfPower.WATT,
        "icon": "mdi:battery-sync",
        "device_class": SensorDeviceClass.POWER,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "grid_net_power": {
        "json_key": "calc_grid_net_power",
        "name": "Grid Net Power",
        "unit": UnitOfPower.WATT,
        "icon": "mdi:transmission-tower",
        "device_class": SensorDeviceClass.POWER,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    # 更多能量流向统计
    "ac_to_battery_energy": {
        "json_key": "acOtBatEgy",
        "name": "AC to Battery Energy",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "icon": "mdi:battery-arrow-up",
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "scale": 0.01,
    },
    "pv_to_battery_energy": {
        "json_key": "pvOtBatEgy",
        "name": "PV to Battery Energy",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "icon": "mdi:solar-power-variant",
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "scale": 0.01,
    },
    "pv_to_ac_energy": {
        "json_key": "pvOtAcEgy",
        "name": "PV to AC Energy",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "icon": "mdi:solar-panel",
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "scale": 0.01,
    },
    "pv_to_grid_energy": {
        "json_key": "pvOtOngridEgy",
        "name": "PV to Grid Energy",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "icon": "mdi:transmission-tower-export",
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "scale": 0.01,
    },
    "grid_to_ac_load_energy": {
        "json_key": "ongridOtAcLoadEgy",
        "name": "Grid to AC Load Energy",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "icon": "mdi:home-import-outline",
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "scale": 0.01,
    },
    "battery_to_ac_energy": {
        "json_key": "batOtAcEgy",
        "name": "Battery to AC Energy",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "icon": "mdi:battery-arrow-down",
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "scale": 0.01,
    },
    "battery_to_grid_energy": {
        "json_key": "batOtGridEgy",
        "name": "Battery to Grid Energy",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "icon": "mdi:transmission-tower-export",
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "scale": 0.01,
    },
    "grid_to_battery_energy": {
        "json_key": "ongridOtBatEgy",
        "name": "Grid to Battery Energy",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "icon": "mdi:battery-arrow-up",
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "scale": 0.01,
    },
    "ct_import_energy": {
        "json_key": "inCtEgy",
        "name": "CT Import Energy",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "icon": "mdi:transmission-tower-import",
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "scale": 0.01,
    },
    "ct_export_energy": {
        "json_key": "outCtEgy",
        "name": "CT Export Energy",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "icon": "mdi:transmission-tower-export",
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "scale": 0.01,
    },
    "ac_to_grid_energy": {
        "json_key": "acOtOngridEgy",
        "name": "AC to Grid Energy",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "icon": "mdi:transmission-tower-export",
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": SensorStateClass.TOTAL_INCREASING,
        "scale": 0.01,
    },

    # Wechselrichter-Stack — semantics unclear; do NOT use for energy balance calculations
    "stack_in_power": {
        "json_key": "stackInPw",
        "name": "Inverter Stack Input Power",
        "unit": UnitOfPower.WATT,
        "icon": "mdi:lightning-bolt-circle",
        "device_class": SensorDeviceClass.POWER,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "stack_out_power": {
        "json_key": "stackOutPw",
        "name": "Inverter Stack Output Power",
        "unit": UnitOfPower.WATT,
        "icon": "mdi:lightning-bolt-circle",
        "device_class": SensorDeviceClass.POWER,
        "state_class": SensorStateClass.MEASUREMENT,
    },

    # BMS SOC (separat von Display-SOC batSoc)
    "bms_soc": {
        "json_key": "soc",
        "name": "BMS SOC",
        "unit": PERCENTAGE,
        "icon": "mdi:battery-heart",
        "device_class": SensorDeviceClass.BATTERY,
        "state_class": SensorStateClass.MEASUREMENT,
    },

    # Batteriestatus
    "battery_state": {
        "json_key": "batState",
        "name": "Battery State",
        "unit": None,
        "icon": "mdi:battery-heart-variant",
        "device_class": None,
        "state_class": None,
    },

    # Netzwerk-Status
    "ethernet_connected": {
        "json_key": "ethPort",
        "name": "Ethernet Connected",
        "unit": None,
        "icon": "mdi:ethernet",
        "device_class": None,
        "state_class": None,
    },
    "wifi_signal": {
        "json_key": "wsig",
        "name": "WiFi Signal",
        "unit": SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        "icon": "mdi:wifi",
        "device_class": SensorDeviceClass.SIGNAL_STRENGTH,
        "state_class": SensorStateClass.MEASUREMENT,
    },

    # Leistungsgrenzen (nur lesbar)
    "max_inverter_standby_power": {
        "json_key": "maxInvStdPw",
        "name": "Max Inverter Standby Power",
        "unit": UnitOfPower.WATT,
        "icon": "mdi:speedometer",
        "device_class": SensorDeviceClass.POWER,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "max_grid_standby_power": {
        "json_key": "maxGridStdPw",
        "name": "Max Grid Standby Power",
        "unit": UnitOfPower.WATT,
        "icon": "mdi:transmission-tower",
        "device_class": SensorDeviceClass.POWER,
        "state_class": SensorStateClass.MEASUREMENT,
    },

    # Netzwerk-Diagnostik
    "wifi_ssid": {
        "json_key": "wname",
        "name": "WiFi SSID",
        "unit": None,
        "icon": "mdi:wifi",
        "device_class": None,
        "state_class": None,
    },
    "ethernet_ip": {
        "json_key": "eip",
        "name": "Ethernet IP",
        "unit": None,
        "icon": "mdi:ip-network",
        "device_class": None,
        "state_class": None,
    },
    "wlan_ip": {
        "json_key": "wip",
        "name": "WLAN IP",
        "unit": None,
        "icon": "mdi:ip-network",
        "device_class": None,
        "state_class": None,
    },
    "device_capability": {
        "json_key": "ability",
        "name": "Device Capability",
        "unit": None,
        "icon": "mdi:chip",
        "device_class": None,
        "state_class": None,
    },
    # funcEnable bitmask (type-106). The individual bits are decoded into the
    # `func_enable_flags` attribute via FUNC_ENABLE_BITS.
    "func_enable": {
        "json_key": "funcEnable",
        "name": "Function Enable Flags",
        "unit": None,
        "icon": "mdi:tune-variant",
        "device_class": None,
        "state_class": None,
    },

    # Gerätestatus (type=2 / type=106) — ENUM sensors with readable labels (Ü5)
    "device_status": {
        "json_key": "stat",
        "name": "Device Status",
        "unit": None,
        "icon": "mdi:state-machine",
        "device_class": SensorDeviceClass.ENUM,
        "state_class": None,
        "options": list(DEVICE_STATUS_MAP.values()),
        "value_map": DEVICE_STATUS_MAP,
    },
    "ongrid_status": {
        "json_key": "ongridStat",
        "name": "OnGrid Status",
        "unit": None,
        "icon": "mdi:transmission-tower",
        "device_class": SensorDeviceClass.ENUM,
        "state_class": None,
        "options": list(ONGRID_STATUS_MAP.values()),
        "value_map": ONGRID_STATUS_MAP,
    },
    "ct_status": {
        "json_key": "ctStat",
        "name": "CT Status",
        "unit": None,
        "icon": "mdi:current-ac",
        "device_class": SensorDeviceClass.ENUM,
        "state_class": None,
        "options": list(CT_STATUS_MAP.values()),
        "value_map": CT_STATUS_MAP,
    },
    "grid_meter_link": {
        "json_key": "gridSate",
        "name": "Grid Meter Link",
        "unit": None,
        "icon": "mdi:lan-connect",
        "device_class": SensorDeviceClass.ENUM,
        "state_class": None,
        "options": list(GRID_METER_LINK_MAP.values()),
        "value_map": GRID_METER_LINK_MAP,
    },

    # Type-106 fields (response to type-105 poll, ~every 5 min)
    "other_load_power": {
        "json_key": "otherLoadPw",
        "name": "Home Load Power (Estimated)",
        "unit": UnitOfPower.WATT,
        "icon": "mdi:home-lightning-bolt-outline",
        "device_class": SensorDeviceClass.POWER,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "grid_in_power": {
        "json_key": "gridInPw",
        "name": "Grid AC Input Power",
        "unit": UnitOfPower.WATT,
        "icon": "mdi:transmission-tower-import",
        "device_class": SensorDeviceClass.POWER,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "grid_out_power": {
        "json_key": "gridOutPw",
        "name": "Grid AC Output Power",
        "unit": UnitOfPower.WATT,
        "icon": "mdi:transmission-tower-export",
        "device_class": SensorDeviceClass.POWER,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "grid_side_in_power": {
        "json_key": "inGridSidePw",
        "name": "Grid Side Input Power",
        "unit": UnitOfPower.WATT,
        "icon": "mdi:transmission-tower-import",
        "device_class": SensorDeviceClass.POWER,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "grid_side_out_power": {
        "json_key": "outGridSidePw",
        "name": "Grid Side Output Power",
        "unit": UnitOfPower.WATT,
        "icon": "mdi:transmission-tower-export",
        "device_class": SensorDeviceClass.POWER,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "energy_plan_power": {
        "json_key": "energyPlanPw",
        "name": "Energy Plan Power",
        "unit": UnitOfPower.WATT,
        "icon": "mdi:lightning-bolt-outline",
        "device_class": SensorDeviceClass.POWER,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "standby_power": {
        "json_key": "standbyPw",
        "name": "Standby Power Threshold",
        "unit": UnitOfPower.WATT,
        "icon": "mdi:power-sleep",
        "device_class": SensorDeviceClass.POWER,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "pv_max_charge_power": {
        "json_key": "pvMaxChgPower",
        "name": "PV Max Charge Power",
        "unit": UnitOfPower.WATT,
        "icon": "mdi:solar-power",
        "device_class": SensorDeviceClass.POWER,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "max_system_output_power": {
        "json_key": "maxSysOutPw",
        "name": "Max System Output Power",
        "unit": UnitOfPower.WATT,
        "icon": "mdi:speedometer",
        "device_class": SensorDeviceClass.POWER,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "max_system_input_power": {
        "json_key": "maxSysInPw",
        "name": "Max System Input Power",
        "unit": UnitOfPower.WATT,
        "icon": "mdi:speedometer",
        "device_class": SensorDeviceClass.POWER,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "off_grid_time": {
        "json_key": "offGridTime",
        "name": "Off-Grid Switch Time",
        "unit": UnitOfTime.SECONDS,
        "icon": "mdi:timer-outline",
        "device_class": None,
        "state_class": None,
    },
    # maxFeedGrid (type-106): enforced system-level grid feed-in cap. Read-back sensor for
    # the value reported by the device. Writable via Number entity in number.py (Issue #11).
    # Distinct from maxOutPw (user-selectable app limit, controlled via JackeryMaxFeedInSelect).
    "max_feed_grid_power": {
        "json_key": "maxFeedGrid",
        "name": "Max Feed Grid Power",
        "unit": UnitOfPower.WATT,
        "icon": "mdi:transmission-tower-export",
        "device_class": SensorDeviceClass.POWER,
        "state_class": SensorStateClass.MEASUREMENT,
    },
}

# 子设备传感器配置
SUBDEVICE_SENSORS = {
    # 智能插座 (devType=6 or 1)
    "plug": {
        "power": {
            "key": "outPw", # Fallback to 'power'
            "name": "Power",
            "unit": UnitOfPower.WATT,
            "device_class": SensorDeviceClass.POWER,
            "state_class": SensorStateClass.MEASUREMENT,
            "icon": "mdi:power-socket-eu",
        },
        "energy": {
            "key": "totalEgy",
            "name": "Energy",
            "unit": UnitOfEnergy.KILO_WATT_HOUR,
            "device_class": SensorDeviceClass.ENERGY,
            "state_class": SensorStateClass.TOTAL_INCREASING,
            "icon": "mdi:lightning-bolt",
            "scale": 0.01,
        },
    },
    # CT / Smart Meter (devType=2, subType 1-4)
    "ct": {
        "power": {
            "key": "phasePw",
            "name": "Power",
            "unit": UnitOfPower.WATT,
            "device_class": SensorDeviceClass.POWER,
            "state_class": SensorStateClass.MEASUREMENT,
            "icon": "mdi:current-ac",
        },
        "energy": {
            "key": "phaseEgy",
            "name": "Energy",
            "unit": UnitOfEnergy.KILO_WATT_HOUR,
            "device_class": SensorDeviceClass.ENERGY,
            "state_class": SensorStateClass.TOTAL_INCREASING,
            "icon": "mdi:lightning-bolt",
            "scale": 0.01,
        },
    },
    # SmartMeter 3P / devType=3 (any subType): HTO907A (subType=5), Shelly Pro 3EM (subType=2)
    # xPhasePw  = Consumption / Grid Import per phase
    # xnPhasePw = Production  / Grid Export per phase
    "ct_3phase": {
        "import_total": {
            "key": "tPhasePw",
            "name": "Grid Import Power",
            "unit": UnitOfPower.WATT,
            "device_class": SensorDeviceClass.POWER,
            "state_class": SensorStateClass.MEASUREMENT,
            "icon": "mdi:transmission-tower-import",
        },
        "export_total": {
            "key": "tnPhasePw",
            "name": "Grid Export Power",
            "unit": UnitOfPower.WATT,
            "device_class": SensorDeviceClass.POWER,
            "state_class": SensorStateClass.MEASUREMENT,
            "icon": "mdi:transmission-tower-export",
        },
        "import_l1": {
            "key": "aPhasePw",
            "name": "L1 Import Power",
            "unit": UnitOfPower.WATT,
            "device_class": SensorDeviceClass.POWER,
            "state_class": SensorStateClass.MEASUREMENT,
            "icon": "mdi:current-ac",
        },
        "import_l2": {
            "key": "bPhasePw",
            "name": "L2 Import Power",
            "unit": UnitOfPower.WATT,
            "device_class": SensorDeviceClass.POWER,
            "state_class": SensorStateClass.MEASUREMENT,
            "icon": "mdi:current-ac",
        },
        "import_l3": {
            "key": "cPhasePw",
            "name": "L3 Import Power",
            "unit": UnitOfPower.WATT,
            "device_class": SensorDeviceClass.POWER,
            "state_class": SensorStateClass.MEASUREMENT,
            "icon": "mdi:current-ac",
        },
        "export_l1": {
            "key": "anPhasePw",
            "name": "L1 Export Power",
            "unit": UnitOfPower.WATT,
            "device_class": SensorDeviceClass.POWER,
            "state_class": SensorStateClass.MEASUREMENT,
            "icon": "mdi:current-ac",
        },
        "export_l2": {
            "key": "bnPhasePw",
            "name": "L2 Export Power",
            "unit": UnitOfPower.WATT,
            "device_class": SensorDeviceClass.POWER,
            "state_class": SensorStateClass.MEASUREMENT,
            "icon": "mdi:current-ac",
        },
        "export_l3": {
            "key": "cnPhasePw",
            "name": "L3 Export Power",
            "unit": UnitOfPower.WATT,
            "device_class": SensorDeviceClass.POWER,
            "state_class": SensorStateClass.MEASUREMENT,
            "icon": "mdi:current-ac",
        },
        "import_energy_total": {
            "key": "tPhaseEgy",
            "name": "Grid Import Energy",
            "unit": UnitOfEnergy.KILO_WATT_HOUR,
            "device_class": SensorDeviceClass.ENERGY,
            "state_class": SensorStateClass.TOTAL_INCREASING,
            "icon": "mdi:transmission-tower-import",
            "scale": 0.01,
        },
        "export_energy_total": {
            "key": "tnPhaseEgy",
            "name": "Grid Export Energy",
            "unit": UnitOfEnergy.KILO_WATT_HOUR,
            "device_class": SensorDeviceClass.ENERGY,
            "state_class": SensorStateClass.TOTAL_INCREASING,
            "icon": "mdi:transmission-tower-export",
            "scale": 0.01,
        },
        "import_energy_l1": {
            "key": "aPhaseEgy",
            "name": "L1 Import Energy",
            "unit": UnitOfEnergy.KILO_WATT_HOUR,
            "device_class": SensorDeviceClass.ENERGY,
            "state_class": SensorStateClass.TOTAL_INCREASING,
            "icon": "mdi:lightning-bolt",
            "scale": 0.01,
        },
        "import_energy_l2": {
            "key": "bPhaseEgy",
            "name": "L2 Import Energy",
            "unit": UnitOfEnergy.KILO_WATT_HOUR,
            "device_class": SensorDeviceClass.ENERGY,
            "state_class": SensorStateClass.TOTAL_INCREASING,
            "icon": "mdi:lightning-bolt",
            "scale": 0.01,
        },
        "import_energy_l3": {
            "key": "cPhaseEgy",
            "name": "L3 Import Energy",
            "unit": UnitOfEnergy.KILO_WATT_HOUR,
            "device_class": SensorDeviceClass.ENERGY,
            "state_class": SensorStateClass.TOTAL_INCREASING,
            "icon": "mdi:lightning-bolt",
            "scale": 0.01,
        },
        "export_energy_l1": {
            "key": "anPhaseEgy",
            "name": "L1 Export Energy",
            "unit": UnitOfEnergy.KILO_WATT_HOUR,
            "device_class": SensorDeviceClass.ENERGY,
            "state_class": SensorStateClass.TOTAL_INCREASING,
            "icon": "mdi:lightning-bolt",
            "scale": 0.01,
        },
        "export_energy_l2": {
            "key": "bnPhaseEgy",
            "name": "L2 Export Energy",
            "unit": UnitOfEnergy.KILO_WATT_HOUR,
            "device_class": SensorDeviceClass.ENERGY,
            "state_class": SensorStateClass.TOTAL_INCREASING,
            "icon": "mdi:lightning-bolt",
            "scale": 0.01,
        },
        "export_energy_l3": {
            "key": "cnPhaseEgy",
            "name": "L3 Export Energy",
            "unit": UnitOfEnergy.KILO_WATT_HOUR,
            "device_class": SensorDeviceClass.ENERGY,
            "state_class": SensorStateClass.TOTAL_INCREASING,
            "icon": "mdi:lightning-bolt",
            "scale": 0.01,
        },
        # Diagnostik-Sensoren
        "comm_mode": {
            "key": "commMode",
            "name": "Communication Mode",
            "unit": None,
            "device_class": SensorDeviceClass.ENUM,
            "state_class": None,
            "icon": "mdi:network",
            "options": ["lan", "cloud"],
            "options_offset": 1,  # commMode is 1-based: 1=LAN, 2=Cloud
        },
        "comm_state": {
            "key": "commState",
            "name": "Communication State",
            "unit": None,
            "device_class": SensorDeviceClass.ENUM,
            "state_class": None,
            "icon": "mdi:connection",
            "options": ["offline", "online"],
        },
        "ip_address": {
            "key": "wip",
            "name": "IP Address",
            "unit": None,
            "device_class": None,
            "state_class": None,
            "icon": "mdi:ip",
        },
    },
    # Meter Collector (devType=4, subType=7, model HTO910A "Smart Meter D0 Reader")
    # Optical D0 interface reader: sits on the IR port of a German electricity meter and reads
    # meter data via IEC 62056-21 / SML protocol. Reports totals from the meter — no per-phase
    # breakdown. Appears in the "collectors" array of type-101 messages (not "cts").
    # Fields confirmed from live MQTT capture (Issue #19, 2026-07-24):
    #   inPw  = total grid import power as reported by the meter (W)
    #   outPw = total grid export power as reported by the meter (W)
    "collector": {
        "import_power": {
            "key": "inPw",
            "unit": UnitOfPower.WATT,
            "device_class": SensorDeviceClass.POWER,
            "state_class": SensorStateClass.MEASUREMENT,
            "icon": "mdi:transmission-tower-import",
        },
        "export_power": {
            "key": "outPw",
            "unit": UnitOfPower.WATT,
            "device_class": SensorDeviceClass.POWER,
            "state_class": SensorStateClass.MEASUREMENT,
            "icon": "mdi:transmission-tower-export",
        },
        "comm_state": {
            "key": "commState",
            "device_class": SensorDeviceClass.ENUM,
            "options": ["offline", "online"],
            "unit": None,
            "icon": "mdi:connection",
        },
        "comm_mode": {
            "key": "commMode",
            "device_class": SensorDeviceClass.ENUM,
            "options": ["lan", "cloud"],
            "options_offset": 1,  # commMode is 1-based: 1=LAN, 2=Cloud
            "unit": None,
            "icon": "mdi:lan",
        },
        "ip_address": {
            "key": "wip",
            "unit": None,
            "icon": "mdi:ip-network",
        },
    },
    # Expansion battery (e.g. BP2500, devType=1, subType=0)
    # Only cumulative energy is exposed via MQTT (type-23 messages). No real-time power.
    "expansion_battery": {
        "charge_energy": {
            "key": "inEgy",
            "name": "Charge Energy",
            "unit": UnitOfEnergy.KILO_WATT_HOUR,
            "device_class": SensorDeviceClass.ENERGY,
            "state_class": SensorStateClass.TOTAL_INCREASING,
            "icon": "mdi:battery-arrow-up",
            "scale": 0.01,
        },
        "discharge_energy": {
            "key": "outEgy",
            "name": "Discharge Energy",
            "unit": UnitOfEnergy.KILO_WATT_HOUR,
            "device_class": SensorDeviceClass.ENERGY,
            "state_class": SensorStateClass.TOTAL_INCREASING,
            "icon": "mdi:battery-arrow-down",
            "scale": 0.01,
        },
    },
}

# funcEnable bitmask: bit index → feature name (1 = enabled, 0 = disabled).
# Exposed as attributes of the `func_enable` sensor.
FUNC_ENABLE_BITS: dict[int, str] = {
    0: "aerosol",            # bit0 aerosol
    1: "soc_calibration",    # bit1 SOC calibration
    2: "low_power",          # bit2 low power
    3: "soh_calibration",    # bit3 SOH calibration
    4: "pcs_comm_diag",      # bit4 PCS communication diagnosis
    5: "shutdown_2h",        # bit5 2h shutdown
    6: "fault_shutdown",     # bit6 fault shutdown
    7: "epo",                # bit7 EPO function
    8: "func_48v",           # bit8 48 V function
    9: "ethernet_debug",     # bit9 Ethernet debug function
    10: "energy_flow_fill",  # bit10 energy flow data backfill
    11: "smart_plug_first",  # bit11 smart plug priority
}

SMARTMETER_HTTP_SENSOR_CONFIGS: dict[str, dict] = {
    "voltage_l1":        {"key": "volt1", "unit": UnitOfElectricPotential.VOLT,           "device_class": SensorDeviceClass.VOLTAGE,        "state_class": SensorStateClass.MEASUREMENT, "icon": "mdi:lightning-bolt"},
    "voltage_l2":        {"key": "volt2", "unit": UnitOfElectricPotential.VOLT,           "device_class": SensorDeviceClass.VOLTAGE,        "state_class": SensorStateClass.MEASUREMENT, "icon": "mdi:lightning-bolt"},
    "voltage_l3":        {"key": "volt3", "unit": UnitOfElectricPotential.VOLT,           "device_class": SensorDeviceClass.VOLTAGE,        "state_class": SensorStateClass.MEASUREMENT, "icon": "mdi:lightning-bolt"},
    "current_l1":        {"key": "curr1", "unit": UnitOfElectricCurrent.AMPERE,           "device_class": SensorDeviceClass.CURRENT,        "state_class": SensorStateClass.MEASUREMENT, "icon": "mdi:current-ac"},
    "current_l2":        {"key": "curr2", "unit": UnitOfElectricCurrent.AMPERE,           "device_class": SensorDeviceClass.CURRENT,        "state_class": SensorStateClass.MEASUREMENT, "icon": "mdi:current-ac"},
    "current_l3":        {"key": "curr3", "unit": UnitOfElectricCurrent.AMPERE,           "device_class": SensorDeviceClass.CURRENT,        "state_class": SensorStateClass.MEASUREMENT, "icon": "mdi:current-ac"},
    "reactive_power_l1": {"key": "rep1",  "unit": UnitOfReactivePower.VOLT_AMPERE_REACTIVE,"device_class": SensorDeviceClass.REACTIVE_POWER, "state_class": SensorStateClass.MEASUREMENT, "icon": "mdi:sine-wave"},
    "reactive_power_l2": {"key": "rep2",  "unit": UnitOfReactivePower.VOLT_AMPERE_REACTIVE,"device_class": SensorDeviceClass.REACTIVE_POWER, "state_class": SensorStateClass.MEASUREMENT, "icon": "mdi:sine-wave"},
    "reactive_power_l3": {"key": "rep3",  "unit": UnitOfReactivePower.VOLT_AMPERE_REACTIVE,"device_class": SensorDeviceClass.REACTIVE_POWER, "state_class": SensorStateClass.MEASUREMENT, "icon": "mdi:sine-wave"},
    "apparent_power_l1": {"key": "ap1",   "unit": UnitOfApparentPower.VOLT_AMPERE,        "device_class": SensorDeviceClass.APPARENT_POWER, "state_class": SensorStateClass.MEASUREMENT, "icon": "mdi:flash"},
    "apparent_power_l2": {"key": "ap2",   "unit": UnitOfApparentPower.VOLT_AMPERE,        "device_class": SensorDeviceClass.APPARENT_POWER, "state_class": SensorStateClass.MEASUREMENT, "icon": "mdi:flash"},
    "apparent_power_l3": {"key": "ap3",   "unit": UnitOfApparentPower.VOLT_AMPERE,        "device_class": SensorDeviceClass.APPARENT_POWER, "state_class": SensorStateClass.MEASUREMENT, "icon": "mdi:flash"},
    "power_factor_l1":   {"key": "fact1", "unit": None, "scale": 0.001,                  "device_class": SensorDeviceClass.POWER_FACTOR,  "state_class": SensorStateClass.MEASUREMENT, "icon": "mdi:angle-acute"},
    "power_factor_l2":   {"key": "fact2", "unit": None, "scale": 0.001,                  "device_class": SensorDeviceClass.POWER_FACTOR,  "state_class": SensorStateClass.MEASUREMENT, "icon": "mdi:angle-acute"},
    "power_factor_l3":   {"key": "fact3", "unit": None, "scale": 0.001,                  "device_class": SensorDeviceClass.POWER_FACTOR,  "state_class": SensorStateClass.MEASUREMENT, "icon": "mdi:angle-acute"},
    "frequency":         {"key": "freq",  "unit": UnitOfFrequency.HERTZ,                 "device_class": SensorDeviceClass.FREQUENCY,     "state_class": SensorStateClass.MEASUREMENT, "icon": "mdi:sine-wave"},
}
