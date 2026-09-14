"""Low-level HTTP transport for SmartMeter measurements."""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import aiohttp


@dataclass(frozen=True, slots=True)
class HttpMeasurementResult:
    """Result of one SmartMeter HTTP request."""

    url: str
    status: int
    data: dict[str, Any] | None


class SmartMeterHttpRequestError(Exception):
    """A handled network or timeout failure while fetching a measurement."""


class SmartMeterHttpTransport:
    """Fetch and validate measurements using an injected shared HTTP session."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        """Initialize the transport with Home Assistant's shared session."""
        self._session = session

    async def fetch_measurement(
        self,
        ip: str,
        measurement_keys: Iterable[str],
    ) -> HttpMeasurementResult:
        """Fetch one response and retain data only when a measurement is numeric."""
        url = f"http://{ip}/api/measurement"
        try:
            async with self._session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=5),
            ) as response:
                if response.status != 200:
                    return HttpMeasurementResult(url, response.status, None)
                try:
                    data = await response.json(content_type=None)
                except ValueError:
                    return HttpMeasurementResult(url, response.status, None)
        except (aiohttp.ClientError, TimeoutError) as error:
            raise SmartMeterHttpRequestError(str(error)) from error

        if not isinstance(data, dict):
            return HttpMeasurementResult(url, response.status, None)
        for key in measurement_keys:
            value = data.get(key)
            if value is None:
                continue
            try:
                float(value)
            except (TypeError, ValueError):
                continue
            return HttpMeasurementResult(url, response.status, data)
        return HttpMeasurementResult(url, response.status, None)
