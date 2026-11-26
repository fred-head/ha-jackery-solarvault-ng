"""Tests for JackerySensor._update_from_coordinator special-case transformations."""
from unittest.mock import MagicMock

import pytest

from custom_components.jackery.sensor import SENSORS, JackeryDataCoordinator, JackerySensor


def make_sensor(sensor_id: str, coord: JackeryDataCoordinator) -> JackerySensor:
    """Create a JackerySensor without registering it in HA."""
    sensor = JackerySensor.__new__(JackerySensor)
    sensor._sensor_id = sensor_id
    sensor._coordinator = coord
    sensor._config = SENSORS[sensor_id]
    sensor._attr_native_value = None
    sensor._attr_available = False
    sensor._has_enum_raw_value = False
    sensor._enum_raw_value = None
    sensor.async_write_ha_state = MagicMock()
    return sensor


def assert_ha_enum_state_is_valid(sensor: JackerySensor) -> None:
    """Mirror HA's enum state check, where a None value is the unknown state."""
    value = sensor._attr_native_value
    options = sensor._config.get("options")
    if value is not None and options is not None and value not in options:
        raise ValueError(f"enum state {value!r} is not in {options!r}")


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        (0, "normal"),
        (5, "low_power"),
        (8, "fast_charging"),
    ],
)
def test_device_status_known_values_map_to_enum_options(coordinator, raw_value, expected):
    sensor = make_sensor("device_status", coordinator)
    sensor.async_write_ha_state.side_effect = lambda: assert_ha_enum_state_is_valid(sensor)

    sensor._update_from_coordinator({"stat": raw_value})

    assert sensor._attr_native_value == expected
    assert sensor._attr_native_value in sensor._config["options"]
    assert sensor.extra_state_attributes["raw_value"] == raw_value
    assert sensor._attr_available is True


@pytest.mark.parametrize("raw_value", [6, 7, 999, "garbage"])
def test_device_status_unknown_values_are_ha_safe_and_diagnostic(coordinator, raw_value):
    sensor = make_sensor("device_status", coordinator)
    sensor.async_write_ha_state.side_effect = lambda: assert_ha_enum_state_is_valid(sensor)

    sensor._update_from_coordinator({"stat": raw_value})

    assert sensor._attr_native_value is None
    assert sensor._attr_native_value not in sensor._config["options"]
    assert sensor.extra_state_attributes["raw_value"] == raw_value
    assert sensor._attr_available is True
    sensor.async_write_ha_state.assert_called_once()


# ---------------------------------------------------------------------------
# battery_temperature: cellTemp × 0.1
# ---------------------------------------------------------------------------

def test_battery_temperature_scaling(coordinator):
    sensor = make_sensor("battery_temperature", coordinator)
    sensor._update_from_coordinator({"cellTemp": 293})
    assert sensor._attr_native_value == pytest.approx(29.3)
    assert sensor._attr_available is True


def test_battery_temperature_zero(coordinator):
    sensor = make_sensor("battery_temperature", coordinator)
    sensor._update_from_coordinator({"cellTemp": 0})
    assert sensor._attr_native_value == 0.0


# ---------------------------------------------------------------------------
# eps_output_power: swEpsOutPw − swEpsInPw
# ---------------------------------------------------------------------------

def test_eps_output_power_net_positive(coordinator):
    sensor = make_sensor("eps_output_power", coordinator)
    sensor._update_from_coordinator({"swEpsOutPw": 500, "swEpsInPw": 100})
    assert sensor._attr_native_value == pytest.approx(400.0)


def test_eps_output_power_net_negative(coordinator):
    sensor = make_sensor("eps_output_power", coordinator)
    sensor._update_from_coordinator({"swEpsOutPw": 50, "swEpsInPw": 200})
    assert sensor._attr_native_value == pytest.approx(-150.0)


def test_eps_output_power_defaults_to_zero_when_missing(coordinator):
    sensor = make_sensor("eps_output_power", coordinator)
    sensor._update_from_coordinator({})
    assert sensor._attr_native_value == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# solar_power_pv1: dict {"pvPw": ...} unpacking
# ---------------------------------------------------------------------------

def test_solar_pv1_dict_pvPw(coordinator):
    sensor = make_sensor("solar_power_pv1", coordinator)
    sensor._update_from_coordinator({"pv1": {"pvPw": 800, "commState": 1}})
    assert sensor._attr_native_value == 800


def test_solar_pv1_dict_w_key(coordinator):
    sensor = make_sensor("solar_power_pv1", coordinator)
    sensor._update_from_coordinator({"pv1": {"w": 600}})
    assert sensor._attr_native_value == 600


def test_solar_pv1_dict_power_key(coordinator):
    sensor = make_sensor("solar_power_pv1", coordinator)
    sensor._update_from_coordinator({"pv1": {"power": 400}})
    assert sensor._attr_native_value == 400


def test_solar_pv1_scalar_value(coordinator):
    """If pv1 is a plain number (unusual), scale × 1 applies."""
    sensor = make_sensor("solar_power_pv1", coordinator)
    sensor._update_from_coordinator({"pv1": 750})
    assert sensor._attr_native_value == pytest.approx(750.0)


# ---------------------------------------------------------------------------
# Energy sensors: scale = 0.01 (×0.01 for kWh)
# ---------------------------------------------------------------------------

def test_grid_import_energy_scale(coordinator):
    sensor = make_sensor("grid_import_energy", coordinator)
    sensor._update_from_coordinator({"inOngridEgy": 12345})
    assert sensor._attr_native_value == pytest.approx(123.45)


def test_battery_charge_energy_scale(coordinator):
    sensor = make_sensor("battery_charge_energy", coordinator)
    sensor._update_from_coordinator({"batChgEgy": 10000})
    assert sensor._attr_native_value == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# grid_net_power: keep last value when None (CT temporarily missing)
# ---------------------------------------------------------------------------

def test_grid_net_power_keeps_last_value_when_none(coordinator):
    sensor = make_sensor("grid_net_power", coordinator)
    sensor._attr_native_value = 350.0

    # CT missing → calc_grid_net_power is None
    sensor._update_from_coordinator({"calc_grid_net_power": None})

    # Value must be unchanged
    assert sensor._attr_native_value == 350.0


def test_grid_net_power_updates_when_value_present(coordinator):
    sensor = make_sensor("grid_net_power", coordinator)
    sensor._update_from_coordinator({"calc_grid_net_power": -500.0})
    assert sensor._attr_native_value == pytest.approx(-500.0)


# ---------------------------------------------------------------------------
# Missing key: sensor stays at previous value, stays unavailable
# ---------------------------------------------------------------------------

def test_missing_key_leaves_sensor_unchanged(coordinator):
    sensor = make_sensor("battery_soc", coordinator)
    sensor._attr_native_value = 42
    sensor._attr_available = True

    sensor._update_from_coordinator({})  # batSoc not in data

    assert sensor._attr_native_value == 42
    # async_write_ha_state must NOT be called (no state change)
    sensor.async_write_ha_state.assert_not_called()


# ---------------------------------------------------------------------------
# async_write_ha_state called on successful update
# ---------------------------------------------------------------------------

def test_state_written_after_update(coordinator):
    sensor = make_sensor("battery_soc", coordinator)
    sensor._update_from_coordinator({"batSoc": 80})
    sensor.async_write_ha_state.assert_called_once()

# ---------------------------------------------------------------------------
# Network states: independent interfaces and no fabricated RSSI/IP values
# ---------------------------------------------------------------------------


def test_ethernet_only_status_handles_missing_wlan_ip(coordinator):
    from custom_components.jackery.protocol.network import wifi_is_disconnected

    payload = {"ethPort": 1, "wname": "     ", "wsig": 0}
    assert wifi_is_disconnected(payload)

    signal = make_sensor("wifi_signal", coordinator)
    signal._update_from_coordinator(payload)
    assert signal._attr_native_value is None
    assert signal._attr_available is True

    quality = make_sensor("wifi_signal_quality", coordinator)
    quality._update_from_coordinator(payload)
    assert quality._attr_native_value == "not_connected"

    wlan_ip = make_sensor("wlan_ip", coordinator)
    wlan_ip._update_from_coordinator(payload)
    assert wlan_ip._attr_native_value == "Not connected"


def test_wifi_only_and_dual_interface_states_are_independent(coordinator):
    from custom_components.jackery.protocol.network import (
        ethernet_port_state,
        wifi_connection_state,
    )

    wlan_payload = {
        "ethPort": 0,
        "eip": None,
        "wname": "Home",
        "wip": "192.0.2.11",
        "wsig": -61,
    }
    assert ethernet_port_state(wlan_payload["ethPort"]) is False
    assert wifi_connection_state(wlan_payload) is True

    ethernet_ip = make_sensor("ethernet_ip", coordinator)
    ethernet_ip._update_from_coordinator(wlan_payload)
    assert ethernet_ip._attr_native_value == "Not connected"

    wlan_ip = make_sensor("wlan_ip", coordinator)
    wlan_ip._update_from_coordinator(wlan_payload)
    assert wlan_ip._attr_native_value == "192.0.2.11"

    dual_payload = {
        "ethPort": 1,
        "eip": "192.0.2.10",
        "wname": "Home",
        "wip": "192.0.2.11",
        "wsig": -52,
    }
    assert ethernet_port_state(dual_payload["ethPort"]) is True
    assert wifi_connection_state(dual_payload) is True
    ethernet_ip._update_from_coordinator(dual_payload)
    wlan_ip._update_from_coordinator(dual_payload)
    assert ethernet_ip._attr_native_value == "192.0.2.10"
    assert wlan_ip._attr_native_value == "192.0.2.11"


def test_unknown_or_missing_wifi_evidence_does_not_invent_disconnection(coordinator):
    from custom_components.jackery.protocol.network import (
        wifi_connection_state,
        wifi_is_disconnected,
    )

    assert wifi_connection_state({"ethPort": 1}) is None
    assert not wifi_is_disconnected({"wname": " ", "ethPort": 1})

    wlan_ip = make_sensor("wlan_ip", coordinator)
    wlan_ip._attr_native_value = "old value"
    wlan_ip._attr_available = True
    wlan_ip._update_from_coordinator({})
    assert wlan_ip._attr_native_value == "old value"
    wlan_ip.async_write_ha_state.assert_not_called()


def test_connected_wifi_without_reported_ip_is_not_shown_as_disconnected(coordinator):
    wlan_ip = make_sensor("wlan_ip", coordinator)
    wlan_ip._update_from_coordinator({"wname": "Home", "wsig": -60})

    assert wlan_ip._attr_native_value == "Connected, no IP address"
    assert wlan_ip._attr_available is True


def test_coordinator_cache_invalidates_network_ips_after_proven_transitions(coordinator):
    coordinator._merge_normalized_cache(
        {
            "ethPort": 1,
            "eip": "192.0.2.10",
            "wname": "Home",
            "wip": "192.0.2.11",
            "wsig": -55,
        }
    )
    coordinator._merge_normalized_cache({"ethPort": 0, "wname": " ", "wsig": 0})

    assert coordinator._data_cache["eip"] is None
    assert coordinator._data_cache["wip"] is None

    coordinator._merge_normalized_cache({"ethPort": 1, "wname": "Guest", "wsig": -64})
    assert coordinator._data_cache["eip"] is None
    assert coordinator._data_cache["wip"] is None
