"""Setup, entity and action tests."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID, STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.netcup_scp.api import API_URL, AUTH_URL
from custom_components.netcup_scp.const import CONF_REFRESH_TOKEN, DOMAIN
from custom_components.netcup_scp.coordinator import latest_sample, parse_metrics
from custom_components.netcup_scp.diagnostics import async_get_config_entry_diagnostics

from .conftest import FIXTURES


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _state(hass: HomeAssistant, entity_id: str) -> str:
    state = hass.states.get(entity_id)
    assert state is not None, entity_id
    return state.state


async def test_setup_and_entities(
    hass: HomeAssistant, mock_api: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    """Servers become devices with sensors."""
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED

    devices = dr.async_entries_for_config_entry(
        dr.async_get(hass), config_entry.entry_id
    )
    assert {d.name for d in devices} == {"web", "backup"}
    web = next(d for d in devices if d.name == "web")
    assert web.model == "RS 200 G11"
    assert web.serial_number == "v1001"

    assert _state(hass, "sensor.web_state") == "running"
    assert _state(hass, "sensor.backup_state") == "shutoff"
    assert float(_state(hass, "sensor.web_cpu_usage")) == 0.4
    assert float(_state(hass, "sensor.web_root_filesystem_usage")) == 25.0
    assert _state(hass, "sensor.web_operating_system") == "NixOS 26.05 (Yarara)"
    assert _state(hass, "sensor.web_ipv4_address") == "192.0.2.10"
    assert _state(hass, "sensor.web_snapshots") == "1"
    assert _state(hass, "switch.web_power") == STATE_ON
    assert _state(hass, "switch.backup_power") == STATE_OFF
    assert _state(hass, "binary_sensor.web_guest_agent") == STATE_ON
    assert _state(hass, "binary_sensor.backup_guest_agent") == STATE_OFF
    assert _state(hass, "binary_sensor.web_restart_required") == STATE_OFF
    # Stopped servers report no throughput instead of stale values
    assert float(_state(hass, "sensor.backup_cpu_usage")) == 0.0
    # Rates are stored in B/s
    entity = er.async_get(hass).async_get("sensor.web_network_in")
    assert entity is not None
    assert (
        hass.states.get("sensor.web_network_in").attributes["unit_of_measurement"]
        == "kbit/s"
    )

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.NOT_LOADED


async def test_power_actions(
    hass: HomeAssistant, mock_api: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    """Switches and buttons patch the server."""
    await _setup(hass, config_entry)

    await hass.services.async_call(
        "switch", "turn_off", {ATTR_ENTITY_ID: "switch.web_power"}, blocking=True
    )
    _, url, data, headers = next(c for c in mock_api.mock_calls if c[0] == "PATCH")
    assert str(url) == f"{API_URL}/servers/1001"
    assert data == {"state": "OFF"}
    assert headers["Content-Type"] == "application/merge-patch+json"
    # Optimistic until the server actually stopped
    assert _state(hass, "switch.web_power") == STATE_OFF

    mock_api.mock_calls.clear()
    await hass.services.async_call(
        "button", "press", {ATTR_ENTITY_ID: "button.web_reset"}, blocking=True
    )
    _, url, data, _ = next(c for c in mock_api.mock_calls if c[0] == "PATCH")
    assert url.query["stateOption"] == "RESET"
    assert data == {"state": "ON"}


async def test_auth_failure_starts_reauth(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """An invalid refresh token triggers re-authentication."""
    aioclient_mock.post(
        f"{AUTH_URL}/token", status=400, json={"error": "invalid_grant"}
    )
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert [f["context"]["source"] for f in flows] == ["reauth"]


async def test_api_down_retries(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """Server errors postpone setup."""
    aioclient_mock.post(
        f"{AUTH_URL}/token", json={"access_token": "a", "expires_in": 300}
    )
    aioclient_mock.get(f"{API_URL}/servers", status=503)
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_token_rotation_persisted(
    hass: HomeAssistant, mock_api: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    """A rotated refresh token is stored in the entry."""
    mock_api.clear_requests()
    mock_api.post(
        f"{AUTH_URL}/token",
        json={"access_token": "a", "expires_in": 300, "refresh_token": "refresh-2"},
    )
    mock_api.get(f"{API_URL}/servers", json=[])
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED
    assert config_entry.data[CONF_REFRESH_TOKEN] == "refresh-2"


async def test_removed_server_device_is_removed(
    hass: HomeAssistant, mock_api: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    """Devices of deleted servers are cleaned up."""
    await _setup(hass, config_entry)
    mock_api.clear_requests()
    mock_api.post(f"{AUTH_URL}/token", json={"access_token": "a", "expires_in": 300})
    mock_api.get(f"{API_URL}/servers", json=FIXTURES["servers"][1:])
    mock_api.get(f"{API_URL}/servers/1002", json=FIXTURES["server_1002"])
    await config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    registry = dr.async_get(hass)
    assert (
        registry.async_get_device_by_identifier((DOMAIN, "1001"), config_entry.entry_id)
        is None
    )
    assert (
        registry.async_get_device_by_identifier((DOMAIN, "1002"), config_entry.entry_id)
        is not None
    )


async def test_diagnostics_redacted(
    hass: HomeAssistant, mock_api: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    """Diagnostics do not leak tokens or addresses."""
    await _setup(hass, config_entry)
    diag = await async_get_config_entry_diagnostics(hass, config_entry)
    text = str(diag)
    assert "refresh-1" not in text
    assert "192.0.2.10" not in text
    assert "02:00:00:00:00:00" not in text


def test_parse_metrics() -> None:
    """The partial newest bucket is ignored and devices are summed."""
    assert latest_sample({"a": {"x": 1.0}}) is None
    metrics = parse_metrics(
        FIXTURES["cpu"], FIXTURES["network"], FIXTURES["packets"], FIXTURES["disk"]
    )
    assert metrics == {
        "cpu": 0.4,
        "net_in": 200.0,
        "net_out": 12.0,
        "packets_in": 2.5,
        "packets_out": 0.25,
        "disk_read": 0.0,
        "disk_write": 0.05,
    }
    assert parse_metrics({}, None, "error", {}) == {}


async def test_rename_updates_device_without_duplicates(
    hass: HomeAssistant, mock_api: AiohttpClientMocker, config_entry: MockConfigEntry
) -> None:
    """Renaming a server in the SCP renames the device and keeps its entities."""
    await _setup(hass, config_entry)
    ent_reg = er.async_get(hass)
    before = {
        e.unique_id: e.entity_id
        for e in er.async_entries_for_config_entry(ent_reg, config_entry.entry_id)
    }

    renamed = {**FIXTURES["server_1001"], "nickname": "api"}
    mock_api.clear_requests()
    mock_api.post(f"{AUTH_URL}/token", json={"access_token": "a", "expires_in": 300})
    mock_api.get(
        f"{API_URL}/servers",
        json=[{**FIXTURES["servers"][0], "nickname": "api"}, FIXTURES["servers"][1]],
    )
    mock_api.get(f"{API_URL}/servers/1001", json=renamed)
    mock_api.get(f"{API_URL}/servers/1002", json=FIXTURES["server_1002"])
    await config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, "1001"), config_entry.entry_id
    )
    assert device is not None
    assert device.name == "api"
    after = {
        e.unique_id: e.entity_id
        for e in er.async_entries_for_config_entry(ent_reg, config_entry.entry_id)
    }
    assert after == before
    assert (
        len(
            dr.async_entries_for_config_entry(dr.async_get(hass), config_entry.entry_id)
        )
        == 2
    )
