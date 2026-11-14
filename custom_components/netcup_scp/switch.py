"""Switches for netcup SCP servers."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import (
    SwitchDeviceClass,
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import NetcupConfigEntry, NetcupCoordinator, ServerData
from .entity import NetcupEntity, async_setup_server_entities
from .helpers import run_action

PARALLEL_UPDATES = 1

# How long a requested power state is assumed while the server boots/shuts down.
_ASSUME_SECONDS = 180


@dataclass(frozen=True, kw_only=True)
class NetcupSwitchDescription(SwitchEntityDescription):
    """Describes a netcup server switch."""

    value_fn: Callable[[ServerData], bool | None]
    patch_fn: Callable[[bool], dict[str, Any]]


SWITCHES: tuple[NetcupSwitchDescription, ...] = (
    NetcupSwitchDescription(
        key="power",
        translation_key="power",
        device_class=SwitchDeviceClass.SWITCH,
        value_fn=lambda s: None if s.state is None else s.state == "RUNNING",
        patch_fn=lambda on: {"state": "ON" if on else "OFF"},
    ),
    NetcupSwitchDescription(
        key="autostart",
        translation_key="autostart",
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda s: s.live.get("autostart"),
        patch_fn=lambda on: {"autostart": on},
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NetcupConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up switches."""

    def factory(coordinator: NetcupCoordinator, server_id: int) -> list[NetcupSwitch]:
        return [NetcupSwitch(coordinator, server_id, d) for d in SWITCHES]

    async_setup_server_entities(entry, async_add_entities, factory)


class NetcupSwitch(NetcupEntity, SwitchEntity):
    """A netcup server switch."""

    entity_description: NetcupSwitchDescription
    _assumed: bool | None = None
    _assumed_until = 0.0

    @property
    def is_on(self) -> bool | None:
        """Return the switch state, bridging the delay of asynchronous SCP tasks."""
        actual = self.entity_description.value_fn(self.server)
        if self._assumed is not None:
            if actual != self._assumed and time.monotonic() < self._assumed_until:
                return self._assumed
            self._assumed = None
        return actual

    async def _async_set(self, on: bool) -> None:
        await run_action(
            self.coordinator, self.server_id, self.entity_description.patch_fn(on)
        )
        self._assumed, self._assumed_until = on, time.monotonic() + _ASSUME_SECONDS
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on."""
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off (graceful ACPI shutdown for power)."""
        await self._async_set(False)
