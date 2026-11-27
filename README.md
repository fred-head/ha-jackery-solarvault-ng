# Jackery SolarVault NG for Home Assistant

[![Open in Home Assistant](https://img.shields.io/badge/Open%20in-Home%20Assistant-18BCF2?logo=homeassistant&logoColor=white)](https://my.home-assistant.io/redirect/hacs_repository/?owner=fred-head&repository=ha-jackery-solarvault-ng&category=integration)
[![Latest Release](https://img.shields.io/github/v/release/fred-head/ha-jackery-solarvault-ng?include_prereleases&sort=semver&label=Latest%20Release)](https://github.com/fred-head/ha-jackery-solarvault-ng/releases)
[![Validate](https://github.com/fred-head/ha-jackery-solarvault-ng/actions/workflows/validate.yml/badge.svg)](https://github.com/fred-head/ha-jackery-solarvault-ng/actions/workflows/validate.yml)
[![License](https://img.shields.io/github/license/fred-head/ha-jackery-solarvault-ng.svg)](LICENSE)

Jackery SolarVault NG is a community-maintained Home Assistant integration for
Jackery SolarVault systems. It connects through the MQTT broker configured for
your device and adds its available readings and controls to Home Assistant.

The integration focuses on local communication after setup. Initial device
provisioning still uses the Jackery app, and some device features may continue
to depend on Jackery cloud services. SolarVault NG is not affiliated with
Jackery or the Home Assistant project.

## What it can do

- Show power, energy, battery, operating-status and diagnostic readings.
- Add readings for supported SmartMeters and selected child devices.
- Provide controls for supported SolarVault settings and Smart Plugs.
- Optionally retrieve local measurements from the Jackery SmartMeter 3P over
  HTTP.
- Optionally enable experimental Protocol discovery to record unknown message
  types, commands and structures with bounded MQTT examples for troubleshooting.
  It is disabled by default; review diagnostic exports before sharing them.
- Optionally check the main device and expansion batteries for Jackery cloud
  firmware offers, with diagnostic firmware sensors and Home Assistant
  notifications.
- Set up through Home Assistant; YAML entity definitions are not required.

Implemented device paths include SolarVault 3 and SolarVault 3 Pro Max,
Jackery SmartMeter 3P, Shelly Pro 3EM data routed through Jackery, and selected
expansion batteries and Smart Plugs. Available entities and controls vary by
model and firmware.

### Optional Jackery cloud firmware checks

Firmware checks are disabled by default. Enable them in the integration's
**Configure** options and provide the Jackery account, password, and account
region. Home Assistant checks firmware metadata for the SolarVault and known
expansion batteries; it does not download or install firmware. Jackery permits
only one active account login, so a check signs the official Jackery app out.
The account credentials and device serial numbers are sent to Jackery for the
checks. Local MQTT operation continues if a cloud check fails. See the
[installation guide](docs/installation.md#jackery-cloud-firmware-checks) for
setup and credential details.

The project is under active development. Check the [changelog](CHANGELOG.md)
before updating, especially when changing from another Jackery integration.

## Quick installation

You need Home Assistant **2025.8.0 or newer**, a configured Home Assistant MQTT
integration, and a SolarVault already set up to use your MQTT broker through
the Jackery app.

### Home Assistant Marketplace

On current Home Assistant versions:

1. Open **Settings → Marketplace** and select **Add from link**.
2. Enter `https://github.com/fred-head/ha-jackery-solarvault-ng` and select
   **Add**. If asked, choose **Integration**.
3. Open the repository in the Marketplace and install it.
4. Restart Home Assistant, then go to **Settings → Devices & services → Add
   integration** and search for **Jackery**.

### HACS on older Home Assistant versions

Open **HACS → Integrations → ⋮ → Custom repositories**, add
`https://github.com/fred-head/ha-jackery-solarvault-ng` as an **Integration**,
then install Jackery and restart Home Assistant.

During integration setup, enter the SolarVault serial number and MQTT token.
Create a Home Assistant backup before replacing an existing Official or
Community installation. See the [installation guide](docs/installation.md) for
the complete setup steps and the [upgrade guide](docs/upgrading.md) before
switching from another Jackery integration.

## Project lineage and credits

- [Jackery-Official/jackery](https://github.com/Jackery-Official/jackery)
  created the original Home Assistant integration and remains an authoritative
  reference for Jackery protocol behavior.
- [csoscd/ha-solarvault](https://github.com/csoscd/ha-solarvault) is the
  community fork on which SolarVault NG directly builds. Its contributors'
  fixes, expanded device support and protocol research form a substantial part
  of this project's foundation.

SolarVault NG gratefully acknowledges the authors, contributors and testers of
both projects. Their work is preserved in the repository history.

## User guides

- [Installation](docs/installation.md)
- [Upgrading from another integration](docs/upgrading.md)
- [Devices and entities](docs/devices-and-entities.md)
- [Energy dashboards](docs/energy-dashboards.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Changelog](CHANGELOG.md)


## License

MIT License. See [LICENSE](LICENSE).
