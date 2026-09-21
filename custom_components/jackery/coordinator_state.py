"""Home Assistant independent ephemeral coordinator runtime state."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Set
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class CoordinatorRuntimeState:
    """Own protocol cache, freshness and source evidence for one coordinator."""

    last_update_time: float
    start_time: float
    ever_received: bool = False
    data_cache: dict[str, Any] = field(default_factory=dict)
    power_live_seen: dict[str, tuple[int, float]] = field(default_factory=dict)
    power_106_samples: dict[str, tuple[Any, float]] = field(default_factory=dict)
    ongrid_live_observed: bool = False
    ongrid_live_seen_at: float | None = None
    ongrid_type106_observed: bool = False
    ongrid_type106_seen_at: float | None = None
    energy_sources: dict[str, Any] = field(default_factory=dict)
    subdevice_last_seen: dict[str, float] = field(default_factory=dict)

    def record_host_activity(self, now: float) -> None:
        """Record one accepted MQTT envelope for the configured host topic."""
        self.last_update_time = now
        self.ever_received = True

    def record_child_activity(self, serial: str, now: float) -> None:
        """Record activity for one validated child serial."""
        self.subdevice_last_seen[serial] = now

    def merge_main_payload(
        self,
        payload: Mapping[str, Any],
        *,
        observed_keys: Iterable[str],
        message_type: int | None,
        live_preferred: Set[str],
        valid_live_fields: Set[str],
    ) -> None:
        """Merge main data and retain the established live-source evidence."""
        self.data_cache.update(payload)
        for key in observed_keys:
            if key not in live_preferred:
                continue
            self.power_live_seen.pop(key, None)
            if key in valid_live_fields and message_type is not None:
                self.power_live_seen[key] = (message_type, self.last_update_time)

    def merge_type106_snapshot(
        self,
        payload: Mapping[str, Any],
        *,
        live_preferred: Set[str],
        live_timeout: float,
    ) -> None:
        """Merge a Type-106 snapshot with the bounded live-value preference."""
        for key, value in payload.items():
            if key in live_preferred:
                self.power_106_samples[key] = (value, self.last_update_time)
                live = self.power_live_seen.get(key)
                if (
                    live is not None
                    and self.last_update_time - live[1] <= live_timeout
                ):
                    continue
                self.power_live_seen.pop(key, None)
            self.data_cache[key] = value

    def record_ongrid_live_evidence(self, valid: bool) -> None:
        """Record receipt metadata for the live on-grid alias family."""
        self.ongrid_live_observed = True
        self.ongrid_live_seen_at = self.last_update_time if valid else None

    def record_ongrid_type106_evidence(self, valid: bool) -> None:
        """Record receipt metadata for the Type-106 on-grid alias family."""
        self.ongrid_type106_observed = True
        self.ongrid_type106_seen_at = self.last_update_time if valid else None

    def child_is_available(
        self,
        serial: str,
        now: float,
        *,
        timeout: float,
        retain_after_first_seen: bool,
    ) -> bool:
        """Apply the established startup grace and child activity timeout."""
        last_seen = self.subdevice_last_seen.get(serial, 0)
        if last_seen == 0 and (now - self.start_time) < timeout:
            return True
        if retain_after_first_seen:
            return last_seen > 0
        return last_seen > 0 and (now - last_seen) <= timeout

    def host_is_stale(self, now: float, timeout: float) -> bool:
        """Return whether host activity exceeds the existing timeout."""
        return now - self.last_update_time > timeout

    def record_energy_source(self, name: str, metadata: Mapping[str, Any]) -> None:
        """Store calculation-owned source decision metadata."""
        self.energy_sources[name] = dict(metadata)
