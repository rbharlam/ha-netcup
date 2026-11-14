"""Binary sensors for netcup SCP servers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import NetcupConfigEntry, NetcupCoordinator, ServerData
from .entity import NetcupEntity, async_setup_server_entities

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class NetcupBinarySensorDescription(BinarySensorEntityDescription):
    """Describes a netcup server binary sensor."""

    value_fn: Callable[[ServerData], bool | None]


def _restart_required(server: ServerData) -> bool | None:
    live = server.live
    if not live:
        return None
    return bool(live.get("configChanged")) or live.get("latestQemu") is False


def _storage_optimization(server: ServerData) -> bool | None:
    value = server.live.get("requiredStorageOptimization")
    return None if value is None else value != "NO"


BINARY_SENSORS: tuple[NetcupBinarySensorDescription, ...] = (
    NetcupBinarySensorDescription(
        key="rescue_system",
        translation_key="rescue_system",
        value_fn=lambda s: s.info.get("rescueSystemActive"),
    ),
    NetcupBinarySensorDescription(
        key="restart_required",
        translation_key="restart_required",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=_restart_required,
    ),
    NetcupBinarySensorDescription(
        key="traffic_throttled",
        translation_key="traffic_throttled",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda s: any(
            i.get("trafficThrottled") for i in s.live.get("interfaces") or []
        ),
    ),
    NetcupBinarySensorDescription(
        key="storage_optimization",
        translation_key="storage_optimization",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_storage_optimization,
    ),
    NetcupBinarySensorDescription(
        key="guest_agent",
        translation_key="guest_agent",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.guest is not None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NetcupConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up binary sensors."""

    def factory(
        coordinator: NetcupCoordinator, server_id: int
    ) -> list[NetcupBinarySensor]:
        return [NetcupBinarySensor(coordinator, server_id, d) for d in BINARY_SENSORS]

    async_setup_server_entities(entry, async_add_entities, factory)


class NetcupBinarySensor(NetcupEntity, BinarySensorEntity):
    """A netcup server binary sensor."""

    entity_description: NetcupBinarySensorDescription

    @property
    def is_on(self) -> bool | None:
        """Return the sensor state."""
        return self.entity_description.value_fn(self.server)
