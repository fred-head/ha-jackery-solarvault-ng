# Changelog

All notable user-facing changes to Jackery SolarVault NG are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

Changes in **Unreleased** are planned for the **3.0.0** release.

## [Unreleased]

### Added

- Add a downloadable Home Assistant diagnostics report for the integration,
  including connection freshness, child-device and entity health information.
  The standard report is bounded and designed to omit or redact sensitive
  identifiers.
- Add optional, disabled-by-default protocol, alert, and BMS log capture for
  targeted troubleshooting. These features can retain raw device data; review
  their diagnostic output before sharing it.
- Add dedicated user guides for installation, upgrades, devices and entities,
  and troubleshooting.

### Changed

- Refactor the original integration’s core, moving key protocol, calculation,
  device-classification, transport, runtime-state, discovery, and
  entity-definition responsibilities into dedicated modules. Preserve
  established behavior and Home Assistant entity identities while providing a
  more maintainable foundation for future development.
- Expose Forced Charging as an on/off switch. It does not set a charge
  percentage.
- Set the default charge-limit range to 50–100% and the discharge-limit range
  to 5–49%; use device-reported bounds when available.
- Allow the public-grid export limit control to reach 2500 W. This is separate
  from the SolarVault's OnGrid AC output limit.
- Apply changed connection and polling options by reloading the integration
  entry.
- Keep Home Assistant 2025.8.0 as the minimum version while supporting newer
  device-registry APIs.

### Fixed

- Preserve existing Home Assistant devices, entities, user settings, and
  history across the tested upgrade paths from Jackery Official, the Community
  integration, and earlier NG installations.
- Keep child devices with the same serial number under different SolarVaults
  separate, and avoid creating replacement entities when an existing record
  can be migrated safely.
- Improve MQTT recovery: stale main-unit and child-device readings become
  unavailable, and valid reports restore them automatically.
- Prevent unrelated or malformed MQTT messages from refreshing the configured
  SolarVault's status or interrupting updates to other entities.
- Keep SmartMeter HTTP availability independent from MQTT updates. Repeated
  HTTP failures mark its readings unavailable, and valid measurements restore
  them.
- Improve grid and home-consumption calculations when meter readings expire or
  are absent, while preserving valid zero-valued measurements.
- Block Smart Plug commands when the plug is not in local/LAN communication
  mode.
- Keep re-authentication tied to the active Home Assistant entry so a refreshed
  token can restart communication cleanly.

---

## Earlier releases

The entries below summarize user-visible changes from versions before 3.0.0.
Historical behavior may have changed since those releases; see the current
user guides for supported devices, controls, and setup instructions.
The former 2.3.0 section was marked unreleased; applicable changes from it have
been consolidated into the 3.0.0 changes above.

## [2.2.0] - 2026-07-27

### Added

- Add support for the Jackery D0 Reader (HTO910A), including total grid import
  and export readings.
- Use D0 Reader measurements as a grid source when a SmartMeter 3P is not
  available.

## [2.1.0] - 2026-07-27

### Added

- Add a writable public-grid export limit control, separate from the
  SolarVault's OnGrid output limit.

## [2.0.3] - 2026-07-26

### Added

- Add the SolarVault's Wi-Fi IP address as a sensor.

## [2.0.2] - 2026-07-25

### Fixed

- Restore SmartMeter and expansion-battery entities after Home Assistant
  restarts, and prevent duplicate unavailable entities after migration.

### Added

- Add the 1200 W output option for SolarVault 3 Pro devices.

## [2.0.1] - 2026-07-24

### Fixed

- Prevent calculated home-consumption power from showing negative values.

## [2.0.0] - 2026-07-23

### Added

- Support multiple SolarVaults in one Home Assistant installation.
- Add a re-authentication flow for an expired or rejected device token.
- Show the detected device model, firmware, and human-readable status readings.

### Changed

- Include the SolarVault serial number in entity identities so multiple units
  can be configured independently.
- Block Smart Plug control while the plug uses cloud-relay communication.

## [1.3.9] - 2026-07-17

### Fixed

- Keep expansion-battery energy entities available between their infrequent
  reports instead of repeatedly removing and recreating them.

## [1.3.8] - 2026-07-17

### Fixed

- Preserve the last valid expansion-battery energy reading when the device
  reports a null value.

## [1.3.7] - 2026-07-17

### Changed

- Restrict the SolarVault OnGrid output setting to the values supported by the
  Jackery app at that time.

## [1.3.6] - 2026-07-17

### Fixed

- Keep BP2500 expansion-battery sensors available between reports.

## [1.3.5] - 2026-07-17

### Fixed

- Correctly display the SmartMeter communication mode as LAN or Cloud.

## [1.3.4] - 2026-07-17

### Added

- Add English and German names for sensors and controls, plus readable device
  and connection status values.

## [1.3.3] - 2026-07-17

### Added

- Add translations for controls and the configuration flow.

### Changed

- Replace German Work Mode option values with translated values. Automations
  that used the old option strings needed to be updated.

## [1.3.2] - 2026-07-17

### Changed

- Reduce the delay before app-initiated operating-mode changes appear in Home
  Assistant.

## [1.3.1] - 2026-07-17

### Fixed

- Keep changes made with supported controls from reverting to the previous
  displayed value while waiting for device updates.

## [1.3.0] - 2026-07-17

### Added

- Add controls for operating mode, default output power, grid-outage fallback,
  and meter-following behavior.

### Changed

- Replace the read-only Work Mode sensor with a selectable operating-mode
  control.

### Removed

- Remove obsolete read-only sensors that duplicated the new controls.

## [1.2.1] - 2026-07-15

### Added

- Add additional grid, inverter, PV-limit, standby, and system power readings
  reported by the SolarVault.

## [1.2.0] - 2026-07-15

### Added

- Add a Home Assistant restart button, an Automatic Standby selector, device
  status readings, and support for meter-reader sub-devices.

## [1.1.70] - 2026-07-15

### Fixed

- Correct the home-consumption calculation for balanced grid export.

## [1.1.69] - 2026-07-15

### Added

- Add Wi-Fi, Ethernet, device-capability, and SmartMeter communication
  diagnostic readings.

## [1.1.67] - 2026-07-14

### Added

- Add an experimental numeric forced-charge target. Its meaning was not fully
  established and the control has since been superseded by the on/off switch
  described under Unreleased.

## [1.1.66] - 2026-07-14

### Added

- Add cumulative CT import and export energy readings.

## [1.1.65] - 2026-07-10

### Added

- Add cumulative BP2500 charge and discharge energy readings.

### Fixed

- Prevent SmartMeter and CT entities from disappearing when the SolarVault
  reports a different sub-device category.

## [1.1.64] - 2026-07-10

### Added

- Add cumulative SmartMeter 3P import and export energy readings for each phase.

## [1.1.63] - 2026-07-10

### Added

- Start the community fork of the Jackery Official integration, adding
  SolarVault 3 Pro Max readings and correcting SmartMeter 3P device detection.
