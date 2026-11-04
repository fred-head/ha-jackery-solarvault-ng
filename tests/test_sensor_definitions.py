"""Direct contract tests for declarative sensor metadata."""

import ast
import json
from pathlib import Path

from custom_components.jackery import sensor
from custom_components.jackery.entities import sensor_definitions


def test_sensor_definition_exports_remain_compatible() -> None:
    """The historical sensor-module imports remain the same objects."""
    for name in sensor_definitions.__all__:
        assert getattr(sensor, name) is getattr(sensor_definitions, name)


def test_sensor_definition_group_shape_is_unchanged() -> None:
    """Protect the complete declarative entity counts and group boundaries."""
    assert len(sensor_definitions.SENSORS) == 75
    assert {
        group: len(configs)
        for group, configs in sensor_definitions.SUBDEVICE_SENSORS.items()
    } == {
        "plug": 2,
        "ct": 2,
        "ct_3phase": 19,
        "collector": 5,
        "expansion_battery": 2,
    }
    assert len(sensor_definitions.SMARTMETER_HTTP_SENSOR_CONFIGS) == 16


def test_battery_count_uses_a_supported_battery_icon() -> None:
    """The battery count sensor uses a valid, broadly supported HA icon."""
    assert sensor_definitions.SENSORS["battery_count"]["icon"] == "mdi:battery"


def test_device_status_identity_and_entity_shape_are_unchanged(coordinator) -> None:
    """Status support extends the existing entity without adding or renaming one."""
    entity = sensor.JackerySensor("device_status", coordinator, "entry")

    assert entity._attr_unique_id == "jackery_TESTSN001_device_status"
    assert entity._attr_translation_key == "device_status"
    assert entity._attr_has_entity_name is True
    assert entity._config["name"] == "Device Status"
    assert list(sensor_definitions.SENSORS).count("device_status") == 1
    assert len(sensor_definitions.SENSORS) == 75
    assert set(sensor_definitions.DEVICE_STATUS_MAP) == {0, 1, 2, 3, 4, 5, 8}


def test_fast_charging_translations_are_complete_and_valid() -> None:
    """All shipped status translation JSON files contain the same option keys."""
    integration_dir = Path(sensor_definitions.__file__).parents[1]
    expected = {
        "strings.json": "Fast charging",
        "translations/en.json": "Fast charging",
        "translations/de.json": "Schnellladen",
        "translations/fr.json": "Charge rapide",
    }
    for relative_path, label in expected.items():
        document = json.loads((integration_dir / relative_path).read_text())
        states = document["entity"]["sensor"]["device_status"]["state"]
        assert set(states) == set(sensor_definitions.DEVICE_STATUS_MAP.values())
        assert states["fast_charging"] == label


def test_sensor_definitions_depend_only_on_ha_metadata() -> None:
    """Declarative metadata must not depend on runtime or entity implementations."""
    path = Path(sensor_definitions.__file__)
    imports = {
        node.module
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.ImportFrom)
    }
    assert imports == {"typing", "homeassistant.components.sensor", "homeassistant.const"}
