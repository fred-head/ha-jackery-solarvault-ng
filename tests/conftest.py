"""Shared test fixtures."""
import time
from unittest.mock import patch

import pytest

from custom_components.jackery.coordinator_state import CoordinatorRuntimeState
from custom_components.jackery.diagnostics_observation import DiagnosticsObservationState
from custom_components.jackery.registry_identity import build_device_info
from custom_components.jackery.sensor import JackeryDataCoordinator


def child_device_info(
    hass,
    entry_id: str,
    *,
    identifiers: set[tuple[str, str]],
    parent_identifier: tuple[str, str],
    name: str,
    manufacturer: str,
    model: str,
    **extra: object,
) -> dict[str, object]:
    """Build fixture DeviceInfo through the same old/modern parent adapter."""
    info = dict(build_device_info(
        hass,
        entry_id,
        identifiers=identifiers,
        parent_identifier=parent_identifier,
        name=name,
        manufacturer=manufacturer,
        model=model,
    ))
    info.update(extra)
    return info


@pytest.fixture(autouse=True, scope="session")
def avoid_new_registry_disk_loads_in_tests():
    """Match HA's other registry mocks when the installed test plugin is older.

    The installed pytest-homeassistant-custom-component fixture patches the
    older registry stores, but its generic storage patch does not replace the
    already-imported Floor, Label and Category registry store classes. Their
    real disk loads wait on an executor before Home Assistant starts.
    """
    from homeassistant.helpers.category_registry import CategoryRegistryStore
    from homeassistant.helpers.floor_registry import FloorRegistryStore
    from homeassistant.helpers.label_registry import LabelRegistryStore

    async def no_disk_load(_store):
        return None

    async def no_disk_save(_store, *_args, **_kwargs):
        return None

    with (
        patch.object(CategoryRegistryStore, "async_load", no_disk_load),
        patch.object(CategoryRegistryStore, "async_save", no_disk_save),
        patch.object(FloorRegistryStore, "async_load", no_disk_load),
        patch.object(FloorRegistryStore, "async_save", no_disk_save),
        patch.object(LabelRegistryStore, "async_load", no_disk_load),
        patch.object(LabelRegistryStore, "async_save", no_disk_save),
    ):
        yield


@pytest.fixture
def mock_recorder_before_hass(request):
    """Prepare Recorder's database URL before HA's test instance starts."""
    if "recorder_mock" in request.fixturenames:
        request.getfixturevalue("recorder_db_url")


@pytest.fixture
def coordinator():
    """Minimal JackeryDataCoordinator without MQTT subscription, for unit tests."""
    coord = JackeryDataCoordinator.__new__(JackeryDataCoordinator)
    coord.hass = None
    coord._topic_prefix = "hb"
    coord._token = "testtoken"
    coord._mqtt_host = "localhost"
    coord._device_sn = "TESTSN001"
    coord._topic_root = "hb"
    coord._sensors = {}
    coord._data_task = None
    coord._subscribed = False
    coord._lifecycle_active = True
    coord._stop_requested = False
    coord._runtime_state = CoordinatorRuntimeState(
        last_update_time=time.time(),
        start_time=time.time(),
    )
    coord._diagnostics_observation = DiagnosticsObservationState()
    coord._protocol_discovery = None
    coord._known_plugs = set()
    coord._subdevice_missing_since = {}
    coord._expansion_battery_sns = set()
    coord._poll_105_counter = 0
    coord._device_type = None
    coord._soft_ver = None
    coord._reauth_started = False
    coord.add_entities_callback = None
    coord.add_switch_entities_callback = None
    coord._topic_status_wildcard = "hb/device/+/status"
    coord._topic_event_wildcard = "hb/device/+/event"
    return coord


class FakeMqttMsg:
    """Minimal MQTT message stub."""

    def __init__(self, topic: str, payload: str | bytes) -> None:
        self.topic = topic
        self.payload = payload.encode() if isinstance(payload, str) else payload
