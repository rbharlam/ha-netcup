# netcup SCP for Home Assistant

Monitor and control your [netcup](https://www.netcup.com) root servers and VPS from Home Assistant, using the official [Server Control Panel REST API](https://www.netcup.com/en/helpcenter/documentation/servercontrolpanel/api).

- Login in the Home Assistant UI. No API keys or passwords are stored, only a revocable OAuth refresh token.
- Every server becomes a device, and servers you add or delete are picked up automatically.
- Live CPU, network and disk metrics, monthly traffic, and filesystem usage via the guest agent.
- Power on, graceful shutdown, reset, power cycle and autostart.
- English and German translations.

## Installation

[![Open in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=rbharlam&repository=ha-netcup&category=integration)

1. In HACS, open **⋮ → Custom repositories** and add `https://github.com/rbharlam/ha-netcup` as type **Integration**.
2. Install **netcup SCP** and restart Home Assistant.
3. Go to **Settings → Devices & services → Add integration → netcup SCP**.
4. Open the link that appears, log in with your netcup customer number and grant access. The dialog finishes on its own.

To install manually, copy `custom_components/netcup_scp` into your `config/custom_components` folder instead.

## Entities (per server)

| Entity | Notes |
| --- | --- |
| State | running, off, paused, crashed, … |
| Boot time | |
| CPU usage | Average over all vCPUs, per minute |
| Network in / out | Sum over all interfaces |
| Monthly traffic in / out | As counted by netcup |
| Root filesystem usage / free | Requires the QEMU guest agent in the VM |
| Disk allocated / capacity, memory, vCPUs, snapshots | |
| Operating system, IPv4, IPv6 prefix, location | Diagnostic |
| Restart required, traffic throttled, rescue system, storage optimization, guest agent | Binary sensors |
| Power, autostart | Switches. Power off is a graceful ACPI shutdown |
| Power cycle, reset, force power off | Buttons |

Packets/s, disk read/write operations, kernel and hostname are available but disabled by default.

The API returns metrics without units. The integration reads CPU as ns of CPU time per second, network as bytes/s and disk as operations/s.

## Options

**Configure** sets the update interval (default 60 s). Each running server costs about six API requests per update.

## Removing

Deleting the integration revokes its token. You can also revoke access at any time in the [netcup account console](https://www.servercontrolpanel.de/realms/scp/account/applications).

## Development

```sh
nix-shell          # or: uv sync
pytest
ruff check . && ruff format .
```
