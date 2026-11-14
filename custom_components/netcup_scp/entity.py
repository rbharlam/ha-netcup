"""Base entity for netcup SCP."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity, EntityDescription
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, SCP_URL
from .coordinator import NetcupConfigEntry, NetcupCoordinator, ServerData


class NetcupEntity(CoordinatorEntity[NetcupCoordinator]):
    """An entity belonging to one netcup server."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: NetcupCoordinator,
        server_id: int,
        description: EntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self.server_id = server_id
        self._attr_unique_id = f"{server_id}_{description.key}"
        info = coordinator.data[server_id].info
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(server_id))},
            name=coordinator.data[server_id].name,
            manufacturer="netcup",
            model=(info.get("template") or {}).get("name"),
            serial_number=info.get("name"),
            configuration_url=SCP_URL,
        )

    @property
    def server(self) -> ServerData:
        """Current data of this entity's server."""
        return self.coordinator.data[self.server_id]

    @property
    def available(self) -> bool:
        """Entity is available while its server is known."""
        return super().available and self.server_id in self.coordinator.data


def async_setup_server_entities(
    entry: NetcupConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    factory: Callable[[NetcupCoordinator, int], Iterable[Entity]],
) -> None:
    """Add entities for every server, including servers added later."""
    coordinator = entry.runtime_data
    known: set[int] = set()

    @callback
    def _add_new() -> None:
        new = coordinator.data.keys() - known
        if new:
            known.update(new)
            async_add_entities(
                e for server_id in new for e in factory(coordinator, server_id)
            )

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))
