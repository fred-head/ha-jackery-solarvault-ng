"""Direct tests for pure Home Assistant entity value transformations."""

import ast
from pathlib import Path

import pytest

from custom_components.jackery.entities import transforms
from custom_components.jackery.entities.transforms import (
    COMM_MODE_CLOUD,
    COMM_MODE_LABELS,
    COMM_MODE_LOCAL,
    plug_comm_mode,
    plug_mqtt_control_allowed,
)


def test_plug_mode_constants_are_unchanged() -> None:
    assert (COMM_MODE_LOCAL, COMM_MODE_CLOUD) == (1, 2)
    assert COMM_MODE_LABELS == {1: "local", 2: "cloud"}


def test_entity_transforms_have_no_runtime_dependencies() -> None:
    path = Path(transforms.__file__)
    imports = [
        node
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    assert imports == []


@pytest.mark.parametrize(
    ("value", "expected"),
    [(1, 1), ("2", 2), (None, None), ("bad", None), ([], None)],
)
def test_plug_comm_mode_preserves_conversion(value, expected) -> None:
    assert plug_comm_mode({"commMode": value}) == expected


@pytest.mark.parametrize(
    ("value", "allowed", "reason"),
    [
        (1, True, ""),
        (2, False, "cloud-connected"),
        (None, False, "Unknown commMode"),
        (3, False, "commMode=3"),
    ],
)
def test_plug_mqtt_control_policy_is_unchanged(value, allowed, reason) -> None:
    result, message = plug_mqtt_control_allowed({"commMode": value})
    assert result is allowed
    assert reason in message
