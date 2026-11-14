"""Config flow tests."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)

from custom_components.netcup_scp.api import (
    AUTH_URL,
    DeviceCode,
    NetcupAuthError,
    poll_device_token,
)
from custom_components.netcup_scp.const import (
    CONF_REFRESH_TOKEN,
    CONF_SCAN_INTERVAL,
    DOMAIN,
)

from .conftest import FIXTURES, mock_token

DEVICE = {
    "device_code": "dev",
    "user_code": "ABCD-EFGH",
    "verification_uri": "https://example.com/device",
    "verification_uri_complete": "https://example.com/device?user_code=ABCD-EFGH",
    "expires_in": 600,
    "interval": 0,
}


def _mock_login(
    aioclient_mock: AiohttpClientMocker, user_info: dict | None = None
) -> None:
    aioclient_mock.post(f"{AUTH_URL}/auth/device", json=DEVICE)
    mock_token(aioclient_mock, "refresh-new")
    aioclient_mock.get(f"{AUTH_URL}/userinfo", json=user_info or FIXTURES["userinfo"])


async def _run_device_flow(hass: HomeAssistant, result: dict) -> dict:
    assert result["type"] is FlowResultType.SHOW_PROGRESS
    assert result["description_placeholders"]["code"] == "ABCD-EFGH"
    await hass.async_block_till_done()
    return await hass.config_entries.flow.async_configure(result["flow_id"])


async def test_full_flow(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Approving the device code creates an entry."""
    _mock_login(aioclient_mock)
    with patch("custom_components.netcup_scp.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await _run_device_flow(hass, result)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "netcup 12345"
    assert result["data"] == {CONF_REFRESH_TOKEN: "refresh-new"}
    assert result["result"].unique_id == "4242"


async def test_already_configured(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """The same account cannot be added twice."""
    config_entry.add_to_hass(hass)
    _mock_login(aioclient_mock)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await _run_device_flow(hass, result)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_denied_then_retry(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A denied login offers a retry with a fresh code."""
    aioclient_mock.post(f"{AUTH_URL}/auth/device", json=DEVICE)
    aioclient_mock.post(
        f"{AUTH_URL}/token", status=400, json={"error": "access_denied"}
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    await hass.async_block_till_done()
    result = await hass.config_entries.flow.async_configure(result["flow_id"])
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "not_approved"

    aioclient_mock.clear_requests()
    _mock_login(aioclient_mock)
    with patch("custom_components.netcup_scp.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        result = await _run_device_flow(hass, result)
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_cannot_connect(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Failing to start the login aborts."""
    aioclient_mock.post(f"{AUTH_URL}/auth/device", status=503)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"


async def test_reauth(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """Re-authentication stores the new token."""
    config_entry.add_to_hass(hass)
    _mock_login(aioclient_mock)
    result = await config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    with patch("custom_components.netcup_scp.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        result = await _run_device_flow(hass, result)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data[CONF_REFRESH_TOKEN] == "refresh-new"


async def test_reauth_wrong_account(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """Re-authenticating with another account is rejected."""
    config_entry.add_to_hass(hass)
    _mock_login(aioclient_mock, {"id": "9999", "sub": "x"})
    result = await config_entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    result = await _run_device_flow(hass, result)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_account"


async def test_options(hass: HomeAssistant, config_entry: MockConfigEntry) -> None:
    """The update interval can be changed."""
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 120}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options == {CONF_SCAN_INTERVAL: 120}


async def test_poll_handles_pending(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Polling continues while authorization is pending and fails on expiry."""
    responses = iter(
        [
            {"error": "authorization_pending"},
            {"error": "slow_down"},
            {"refresh_token": "rt"},
        ]
    )

    async def _token(method, url, data):
        return AiohttpClientMockResponse(method, url, json=next(responses))

    aioclient_mock.post(f"{AUTH_URL}/token", side_effect=_token)
    session = async_get_clientsession(hass)
    with patch("custom_components.netcup_scp.api.asyncio.sleep"):
        assert (
            await poll_device_token(session, DeviceCode("d", "u", "v", "vc", 600, 0))
            == "rt"
        )

    with pytest.raises(NetcupAuthError, match="expired_token"):
        await poll_device_token(session, DeviceCode("d", "u", "v", "vc", 0, 0))
