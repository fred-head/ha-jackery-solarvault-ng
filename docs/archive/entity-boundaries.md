# Setup, coordinator and entity boundaries

This inventory records the Phase 2 HA-facing ownership boundary. It describes
implemented behavior and does not propose a new lifecycle.

## Ownership inventory

| Responsibility | Owner |
| --- | --- |
| Coordinator construction and storage | Integration `async_setup_entry` in `__init__.py`, before platform forwarding |
| Platform forwarding and runtime start | Integration setup forwards all five platforms, then calls `coordinator.async_start()` after the sensor and switch callbacks exist |
| Transport/task start and stop | `JackeryDataCoordinator`; integration unload calls stop before unloading platforms |
| Static main sensors | Sensor platform setup, from `entities.sensor_definitions.SENSORS` |
| Static switches, numbers, selects and button | Their respective platform setup modules |
| Dynamic child sensors | `discovery.py` supplies membership decisions and family specifications; coordinator checks identity and constructs; sensor callback adds |
| Dynamic HTTP sensors | Coordinator HTTP policy decides and constructs; sensor callback adds |
| Dynamic plug switches | Discovery specification selects plugs; coordinator constructs `JackeryPlugSwitch`; switch callback adds |
| Registration and unregistration | Entity `async_added_to_hass` / `async_will_remove_from_hass`, through coordinator `register_sensor` / `unregister_sensor` |
| Raw-to-native sensor conversion | Existing sensor entity update methods; the pure plug communication-mode conversion is in `entities.transforms` |
| Unique IDs and device information | Existing entity constructors using `identity.py`; unchanged by this extraction |
| Registry migration | Integration setup and `child_migration.py`, now reading declarative keys directly from `entities.sensor_definitions` |
| Failed setup cleanup | Integration setup stops the coordinator and unloads already-forwarded platforms |

## Extracted HA-facing modules

`entities/sensor_definitions.py` owns the unchanged main, child and SmartMeter
HTTP sensor dictionaries plus their enum/status display maps. It imports only HA
sensor metadata and HA unit constants. `sensor.py` re-exports the established
names for compatibility with downstream imports and tests.

`entities/transforms.py` owns the two pure Smart Plug `commMode` conversion and
MQTT-control eligibility functions. It has no coordinator, cache, transport or
entity dependency. `switch.py` consumes these helpers directly, while
`sensor.py` retains compatibility re-exports.

## Child discovery boundary

`ChildDiscoveryState` owns known-child membership, expansion membership and
missing timers without holding HA objects. It computes reappearance, first
absence and strict-timeout removal candidates. The module also owns the pure
family mapping to sensor group, cache key and plug-switch requirement.

The coordinator retains migration eligibility, entity construction, callbacks,
device-registry lookup/removal, ownership checks and listener cleanup. This keeps
HA side effects outside discovery state and preserves platform setup ordering.

| Existing symbol | Reads/writes and retained dependencies |
| --- | --- |
| `_known_plugs` | Compatibility view of discovery `known_children`; read by discovery, availability and entity lookup; changed only by register/removal decisions |
| `_expansion_battery_sns` | Compatibility view of discovery expansion membership; read by deletion exemption and availability retention |
| `_subdevice_missing_since` | Compatibility view of discovery timers; reconciled from non-empty Type-101 child snapshots |
| `_check_for_new_plugs` | Collects cached arrays, asks discovery state to reconcile, classifies with `devices.classification`, checks migration eligibility, constructs entities and invokes callbacks |
| `_check_for_new_expansion_batteries` | Keeps the explicit Type-23 path, identity gate, sensor construction and value pre-initialization; registers expansion membership through discovery state |
| `_remove_subdevice_from_ha` | Retains device-registry lookup, host-scoped identity, config-entry ownership guard and entity listener cleanup; tells discovery state to forget successful removals |
| `_entity_keys_for_subdevice` | Reads coordinator listener entities to locate existing child sensor/HTTP keys; remains HA-facing |
| `child_identity_allowed` | Reads migration results before construction or deletion; remains coordinator-owned identity policy |
| `add_entities_callback` / `add_switch_entities_callback` | Installed by platform setup and invoked after complete batches; ordering and duplicate suppression remain unchanged |

## Deliberately retained coupling

The coordinator still creates dynamic child sensor objects and imports the plug
switch class at discovery time. No entity factory was introduced because the
child sensor class remains in `sensor.py`; moving construction now would create
a cycle or require a broader platform rewrite. Registry deletion, callbacks and
HTTP creation state remain behavior-sensitive HA lifecycle work.

Sensor entity classes still read coordinator cache/identity fields and perform
their established native-value and availability writes. Their transformations
include route- and firmware-specific fallbacks, so only the already-independent
plug mode helpers moved in this step. No broad entity facade or factory framework
was introduced.

The coordinator API, setup sequence, callback timing, listener keys, entity
counts, unique IDs, device identifiers, translations, metadata and values remain
unchanged.
