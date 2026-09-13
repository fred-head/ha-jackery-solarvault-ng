"""Per-coordinator Home Assistant MQTT transport mechanics."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from homeassistant.components import mqtt as ha_mqtt
from homeassistant.core import CALLBACK_TYPE, HomeAssistant


class JackeryMqttTransport:
    """Own MQTT calls and subscription cleanup for one coordinator."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._unsubscribers: list[CALLBACK_TYPE] = []

    @property
    def unsubscribe_count(self) -> int:
        """Return the number of currently owned subscription handles."""
        return len(self._unsubscribers)

    @property
    def unsubscribers(self) -> list[CALLBACK_TYPE]:
        """Expose the owned handles for the coordinator compatibility view."""
        return self._unsubscribers

    async def async_subscribe(
        self,
        topics: Iterable[str],
        message_callback: Callable[[Any], None],
    ) -> None:
        """Subscribe to each topic and retain each cleanup handle immediately."""
        try:
            for topic in topics:
                unsubscribe = await ha_mqtt.async_subscribe(
                    self.hass,
                    topic,
                    message_callback,
                    1,
                )
                self._unsubscribers.append(unsubscribe)
        except Exception:
            await self.async_stop()
            raise

    async def async_publish(self, topic: str, payload: Mapping[str, Any]) -> None:
        """Serialize and publish one action payload with established options."""
        await ha_mqtt.async_publish(
            self.hass,
            topic,
            json.dumps(payload),
            0,
            False,
        )

    async def async_stop(self) -> None:
        """Attempt every currently owned unsubscribe exactly once."""
        unsubscribers, self._unsubscribers = self._unsubscribers, []
        errors: list[Exception] = []
        for unsubscribe in unsubscribers:
            try:
                unsubscribe()
            except Exception as error:
                errors.append(error)
        if errors:
            raise ExceptionGroup("MQTT subscription cleanup failed", errors)
