"""Fixtures for netcup SCP tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.netcup_scp.api import API_URL, AUTH_URL
from custom_components.netcup_scp.const import CONF_REFRESH_TOKEN, DOMAIN

FIXTURES: dict[str, Any] = json.loads(
    (Path(__file__).parent / "fixtures.json").read_text()
)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable custom integrations in all tests."""


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """A configured netcup account."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="netcup 12345",
        unique_id="4242",
        data={CONF_REFRESH_TOKEN: "refresh-1"},
    )


def mock_token(
    aioclient_mock: AiohttpClientMocker, refresh_token: str = "refresh-1"
) -> None:
    """Mock a successful token refresh."""
    aioclient_mock.post(
        f"{AUTH_URL}/token",
        json={
            "access_token": "access",
            "expires_in": 300,
            "refresh_token": refresh_token,
        },
    )


@pytest.fixture
def mock_api(aioclient_mock: AiohttpClientMocker) -> AiohttpClientMocker:
    """Mock the SCP API with one running and one stopped server."""
    mock_token(aioclient_mock)
    aioclient_mock.get(f"{AUTH_URL}/userinfo", json=FIXTURES["userinfo"])
    aioclient_mock.get(f"{API_URL}/servers", json=FIXTURES["servers"])
    for server_id in (1001, 1002):
        aioclient_mock.get(
            f"{API_URL}/servers/{server_id}", json=FIXTURES[f"server_{server_id}"]
        )
    base = f"{API_URL}/servers/1001"
    aioclient_mock.get(f"{base}/metrics/cpu", json=FIXTURES["cpu"])
    aioclient_mock.get(f"{base}/metrics/network", json=FIXTURES["network"])
    aioclient_mock.get(f"{base}/metrics/network/packet", json=FIXTURES["packets"])
    aioclient_mock.get(f"{base}/metrics/disk", json=FIXTURES["disk"])
    aioclient_mock.get(f"{base}/guest-agent", json=FIXTURES["guest_agent"])
    aioclient_mock.patch(base, status=202, json={"uuid": "task", "state": "PENDING"})
    aioclient_mock.post(f"{AUTH_URL}/revoke", status=200)
    return aioclient_mock
