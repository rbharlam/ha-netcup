"""Buttons for netcup SCP servers."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.button import (
    ButtonDeviceClass,
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import NetcupConfigEntry, NetcupCoordinator
from .entity import NetcupEntity, async_setup_server_entities
from .helpers import run_action

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class NetcupButtonDescription(ButtonEntityDescription):
    """Describes a netcup server power action."""

    state: str
    option: str


BUTTONS: tuple[NetcupButtonDescription, ...] = (
    NetcupButtonDescription(
        key="power_cycle",
        translation_key="power_cycle",
        device_class=ButtonDeviceClass.RESTART,
        entity_category=EntityCategory.CONFIG,
        state="ON",
        option="POWERCYCLE",
    ),
    NetcupButtonDescription(
        key="reset",
        translation_key="reset",
        device_class=ButtonDeviceClass.RESTART,
        entity_category=EntityCategory.CONFIG,
        state="ON",
        option="RESET",
    ),
    NetcupButtonDescription(
        key="power_off",
        translation_key="power_off",
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        state="OFF",
        option="POWEROFF",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NetcupConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up buttons."""

    def factory(coordinator: NetcupCoordinator, server_id: int) -> list[NetcupButton]:
        return [NetcupButton(coordinator, server_id, d) for d in BUTTONS]

    async_setup_server_entities(entry, async_add_entities, factory)


class NetcupButton(NetcupEntity, ButtonEntity):
    """A netcup server power action."""

    entity_description: NetcupButtonDescription

    async def async_press(self) -> None:
        """Run the power action."""
        d = self.entity_description
        await run_action(self.coordinator, self.server_id, {"state": d.state}, d.option)
