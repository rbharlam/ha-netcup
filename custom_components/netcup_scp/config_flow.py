"""Config flow for netcup SCP using the OAuth device authorization grant."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    SOURCE_REAUTH,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .api import (
    DeviceCode,
    NetcupAuthError,
    NetcupClient,
    NetcupError,
    poll_device_token,
    request_device_code,
)
from .const import (
    CONF_REFRESH_TOKEN,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


class NetcupConfigFlow(ConfigFlow, domain=DOMAIN):
    """Log in to the netcup Server Control Panel."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._device: DeviceCode | None = None
        self._login_task: asyncio.Task[str] | None = None
        self._refresh_token: str | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> NetcupOptionsFlow:
        """Return the options flow."""
        return NetcupOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Start the login."""
        return await self.async_step_device()

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle an expired or revoked token."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm re-authentication."""
        if user_input is None:
            return self.async_show_form(step_id="reauth_confirm")
        return await self.async_step_device()

    async def async_step_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the verification link and wait for the user to approve it."""
        session = async_get_clientsession(self.hass)
        if self._device is None:
            try:
                self._device = await request_device_code(session)
            except NetcupError as err:
                _LOGGER.error("Could not start netcup login: %s", err)
                return self.async_abort(reason="cannot_connect")
        if self._login_task is None:
            self._login_task = self.hass.async_create_task(
                poll_device_token(session, self._device)
            )

        if not self._login_task.done():
            return self.async_show_progress(
                step_id="device",
                progress_action="wait_for_device",
                description_placeholders={
                    "url": self._device.verification_uri_complete,
                    "code": self._device.user_code,
                },
                progress_task=self._login_task,
            )

        try:
            self._refresh_token = self._login_task.result()
        except NetcupAuthError as err:
            _LOGGER.debug("netcup login not completed: %s", err)
            return self.async_show_progress_done(next_step_id="not_approved")
        except NetcupError as err:
            _LOGGER.error("netcup login failed: %s", err)
            return self.async_show_progress_done(next_step_id="connection_failed")
        return self.async_show_progress_done(next_step_id="finish")

    async def async_step_not_approved(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Login was denied or timed out; offer to retry."""
        if user_input is None:
            return self.async_show_form(step_id="not_approved")
        self._device = self._login_task = None
        return await self.async_step_device()

    async def async_step_connection_failed(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Abort after a connection error during login."""
        return self.async_abort(reason="cannot_connect")

    async def async_step_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Identify the account and create or update the entry."""
        assert self._refresh_token
        client = NetcupClient(async_get_clientsession(self.hass), self._refresh_token)
        try:
            info = await client.get_userinfo()
        except NetcupError as err:
            _LOGGER.error("Could not read netcup account: %s", err)
            return self.async_abort(reason="cannot_connect")

        await self.async_set_unique_id(str(info.get("id") or info["sub"]))
        data = {CONF_REFRESH_TOKEN: client.refresh_token}
        if self.source == SOURCE_REAUTH:
            self._abort_if_unique_id_mismatch(reason="wrong_account")
            return self.async_update_reload_and_abort(
                self._get_reauth_entry(), data=data
            )

        self._abort_if_unique_id_configured()
        title = info.get("preferred_username") or info.get("name") or "netcup"
        return self.async_create_entry(title=f"netcup {title}", data=data)

    @callback
    def async_remove(self) -> None:
        """Stop polling when the flow is closed."""
        if self._login_task and not self._login_task.done():
            self._login_task.cancel()


class NetcupOptionsFlow(OptionsFlow):
    """Polling options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(
                data={CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL])}
            )
        current = self.config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL.seconds
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCAN_INTERVAL, default=current): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_SCAN_INTERVAL,
                            max=3600,
                            step=10,
                            unit_of_measurement="s",
                            mode=NumberSelectorMode.BOX,
                        )
                    )
                }
            ),
        )
