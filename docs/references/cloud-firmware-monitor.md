# Optional cloud firmware monitor

## Scope

The optional firmware monitor reads `device/ota/list` only. It does not call
firmware version-list, download, Bluetooth, MQTT OTA, or update-start endpoints.
The monitor is disabled unless the user enables it in integration options.
Local MQTT setup and controls continue if cloud credentials or API requests fail.

The Jackery account, password, and region are stored in the config entry when
the user opts in. The account-derived `macId` is generated from the trimmed
account string using the established MD5/UUID-v3 procedure and is not stored.
The password is not prefilled in options forms, emitted in logs, or included in
integration diagnostics. The API session token exists only in the monitor's
memory for one polling cycle.

Jackery allows only one active account login. A Home Assistant firmware check
therefore signs the user out of the official Jackery app; the app requires a
new login to be used again.

Each poll performs one encrypted `auth/login` and then one sequential
`GET /device/ota/list?deviceSnList=<serial>` per target serial. The targets are
the configured SolarVault and known expansion batteries. Serial numbers are
matched exactly against one response row. A missing or duplicate row affects
only that device. Each cycle runs at startup, after newly discovered expansion
batteries, and then at a 24-hour interval. The monitor owns one cancellable task
and unload stops it.

## Response contract

`custom_components/jackery/protocol/ota.py` retains only the scalar
`currentVersion`, `targetVersion`, `updateStatus`, and `targetVersionId` values.
It does not convert or order version strings. Duplicate JSON object keys,
non-finite values, oversized responses, invalid JSON, non-success API codes,
and ambiguous device matches are rejected. Unknown API values do not create a
new Home Assistant entity or update classification.

The Jackery app callback explicitly maps these list-response status codes:

| Code | Meaning | Integration behavior |
| ---: | --- | --- |
| `0` | Update offered (`UPDATE_STATE_HAVE`) | Show the raw target value and create one persistent notification per changed offer. |
| `1` | Downloading | Show the raw status and dismiss the offer notification. |
| `2` | Installing | Show the raw status and dismiss the offer notification. |
| `6` | No pending update (`UPDATE_STATE_NO`) | Show the raw status, dismiss the offer notification, and clear its deduplication key. |
| Other | Not mapped for the list callback | Preserve the raw scalar as an unknown status; do not notify or reinterpret it. |

Status `3`, `4`, `1007`, and `1008` are app/UI constants but were not shown as
branches in the inspected list-response callback. Status `5` is also unmapped.
The integration therefore does not treat any of them as API success, failure,
or update availability.

`targetVersion` is an offered release value in the app's update flow, not proof
that an update was installed. The raw API field remains `null` when absent; a
separate `app_display_target_version` attribute mirrors the app's fallback to
`currentVersion` for its target label. Notifications do not present that
fallback current value as a new target. Update detection uses only the
callback-confirmed status `0`, never a lexicographic or numeric version
comparison. The status meanings are based on static app analysis. The available
saved API report verifies only `currentVersion="1.6.0"`, `updateStatus=6`, and
`targetVersion=null` for one host. An expansion-battery API result and an
update-offered API result have not yet been captured.

## Failure and freshness behavior

Each monitor observation records the latest check time, last successful check,
and a sanitized error category. After a failed latest request, its sensor is
unavailable rather than presenting an older cloud version as current. A failed
device request does not prevent later serials in the same cycle from being
queried. A later successful response restores the sensor automatically.

Notification deduplication state is stored separately under Home Assistant's
normal `.storage` mechanism. It contains hashed device keys and hashes of the
reported version tuple, not credentials or raw responses. Diagnostics expose
neither that store, account details, password, `macId`, nor session token.
