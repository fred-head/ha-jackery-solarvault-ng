# AGENTS.md

## Project Mission

This repository provides a robust, local-first Home Assistant integration for Jackery SolarVault systems.

The goal is to build the best practical implementation from:

1. `csoscd/ha-solarvault` as the primary functional baseline.
2. `Jackery-Official/jackery` as the authoritative upstream reference for Jackery protocol behavior.
3. Additional architecture, diagnostics, testing, maintainability, and reliability improvements developed in this repository.

This project is NOT a blind merge of two repositories.

Changes must preserve known working behavior while progressively improving architecture.

---

# Primary Goals

The integration should be:

* stable
* local-first
* observable
* testable
* maintainable
* extensible
* backward compatible where reasonably possible
* useful for troubleshooting real SolarVault installations

Functionality from either upstream must not be lost without an explicit documented reason.

The project should eventually become easier to extend than either upstream implementation.

---

# Current Scope

Current development focuses on:

* Home Assistant integration quality
* MQTT protocol handling
* SmartMeter support
* local SmartMeter HTTP support
* device discovery and classification
* energy-flow calculation
* entity correctness
* controls
* diagnostics
* logging
* test coverage
* architecture

Reverse engineering of cloud-free provisioning, SmartMeter pairing, virtual SmartMeters, or alternative EMS control is intentionally deferred until the integration core is stable.

Do not mix speculative reverse-engineering work into normal refactoring.

---

# Upstream Repositories

Primary baseline:

`csoscd/ha-solarvault`

Protocol/reference upstream:

`Jackery-Official/jackery`

The csoscd implementation should normally win where it contains tested real-world fixes or expanded hardware support.

The Jackery-Official implementation should normally win where it contains newer protocol knowledge, message formats, command semantics, device fields, or authoritative behavior not yet incorporated downstream.

Never overwrite one implementation with another merely because it is newer.

Compare behavior first.

---

# Golden Rule

DO NOT perform a big-bang rewrite.

All refactoring must be incremental and behavior-preserving.

At every significant step:

1. existing tests must pass
2. new behavior must have tests
3. entity IDs and unique IDs must be considered
4. Home Assistant state/history compatibility must be considered
5. MQTT parsing behavior must remain compatible with recorded real-world payloads

A refactor that makes the architecture prettier but silently changes runtime behavior is a regression.

---

# Phase 0 — Baseline Before Refactoring

Before architectural changes:

* run the complete test suite
* run Ruff
* run mypy if configured
* run Hassfest if configured
* run HACS validation if configured
* document current failures separately
* do not treat pre-existing failures as caused by the refactor

Generate a baseline inventory containing:

* supported device types
* supported sub-device types
* MQTT message types handled
* outgoing commands
* entities
* configuration/options
* translations
* calculations
* availability rules
* HTTP SmartMeter behavior
* unique-ID formats
* migration behavior

This inventory becomes the behavioral contract for the refactor.

---

# Phase 1 — Upstream Feature Matrix

Compare the current repository against:

`Jackery-Official/jackery`

Create:

`docs/upstream-feature-matrix.md`

Every relevant feature should be classified as:

* SAME
* LOCAL_ONLY
* OFFICIAL_ONLY
* DIFFERENT
* UNKNOWN

Examples:

* message type 101
* message type 102
* message type 106
* message type 107
* flat MQTT payload handling
* SmartMeter classification
* Smart Plug control
* energy flow calculations
* offline handling
* reauthentication
* unique-ID migration
* device registry behavior
* sensor definitions
* switches
* numbers
* selects
* buttons

Do not merge OFFICIAL_ONLY functionality until its behavior is understood.

For DIFFERENT functionality, document why the implementations differ.

---

# Target Architecture

The current oversized `sensor.py` must be decomposed gradually.

Target structure:

```text
custom_components/jackery/
│
├── __init__.py
├── manifest.json
├── config_flow.py
├── const.py
│
├── coordinator.py
│
├── protocol/
│   ├── __init__.py
│   ├── messages.py
│   ├── parser.py
│   ├── normalization.py
│   ├── commands.py
│   └── constants.py
│
├── transport/
│   ├── __init__.py
│   ├── mqtt.py
│   └── smartmeter_http.py
│
├── devices/
│   ├── __init__.py
│   ├── base.py
│   ├── registry.py
│   ├── solarvault.py
│   ├── smartmeter.py
│   ├── battery.py
│   └── plug.py
│
├── calculations/
│   ├── __init__.py
│   └── energy_flow.py
│
├── diagnostics.py
│
├── entity.py
├── sensor.py
├── switch.py
├── number.py
├── select.py
└── button.py
```

This is a direction, not permission to create every module at once.

Move one cohesive concern at a time.

---

# Separation of Responsibilities

## protocol/

Must contain Jackery protocol knowledge.

Examples:

* message types
* payload parsing
* aliases
* normalization
* message validation
* outgoing command construction

It must not contain Home Assistant Entity classes.

Whenever practical, protocol code should be testable without Home Assistant.

---

## transport/

Responsible only for obtaining or sending data.

Examples:

* MQTT subscribe
* MQTT publish
* SmartMeter HTTP polling

Transport code must not decide which Home Assistant sensors exist.

---

## devices/

Responsible for interpreting devices and capabilities.

Examples:

* main SolarVault
* expansion batteries
* SmartMeters
* plugs

Avoid scattering `devType` and `subType` conditionals throughout the repository.

Centralize device classification.

---

## calculations/

Contains derived values.

Examples:

* grid import/export
* battery net flow
* solar totals
* home consumption
* preferred meter source

Calculation functions should preferably be pure functions.

Pure calculation functions require direct unit tests.

---

## coordinator.py

Coordinates runtime state.

Responsibilities may include:

* subscriptions
* state cache
* device last-seen tracking
* update listeners
* availability
* periodic polling coordination

The coordinator should orchestrate components rather than becoming another monolithic implementation.

---

## Platform Files

`sensor.py`, `switch.py`, `number.py`, `select.py`, and `button.py` should primarily expose Home Assistant entities.

Protocol parsing and complex business logic do not belong here.

---

# Capability-Based Device Model

Prefer capability detection over model-specific condition chains.

Bad:

```python
if model == "HTO907A":
    ...
elif model == "Shelly Pro 3EM":
    ...
```

Preferred concept:

```python
capabilities = {
    "grid_power",
    "phase_power",
    "phase_energy",
    "voltage",
    "current",
    "frequency",
}
```

Model information can be used to determine capabilities, but downstream logic should consume capabilities whenever practical.

This architecture must remain compatible with currently supported devices.

Do not invent unsupported capabilities.

---

# Canonical State Model

Separate three concepts:

## Raw protocol data

Examples:

* `pvPw`
* `gridInPw`
* `gridOutPw`
* `tPhasePw`
* `tnPhasePw`

## Normalized state

Examples:

* `solar_power`
* `grid_import_power`
* `grid_export_power`
* `battery_charge_power`
* `battery_discharge_power`

## Derived state

Examples:

* `battery_net_power`
* `home_consumption`
* `solar_surplus`

Never destroy raw values merely because normalized equivalents exist.

Raw protocol information is valuable for diagnostics and reverse engineering.

---

# Source Tracking

Where the same logical measurement can originate from different sources, architecture should allow the source to be represented.

Possible sources include:

* SolarVault MQTT
* SmartMeter MQTT
* SmartMeter HTTP
* calculated fallback

Internally prefer a representation capable of carrying:

```text
value
source
timestamp
quality/availability
```

Do not expose unnecessary complexity to normal Home Assistant users.

Diagnostic output may expose source information.

---

# Source Priority

Do not silently change measurement precedence.

Existing production behavior must be documented and covered by tests before changing source-selection rules.

Example conceptual hierarchy:

```text
SmartMeter native measurement
→ SmartMeter HTTP measurement
→ SolarVault meter/CT measurement
→ system estimate
```

Actual precedence must be based on verified device behavior and existing implementation semantics.

Never assume this example is correct without tests.

---

# MQTT Parsing Rules

MQTT handling must tolerate known Jackery payload variants.

Known behavior that must remain regression tested includes where applicable:

* nested body payloads
* flat payloads
* incremental updates
* full-state updates
* sub-device arrays
* point updates
* aliases between firmware field names
* zero values
* missing fields
* null fields
* out-of-order updates
* repeated messages

Zero is a valid measurement.

Never treat numeric zero as missing merely because it is falsy.

---

# Unknown Protocol Data

Unknown fields must never crash the integration.

Unknown fields should generally be:

* preserved when useful
* ignored safely for entity creation
* optionally recorded in debug diagnostics

Do not automatically create Home Assistant entities for unknown protocol keys.

Unknown does not mean safe or meaningful.

---

# Protocol Discovery Support

Architecture should make future protocol discovery possible.

Optional debug functionality may report:

* observed message types
* unknown message types
* unknown payload keys
* device types
* sub-device types

Sensitive values must be redacted.

Protocol discovery must be disabled by default if it produces substantial logs.

---

# Diagnostics

Implement Home Assistant diagnostics according to HA conventions.

Diagnostics should make GitHub bug reports useful without requiring users to manually disclose sensitive configuration.

Useful diagnostic information includes where available:

* integration version
* Home Assistant version
* configured device model
* firmware version
* detected capabilities
* configured transports
* MQTT connection state
* last successful MQTT message age
* sub-device list
* sub-device communication mode
* last-seen age
* SmartMeter HTTP state
* HTTP failure count
* selected measurement source
* detected MQTT message types
* unavailable entities/reasons
* sanitized recent protocol metadata

Redact at minimum:

* tokens
* passwords
* account IDs
* credentials
* authorization headers
* Wi-Fi credentials
* sensitive URLs/query strings
* private keys

Serial numbers should be sanitized or partially redacted in downloadable diagnostics unless there is a compelling technical reason not to.

Do not leak secrets into logs.

---

# Logging Philosophy

Normal operation should not spam the Home Assistant log.

Use levels intentionally.

## ERROR

Only when functionality has failed and intervention may be required.

## WARNING

Degraded operation or unexpected conditions that users or maintainers should know about.

## INFO

Important lifecycle events.

Examples:

* integration setup
* transport connected
* device discovered
* device becomes unavailable
* device recovers

Avoid logging every MQTT message at INFO.

## DEBUG

Detailed protocol behavior.

Examples:

* message type received
* normalized fields
* source-selection decisions
* outgoing commands
* availability reasoning

## Protocol Trace

If verbose raw protocol logging is implemented, make it separately opt-in.

Sensitive fields must be redacted before logging.

---

# Availability Semantics

Never silently present stale data as current.

Track freshness separately for:

* main SolarVault
* each sub-device
* SmartMeter HTTP source

A temporary failure should not immediately destroy entities.

Use deterministic availability rules.

Recovery must occur automatically after valid data returns.

All availability state transitions require tests.

---

# HTTP SmartMeter Polling

HTTP polling is supplemental transport functionality.

It must:

* remain optional
* use configurable sane intervals
* not block Home Assistant's event loop
* handle timeout and connection errors
* mark values unavailable after a defined failure threshold
* recover automatically
* stop cleanly on unload/reload
* avoid duplicate poll tasks

Polling behavior requires tests.

---

# Commands and Writable Entities

Outgoing commands must be centralized progressively.

Preferred direction:

```text
Entity
→ Command Manager
→ Protocol command builder
→ Transport
```

Command behavior should distinguish:

* command sent
* optimistic state
* confirmed state
* timeout
* rejected/unsupported operation

Do not assume successful MQTT publish means successful device execution.

Where confirmation semantics are unknown, document that limitation.

---

# Home Assistant Entity Stability

Entity stability is critical.

Before changing:

* `unique_id`
* device identifiers
* translation keys
* platform
* entity naming
* device association

determine whether a migration is required.

Never knowingly create duplicate orphan entities.

Do not break recorder history unnecessarily.

Migration logic requires tests.

---

# Entity Quality

Use correct Home Assistant metadata:

* device class
* state class
* native unit
* entity category
* enabled-by-default behavior
* diagnostic classification

Avoid exposing every low-level field as a default-visible entity.

Prefer:

* primary useful sensors enabled
* obscure diagnostics disabled by default
* internal/debug values not exposed unless useful

---

# Tests

Every bug fix should ideally include a regression test reproducing the bug.

Every new protocol message handler requires tests.

Every new device classification requires tests.

Every migration requires tests.

Every energy-flow behavior change requires tests.

Every availability behavior change requires tests.

Every command encoding change requires tests.

---

# Test Layers

Maintain several levels of testing.

## Unit Tests

For:

* parsers
* normalization
* calculations
* classifiers
* mappings

## Coordinator Tests

For:

* MQTT routing
* cache merging
* freshness
* availability
* message ordering

## Home Assistant Tests

For:

* config flows
* options flows
* entity creation
* migrations
* setup/unload/reload

## Regression Fixtures

Introduce sanitized real-world MQTT fixtures.

Suggested layout:

```text
tests/fixtures/
├── solarvault3/
├── solarvault3_pro/
├── solarvault3_pro_max/
├── hto907a/
├── shelly_pro_3em/
└── generic/
```

Fixtures should represent scenarios, not random dumps.

Examples:

```text
startup.json
full_state.json
incremental_update.json
grid_import.json
grid_export.json
charging.json
discharging.json
smartmeter_lan.json
smartmeter_cloud.json
subdevice_missing.json
subdevice_recovery.json
```

Never commit real authentication tokens or identifiable customer data.

---

# Golden Fixture Tests

Recorded production payloads are considered valuable compatibility artifacts.

A protocol refactor is not complete until fixture playback produces equivalent normalized state before and after the refactor.

Where intentional differences exist, document them.

---

# CI Quality Gates

A pull request should not be considered complete unless applicable checks pass:

* pytest
* Ruff
* mypy
* Home Assistant config-flow tests
* HACS validation
* Hassfest
* translation validation

Do not disable checks merely to obtain a green pipeline.

Fix the cause or document a narrowly scoped exception.

---

# Refactoring Workflow

For large modules such as `sensor.py`, use extraction steps.

Example:

### Step 1

Move pure energy-flow calculations to:

`calculations/energy_flow.py`

No behavioral changes.

Run tests.

Commit.

### Step 2

Move payload normalization helpers to:

`protocol/normalization.py`

No behavioral changes.

Run tests.

Commit.

### Step 3

Move device classification to:

`devices/registry.py`

No behavioral changes.

Run tests.

Commit.

### Step 4

Move MQTT protocol parsing.

Run tests.

Commit.

### Step 5

Move transport lifecycle.

Run tests.

Commit.

Only after structural extraction is stable should internal APIs be redesigned.

---

# Changelog

Maintain `CHANGELOG.md` according to [Keep a Changelog](https://keepachangelog.com/en/).

---

# Commit Discipline

Prefer small commits with one purpose.

Good:

```text
refactor: extract energy-flow calculations
test: add recorded HTO907A fixture
feat: add diagnostics endpoint
fix: preserve zero-valued CT measurements
```

Bad:

```text
rewrite integration
```

Each refactor commit should ideally be reviewable independently.

---

# No Opportunistic Feature Creep During Refactors

If a refactor exposes an unrelated bug:

1. document it
2. add a failing regression test if appropriate
3. fix it in a separate commit

Do not silently change behavior while moving code.

This makes upstream comparison and bisecting possible.

---

# Upstream Sync Policy

Regularly inspect both:

* `Jackery-Official/jackery`
* `csoscd/ha-solarvault`

Do not blindly merge upstream branches after this architecture diverges.

Instead:

1. inspect upstream commits
2. classify each as protocol, bugfix, feature, docs, or architecture
3. determine whether equivalent behavior already exists
4. port the behavior into the local architecture
5. add or update regression tests
6. record relevant upstream commit references

Maintain:

`docs/upstream-sync.md`

Suggested format:

```text
Upstream commit:
Repository:
Classification:
Relevant:
Already implemented:
Ported as:
Tests:
Notes:
```

---

# Architecture Documentation

Maintain:

```text
docs/architecture.md
docs/protocol.md
docs/device-support.md
docs/upstream-feature-matrix.md
docs/upstream-sync.md
docs/diagnostics.md
```

Architecture decisions that affect future development should be documented.

---

# Device Support Matrix

Maintain an explicit support matrix.

For each device/model record:

* detection method
* devType
* subType where known
* MQTT support
* HTTP support
* controls
* known limitations
* tested/untested status

Do not claim hardware as tested unless evidence exists.

---

# Security

Treat all protocol data as untrusted input.

Validate types before calculations.

Never evaluate payload content.

Never execute arbitrary values as code.

Do not expose credentials in diagnostics.

Do not weaken TLS/security behavior solely for convenience without clear opt-in and documentation.

---

# Performance

Avoid unnecessary polling.

Prefer event-driven state updates where reliable.

Do not create duplicate MQTT subscriptions.

Do not create one polling task per entity.

Network access must be asynchronous.

Expensive parsing should not run separately for every entity.

Normalize incoming data once and distribute normalized state.

---

# Future Cloud-Independence Work

The architecture should permit later investigation of:

* local provisioning
* local SmartMeter pairing
* child-device configuration
* virtual SmartMeter endpoints
* Shelly RPC emulation
* alternative meter sources
* direct meter-value injection
* direct EMS power control

However, none of these are part of the initial refactoring milestone.

Do not add speculative writable protocol commands to production entities.

Experimental reverse-engineering tools must remain clearly separated from stable integration behavior.

---

# Definition of Done — Initial Refactoring Milestone

The first major milestone is complete only when:

1. all functionality from the starting csoscd baseline still works
2. relevant missing functionality from Jackery-Official has been assessed
3. justified upstream functionality has been ported
4. `sensor.py` no longer contains unrelated protocol, transport, calculation, and entity responsibilities
5. energy calculations are isolated and tested
6. MQTT parsing/normalization is isolated and tested
7. device classification is centralized
8. SmartMeter HTTP transport is isolated
9. diagnostics are implemented with redaction
10. logging is structured and useful
11. real-world regression fixtures exist
12. setup/unload/reload is tested
13. stale-data behavior is tested
14. unique-ID migration is tested
15. CI is green
16. architecture documentation exists
17. upstream synchronization strategy is documented

---

# Agent Behavior

When working autonomously:

* inspect existing implementation before editing
* prefer minimal safe changes
* preserve behavior during refactoring
* run targeted tests after each logical change
* run the full suite before completion
* never assume protocol semantics without evidence
* mark assumptions explicitly
* distinguish observed behavior from inferred behavior
* never delete unexplained protocol handling merely because it appears unused
* do not simplify compatibility code until tests prove it obsolete
* add comments explaining protocol quirks, not obvious Python syntax
* avoid giant commits
* stop and report when evidence is insufficient for a potentially breaking protocol decision

When there are multiple possible implementations, prefer the one that:

1. preserves compatibility
2. can be regression tested
3. isolates protocol knowledge
4. reduces coupling
5. makes future hardware support easier

---

# Final Principle

This project should evolve from:

"one large Home Assistant integration that understands Jackery"

into:

"a tested Jackery protocol/device layer with a clean Home Assistant adapter."

Reliability and preservation of real device behavior take priority over architectural elegance.
