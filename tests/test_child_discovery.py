"""Direct tests for HA-independent child discovery decisions."""

from custom_components.jackery.devices.classification import (
    DeviceClassification,
    DeviceFamily,
)
from custom_components.jackery.discovery import (
    ChildDiscoveryState,
    child_entity_spec,
)


def test_membership_tracks_missing_reappearance_and_strict_timeout() -> None:
    state = ChildDiscoveryState()
    state.known_children.update({"PRESENT", "MISSING"})

    first = state.reconcile({"PRESENT"}, now=100.0, deletion_timeout=60)
    assert first.newly_missing == ("MISSING",)
    assert first.reappeared == ()
    assert first.due_for_removal == ()
    assert state.missing_since == {"MISSING": 100.0}

    boundary = state.reconcile({"PRESENT"}, now=160.0, deletion_timeout=60)
    assert boundary.newly_missing == ()
    assert boundary.due_for_removal == ()
    assert state.missing_since == {"MISSING": 100.0}

    overdue = state.reconcile({"PRESENT"}, now=160.1, deletion_timeout=60)
    assert overdue.due_for_removal == ("MISSING",)

    reappeared = state.reconcile(
        {"PRESENT", "MISSING"}, now=161.0, deletion_timeout=60
    )
    assert reappeared.reappeared == ("MISSING",)
    assert state.missing_since == {}


def test_expansion_children_are_exempt_and_stale_timers_are_cleaned() -> None:
    state = ChildDiscoveryState(
        known_children={"PRESENT", "BATTERY"},
        expansion_batteries={"BATTERY"},
        missing_since={"BATTERY": 1.0, "ORPHAN": 2.0},
    )

    changes = state.reconcile({"PRESENT"}, now=1000.0, deletion_timeout=60)

    assert changes.newly_missing == ()
    assert changes.due_for_removal == ()
    assert state.missing_since == {}


def test_registration_removal_and_instances_are_isolated() -> None:
    first = ChildDiscoveryState()
    second = ChildDiscoveryState()

    assert first.register("PLUG")
    assert not first.register("PLUG")
    assert first.register("BATTERY", expansion_battery=True)
    assert first.known_children == {"PLUG", "BATTERY"}
    assert first.expansion_batteries == {"BATTERY"}
    assert second.known_children == set()

    first.missing_since["PLUG"] = 1.0
    first.remove("PLUG")
    assert first.known_children == {"BATTERY"}
    assert first.missing_since == {}


def test_child_entity_spec_preserves_existing_family_mapping() -> None:
    expected = {
        DeviceFamily.PLUG: ("plug", "plugs", True),
        DeviceFamily.CT: ("ct", "cts", False),
        DeviceFamily.SMARTMETER: ("ct_3phase", "cts", False),
        DeviceFamily.COLLECTOR: ("collector", "collectors", False),
        DeviceFamily.EXPANSION_BATTERY: (
            "expansion_battery",
            None,
            False,
        ),
    }

    for family, values in expected.items():
        spec = child_entity_spec(DeviceClassification(family, 6))
        assert spec is not None
        assert (spec.sensor_group, spec.data_key, spec.create_plug_switch) == values

    assert child_entity_spec(DeviceClassification(DeviceFamily.UNKNOWN)) is None
