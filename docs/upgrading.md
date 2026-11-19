# Upgrading

SolarVault NG supports upgrades from **Jackery Official**, the **Community
integration**, and earlier **SolarVault NG** versions. The migration runs
automatically when Home Assistant starts with the updated NG integration. These
migration paths have been tested.

In normal cases, your existing configuration, devices, entities and history
remain in place, and the system continues working as before. You should not
need to add the SolarVault again or rebuild your dashboards and automations.

## Before upgrading

1. Create a full Home Assistant backup that includes Home Assistant settings
   and history.
2. If Recorder uses an external database, create a separate backup of that
   database.
3. Keep a copy of the backup outside the Home Assistant system.
4. Review the [changelog](../CHANGELOG.md) for changes that may affect your
   setup.

See Home Assistant's [backup and restore guide](https://www.home-assistant.io/common-tasks/general/backups/)
for current instructions.

## Upgrade to a newer SolarVault NG version

1. Update Jackery SolarVault NG through the store where you installed it:
   **Settings → Updates** in the Marketplace, or **HACS → Integrations** on
   Home Assistant versions that use HACS.
2. Restart Home Assistant if prompted, or after installing the integration
   update.

Keep the existing Jackery integration entry. Updating the installed integration
preserves its configuration and lets NG migrate the existing Home Assistant
records automatically.

## Upgrade from Jackery Official or the Community integration

1. Create the backup described above.
2. Install Jackery SolarVault NG using the appropriate method in the
   [installation guide](installation.md).
3. Keep the existing Jackery config entry. Do not remove it or add a second
   entry for the same SolarVault.
4. Restart Home Assistant if prompted.

On startup, NG migrates the existing integration data. Once Home Assistant has
restarted and the SolarVault is online, its devices and supported entities
should resume updating. Existing dashboards and automations should continue to
work with their existing entity IDs.

## After the upgrade

- Confirm that the Jackery integration is loaded and the SolarVault device is
  present under **Settings → Devices & services**.
- Check that sensor values resume updating and that any SmartMeters or other
  supported child devices are present.
- Check a few existing dashboard cards, automations and history graphs.

Most users should not need to re-enter the MQTT token or recreate entities. If
Home Assistant does not load the integration or the device does not resume
reporting, keep the pre-upgrade backup and contact the project maintainer before
removing entries or entities.

## Home Assistant 2026.11: HACS moves to Marketplace

When Home Assistant updates to 2026.11 or newer, the built-in Marketplace
automatically takes over existing HACS repositories and update entities. This
is a change to the store interface; it does not require reinstalling Jackery
SolarVault NG. See [Home Assistant's Marketplace migration notes](https://www.home-assistant.io/integrations/marketplace/#coming-from-hacs).

## Rollback

If you need to return to the state from before an upgrade, restore the complete
backup created before upgrading, including history. Restore the separate
database backup too if Recorder uses an external database. Do not downgrade by
installing older integration code alone; restore the backup instead.
