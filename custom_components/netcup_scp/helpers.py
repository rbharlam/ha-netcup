"""Shared helpers for netcup SCP entities."""

from __future__ import annotations

from typing import Any

from homeassistant.exceptions import HomeAssistantError

from .api import NetcupAuthError, NetcupError
from .const import DOMAIN
from .coordinator import NetcupCoordinator


async def run_action(
    coordinator: NetcupCoordinator,
    server_id: int,
    patch: dict[str, Any],
    state_option: str | None = None,
) -> None:
    """Patch a server and schedule a refresh, translating API errors."""
    try:
        await coordinator.client.patch_server(server_id, patch, state_option)
    except NetcupAuthError:
        coordinator.config_entry.async_start_reauth(coordinator.hass)
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="auth_failed"
        ) from None
    except NetcupError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="action_failed",
            translation_placeholders={"error": str(err)},
        ) from err
    await coordinator.async_request_refresh()
