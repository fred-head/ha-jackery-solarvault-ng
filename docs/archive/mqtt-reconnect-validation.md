# MQTT disconnect and reconnect validation

## Scope

This report records focused lifecycle evidence from foundation
`c764e20c81ae45fe4f1f9233d9e568c0ce2dda14` using Home Assistant 2026.2.3.
It tests the boundary between Home Assistant's MQTT integration and SolarVault
NG; it does not add an MQTT client or reconnect mechanism to SolarVault NG.

The automated evidence is **[TEST-VERIFIED]** fault injection. The test harness
keeps Home Assistant-level subscription registrations alive while disabling
message delivery and making publishes fail, then restores delivery without
reloading the Jackery entry. No local broker binary or existing broker-test
dependency was available, so this report does not claim **[LOCAL BROKER
VERIFIED]** or hardware validation.

## Ownership contract

Home Assistant owns the broker client, socket connection, reconnect loop and
broker resubscription. In Home Assistant 2026.2.3:

- `mqtt.async_subscribe()` registers the callback with the HA MQTT client and
  returns a cleanup callback;
- the disconnect callback changes HA's connection state without deleting the
  registered callback;
- the connect callback queues every tracked subscription for resubscription;
- `mqtt.async_publish()` reports unsuccessful publication through the HA MQTT
  boundary.

This contract was checked against the installed package and the corresponding
[Home Assistant MQTT client implementation](https://github.com/home-assistant/core/blob/2026.2.3/homeassistant/components/mqtt/client.py).

SolarVault NG owns only its entry-scoped use of that API. Its MQTT transport
keeps two cleanup handles, releases them on stop, and delegates publish and
subscribe operations to HA. Coordinator `_subscribed` therefore means that the
runtime registered its logical HA subscriptions; it is not broker-socket state.
NG must not add a second reconnect or resubscribe loop.

## Scenario evidence

| Scenario | Expected | Observed | Evidence |
| --- | --- | --- | --- |
| Short disconnect | Keep one coordinator and its logical subscriptions; resume one delivery per message after reconnect. | Five disconnect/reconnect cycles kept the same coordinator, poll/HTTP tasks and two handles. Each post-reconnect message was delivered once. | **[TEST-VERIFIED]** |
| Outage beyond `OFFLINE_TIMEOUT` | Preserve entities, expire MQTT-owned availability, and recover only from new accepted evidence. | Host and child entities remained registered and became unavailable. New host telemetry restored the host only; later child telemetry restored that child. | **[TEST-VERIFIED]** |
| Poll publish failure | A failed cycle must not kill the periodic poll task; later cycles must publish again. | Every disconnected publish attempt failed at the synthetic HA boundary and was contained by the existing per-request handling. The same poll task remained active and the next cycle published after reconnect. | **[TEST-VERIFIED]** |
| HTTP independence | MQTT loss must not stop or invalidate healthy HTTP-owned data. | Three HTTP updates remained available during MQTT loss, the existing HTTP task stayed active, and MQTT delivery later resumed without creating another HTTP task. | **[TEST-VERIFIED]** |
| Multi-entry | Preserve one isolated runtime per entry and route by host/topic after reconnect. | Both coordinators and their tasks survived a shared disconnect. Host A and B each received only their own post-reconnect telemetry. | **[TEST-VERIFIED]** |
| Options reload while disconnected | Stop old runtime and prevent its callback from returning after reconnect. | The old handles were removed once; only the replacement coordinator on the changed topic root received telemetry. | **[TEST-VERIFIED]** |
| Reauth reload overlap | A reauth replacement must leave the old callback inert after reconnect. | Token update/reload stopped the original runtime; later telemetry reached only the new coordinator. | **[TEST-VERIFIED]** |
| Startup silence | Preserve the documented heuristic without claiming that silence proves a bad token. | The existing timeout regression confirms one reauth hint when no host message arrives; NG has no separate broker-state input in that decision. | **[TEST-VERIFIED]** contract; root cause **[OPEN]** |
| Repeated-cycle cleanup | Handle count and task count must remain bounded, and unload must release every owned handle once. | Reconnect did not register new NG subscriptions or tasks. Final unload removed both handles exactly once. | **[TEST-VERIFIED]** |

## Availability and recovery

A brief broker outage does not itself mutate cached values or create a new
coordinator. When accepted messages stop for longer than the existing freshness
window, normal host and per-child evidence expiry makes MQTT-owned entities
unavailable. Cache presence alone does not restore availability. New valid host
telemetry restores host-owned entities, while a child remains unavailable until
new evidence for that child arrives.

SmartMeter HTTP health remains separate. Healthy HTTP observations continue to
update HTTP-owned sensors while MQTT delivery is absent; MQTT recovery does not
replace or duplicate the HTTP polling task.

## Startup silence heuristic

The existing reauthentication hint remains deliberately heuristic. A broker or
network outage immediately after setup can produce the same observable state as
an invalid token or host serial: no valid host response before
`REAUTH_HINT_TIMEOUT`. The coordinator does not own a stable, entry-scoped
broker-connection contract from HA and therefore does not reinterpret that
silence in this change. A silence-triggered reauth dialog must continue to be
understood as an authentication hint rather than proof of token rejection.

## Result

No SolarVault NG production defect was reproduced. Production code is unchanged.
The evidence supports relying on Home Assistant's reconnect and resubscription
ownership while retaining NG's existing freshness, polling, cleanup and
multi-entry contracts.

## Remaining evidence gap

Real broker and device behavior remains **[OPEN]**. A later soak should use a
supported HA/MQTT configuration and a SolarVault device to cover repeated broker
restart, network interruption, retained-message behavior, long outages, later
unload/reload and multi-day task/handle stability. It should record callback
counts and resource ownership without adding private payloads or credentials to
the repository. Broker connection state in diagnostics is also a separate
contract and privacy decision, not part of this validation.
