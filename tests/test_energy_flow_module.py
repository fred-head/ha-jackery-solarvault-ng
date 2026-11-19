"""Focused unit tests for the calculation package boundary."""

from custom_components.jackery.calculations.energy_flow import (
    GridSourceSelection,
    SourceFreshness,
    calculate_energy_flow,
    select_grid_source,
)


def test_calculation_mutates_and_returns_same_mapping():
    data = {"pvPw": 100, "outOngridPw": 40}
    result = calculate_energy_flow(data)
    assert result is data
    assert result["calc_batt_net_power"] == 60
    assert result["calc_home_power"] == 40


def test_selected_source_is_explicit_input_to_formula():
    data = {"inOngridPw": 500}
    selected = GridSourceSelection(grid_buy=800, available=True, source="cts")
    result = calculate_energy_flow(data, selected)
    assert result["calc_grid_net_power"] == 800
    assert result["calc_home_power"] == 300
    assert result["total_battery_charge_power"] == 500


def test_grid_selection_uses_caller_owned_freshness_without_mutating_raw_data():
    data = {
        "cts": [{"deviceSn": "METER", "tPhasePw": 700}],
        "collectors": [{"deviceSn": "COLLECTOR", "inPw": 200}],
        "gridInPw": 50,
    }
    before = {key: [dict(item) for item in value] if isinstance(value, list) else value for key, value in data.items()}
    selected = select_grid_source(
        data,
        {
            "METER": SourceFreshness(False, 61),
            "COLLECTOR": SourceFreshness(True, 20),
        },
    )
    assert selected == GridSourceSelection(
        grid_buy=200,
        available=True,
        source="collectors",
        activity_age=20,
        skipped_stale=1,
    )
    assert selected.metadata() == {
        "source": "collectors",
        "activity_age": 20,
        "skipped_stale": 1,
        "skipped_missing": 0,
        "reason": "first usable meter",
    }
    assert data == before


def test_no_usable_meter_returns_existing_system_fallback():
    selected = select_grid_source({"cts": [{"commState": 1}], "gridOutPw": 90})
    assert selected == GridSourceSelection(
        grid_sell=90,
        available=True,
        source="system",
        skipped_missing=1,
    )
