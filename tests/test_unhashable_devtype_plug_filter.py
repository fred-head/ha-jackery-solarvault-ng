"""Regression tests for malformed devType values in plug-switch filtering."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from custom_components.jackery import DOMAIN
from custom_components.jackery.devices.classification import (
    should_create_plug_switch,
)
from custom_components.jackery.sensor import (
    should_create_plug_switch as sensor_should_create_plug_switch,
)
from custom_components.jackery.switch import (
    JackeryPlugSwitch,
    async_setup_entry,
)


@pytest.mark.parametrize(
    ("dev_type", "expected"),
    [
        ([], False),
        ({}, False),
        ([[{"nested": True}]], False),
        ({"nested": []}, False),
        (99, False),
        ("unknown", False),
        (None, False),
        (6, True),
        (2, False),
    ],
)
def test_plug_filter_rejects_malformed_and_unsupported_types(dev_type, expected):
    payload = {"devType": dev_type}
    assert should_create_plug_switch(payload) is expected


@pytest.mark.parametrize("dev_type", [[], {}, [[{}]], {"nested": []}])
def test_sensor_compatibility_export_matches_classifier(dev_type):
    payload = {"devType": dev_type}
    assert sensor_should_create_plug_switch(payload) is should_create_plug_switch(
        payload
    )


async def test_switch_platform_skips_malformed_types_without_writable_controls(hass):
    coordinator = Mock()
    coordinator._device_sn = "HOST"
    coordinator.child_identity_allowed.return_value = True
    coordinator.get_subdevices.return_value = [
        {"sn": "LIST", "devType": []},
        {"sn": "DICT", "devType": {}},
        {"sn": "UNKNOWN", "devType": 99},
        {"sn": "STRING", "devType": "6"},
        {"sn": "MISSING"},
        {"sn": "CT", "devType": 2},
        {"sn": "PLUG", "devType": 6},
    ]
    hass.data.setdefault(DOMAIN, {})["entry"] = {"coordinator": coordinator}
    entities = []

    await async_setup_entry(
        hass,
        SimpleNamespace(entry_id="entry"),
        entities.extend,
    )

    plug_switches = [entity for entity in entities if isinstance(entity, JackeryPlugSwitch)]
    assert [entity._plug_sn for entity in plug_switches] == ["PLUG"]
