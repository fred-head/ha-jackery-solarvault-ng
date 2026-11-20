# Upgrading

SolarVault NG supports upgrades from **Jackery Official**, the **Community
integration**, and earlier **SolarVault NG** versions. The migration runs
automatically when Home Assistant starts with the updated NG integration. The
maintainer has tested these paths with real Jackery hardware in a pre-production
Home Assistant installation:

- Fresh SolarVault NG installation.
- Jackery Official to SolarVault NG.
- Community integration to SolarVault NG.
- Jackery Official to Community integration to SolarVault NG.

These reported pre-production paths used the CLI to copy the integration's
Python package files; they did not exercise installation or updates through
HACS or Marketplace.

The **3.0.0-rc.1 Marketplace installation test passed** on the pre-production
Home Assistant installation: Marketplace installed NG over an existing
Jackery installation after the ownership workaround below, and the subsequent
Home Assistant restart completed successfully. This verifies the Marketplace
install and restart for the tested Official-owned installation. It does not
claim that every hardware migration path listed above was repeated through
Marketplace.

Automated registry and recorder tests provide additional coverage. The exact
Home Assistant, integration, hardware and firmware versions used in the
pre-production runs are not recorded in this guide.

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

## Home Assistant 2026.11 Marketplace ownership workaround

Marketplace tracks which repository owns an installed integration directory.
When replacing an existing Jackery installation, it may stop with an error
such as:

> The `jackery` directory belongs to `Jackery-Official/jackery`.

This is a Marketplace ownership conflict. Do not rename the `jackery` directory,
delete the existing integration entry, or choose **Delete and uninstall** to
work around it. Those actions can break the existing Home Assistant
configuration and entity identities.

The following workaround was tested in pre-production when the recorded owner
was `Jackery-Official/jackery`:

1. Make a full Home Assistant backup.
2. Temporarily disable the **Marketplace** integration itself. Do not disable
   or remove Jackery. You can open Marketplace from **Settings → Devices &
   services → Devices**, search for a Marketplace device, open it, then select
   its Marketplace integration and choose **⋮ → Disable**.
3. Make a separate backup of
   `/config/.storage/marketplace.repositories`.
4. Open that file in a text editor and search for
   `Jackery-Official/jackery`. In that repository's entry, remove only the
   `"installed": true` property, including its comma. Keep the repository
   entry and all Jackery files and config entries. Preserve valid JSON.
5. Enable Marketplace again. If it is not visible, show disabled devices in
   **Settings → Devices & services → Devices** and open the Marketplace
   integration there.
6. Install SolarVault NG from Marketplace and restart Home Assistant when
   prompted.

This edits Marketplace's internal repository record; it is a workaround for
the Marketplace ownership check, not an integration setting. The procedure
has only been verified for the `Jackery-Official/jackery` owner shown above. If
the error names a different repository, do not assume the same procedure has
been validated for that owner. Home Assistant tracks the broader Marketplace
issue in [Core issue #190454](https://github.com/home-assistant/core/issues/190454).

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

### Retained old Jackery meter device

An earlier Official 1.0-to-2.0 update could leave two Jackery device cards for
the same meter: an older card with two CT sensors and a newer card with ten
directional sensors. NG automatically handles this specific verified pattern.
It migrates the active card and keeps the historical card and its sensor
entries. The separate Shelly integration's device is unaffected.

This also recovers the known `duplicate-device-target` block after an update
to NG RC1. Install an NG version containing the fix through your usual store
and restart Home Assistant. Keep the existing integration entry; restoring
the pre-RC1 backup or reinstalling the integration is not required for this
case.

The retained card receives the label **Jackery: old device – review** (or its
translation, such as **Jackery: Altbestand – prüfen**). A notification links
to both cards and explains the result. Existing custom names and labels remain
intact. Dismissing the notification is remembered across restarts.

The old card's two sensors no longer receive measurements. Check automations,
dashboards and external monitoring for references to them, and switch to the
appropriate sensors on the active card if necessary. These old measurements
are not automatically equated with new total measurements. You may keep the
historical card for reference or delete that card through its Home Assistant
device page after checking. Deleting it also removes its associated entity
entries; continued access to their history is not guaranteed. NG does not
recreate the old card after deletion.

Other conflicts still pause the affected child's discovery. A device name or
label alone does not make a card safe to remove. If the conflict warning
remains, retain the records and follow the [troubleshooting guide](troubleshooting.md).

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
