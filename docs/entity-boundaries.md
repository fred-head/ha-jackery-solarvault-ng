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
| Dynamic child and HTTP sensors | Coordinator discovery decides when; existing sensor constructors create the entities; the sensor platform callback adds them |
| Dynamic plug switches | Coordinator discovery decides when; `JackeryPlugSwitch` constructs the entity; the switch platform callback adds it |
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

## Deliberately retained coupling

The coordinator still creates dynamic child sensor objects and imports the plug
switch class at discovery time. Discovery membership, missing timers, registry
deletion, entity callbacks and HTTP creation state are one behavior-sensitive
lifecycle boundary. Moving them requires a separate discovery/child-management
change with explicit callback and unload tests.

Sensor entity classes still read coordinator cache/identity fields and perform
their established native-value and availability writes. Their transformations
include route- and firmware-specific fallbacks, so only the already-independent
plug mode helpers moved in this step. No broad entity facade or factory framework
was introduced.

The coordinator API, setup sequence, callback timing, listener keys, entity
counts, unique IDs, device identifiers, translations, metadata and values remain
unchanged.
