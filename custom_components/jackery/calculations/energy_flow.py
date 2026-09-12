"""Pure energy-flow calculations and measurement-source selection.

The caller owns protocol normalization, freshness clocks, cache lifecycle and
Home Assistant entity updates. This module mutates only the supplied data dict,
matching the integration's established calculation contract.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class SourceFreshness:
    """Coordinator-owned availability information for one child source."""

    available: bool
    activity_age: float | None


@dataclass(frozen=True, slots=True)
class GridSourceSelection:
    """Selected directional grid measurement and its decision metadata."""

    grid_buy: float = 0.0
    grid_sell: float = 0.0
    available: bool = False
    source: str = "unavailable"
    activity_age: float | None = None
    skipped_stale: int = 0
    skipped_missing: int = 0

    def metadata(self) -> dict[str, Any]:
        """Return the existing coordinator observability shape."""
        return {
            "source": self.source,
            "activity_age": self.activity_age,
            "skipped_stale": self.skipped_stale,
            "skipped_missing": self.skipped_missing,
            "reason": (
                "first usable meter"
                if self.source in ("cts", "collectors")
                else "no usable meter"
            ),
        }


def _field_present(data: Mapping[str, Any], key: str) -> bool:
    """Return whether a field exists and is non-null; zero is present."""
    return key in data and data[key] is not None


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Convert a protocol field to float, preserving the established fallback."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _power_sample(value: Any) -> float | None:
    """Read finite power, preserving zero and the existing PV dictionary aliases."""
    if isinstance(value, dict):
        value = next(
            (value[key] for key in ("pvPw", "w", "power") if value.get(key) is not None),
            None,
        )
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _pick_best_power_net(candidates: list[float]) -> float:
    """Select the established largest-magnitude non-zero host candidate."""
    if not candidates:
        return 0.0
    non_zero = [value for value in candidates if abs(value) > 0]
    if non_zero:
        return max(non_zero, key=abs)
    return candidates[-1]


def _effective_ongrid_net(
    data: Mapping[str, Any],
    grid_in: float,
    grid_out: float,
    ongrid_charge: float,
    ongrid_supply: float,
    in_grid_side: float,
    out_grid_side: float,
) -> float:
    """Return grid-tied port net power; positive means grid to unit."""
    candidates: list[float] = []
    if _field_present(data, "gridInPw") or _field_present(data, "gridOutPw"):
        candidates.append(grid_in - grid_out)
    if _field_present(data, "inOngridPw") or _field_present(data, "outOngridPw"):
        candidates.append(ongrid_charge - ongrid_supply)
    if _field_present(data, "inGridSidePw") or _field_present(data, "outGridSidePw"):
        candidates.append(in_grid_side - out_grid_side)
    return _pick_best_power_net(candidates)


def _grid_net_from_system(
    data: Mapping[str, Any],
    grid_in: float,
    grid_out: float,
    ongrid_charge: float,
    ongrid_supply: float,
    in_grid_side: float,
    out_grid_side: float,
    *,
    include_ongrid: bool = True,
) -> tuple[float, bool]:
    """Derive system grid net power and its presence flag."""
    candidates: list[float] = []
    if _field_present(data, "inGridSidePw") or _field_present(data, "outGridSidePw"):
        candidates.append(in_grid_side - out_grid_side)
    if _field_present(data, "gridInPw") or _field_present(data, "gridOutPw"):
        candidates.append(grid_in - grid_out)
    if include_ongrid and (
        _field_present(data, "inOngridPw") or _field_present(data, "outOngridPw")
    ):
        candidates.append(ongrid_charge - ongrid_supply)
    if not candidates:
        return 0.0, False
    return _pick_best_power_net(candidates), True


def _ct_power(
    ct: Mapping[str, Any],
    total: tuple[str, str],
    phases: tuple[str, ...],
) -> float | None:
    """Prefer a reported total, including zero, then sum reported phases."""
    value = next((ct[key] for key in total if ct.get(key) is not None), None)
    if value is not None:
        return _power_sample(value)
    samples: list[float] = []
    for key in phases:
        alias = key[0].upper() + key[1:].replace("Phase", "phase")
        raw = ct.get(alias) if ct.get(alias) is not None else ct.get(key)
        sample = _power_sample(raw)
        if sample is not None:
            samples.append(sample)
    return sum(samples) if samples else None


def _source_serial(item: Mapping[str, Any]) -> str | None:
    """Read the child identity needed only to apply caller-owned freshness."""
    serial = item.get("deviceSn") or item.get("sn")
    return serial if isinstance(serial, str) and serial else None


def select_grid_source(
    data: Mapping[str, Any],
    child_freshness: Mapping[str, SourceFreshness] | None = None,
) -> GridSourceSelection:
    """Apply the established CT, collector, then system source priority."""
    skipped_stale = 0
    skipped_missing = 0

    for array in ("cts", "collectors"):
        items = data.get(array)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            activity_age = None
            serial = _source_serial(item)
            if child_freshness is not None and serial is not None:
                freshness = child_freshness.get(serial)
                if freshness is not None:
                    activity_age = freshness.activity_age
                    if not freshness.available:
                        skipped_stale += 1
                        continue
            if array == "cts":
                grid_buy = _ct_power(
                    item,
                    ("TphasePw", "tPhasePw"),
                    ("aPhasePw", "bPhasePw", "cPhasePw"),
                )
                grid_sell = _ct_power(
                    item,
                    ("TnphasePw", "tnPhasePw"),
                    ("anPhasePw", "bnPhasePw", "cnPhasePw"),
                )
            else:
                grid_buy = _power_sample(item.get("inPw"))
                grid_sell = _power_sample(item.get("outPw"))
            if grid_buy is None and grid_sell is None:
                skipped_missing += 1
                continue
            return GridSourceSelection(
                grid_buy=grid_buy if grid_buy is not None else 0.0,
                grid_sell=grid_sell if grid_sell is not None else 0.0,
                available=True,
                source=array,
                activity_age=activity_age,
                skipped_stale=skipped_stale,
                skipped_missing=skipped_missing,
            )

    grid_in = _safe_float(data.get("gridInPw"))
    grid_out = _safe_float(data.get("gridOutPw"))
    ongrid_charge = _safe_float(data.get("inOngridPw"))
    ongrid_supply = _safe_float(data.get("outOngridPw"))
    in_grid_side = _safe_float(data.get("inGridSidePw"))
    out_grid_side = _safe_float(data.get("outGridSidePw"))
    system_net, system_available = _grid_net_from_system(
        data,
        grid_in,
        grid_out,
        ongrid_charge,
        ongrid_supply,
        in_grid_side,
        out_grid_side,
        include_ongrid=False,
    )
    return GridSourceSelection(
        grid_buy=max(0.0, system_net) if system_available else 0.0,
        grid_sell=max(0.0, -system_net) if system_available else 0.0,
        available=system_available,
        source="system" if system_available else "unavailable",
        skipped_stale=skipped_stale,
        skipped_missing=skipped_missing,
    )


def calculate_energy_flow(
    data: dict[str, Any],
    grid_source: GridSourceSelection | None = None,
) -> dict[str, Any]:
    """Mutate and return normalized raw state with established derived values."""
    pv = _power_sample(data.get("pvPw"))
    if pv is None:
        pv = 0.0

    grid_in = _safe_float(data.get("gridInPw"))
    grid_out = _safe_float(data.get("gridOutPw"))
    ongrid_charge = _safe_float(data.get("inOngridPw"))
    ongrid_supply = _safe_float(data.get("outOngridPw"))
    in_grid_side = _safe_float(data.get("inGridSidePw"))
    out_grid_side = _safe_float(data.get("outGridSidePw"))
    ongrid_net = _effective_ongrid_net(
        data,
        grid_in,
        grid_out,
        ongrid_charge,
        ongrid_supply,
        in_grid_side,
        out_grid_side,
    )

    eps_in = _safe_float(data.get("swEpsInPw"))
    eps_out = _safe_float(data.get("swEpsOutPw"))
    selected = grid_source if grid_source is not None else select_grid_source(data)
    grid_net = selected.grid_buy - selected.grid_sell if selected.available else None

    # Preserve the established <=50 W correction exactly.
    if (
        grid_net is not None
        and selected.grid_buy < ongrid_charge
        and (ongrid_charge - selected.grid_buy) <= 50
    ):
        grid_net = ongrid_net

    # batInPw/batOutPw describe only the main unit. Preserve the community
    # total-stack balance validated with an active BP2500 expansion battery.
    battery_net = pv + ongrid_charge - ongrid_supply - eps_out + eps_in
    battery_charge = max(0.0, battery_net)
    battery_discharge = max(0.0, -battery_net)

    if grid_net is not None:
        home = grid_net - ongrid_net
        if (
            selected.grid_buy > 0
            and ongrid_charge > 0
            and selected.grid_buy < ongrid_charge
            and (ongrid_charge - selected.grid_buy) <= 50
        ):
            home = 0.0
        elif (
            selected.grid_buy > 0
            and ongrid_charge > 0
            and selected.grid_buy < ongrid_charge
            and (ongrid_charge - selected.grid_buy) > 50
        ):
            home = ongrid_charge - selected.grid_buy
    else:
        home = max(0.0, -ongrid_net)

    data["calc_home_power"] = max(0.0, home)
    data["calc_batt_net_power"] = battery_net
    data["total_battery_charge_power"] = battery_charge
    data["total_battery_discharge_power"] = battery_discharge
    data["grid_available"] = selected.available
    data["calc_grid_net_power"] = grid_net if selected.available else None
    return data
