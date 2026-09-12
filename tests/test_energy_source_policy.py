"""Synthetic wire playback, not recorded hardware evidence.

The (elapsed seconds, message type, body) sequences can also carry future
sanitized captures; receipt time is deliberately independent of wire timestamps.
"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from custom_components.jackery import sensor as sensor_module
from custom_components.jackery.sensor import JackeryDataCoordinator

from .test_protocol_contract import PROTECTED, receive


@pytest.fixture
def source(monkeypatch):
    clock = SimpleNamespace(now=1000.0)
    monkeypatch.setattr(sensor_module, "time", SimpleNamespace(time=lambda: clock.now))
    c = JackeryDataCoordinator(None, "hb", "synthetic", "localhost", "HOST")
    c.add_entities_callback = Mock()
    return c, clock


@pytest.mark.parametrize("field", PROTECTED)
@pytest.mark.parametrize("live", [2, 25, 107])
@pytest.mark.parametrize("value", [0, 42])
def test_live_field_protection_expires_independently(source, field, live, value):
    c, clock = source
    receive(c, live, {field: value})
    clock.now += 60
    receive(c, 106, {field: 90, "gridBuyPw": 0})
    assert c._data_cache[field] == value
    assert c._data_cache["gridInPw"] == 0
    # Unrelated live traffic and rejected snapshots cannot renew this field.
    receive(c, live, {"batSoc": 80})
    clock.now += 0.01
    receive(c, 106, {field: 91})
    assert c._data_cache[field] == 91
    receive(c, 106, {field: 92})
    assert c._data_cache[field] == 92
    receive(c, live, {field: 0})
    receive(c, 106, {field: 99})
    assert c._data_cache[field] == 0


@pytest.mark.parametrize("field", PROTECTED)
@pytest.mark.parametrize("live", [2, 107])
def test_live_null_does_not_lock_field(source, field, live):
    c, _ = source
    receive(c, live, {field: 12})
    receive(c, live, {field: None})
    receive(c, 106, {field: 90})
    assert c._data_cache[field] == 90


@pytest.mark.parametrize("sequence,expected", [
    ((106, 106), 20), ((106, 2), 20), ((2, 106), 10),
    ((106, 107), 20), ((107, 106), 10), ((2, 107, 106), 20),
])
@pytest.mark.parametrize("field", PROTECTED)
def test_order_matrix(source, sequence, expected, field):
    c, clock = source
    for i, kind in enumerate(sequence, 1):
        clock.now += 1
        receive(c, kind, {field: i * 10}, ts=100 - i)
    assert c._data_cache[field] == expected


@pytest.mark.parametrize("dtype", [2, 3, 4])
def test_stale_meter_falls_back_and_recovers_with_zero(source, dtype):
    c, clock = source
    meter = {"deviceSn": "METER", "devType": dtype, "tPhasePw": 800, "tnPhasePw": 0}
    receive(c, 101, {"cts": [meter]})
    assert c._data_cache["calc_grid_net_power"] == 800
    clock.now += 40
    receive(c, 101, {"collectors": [{"deviceSn": "COLLECTOR", "devType": 4,
                                     "subType": 7, "inPw": 300, "outPw": 0}]})
    clock.now += 20
    receive(c, 2, {"gridInPw": 100})
    assert c._data_cache["calc_grid_net_power"] == 800
    clock.now += 0.01
    receive(c, 2, {"gridInPw": 100})
    assert c._data_cache["calc_grid_net_power"] == 300
    assert c._data_cache["cts"][0]["tPhasePw"] == 800  # raw evidence retained
    clock.now += 40
    receive(c, 2, {"gridInPw": 100})
    assert c._data_cache["calc_grid_net_power"] == 100
    receive(c, 102, {"deviceSn": "METER", "tPhasePw": 0})
    assert c._data_cache["calc_grid_net_power"] == 0


@pytest.mark.parametrize("ct,expected", [
    ({"TphasePw": 0, "tPhasePw": 700}, 0),
    ({"TnphasePw": 0, "tnPhasePw": 700}, 0),
    ({"tPhasePw": 0, "aPhasePw": 700}, 0),
    ({"aPhasePw": 0, "AphasePw": 0, "bPhasePw": 40}, 40),
    ({"tPhasePw": None, "aPhasePw": 40}, 40),
    ({"commState": 1}, 200),
    ({"tPhasePw": None, "tnPhasePw": None}, 200),
])
def test_meter_presence_aliases_and_fallback(source, ct, expected):
    c, _ = source
    receive(c, 2, {"cts": [ct], "collectors": [{"inPw": 200}], "gridInPw": 900})
    assert c._data_cache["calc_grid_net_power"] == expected


def test_first_usable_meter_not_first_empty_entry(source):
    c, _ = source
    receive(c, 2, {"cts": [{"commState": 1}, {"tPhasePw": 80}], "gridInPw": 900})
    assert c._data_cache["calc_grid_net_power"] == 80


@pytest.mark.parametrize("pv", [{"pvPw": 0, "w": 700}, {"w": 0, "power": 700}])
def test_nested_pv_zero_is_authoritative(source, pv):
    c, _ = source
    receive(c, 106, {"pvPw": pv})
    assert c._data_cache["calc_batt_net_power"] == 0


@pytest.mark.parametrize("pv,charge,supply,eps_in,eps_out,buy,sell,battery,home", [
    (0, 0, 0, 0, 0, 0, 0, 0, 0),  # idle / zero crossing
    (1500, 0, 500, 0, 0, 0, 0, 1000, 500),  # PV surplus charging
    (1500, 0, 1500, 0, 0, 0, 1000, 0, 500),  # PV exporting
    (0, 500, 0, 0, 0, 800, 0, 500, 300),  # grid charging
    (0, 0, 500, 0, 0, 0, 0, -500, 500),  # battery to home
    (0, 0, 800, 0, 0, 0, 300, -800, 500),  # battery export
    (500, 0, 0, 0, 200, 0, 0, 300, 0),  # EPS output
    (0, 0, 0, 200, 0, 0, 0, 200, 0),  # EPS input
])
def test_energy_balance(source, pv, charge, supply, eps_in, eps_out, buy, sell, battery, home):
    c, _ = source
    receive(c, 2, {"pvPw": pv, "inOngridPw": charge, "outOngridPw": supply,
                   "swEpsInPw": eps_in, "swEpsOutPw": eps_out,
                   "batInPw": 999, "stackInPw": 999,
                   "cts": [{"tPhasePw": buy, "tnPhasePw": sell}]})
    data = c._data_cache
    assert data["calc_grid_net_power"] == buy - sell
    assert data["calc_home_power"] == home
    assert data["calc_batt_net_power"] == battery
    assert data["total_battery_charge_power"] == max(0, battery)
    assert data["total_battery_discharge_power"] == max(0, -battery)


def test_system_magnitude_and_cached_source_limitation(source):
    """Characterization: no evidence yet to replace host alias magnitude policy."""
    c, clock = source
    receive(c, 2, {"gridInPw": 900})
    clock.now += 120
    receive(c, 107, {"inGridSidePw": 0})
    assert c._data_cache["calc_grid_net_power"] == 900
    receive(c, 101, {"cts": [{"deviceSn": "METER", "devType": 3, "tPhasePw": 0}]})
    assert c._data_cache["calc_grid_net_power"] == 0


def test_metadata_only_child_refresh_is_not_measurement_freshness(source):
    c, clock = source
    receive(c, 101, {"cts": [{"deviceSn": "METER", "devType": 3, "tPhasePw": 800}]})
    clock.now += 120
    receive(c, 102, {"deviceSn": "METER", "commState": 1})
    assert c._data_cache["calc_grid_net_power"] == 800


def test_source_observability_retains_suppressed_raw_snapshot(source):
    c, clock = source
    receive(c, 2, dict.fromkeys(PROTECTED, 0))
    live_time = clock.now
    clock.now += 20
    receive(c, 106, dict.fromkeys(PROTECTED, 90))
    assert c._power_live_seen == dict.fromkeys(PROTECTED, (2, live_time))
    assert c._power_106_samples == dict.fromkeys(PROTECTED, (90, clock.now))
    assert all(c._data_cache[key] == 0 for key in PROTECTED)
    receive(c, 101, {"cts": [{"deviceSn": "PRIVATE_METER", "devType": 3, "tPhasePw": 0}]})
    clock.now += 61
    receive(c, 2, {"gridInPw": 40})
    assert c._energy_sources["grid"] == {
        "source": "system", "activity_age": None, "skipped_stale": 1,
        "skipped_missing": 0, "reason": "no usable meter",
    }
    receive(c, 102, {"deviceSn": "PRIVATE_METER", "tPhasePw": 0})
    assert c._energy_sources["grid"]["source"] == "cts"
    assert c._energy_sources["grid"]["activity_age"] == 0
    assert "PRIVATE_METER" not in repr(c._energy_sources)
    other = JackeryDataCoordinator(None, "hb", "synthetic", "localhost", "OTHER")
    assert other._power_live_seen == other._power_106_samples == other._energy_sources == {}


@pytest.mark.parametrize("bad", [True, "bad", float("nan"), float("inf"), [], {"unknown": 2}])
def test_invalid_power_cannot_establish_live_preference(source, bad):
    c, _ = source
    receive(c, 2, {"pvPw": bad})
    receive(c, 106, {"pvPw": 40})
    assert c._data_cache["pvPw"] == 40
    assert c._data_cache["calc_batt_net_power"] == 40


def test_pv_dictionary_live_zero_is_protected_and_then_expires(source):
    c, clock = source
    receive(c, 2, {"pvPw": {"pvPw": 0, "w": 900}})
    receive(c, 106, {"pvPw": 40})
    assert c._data_cache["calc_batt_net_power"] == 0
    clock.now += 61
    receive(c, 106, {"pvPw": {"w": 40}})
    assert c._data_cache["calc_batt_net_power"] == 40


@pytest.mark.parametrize("kind,body,expected", [
    (23, {"deviceSn": "HOST", "pvPw": 0}, 0),
    (23, {"deviceSn": "CHILD", "devType": 1, "pvPw": 0}, 90),
    (999, {"pvPw": 0}, 90),
])
def test_only_known_host_live_routes_establish_preference(source, kind, body, expected):
    c, _ = source
    receive(c, kind, body)
    receive(c, 106, {"pvPw": 90})
    assert c._data_cache["pvPw"] == expected


def test_zero_meter_small_charge_anomaly_is_explicitly_retained(source):
    c, _ = source
    receive(c, 2, {"cts": [{"tPhasePw": 0}], "inOngridPw": 20})
    assert c._energy_sources["grid"]["source"] == "cts"
    assert c._data_cache["calc_grid_net_power"] == 20
