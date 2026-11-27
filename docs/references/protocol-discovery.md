# Protocol Discovery contract

Protocol Discovery is a passive, opt-in observer for accepted MQTT messages
from the configured SolarVault host. It sends no requests or controls. Normal
status/event parsing continues independently of whether the observer is enabled.

## What counts as known

A known field is a field name accepted by the discovery checker in one specific
message/device context. It does not mean that Home Assistant creates an entity
for it. Entity exposure remains defined by the platform files and
`entities/sensor_definitions.py`.

The checker uses the message type, supported `cmd` where established, and child
family to choose its field set. It does not use one payload allowlist for every
message. A field accepted in Type 2 can therefore still be reported if it
appears in Type 23 or in an unrelated child family.
Child-list containers such as `plugs`, `cts`, and `collectors` are accepted
only in Type 101/102 contexts; they do not become common host fields.

Envelope checks are separate. When present, `type` must be an integer and
`body` must be an object. Missing fields are not treated as errors; partial and
incremental messages are valid. No value is required merely because it appears
in a field inventory.

## Context field inventory

The tables group fields with the same expected JSON type. Numeric readings
accept JSON integers or numbers. Status, mode, command and device identifiers
expect integers. String and container types are checked only where the
repository or the protocol reference establishes them.

| Message/context | Device scope | Expected JSON type | Known fields | Evidence and decision |
| --- | --- | --- | --- | --- |
| Envelope | Host message | `integer` / `object` | `type`; `body` | Implemented routing contract in `protocol/routing.py`; envelope metadata also includes `eventId`, `messageId`, `ts`, `deviceType`, `token`, and `softver`. Only `type` and `body` have structural type checks. |
| Type 2, `cmd` absent or `cmd=106` | Host status | `integer` or `number` | `batSoc`, `soc`, `batInPw`, `batOutPw`, `cellTemp`, `batNum`, `batState`, `pvPw`, `inOngridPw`, `outOngridPw`, `maxOutPw`, `maxFeedGrid`, `maxInvStdPw`, `maxGridStdPw`, `swEpsInPw`, `swEpsOutPw`, `swEpsState`, `swEps`, `stackInPw`, `stackOutPw`, `socChgLimit`, `socDischgLimit`, `socForceChg`, `autoStandby`, `isAutoStandby`, `ethPort`, `wsig`, `ability`, `maxIotNum`, `stat`, `workMode`, `workModel`, `ongridStat`, `ctStat`, `gridSate`, `otherLoadPw`, `inCtEgy`, `outCtEgy`, `maxCellTemp`, `minCellTemp`, `maxCellVolt`, `minCellVolt`, `stackChgCurLimit`, `stackDischgCurLimit`, `emsChgCurLimit`, `emsDischgCurLimit`, `pcsSetPw` | Category C for the original set. Category A for the nine appended names: the sanitized 3.0.1 replay observed each as a JSON integer in all five Type-2 `cmd=106` samples. Their exact semantic roles, units and ranges remain unverified. Missing `cmd` remains valid for partial status updates. |
| Type 2, `cmd=107` | Host write acknowledgement | `integer` or `number` | Writable status fields: `socChgLimit`, `socDischgLimit`, `maxOutPw`, `maxFeedGrid`, `autoStandby`, `isAutoStandby`, `swEps`, `socForceChg`, `reboot`, `workModel`, `defaultPw`, `isFollowMeterPw`, `offGridDown` | Category C: RE §7.6.8 documents the Type-1 write acknowledgement as Type 2 / `cmd=107` and lists acknowledged parameters. This narrow context does not inherit every Type-2 status field. |
| Type 2, `cmd` absent or `cmd=106` | Host status | `string` | `wname`, `eip`, `emac`, `wip` | Category C: RE §7.6.3.7 and existing network status handling. |
| Type 2, `cmd` absent or `cmd=106` | Host status | `object` | `pv1`, `pv2`, `pv3`, `pv4` | Category C: RE §7.6.3.2 documents each PV string as an object containing `pvPw` and `commState`. Those nested keys are checked too. A scalar in place of this object is a type mismatch. |
| Type 106, `cmd` absent or `cmd=120` | Host full state | Type-2 status fields established independently plus numeric fields | Established Type-2 status fields, plus `gridInPw`, `gridOutPw`, `gridBuyPw`, `gridSellPw`, `inGridSidePw`, `outGridSidePw`, `defaultPw`, `energyPlanPw`, `isFollowMeterPw`, `offGridDown`, `offGridTime`, `standbyPw`, `pvMaxChgPower`, `maxSysOutPw`, `maxSysInPw`, `chargePlanPw`, `wps`, `wpc`, `funcEnable` | Category C for the implemented set. The nine replay-only Type-2 additions are not inherited without Type-106 evidence. `chargePlanPw` also appears in all five replayed Type-106 samples. Missing `cmd` is accepted for partial state updates. |
| Type 106, `cmd` absent or `cmd=120` | Host full state | `integer` | `tempUnit` | Category A: observed as an integer in all five sanitized Type-106 samples. The field's meaning and enum/range remain unverified. |
| Type 23 | Host energy statistics | `integer` or `number` | `pvEgy`, `pv1Egy`, `pv2Egy`, `pv3Egy`, `pv4Egy`, `batChgEgy`, `batDisChgEgy`, `inOngridEgy`, `outOngridEgy`, `inEpsEgy`, `outEpsEgy`, `pvOtBatEgy`, `pvOtAcEgy`, `pvOtOngridEgy`, `ongridOtAcLoadEgy`, `batOtAcEgy`, `batOtGridEgy`, `ongridOtBatEgy`, `acOtBatEgy`, `acOtOngridEgy` | Category B: HA energy definitions plus the historical Type-23 host observation in RE §7.6.4.1; no raw packet is checked in here. |
| Type 23 | BP2500, `devType=1`, `subType=0` | `integer` or `number` | `inEgy`, `outEgy` | Category A: these are existing expansion-energy entities and are named in the supplied 3.0.1 live diagnosis as the same two fields counted on both observer paths. RE §7.6.4.3 documents their meaning. They are now checked once on `expansion_item`. |
| Type 23 | SmartMeter, `devType=3`, `subType=5` | `integer` or `number` | `tPhaseEgy`, `tnPhaseEgy`, `aPhaseEgy`, `bPhaseEgy`, `cPhaseEgy`, `anPhaseEgy`, `bnPhaseEgy`, `cnPhaseEgy` | Category C: RE §7.6.4.2 and existing child sensor definitions. Type-101 real-time power fields are not accepted in this Type-23 energy context. |
| Type 101 | Host child lists | `array` | `plugs`, `plug`, `socket`, `sockets`, `cts`, `ct`, `collectors` | Existing MQTT routing and child-discovery containers. Each list item is checked separately using its family. |
| Type 101 child | Smart Plug, `devType=6` (or inferred from the plug list) | `integer` or `number` | `switchSta`, `sysSwitch`, `totalEgy`, `inPw`, `outPw`, `power` | Category C: existing switch/entity mappings and classification contract. Common child identity and communication fields also apply. |
| Type 101 child | CT/SmartMeter supported subtype | `integer` or `number` | `phasePw`, `phaseEgy`, `aPhasePw`, `bPhasePw`, `cPhasePw`, `tPhasePw`, `anPhasePw`, `bnPhasePw`, `cnPhasePw`, `tnPhasePw`, uppercase phase aliases, corresponding `*PhaseEgy` fields, `inPw`, `outPw` | Category C: child sensor definitions and RE field tables. Meter-specific fields are not accepted for an unrecognized subtype merely because the generic device classifier has a fallback. |
| Type 101 child | HTO910A collector, `devType=4`, `subType=7` | `integer` or `number` | `inPw`, `outPw` | Category A: `sensor_definitions.py` identifies these fields as confirmed by the live MQTT capture for Issue 19 (2026-07-24); the same fields are implemented as collector sensors. |
| Child identity/common | Supported child item | `string` / `integer` | `deviceSn`, `sn`, `softver`, `name`, `scanName`; `devType`, `subType`, `commMode`, `commState` | Category C: current classification, diagnostics and child entity code. The serial and names are examined in memory only; structural state never stores their values. |

The replay establishes the nine added Type-2 names in the observed `type=2`,
`cmd=106` context, but does not establish their full semantics, units, ranges,
model coverage, or whether they are writable. Static firmware evidence in
`solarvault-re-ng/docs/firmware-1.5-to-1.6-analysis.md` remains unresolved on
those points. `tempUnit` is accepted only in the Type-106 state context; its
integer shape is observed, while its meaning/value mapping is not established.
These discovery contracts do not create or imply HA entities.

### Real-capture replay (2026-11-27)

The maintainer supplied a sanitized, name-level export from integration 3.0.1.
All 17 Base64 payloads decoded as JSON and were replayed offline through the
3.0.1 release implementation (`b969131`) and the optimized implementation.
The replay topic was reconstructed with the fixture's `replay_topic_prefix` and
`replay_host_sn`; no broker was contacted. The capture was not copied into the
repository.

| Context | Samples | 3.0.1 findings | Optimized before replay correction | Final after evidence update | Cause |
| --- | ---: | ---: | ---: | ---: | --- |
| Type 2 / `cmd=106` | 5 | 5 | 5 | 0 | Nine live fields (`maxCellTemp`, `minCellTemp`, `maxCellVolt`, `minCellVolt`, `stackChgCurLimit`, `stackDischgCurLimit`, `emsChgCurLimit`, `emsDischgCurLimit`, `pcsSetPw`) were absent from the context contract. Each sample grouped them into one structural finding. |
| Type 106 / `cmd=120` | 5 | 5 | 5 | 0 | `tempUnit` was absent from the context contract. `chargePlanPw` was already known and produced no finding. |
| Type 23 / BP2500 (`devType=1`, `subType=0`) | 7 | 14 | 0 | 0 | The 3.0.1 logic reported the same `inEgy`/`outEgy` pair on both generic payload and expansion-item paths (two findings per sample). The optimized child-family route recognizes them once. |
| **Total** | **17** | **24** | **10** | **0** | All 10 optimized pre-correction findings came from the two repeated field groups above; no actual unknown command, message type, or JSON type mismatch occurred. |

The nine Type-2 fields and `tempUnit` were present in every sample of their
respective contexts, so they are live-observed structural fields even though
their domain semantics remain open. `chargePlanPw` was also present in all five
Type-106 samples and was already covered. The capture contains no Type-23 host
or Type-101 SmartMeter sample; those contexts are not real-capture verified.
The 17-event export is a subset of 93 stored samples (76 omitted), from one
sanitized host, so it does not establish device/model-wide prevalence.

### Evidence limits

Evidence labels follow the project's RE vocabulary:

* **A — implemented and live evidenced:** implementation plus an identified
  live payload source. The 2026-11-27 sanitized replay provides name-level
  evidence for the nine Type-2 fields, Type-106 `tempUnit` and
  Type-23/BP2500 `inEgy`/`outEgy`; collector power fields have the Issue 19
  capture note in code. This is structural/context evidence, not full semantic
  or model-coverage evidence.
* **B — protocol known and live evidenced:** the RE report records historical
  Type-23 host observation, but its raw packet is not present in this checkout.
* **C — static evidence:** current HA code or checked-in protocol tables
  identify the field and context, without field-level live evidence. C fields
  are included only where the existing integration already consumes them or
  the protocol reference assigns them to the exact context.
* **D — unconfirmed:** not used as a known field.

The live 3.0.1 export supplied for this task reports aggregate signature shapes,
not field names. Therefore no field outside the names directly supplied or
the checked-in live-capture code comment is promoted to category A solely from
that aggregate count.

## Type mismatches and new structures

Known keys are still checked when the evidence supports a JSON type. For
example, `soc` accepts an integer or number in Type 2 `cmd=106`; `cmd`,
`devType`, and `subType` are integer identifiers; envelope `body` is an object;
and Type-2 `pv1` is an object. A mismatch creates a structural finding. No
required-key checks are made, so optional and incremental omissions are quiet.

Child fields are scoped by family and subtype. A generic fallback for a known
`devType` does not make every subtype payload known: when the subtype has no
specific field contract, only common child metadata is accepted and unfamiliar
family fields remain visible as structural findings. Completely unknown
numeric device pairs retain their existing bounded `unknown_device_type`
records.

The observer walks Type-101/102 child arrays and the known Type-2 PV objects.
Unknown nested keys and unexpected value types remain detectable. Array/object
limits and structural traversal limits are unchanged.

Command identifiers are tracked only in documented command/response
namespaces: Type 2 (`106` status response to Type 25, and `107` write
acknowledgement), Type 101 (`110` response to Type 100), and Type 106 (`120`
response to Type 105). These mappings are listed in RE §§7.6.2, 7.6.8, and
21.4; the supplied live diagnosis also names Type 2 `cmd=106` and Type 106
`cmd=120`. No inner command contract is established for Type 23, so its `cmd`
field is not classified against an invented allowlist. Missing `cmd` is
allowed. For Type 2 and Type 106, its absence uses the message's established
status field set; an unsupported or malformed command does not. An integer
command outside a tracked context's set is recorded as `unknown_command`, with
bounded numeric message/command IDs and occurrence ages. It does not make a
field known in another context.

## Persistence, reset, and capture

`DISCOVERY_VERSION` is now `2` because the bounded state adds unknown-command
buckets and context-owned paths. Version-1 discovery summaries migrate without
reclassifying or deleting old structural signatures: old signatures do not
contain field names, so they cannot be reevaluated under the new contracts.
The next save uses version 2. `PROTOCOL_CAPTURE_VERSION` remains `1`: the raw
event format, sampling, ring buffer, host binding, privacy rules, and storage
budgets did not change. Version-1 capture stores remain loadable through the
discovery-state migration.

To start a fresh observation period, open the Jackery integration's options,
turn off **Protocol discovery**, submit the change, then enable it again. The
disable/unload path deletes both the structural state and raw samples. The
re-enabled observer starts with empty counters and sampling buckets. Merely
updating the integration or restarting Home Assistant preserves existing
records.

The 100-event ring buffer, payload byte limit, signature sampling cadence,
host-fingerprint binding, topic filter, privacy warning, 8-KiB summary budget,
and raw-export size limits are unchanged. Known messages produce no raw sample;
new fields, mismatches, unsupported message/device identifiers, unknown
commands, and malformed envelopes still use the passive capture path.

## Maintainer sources

* HA field handling: `entities/sensor_definitions.py`, `number.py`,
  `switch.py`, `select.py`, `protocol/routing.py`, and `sensor.py`.
* Discovery and persistence: `protocol_discovery.py` and `protocol_capture.py`.
* Regression contract: `tests/test_protocol_discovery.py` and
  `tests/test_protocol_capture.py`.
* Static/historical RE field tables: local
  `solarvault-re-ng/docs/SolarVault Reverse Engineering.md`, §§7.6.3–7.6.5;
  scope and evidence limits: `solarvault-re-ng/protocols/mqtt/README.md`.
