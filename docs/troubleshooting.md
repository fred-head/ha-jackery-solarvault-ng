# Troubleshooting

Use this guide to investigate setup problems, missing readings, and unexpected
values. If you are upgrading from Jackery Official or the Community integration,
keep the existing integration entry and follow the [upgrade guide](upgrading.md)
before removing or recreating anything.

For entity names and device-specific availability, see
[Devices and entities](devices-and-entities.md).

## Quick checks

Before changing settings, check the following:

1. Home Assistant's MQTT integration is configured and connected to the broker.
2. The SolarVault is powered, online, and configured to use that same broker.
3. The SolarVault serial number, device token, and MQTT topic prefix in Jackery
   SolarVault NG match the device configuration.
4. The Home Assistant log does not show a current Jackery setup or connection
   error. Open **Settings → System → Logs**.

The device token is not the MQTT broker password. The default topic prefix is
<code>hb</code>; change it only when the SolarVault uses a different prefix.

## Setup and connection problems

### Home Assistant says that MQTT is not configured

Jackery SolarVault NG requires Home Assistant's MQTT integration to be set up
and connected before the Jackery integration can be added.

- Open **Settings → Devices & services**, select **MQTT**, and confirm that
  the integration is configured and connected.
- Check that the broker host, port, and credentials are correct.
- Use the broker's network address, not the Home Assistant dashboard URL.
- Confirm that the SolarVault can also connect to this broker.

See the [installation guide](installation.md) for the MQTT setup steps.

### Jackery is not listed when adding an integration

- Confirm that Jackery SolarVault NG is installed through the
  [Home Assistant Marketplace or HACS](installation.md#3-install-the-integration).
- Restart Home Assistant after installing the integration.
- Then open **Settings → Devices & services → Add integration** and search for
  **Jackery**.

### The integration is set up, but no readings arrive

Check each connection in order:

1. In the Jackery app, confirm that MQTT is enabled for the SolarVault.
2. Confirm that the broker details entered in the Jackery app point to the same
   broker used by Home Assistant.
3. In the Home Assistant Jackery configuration, check the main SolarVault
   serial number and device token. The token comes from the app's MQTT settings;
   it is not the broker password.
4. Check the **MQTT Topic Prefix**. It is normally <code>hb</code>.
5. Wait for the SolarVault to report data, then check **Settings → System →
   Logs** for a Jackery error.

Do not remove and add the config entry as a first troubleshooting step. If this
is an upgrade, removing it can disrupt the migration of existing devices and
entities; see the [upgrade guide](upgrading.md).

### Home Assistant asks you to re-authenticate

Follow the Home Assistant re-authentication prompt and enter the current
SolarVault device token from the Jackery app's MQTT settings.

A re-authentication prompt can mean that the token was rejected, but it can
also appear when the integration receives no valid response from the device.
If the prompt returns, check the MQTT broker connection, device MQTT settings,
serial number, and topic prefix as well as the token.

## Missing or unavailable readings

### Duplicate Jackery meter cards or `duplicate-device-target` after an upgrade

NG can automatically recognize the specific old/new CT split left by an earlier
Official 1.0-to-2.0 update. Update to an NG version containing the Issue #58 fix
and restart Home Assistant, including if you already installed RC1. No backup
restore or manual registry edit is needed for the recognized case.

The active card resumes normal discovery. The old card stays available as
historical inventory, marked **Jackery: old device – review** (localized).
Read the notification and the [upgrade instructions](upgrading.md#retained-old-jackery-meter-device)
before choosing whether to remove it. The old sensors do not resume reporting.
This is about two Jackery-owned cards, not the separate Shelly integration.

If the warning persists, NG could not establish this known safe case. Keep the
records, retain your backup and contact the maintainer with the warning category
and sanitized diagnostics. Do not delete devices to force migration.

### Main SolarVault entities become unavailable

The integration marks main entities unavailable after it stops receiving
SolarVault data for about a minute. Check that the SolarVault and Home Assistant
can both reach the broker and that the device still has MQTT enabled. When valid
data resumes, entities should recover automatically.

If the SolarVault is online in the Jackery app but Home Assistant receives no
data, check the MQTT and Jackery errors in **Settings → System → Logs**. If the
problem started after an update, review the [changelog](../CHANGELOG.md).

### One or more SolarVault sensors are unavailable

Not every device or firmware reports every measurement. Some readings also
require a connected meter, expansion battery, or other sub-device. Check the
description and device path in [Devices and entities](devices-and-entities.md).
An entity can exist even when its device has not supplied a value.

### A SmartMeter, CT meter, D0 Reader, expansion battery, or Smart Plug is missing

Child-device entities appear after the SolarVault reports the child device to
the integration.

- Confirm that the child device is paired or configured in the Jackery app and
  is online there.
- Check that it is connected to the SolarVault and that the SolarVault remains
  connected to MQTT.
- Check the device page in **Settings → Devices & services** for the
  SolarVault's discovered devices.
- Confirm that the device type is covered in the [device overview](devices-and-entities.md#device-overview).

The entity set depends on the reported device type and firmware. The integration
does not create entities for every meter or accessory model.

### SmartMeter shows online, but its power readings are missing or stale

Check the SmartMeter's **SmartMeter communication mode** and
**SmartMeter communication status** entities.

If the mode is **Cloud** while measurement values are missing, the meter may be
connected through cloud relay without sending its local measurement data to
Home Assistant. Restarting the SolarVault from the Jackery app or its **Restart**
button can return the meter to **LAN** mode. Check the mode and readings again
after it reconnects.

### Optional SmartMeter HTTP readings are unavailable

HTTP polling is disabled by default and applies to a compatible Jackery
SmartMeter 3P (HTO907A).

- In the Jackery integration options, enable **Poll SmartMeter via HTTP**.
- Confirm that the SmartMeter has an IP address and that Home Assistant can
  reach it on the local network.
- Confirm that the SolarVault is still sending the SmartMeter details through
  MQTT; the integration learns the meter's address from that data.
- Three consecutive failed HTTP polls mark these entities unavailable.
  They should recover when valid numeric readings are received again.

If the SmartMeter has no IP address in Home Assistant, first troubleshoot its
MQTT connection. See the [optional HTTP entity list](devices-and-entities.md#optional-smartmeter-http-entities).

### The Smart Plug switch is unavailable or does not control the plug

The integration allows Smart Plug control only while the plug is in local/LAN
communication mode. Check its communication mode and switch state. If the plug
is in Cloud mode, use the Jackery app or restore its local/LAN connection before
trying the Home Assistant switch again.

## Readings or controls do not match expectations

### Grid readings do not match the whole-home meter

The SolarVault's **Energy to home grid**, **Energy from home grid**, and
**Power to home grid** entities describe its own OnGrid connection. They are
not whole-home grid import/export readings.

For whole-home measurements, use an entity from a supported SmartMeter, CT
meter, or D0 Reader. The entity descriptions and measurement limits are listed
in [Devices and entities](devices-and-entities.md).

### Home consumption is an estimate

**Home consumption (calculated)** is derived from available meter and
SolarVault readings. Without a suitable meter, it is only an estimate based on
SolarVault power readings. **Home consumption (device estimate)** is a separate
value reported by the SolarVault. These readings can differ.

### A setting or switch does not change, or changes back

- Check whether the device and firmware support that control.
- **Follow meter** is available only in **Custom** operating mode.
- Wait for the SolarVault to report its new state. Sending a command does not
  always confirm that the device applied it.
- If Home Assistant still shows the old value, check the same setting in the
  Jackery app and review the Home Assistant log.

See [SolarVault controls](devices-and-entities.md#solarvault-controls) for the
available controls and their behavior.

## Download diagnostics and report a problem

Home Assistant can create a diagnostic file for the Jackery config entry:

1. Open **Settings → Devices & services → Integrations**.
2. Select the **Jackery** integration entry for the affected SolarVault.
3. Open the integration's menu and select **Download diagnostics**.

The standard diagnostic snapshot is designed to omit or redact credentials and
identifiers. Review the file before sharing it. If any experimental protocol,
alert, or BMS log capture option has been enabled, its export can contain raw
device data; inspect those sections carefully and remove anything you do not
want to share. These capture options are disabled by default and are intended
for specific troubleshooting requests.

When reporting a problem, include:

- Home Assistant version and Jackery SolarVault NG version.
- SolarVault model and firmware, if known.
- The affected entity names and what you expected to see.
- When the issue began and the steps that reproduce it.
- Relevant Home Assistant log messages and the reviewed diagnostics file.

Never post your device token, MQTT broker password, or unreviewed screenshots,
logs, or diagnostic data publicly.
