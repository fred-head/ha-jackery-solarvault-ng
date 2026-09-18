"""Direct contract tests for declarative sensor metadata."""

import ast
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


def test_sensor_definitions_depend_only_on_ha_metadata() -> None:
    """Declarative metadata must not depend on runtime or entity implementations."""
    path = Path(sensor_definitions.__file__)
    imports = {
        node.module
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.ImportFrom)
    }
    assert imports == {"typing", "homeassistant.components.sensor", "homeassistant.const"}
