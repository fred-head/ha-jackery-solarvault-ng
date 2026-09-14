"""Direct tests for the SmartMeter HTTP transport boundary."""

from unittest.mock import AsyncMock, Mock

import aiohttp
import pytest

from custom_components.jackery.transport.smartmeter_http import (
    SmartMeterHttpRequestError,
    SmartMeterHttpTransport,
)

MEASUREMENT_KEYS = ("freq", "volt1")


def _transport_response(*, status=200, data=None):
    response = Mock(status=status)
    response.json = AsyncMock(return_value=data)
    request = AsyncMock()
    request.__aenter__.return_value = response
    session = Mock()
    session.get.return_value = request
    return SmartMeterHttpTransport(session), session, response, request


async def test_fetch_measurement_uses_exact_request_contract_and_returns_data():
    data = {"freq": "50", "other": [1, 2]}
    transport, session, response, _ = _transport_response(data=data)

    result = await transport.fetch_measurement("192.0.2.1", MEASUREMENT_KEYS)

    assert result.status == 200
    assert result.data is data
    session.get.assert_called_once()
    assert session.get.call_args.args == ("http://192.0.2.1/api/measurement",)
    assert session.get.call_args.kwargs["timeout"].total == 5
    response.json.assert_awaited_once_with(content_type=None)
    assert data == {"freq": "50", "other": [1, 2]}


@pytest.mark.parametrize(
    "data",
    [None, [], {}, {"freq": None}, {"freq": "bad"}, {"freq": {}}, {"other": 50}],
)
async def test_fetch_measurement_rejects_bodies_without_valid_numeric_measurement(data):
    transport, _, _, _ = _transport_response(data=data)

    result = await transport.fetch_measurement("192.0.2.1", MEASUREMENT_KEYS)

    assert result.status == 200
    assert result.data is None


async def test_fetch_measurement_treats_invalid_json_as_failed_measurement():
    transport, _, response, _ = _transport_response()
    response.json.side_effect = ValueError("invalid JSON")

    result = await transport.fetch_measurement("192.0.2.1", MEASUREMENT_KEYS)

    assert result.status == 200
    assert result.data is None


async def test_fetch_measurement_preserves_non_200_status_without_decoding_body():
    transport, _, response, _ = _transport_response(status=503, data={"freq": 50})

    result = await transport.fetch_measurement("192.0.2.1", MEASUREMENT_KEYS)

    assert result.status == 503
    assert result.data is None
    response.json.assert_not_awaited()


@pytest.mark.parametrize("error", [aiohttp.ClientError("offline"), TimeoutError("slow")])
async def test_fetch_measurement_reports_request_errors(error):
    transport, _, _, request = _transport_response()
    request.__aenter__.side_effect = error

    with pytest.raises(SmartMeterHttpRequestError, match=str(error)):
        await transport.fetch_measurement("192.0.2.1", MEASUREMENT_KEYS)
