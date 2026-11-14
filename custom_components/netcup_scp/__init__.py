"""The netcup Server Control Panel integration."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceEntry

from .api import NetcupClient, NetcupError
from .const import CONF_REFRESH_TOKEN, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN
from .coordinator import NetcupConfigEntry, NetcupCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.SENSOR, Platform.SWITCH]


async def async_setup_entry(hass: HomeAssistant, entry: NetcupConfigEntry) -> bool:
    """Set up netcup SCP from a config entry."""

    @callback
    def _store_token(token: str) -> None:
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_REFRESH_TOKEN: token}
        )

    client = NetcupClient(
        async_get_clientsession(hass), entry.data[CONF_REFRESH_TOKEN], _store_token
    )
    interval = entry.options.get(CONF_SCAN_INTERVAL)
    coordinator = NetcupCoordinator(
        hass,
        entry,
        client,
        timedelta(seconds=interval) if interval else DEFAULT_SCAN_INTERVAL,
    )

    entry.runtime_data = coordinator
    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: NetcupConfigEntry) -> None:
    # Token rotation also updates the entry; only reload on option changes.
    coordinator = entry.runtime_data
    interval = timedelta(
        seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL.seconds)
    )
    if coordinator.update_interval != interval:
        await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: NetcupConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: NetcupConfigEntry) -> None:
    """Revoke the refresh token when the integration is removed."""
    client = NetcupClient(async_get_clientsession(hass), entry.data[CONF_REFRESH_TOKEN])
    try:
        await client.revoke()
    except NetcupError as err:
        _LOGGER.warning("Could not revoke netcup refresh token: %s", err)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: NetcupConfigEntry, device: DeviceEntry
) -> bool:
    """Allow removing devices of servers that no longer exist."""
    servers = entry.runtime_data.data or {}
    return not any(
        d == DOMAIN and i.isdigit() and int(i) in servers for d, i in device.identifiers
    )
