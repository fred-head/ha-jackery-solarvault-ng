"""Direct tests for the pure child-device classifier."""

import pytest

from custom_components.jackery.devices.classification import (
    ClassificationContext,
    DeviceClassification,
    DeviceFamily,
    DeviceModel,
    classify_device,
    should_create_plug_switch,
)


@pytest.mark.parametrize(
    ("payload", "context", "expected"),
    [
        (
            {"devType": 1, "subType": 0},
            ClassificationContext.TYPE23_CHILD,
            DeviceClassification(DeviceFamily.EXPANSION_BATTERY, 1),
        ),
        (
            {"devType": 1, "subType": 0},
            ClassificationContext.DISCOVERY,
            DeviceClassification(DeviceFamily.UNKNOWN, 1),
        ),
        (
            {"devType": 2, "subType": 1},
            ClassificationContext.DISCOVERY,
            DeviceClassification(DeviceFamily.CT, 2),
        ),
        (
            {"devType": 4, "subType": 2},
            ClassificationContext.DISCOVERY,
            DeviceClassification(DeviceFamily.CT, 4),
        ),
        (
            {"devType": 3, "subType": 5},
            ClassificationContext.DISCOVERY,
            DeviceClassification(
                DeviceFamily.SMARTMETER,
                3,
                DeviceModel.HTO907A,
            ),
        ),
        (
            {"devType": 3, "subType": 2},
            ClassificationContext.DISCOVERY,
            DeviceClassification(
                DeviceFamily.SMARTMETER,
                3,
                DeviceModel.SHELLY_PRO_3EM,
            ),
        ),
        (
            {"devType": 3, "subType": 999},
            ClassificationContext.DISCOVERY,
            DeviceClassification(DeviceFamily.SMARTMETER, 3),
        ),
        (
            {"devType": 4, "subType": 7},
            ClassificationContext.DISCOVERY,
            DeviceClassification(
                DeviceFamily.COLLECTOR,
                4,
                DeviceModel.HTO910A,
            ),
        ),
        (
            {"devType": 6, "subType": 0},
            ClassificationContext.DISCOVERY,
            DeviceClassification(DeviceFamily.PLUG, 6),
        ),
    ],
)
def test_established_device_matrix(payload, context, expected):
    assert classify_device(payload, context) == expected


@pytest.mark.parametrize(
    ("context", "payload", "family", "dev_type"),
    [
        (ClassificationContext.PLUG_ARRAY, {}, DeviceFamily.PLUG, 6),
        (ClassificationContext.CT_ARRAY, {}, DeviceFamily.CT, 2),
        (
            ClassificationContext.COLLECTOR_ARRAY,
            {"subType": 2},
            DeviceFamily.UNKNOWN,
            None,
        ),
        (
            ClassificationContext.DISCOVERY,
            {"subType": 2},
            DeviceFamily.CT,
            2,
        ),
        (ClassificationContext.DISCOVERY, {}, DeviceFamily.UNKNOWN, None),
    ],
)
def test_missing_type_depends_on_explicit_context(
    context,
    payload,
    family,
    dev_type,
):
    result = classify_device(payload, context)
    assert result.family is family
    assert result.dev_type == dev_type


@pytest.mark.parametrize(
    "field",
    ["switchSta", "sysSwitch", "totalEgy"],
)
def test_point_update_infers_plug_from_established_fields(field):
    result = classify_device({field: 0}, ClassificationContext.POINT_UPDATE)
    assert result == DeviceClassification(DeviceFamily.PLUG, 6)


@pytest.mark.parametrize(
    "field",
    ["aPhasePw", "AphasePw", "tPhasePw", "TphasePw", "phasePw"],
)
def test_point_update_infers_smartmeter_from_established_fields(field):
    result = classify_device({field: 0}, ClassificationContext.POINT_UPDATE)
    assert result == DeviceClassification(DeviceFamily.SMARTMETER, 3)


def test_point_update_plug_fields_win_over_meter_fields():
    payload = {"sysSwitch": 0, "aPhasePw": 10}
    assert classify_device(payload, ClassificationContext.POINT_UPDATE) == (
        DeviceClassification(DeviceFamily.PLUG, 6)
    )


@pytest.mark.parametrize("dev_type", [99, "3", [3], {"type": 3}])
def test_explicit_unknown_type_is_not_inferred_from_known_fields(dev_type):
    payload = {"devType": dev_type, "sysSwitch": 0, "aPhasePw": 10}
    result = classify_device(payload, ClassificationContext.POINT_UPDATE)
    assert result.family is DeviceFamily.UNKNOWN
    assert result.dev_type == dev_type


def test_out_power_alone_does_not_infer_a_missing_type():
    result = classify_device({"outPw": 9}, ClassificationContext.POINT_UPDATE)
    assert result == DeviceClassification(DeviceFamily.UNKNOWN)


@pytest.mark.parametrize(
    ("context", "payload", "family"),
    [
        (
            ClassificationContext.PLUG_ARRAY,
            {"devType": 3, "subType": 5},
            DeviceFamily.SMARTMETER,
        ),
        (
            ClassificationContext.CT_ARRAY,
            {"devType": 6},
            DeviceFamily.PLUG,
        ),
        (
            ClassificationContext.CT_ARRAY,
            {"devType": 4, "subType": 7},
            DeviceFamily.COLLECTOR,
        ),
        (
            ClassificationContext.COLLECTOR_ARRAY,
            {"devType": 4, "subType": 2},
            DeviceFamily.CT,
        ),
    ],
)
def test_explicit_metadata_wins_over_conflicting_array_context(
    context,
    payload,
    family,
):
    assert classify_device(payload, context).family is family


def test_classification_does_not_mutate_payload():
    payload = {"subType": 2, "future": {"value": 1}}
    before = {**payload}
    result = classify_device(payload)
    assert result == DeviceClassification(DeviceFamily.CT, 2)
    assert payload == before
    assert payload["future"] is before["future"]


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"devType": 6}, True),
        ({"devType": 6.0}, True),
        ({"devType": 2}, False),
        ({"devType": 3}, False),
        ({"devType": 4}, False),
        ({}, False),
    ],
)
def test_static_plug_switch_filter_preserves_exact_type_rule(payload, expected):
    assert should_create_plug_switch(payload) is expected
