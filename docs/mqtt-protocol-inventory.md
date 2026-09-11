# MQTT protocol inventory

See [baseline](baseline.md) for pinned sources. Message **type**, `body.cmd`, `eventId`, and `body.devType` are separate namespaces. `body.cmd=106` inside type=2 is not top-level type=106. Body devType can be a query category; item devType classifies a child. No command semantics beyond source and attributed evidence are assumed.

## Topics and envelopes

C subscribes QoS 1 to `{prefix}/device/+/status` and `{prefix}/device/+/event`; both run the same handler. There is no enforced type-to-topic split. Matching other SNs are ignored after the heartbeat has already advanced. O instead subscribes to the configured host SN and updates heartbeat after SN filtering. Both discard unsubscribe callbacks. C definitions: `sensor.py:1314,1363,1421`; O: `sensor.py:1000,1051,1097`.

Every outbound publish goes to `{prefix}/device/{main_sn}/action`, QoS 0, retain=false, through `homeassistant.components.mqtt.async_publish`. Envelopes contain type, eventId, random messageId 1000–9999 and integer wall-clock ts; polls always contain token, controls include it only when truthy. There is no pending-command map, response correlation, rejection tracking or timeout/retry manager. Publish success means MQTT submission, not device execution.

## Known top-level types

| Type | Classification / direction | Purpose and important body | Cache effects / response expectation | C location and existing tests |
| --- | --- | --- | --- | --- |
| 1 | Sent (`/action`) | Main command: eventId=3, body `cmd=5,rc=1` plus writable field(s); reboot is `reboot=1`. | Method does not update cache; optimistic entities do so before calling it. Comments/changelog mention cmd=107 acknowledgement; no dedicated acknowledgement handler. | `sensor.py:1969`; button/switch/number/select call it. `test_switch_select_cache.py` verifies selected parameter dicts using fake coordinator, **not wire envelope**. |
| 2 | Both | Outgoing read-all-settings body=null, eventId=0; incoming status/settings dict (including observed `cmd=106`). | Incoming generic normalization/cache update; nested arrays here are shallow-updated, not passed through dedicated array merging. No correlated response validation. | `sensor.py:1535,2251`; `test_mqtt_routing::test_type2_*`, `test_upstream_sync::test_type2_grid_buy_alias_normalized`. |
| 23 | Received; parsed, not generated | Statistics: `deviceSn`, `devType`, energy fields. `system`/missing SN → main; devType=1 child → expansion battery. | Expansion drops null updates, timestamps child and creates sensors; other children patched only if already in plugs/plug/cts. Main's literal SN is **not** accepted as main by C. Collectors not searched. | `sensor.py:1468`; `test_type23_*`, `test_expansion_battery_null_values_do_not_overwrite_cache`. |
| 25 | Both | Status poll body=null; response body contains main fields. | Incoming generic normalized merge. Poll-response relationship is documented, not tracked. | `sensor.py:1535,2240`; no outbound poll assertion; generic receive path/flat helper covered. |
| 100 | Sent | Child poll body `devType=2`, `3`, `6`, eventId=0. | Intended response 101. Device category 4 collector is reported under category 2 per source comment, no explicit type=100/devType=4 request. | `sensor.py:2278`; untested publishing. |
| 101 | Received; parsed, not generated | Full child data, arrays `plug/plugs/socket/sockets`, `ct/cts`, `collectors`; null body returns immediately. | Nonempty lists merge by SN; empty lists do not clear; missing fields retained, explicit null can overwrite. Defaults missing plug/CT type to 6/2. Sets child last-seen even for metadata-only entries. No main-SN exclusion in arrays. | `sensor.py:1497,1556`; routing tests cover CT/plug isolation, SN merge, defaults indirectly, null body. Collector branch untested. |
| 102 | Received; parsed, not generated | Child increment: same arrays or direct `deviceSn/sn`, devType, measurement/switch fields. | Arrays win over point processing if any nonempty section merged; known point child patched excluding null; new point classified. Rejects point SN=main/system. Records point freshness before successful classification. Source says not observed on Pro Max. | `sensor.py:1505,1626`; `test_upstream_sync::test_type102_*` (synthetic, not firmware confirmation). |
| 105 | Sent | Full-system poll body=null, eventId=0. | Expected 106; initial production counter=2 sends it on first cycle, then every third cycle. | `sensor.py:2264`; no timing/publish tests; fixture counter=0 differs from constructor. |
| 106 | Received; parsed, not generated | Full-system dict: workModel, status, settings, power. | Normalizes then merges, **except** established `batInPw,batOutPw,pvPw,pv1–4,swEpsInPw,swEpsOutPw,stackInPw,stackOutPw` never overwritten by 106. Presence of cache key is the only test; no source/age tracking. Two 106-only snapshots can freeze these values. | `sensor.py:1095,1510`; tests cover initial merge and workModel alias, **not protected-field ordering**. |
| 107 | Received; parsed, not generated | Incremental system dict, e.g. soc/workMode/workModel. | Normalized main merge; no special acknowledgement matching. | `sensor.py:1525`; `test_upstream_sync::test_type107_*`. |
| 123 | Received; parsed, not generated | Auth/error notification `errorCode`. | 401 starts guarded reauth; other codes ignored. Calculation/discovery/fan-out still follow. | `sensor.py:1530,1699`; two routing tests assert reauth flag / non-401 no-op; no completed reauth-flow test. |
| Missing/unknown (test example 99) | Received fallback | Dict body, or recognized flat fields without body. | Unknown dict keys enter main cache, then calculations and distribution; no observed-type inventory. Unknown numeric types are not explicitly rejected. | `sensor.py:1535`; `test_unknown_message_type_falls_back_to_flat_merge`. |

There is no separate known-unused enumerated message type in these Python implementations. A type sent by C but received unexpectedly can reach the generic dict merge; this is permissive fallback, not evidence of bidirectional protocol support for every command.

## Payload variants and normalization

`_extract_flat_body` (`sensor.py:1301`) recognizes any of: batSoc, soc, pvPw, stat, workMode, inOngridPw, outOngridPw, gridInPw, gridOutPw, inGridSidePw, outGridSidePw, swEpsInPw, swEpsOutPw, batInPw, batOutPw, otherLoadPw. It strips type/eventId/messageId/ts/deviceType/token/softver/body. Flat payloads containing **only** workModel, gridBuyPw, energy or child arrays are not recognized. A present non-dict body is not replaced by flat fields. `json.loads` accepts more than dicts; non-dict top-level data reaches the outer exception logger.

Aliases (`sensor.py:1280`): gridBuyPw→gridInPw, gridSellPw→gridOutPw, workModel→workMode, only if target is missing or None. Original keys remain; explicit target zero wins. `soc` and `batSoc` are independent, not aliases. Phase casing alternatives are handled in calculations/legacy CT entities, **not** globally normalized; devType=3 sensor direct reads use lowercase keys only.

Cache rules differ by path: main updates and arrays can write null; known point updates and expansion statistics filter null; 106 can ignore even non-null values if a protected key exists. All merges are shallow. Timestamps/messageId do not order or deduplicate incoming updates. No freshness guard prevents a cached measurement from outranking a new source.

## All outbound action paths

| Publish site | Callers | Cadence / constraints |
| --- | --- | --- |
| `async_control_main_device`, `sensor.py:1969` | Main/optimistic/follow-meter switch actions; number setter; standby/work-mode selects; reboot button | Type=1/cmd=5 as above. Returns without error when no host SN; controls have no centralized capability check. |
| `async_control_subdevice_switch`, `sensor.py:1939` | Plug turn_on/turn_off/toggle after entity commMode check | Type=103 with child deviceSn/devType/sysSwitch. Coordinator itself does not enforce mode. |
| `_send_poll_requests`, `sensor.py:2232` (four publish call sites) | `_periodic_data_request` | Type=25,2 each cycle;105 every third;100 loop [2,3,6], each followed by 0.5s sleep. Loop waits REQUEST_INTERVAL=10s **after** request work, so nominal cadence includes 1.5s plus publish time. |

Startup waits 2 seconds, sends one initial batch, then enters the loop and sends another batch before its first 10-second sleep. Initial request lies outside loop exception handling. O sends an immediate initial batch, sleeps 2 seconds, then loops with REQUEST_INTERVAL=5 and no child pacing; it polls category 2 and 6 only and type105 every cycle (`O sensor.py:1839`). No independent outbound `/action` path exists in other production modules (repository-wide search verified).

## Unresolved protocol questions

Does type101 mean authoritative membership or partial category report on each firmware? How should totals of zero interact with contradictory phase data? Are type106 protected fields genuinely stale, and for how long? Which type23 SN forms occur per model? Is cmd107 an acknowledgement, telemetry echo, or both? Are messageId/eventId reliable correlation keys? How should HTO subtype labels vary by devType? No speculative outbound commands should be created to answer these questions in this phase.
