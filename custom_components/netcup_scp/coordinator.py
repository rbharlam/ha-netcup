"""Data update coordinator for netcup SCP."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import NetcupAuthError, NetcupClient, NetcupError
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

type NetcupConfigEntry = ConfigEntry[NetcupCoordinator]

# Limit concurrent requests so large accounts don't hammer the API.
_MAX_PARALLEL = 4


@dataclass(slots=True)
class ServerData:
    """Snapshot of one server."""

    info: dict[str, Any]
    metrics: dict[str, float] = field(default_factory=dict)
    guest: dict[str, Any] | None = None

    @property
    def live(self) -> dict[str, Any]:
        """Live info reported by the hypervisor (empty if unavailable)."""
        return self.info.get("serverLiveInfo") or {}

    @property
    def state(self) -> str | None:
        """Hypervisor state, e.g. RUNNING or SHUTOFF."""
        return self.live.get("state")

    @property
    def name(self) -> str:
        """Display name: nickname, falling back to the server name."""
        return self.info.get("nickname") or self.info["name"]


def latest_sample(
    series: dict[str, dict[str, float]] | None,
) -> dict[str, float] | None:
    """Return the most recent complete sample of a metric series.

    The newest bucket is the still-running minute and always reads 0, so the
    second newest one is used.
    """
    if not series or len(series) < 2:
        return None
    return series[sorted(series)[-2]]


def parse_metrics(cpu: Any, network: Any, packets: Any, disk: Any) -> dict[str, float]:
    """Reduce SCP metric series to current values.

    cpu:      {"CPU0": ns of CPU time per second}
    network:  {"<mac> IN|OUT": bytes per second}
    packets:  {"<mac> IN|OUT": packets per second}
    disk:     {"<dev> Read|Write": operations per second}
    """
    result: dict[str, float] = {}

    def total(sample: dict[str, float], suffix: str) -> float:
        return sum(v for k, v in sample.items() if k.endswith(f" {suffix}"))

    if isinstance(cpu, dict) and (sample := latest_sample(cpu)):
        result["cpu"] = sum(sample.values()) / len(sample) / 1e7  # ns/s -> %
    if isinstance(network, dict) and (sample := latest_sample(network)):
        result["net_in"] = total(sample, "IN")
        result["net_out"] = total(sample, "OUT")
    if isinstance(packets, dict) and (sample := latest_sample(packets)):
        result["packets_in"] = total(sample, "IN")
        result["packets_out"] = total(sample, "OUT")
    if isinstance(disk, dict) and (sample := latest_sample(disk)):
        result["disk_read"] = total(sample, "Read")
        result["disk_write"] = total(sample, "Write")
    return result


class NetcupCoordinator(DataUpdateCoordinator[dict[int, ServerData]]):
    """Polls all servers of one SCP account."""

    config_entry: NetcupConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: NetcupConfigEntry,
        client: NetcupClient,
        update_interval: timedelta,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=update_interval,
        )
        self.client = client
        self._semaphore = asyncio.Semaphore(_MAX_PARALLEL)

    async def _limited(self, coro: Any) -> Any:
        async with self._semaphore:
            return await coro

    async def _fetch_server(self, server_id: int) -> ServerData:
        info = await self._limited(self.client.get_server(server_id))
        data = ServerData(info=info)
        if data.state != "RUNNING":
            return data

        base = f"/servers/{server_id}"
        cpu, network, packets, disk, guest = await asyncio.gather(
            self._limited(self.client.get(f"{base}/metrics/cpu", params={"hours": 1})),
            self._limited(
                self.client.get(f"{base}/metrics/network", params={"hours": 1})
            ),
            self._limited(
                self.client.get(f"{base}/metrics/network/packet", params={"hours": 1})
            ),
            self._limited(self.client.get(f"{base}/metrics/disk", params={"hours": 1})),
            self._limited(self.client.get(f"{base}/guest-agent")),
            return_exceptions=True,
        )
        for result in (cpu, network, packets, disk, guest):
            if isinstance(result, NetcupAuthError):
                raise result
            if isinstance(result, BaseException):
                _LOGGER.debug(
                    "Optional data for server %s unavailable: %s", server_id, result
                )
        data.metrics = parse_metrics(cpu, network, packets, disk)
        if isinstance(guest, dict) and guest.get("guestAgentAvailable"):
            data.guest = guest.get("guestAgentData") or {}
        return data

    async def _async_update_data(self) -> dict[int, ServerData]:
        try:
            servers = await self.client.get_servers()
            ids = [server["id"] for server in servers]
            results = await asyncio.gather(
                *(self._fetch_server(i) for i in ids), return_exceptions=True
            )
        except NetcupAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except NetcupError as err:
            raise UpdateFailed(str(err)) from err

        previous = self.data or {}
        data: dict[int, ServerData] = {}
        for server_id, result in zip(ids, results, strict=True):
            if isinstance(result, NetcupAuthError):
                raise ConfigEntryAuthFailed(str(result)) from result
            if isinstance(result, BaseException):
                _LOGGER.warning("Failed to update server %s: %s", server_id, result)
                if server_id in previous:
                    data[server_id] = previous[server_id]
                continue
            data[server_id] = result

        if ids and not data:
            raise UpdateFailed("Failed to update any server")

        self._sync_devices(data, set(ids))
        return data

    def _sync_devices(self, data: dict[int, ServerData], server_ids: set[int]) -> None:
        """Follow renames in the SCP and drop devices of deleted servers."""
        registry = dr.async_get(self.hass)
        for device in dr.async_entries_for_config_entry(
            registry, self.config_entry.entry_id
        ):
            ids = {int(i) for d, i in device.identifiers if d == DOMAIN and i.isdigit()}
            if not ids:
                continue
            if not ids & server_ids:
                registry.async_remove_device(device.id)
                continue
            server = data.get(next(iter(ids)))
            if server is None:
                continue
            model = (server.info.get("template") or {}).get("name")
            if device.name != server.name or device.model != model:
                registry.async_update_device(device.id, name=server.name, model=model)
