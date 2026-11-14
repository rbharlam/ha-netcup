"""Sensors for netcup SCP servers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfDataRate,
    UnitOfInformation,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.util import dt as dt_util

from .coordinator import NetcupConfigEntry, NetcupCoordinator, ServerData
from .entity import NetcupEntity, async_setup_server_entities

PARALLEL_UPDATES = 0

SERVER_STATES = [
    "nostate",
    "running",
    "blocked",
    "paused",
    "shutdown",
    "shutoff",
    "crashed",
    "pmsuspended",
    "disk_snapshot",
]


def _sum_disks(server: ServerData, key: str) -> int | None:
    disks = server.live.get("disks")
    return sum(d.get(key) or 0 for d in disks) if disks else None


def _sum_interfaces(server: ServerData, key: str) -> int | None:
    interfaces = server.live.get("interfaces")
    return sum(i.get(key) or 0 for i in interfaces) if interfaces else None


def _root_fs(server: ServerData) -> tuple[int, int] | None:
    """Return (total, used) bytes of the root filesystem reported by the guest agent."""
    guest = server.guest
    if not guest:
        return None
    count = int(guest.get("fs.count") or 0)
    mounts = [guest.get(f"fs.{i}.mountpoint") for i in range(count)]
    for root in ("/", "C:\\"):
        if root in mounts:
            i = mounts.index(root)
            total, used = (
                guest.get(f"fs.{i}.total-bytes"),
                guest.get(f"fs.{i}.used-bytes"),
            )
            if total and used is not None:
                return total, used
    return None


def _root_fs_usage(server: ServerData) -> float | None:
    if fs := _root_fs(server):
        return fs[1] / fs[0] * 100
    return None


def _root_fs_free(server: ServerData) -> int | None:
    if fs := _root_fs(server):
        return fs[0] - fs[1]
    return None


def _first(items: list[dict[str, Any]] | None, key: str) -> str | None:
    return items[0].get(key) if items else None


def _state(server: ServerData) -> str | None:
    return server.state.lower() if server.state else None


def _boot_time(server: ServerData) -> datetime | None:
    uptime = server.live.get("uptimeInSeconds")
    if not uptime or server.state != "RUNNING":
        return None
    return (dt_util.utcnow() - timedelta(seconds=uptime)).replace(
        second=0, microsecond=0
    )


@dataclass(frozen=True, kw_only=True)
class NetcupSensorDescription(SensorEntityDescription):
    """Describes a netcup server sensor."""

    value_fn: Callable[[ServerData], StateType | datetime]


def _metric(key: str) -> Callable[[ServerData], float | None]:
    return lambda s: s.metrics.get(
        key, 0.0 if s.state and s.state != "RUNNING" else None
    )


_MIB = {
    "native_unit_of_measurement": UnitOfInformation.MEBIBYTES,
    "device_class": SensorDeviceClass.DATA_SIZE,
    "suggested_unit_of_measurement": UnitOfInformation.GIBIBYTES,
    "suggested_display_precision": 1,
}
_RATE = {
    "native_unit_of_measurement": UnitOfDataRate.BYTES_PER_SECOND,
    "device_class": SensorDeviceClass.DATA_RATE,
    "state_class": SensorStateClass.MEASUREMENT,
    "suggested_unit_of_measurement": UnitOfDataRate.KILOBITS_PER_SECOND,
    "suggested_display_precision": 1,
}
_PER_SECOND = {
    "state_class": SensorStateClass.MEASUREMENT,
    "suggested_display_precision": 2,
    "entity_registry_enabled_default": False,
}

SENSORS: tuple[NetcupSensorDescription, ...] = (
    NetcupSensorDescription(
        key="state",
        translation_key="state",
        device_class=SensorDeviceClass.ENUM,
        options=SERVER_STATES,
        value_fn=_state,
    ),
    NetcupSensorDescription(
        key="boot_time",
        translation_key="boot_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_boot_time,
    ),
    NetcupSensorDescription(
        key="cpu_usage",
        translation_key="cpu_usage",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_metric("cpu"),
    ),
    NetcupSensorDescription(
        key="network_in",
        translation_key="network_in",
        value_fn=_metric("net_in"),
        **_RATE,
    ),
    NetcupSensorDescription(
        key="network_out",
        translation_key="network_out",
        value_fn=_metric("net_out"),
        **_RATE,
    ),
    NetcupSensorDescription(
        key="packets_in",
        translation_key="packets_in",
        native_unit_of_measurement="packets/s",
        value_fn=_metric("packets_in"),
        **_PER_SECOND,
    ),
    NetcupSensorDescription(
        key="packets_out",
        translation_key="packets_out",
        native_unit_of_measurement="packets/s",
        value_fn=_metric("packets_out"),
        **_PER_SECOND,
    ),
    NetcupSensorDescription(
        key="disk_read",
        translation_key="disk_read",
        native_unit_of_measurement="ops/s",
        value_fn=_metric("disk_read"),
        **_PER_SECOND,
    ),
    NetcupSensorDescription(
        key="disk_write",
        translation_key="disk_write",
        native_unit_of_measurement="ops/s",
        value_fn=_metric("disk_write"),
        **_PER_SECOND,
    ),
    NetcupSensorDescription(
        key="traffic_in",
        translation_key="traffic_in",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda s: _sum_interfaces(s, "rxMonthlyInMiB"),
        **_MIB,
    ),
    NetcupSensorDescription(
        key="traffic_out",
        translation_key="traffic_out",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda s: _sum_interfaces(s, "txMonthlyInMiB"),
        **_MIB,
    ),
    NetcupSensorDescription(
        key="root_fs_usage",
        translation_key="root_fs_usage",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_root_fs_usage,
    ),
    NetcupSensorDescription(
        key="root_fs_free",
        translation_key="root_fs_free",
        native_unit_of_measurement=UnitOfInformation.BYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_unit_of_measurement=UnitOfInformation.GIBIBYTES,
        suggested_display_precision=1,
        value_fn=_root_fs_free,
    ),
    NetcupSensorDescription(
        key="disk_allocated",
        translation_key="disk_allocated",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: _sum_disks(s, "allocationInMiB"),
        **_MIB,
    ),
    NetcupSensorDescription(
        key="disk_capacity",
        translation_key="disk_capacity",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: _sum_disks(s, "capacityInMiB"),
        **_MIB,
    ),
    NetcupSensorDescription(
        key="memory",
        translation_key="memory",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.live.get("currentServerMemoryInMiB"),
        **_MIB,
    ),
    NetcupSensorDescription(
        key="vcpus",
        translation_key="vcpus",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.live.get("cpuCount"),
    ),
    NetcupSensorDescription(
        key="snapshots",
        translation_key="snapshots",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.info.get("snapshotCount"),
    ),
    NetcupSensorDescription(
        key="operating_system",
        translation_key="operating_system",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.guest.get("os.pretty-name") if s.guest else None,
    ),
    NetcupSensorDescription(
        key="kernel",
        translation_key="kernel",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.guest.get("os.kernel-release") if s.guest else None,
    ),
    NetcupSensorDescription(
        key="ipv4",
        translation_key="ipv4",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: _first(s.info.get("ipv4Addresses"), "ip"),
    ),
    NetcupSensorDescription(
        key="ipv6",
        translation_key="ipv6",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: _first(s.info.get("ipv6Addresses"), "networkPrefix"),
    ),
    NetcupSensorDescription(
        key="hostname",
        translation_key="hostname",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.info.get("hostname"),
    ),
    NetcupSensorDescription(
        key="location",
        translation_key="location",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: (s.info.get("site") or {}).get("city"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NetcupConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors."""

    def factory(coordinator: NetcupCoordinator, server_id: int) -> list[NetcupSensor]:
        return [NetcupSensor(coordinator, server_id, d) for d in SENSORS]

    async_setup_server_entities(entry, async_add_entities, factory)


class NetcupSensor(NetcupEntity, SensorEntity):
    """A netcup server sensor."""

    entity_description: NetcupSensorDescription

    @property
    def native_value(self) -> StateType | datetime:
        """Return the sensor value."""
        value = self.entity_description.value_fn(self.server)
        # Uptime-derived boot time jitters by a minute between polls; keep it stable.
        previous = self._attr_native_value
        if (
            isinstance(value, datetime)
            and isinstance(previous, datetime)
            and abs(value - previous) <= timedelta(minutes=2)
        ):
            return previous
        self._attr_native_value = value
        return value
