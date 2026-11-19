"""Home Assistant-independent child discovery and membership decisions."""

from __future__ import annotations

from dataclasses import dataclass, field

from .devices.classification import DeviceClassification, DeviceFamily


@dataclass(frozen=True, slots=True)
class ChildMembershipChanges:
    """Membership transitions produced by one discovery snapshot."""

    reappeared: tuple[str, ...] = ()
    newly_missing: tuple[str, ...] = ()
    due_for_removal: tuple[str, ...] = ()


@dataclass(slots=True)
class ChildDiscoveryState:
    """Track child membership without owning entities or registry handles."""

    known_children: set[str] = field(default_factory=set)
    expansion_batteries: set[str] = field(default_factory=set)
    missing_since: dict[str, float] = field(default_factory=dict)

    def register(self, serial: str, *, expansion_battery: bool = False) -> bool:
        """Register a child and report whether it was newly known."""
        if serial in self.known_children:
            return False
        self.known_children.add(serial)
        if expansion_battery:
            self.expansion_batteries.add(serial)
        return True

    def remove(self, serial: str) -> None:
        """Forget all discovery membership for a removed child."""
        self.known_children.discard(serial)
        self.expansion_batteries.discard(serial)
        self.missing_since.pop(serial, None)

    def reconcile(
        self,
        current_serials: set[str],
        *,
        now: float,
        deletion_timeout: float,
    ) -> ChildMembershipChanges:
        """Update missing timers and return transitions requiring orchestration."""
        reappeared: list[str] = []
        newly_missing: list[str] = []
        due_for_removal: list[str] = []

        for serial in current_serials:
            if serial in self.missing_since:
                reappeared.append(serial)
                del self.missing_since[serial]

        for serial in self.known_children:
            if serial in self.expansion_batteries:
                continue
            if serial not in current_serials and serial not in self.missing_since:
                self.missing_since[serial] = now
                newly_missing.append(serial)

        for serial in list(self.missing_since):
            if serial not in self.known_children:
                del self.missing_since[serial]
                continue
            if serial in self.expansion_batteries:
                del self.missing_since[serial]
                continue
            if serial in current_serials:
                del self.missing_since[serial]
                continue
            if now - self.missing_since[serial] > deletion_timeout:
                due_for_removal.append(serial)

        return ChildMembershipChanges(
            reappeared=tuple(reappeared),
            newly_missing=tuple(newly_missing),
            due_for_removal=tuple(due_for_removal),
        )


@dataclass(frozen=True, slots=True)
class ChildEntitySpec:
    """Existing entity-construction mapping for one supported child family."""

    sensor_group: str
    data_key: str | None
    create_plug_switch: bool = False


_ENTITY_SPECS: dict[DeviceFamily, ChildEntitySpec] = {
    DeviceFamily.PLUG: ChildEntitySpec("plug", "plugs", True),
    DeviceFamily.CT: ChildEntitySpec("ct", "cts"),
    DeviceFamily.SMARTMETER: ChildEntitySpec("ct_3phase", "cts"),
    DeviceFamily.COLLECTOR: ChildEntitySpec("collector", "collectors"),
    DeviceFamily.EXPANSION_BATTERY: ChildEntitySpec("expansion_battery", None),
}


def child_entity_spec(
    classification: DeviceClassification,
) -> ChildEntitySpec | None:
    """Return the established entity specification for a classification."""
    return _ENTITY_SPECS.get(classification.family)
