"""Diagnostics for netcup SCP."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_REFRESH_TOKEN
from .coordinator import NetcupConfigEntry

TO_REDACT = {
    CONF_REFRESH_TOKEN,
    "hostname",
    "ip",
    "ipv4Addresses",
    "ipv6Addresses",
    "ipv6LinkLocalAddresses",
    "ipv6NetworkPrefixes",
    "networkPrefix",
    "gateway",
    "broadcast",
    "mac",
    "guest",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: NetcupConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    servers = entry.runtime_data.data or {}
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
        "servers": {
            str(server_id): async_redact_data(asdict(server), TO_REDACT)
            for server_id, server in servers.items()
        },
    }
