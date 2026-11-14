"""Minimal async client for the netcup Server Control Panel (SCP) REST API."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from json import loads as json_loads
from typing import Any

import aiohttp

AUTH_URL = "https://www.servercontrolpanel.de/realms/scp/protocol/openid-connect"
API_URL = "https://www.servercontrolpanel.de/scp-core/api/v1"
CLIENT_ID = "scp"

_TIMEOUT = aiohttp.ClientTimeout(total=30)
_PAGE_SIZE = 100


class NetcupError(Exception):
    """Generic SCP error."""


class NetcupAuthError(NetcupError):
    """Credentials are invalid, expired or were revoked."""


@dataclass(frozen=True, slots=True)
class DeviceCode:
    """OAuth device authorization grant."""

    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str
    expires_in: int
    interval: int


async def _token_request(
    session: aiohttp.ClientSession, data: dict[str, str]
) -> dict[str, Any]:
    try:
        async with session.post(
            f"{AUTH_URL}/token", data={"client_id": CLIENT_ID, **data}, timeout=_TIMEOUT
        ) as resp:
            body = await resp.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError, ValueError) as err:
        raise NetcupError(f"Token request failed: {err}") from err
    if resp.status >= 500:
        raise NetcupError(f"Token endpoint returned {resp.status}")
    return body


async def request_device_code(session: aiohttp.ClientSession) -> DeviceCode:
    """Start the device authorization flow."""
    try:
        async with session.post(
            f"{AUTH_URL}/auth/device",
            data={"client_id": CLIENT_ID, "scope": "offline_access openid"},
            timeout=_TIMEOUT,
        ) as resp:
            resp.raise_for_status()
            body = await resp.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError, ValueError) as err:
        raise NetcupError(f"Device authorization failed: {err}") from err
    return DeviceCode(
        device_code=body["device_code"],
        user_code=body["user_code"],
        verification_uri=body["verification_uri"],
        verification_uri_complete=body["verification_uri_complete"],
        expires_in=int(body.get("expires_in", 600)),
        interval=int(body.get("interval", 5)),
    )


async def poll_device_token(session: aiohttp.ClientSession, device: DeviceCode) -> str:
    """Wait for the user to approve the device code and return the offline refresh token."""
    interval = device.interval
    deadline = time.monotonic() + device.expires_in
    while time.monotonic() < deadline:
        await asyncio.sleep(interval)
        body = await _token_request(
            session,
            {
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "device_code": device.device_code,
            },
        )
        if "refresh_token" in body:
            return body["refresh_token"]
        match body.get("error"):
            case "authorization_pending":
                continue
            case "slow_down":
                interval += 5
            case error:
                raise NetcupAuthError(error or "unknown error")
    raise NetcupAuthError("expired_token")


class NetcupClient:
    """Authenticated SCP API client that keeps its access token fresh."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        refresh_token: str,
        on_token_update: Callable[[str], None] | None = None,
    ) -> None:
        self._session = session
        self.refresh_token = refresh_token
        self._on_token_update = on_token_update
        self._access_token: str | None = None
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    async def _ensure_token(self, force: bool = False) -> str:
        async with self._lock:
            if not force and self._access_token and time.monotonic() < self._expires_at:
                return self._access_token
            body = await _token_request(
                self._session,
                {"grant_type": "refresh_token", "refresh_token": self.refresh_token},
            )
            if "access_token" not in body:
                raise NetcupAuthError(
                    body.get("error_description")
                    or body.get("error")
                    or "refresh failed"
                )
            self._access_token = body["access_token"]
            self._expires_at = time.monotonic() + int(body.get("expires_in", 300)) - 30
            if (new := body.get("refresh_token")) and new != self.refresh_token:
                self.refresh_token = new
                if self._on_token_update:
                    self._on_token_update(new)
            return self._access_token

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        content_type: str = "application/json",
    ) -> Any:
        for attempt in range(2):
            token = await self._ensure_token(force=attempt > 0)
            headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
            if json is not None:
                headers["Content-Type"] = content_type
            try:
                async with self._session.request(
                    method,
                    url,
                    params=params,
                    json=json,
                    headers=headers,
                    timeout=_TIMEOUT,
                ) as resp:
                    if resp.status == 401 and attempt == 0:
                        continue
                    if resp.status == 401:
                        raise NetcupAuthError("Unauthorized")
                    if resp.status >= 400:
                        raise NetcupError(
                            f"{method} {url} returned {resp.status}: {(await resp.text())[:200]}"
                        )
                    text = await resp.text()
                    return json_loads(text) if text else None
            except (aiohttp.ClientError, TimeoutError, ValueError) as err:
                raise NetcupError(f"{method} {url} failed: {err}") from err
        raise NetcupAuthError("Unauthorized")

    async def get_userinfo(self) -> dict[str, Any]:
        """Return the OIDC user info of the authenticated account."""
        return await self._request("GET", f"{AUTH_URL}/userinfo")

    async def get_servers(self) -> list[dict[str, Any]]:
        """Return all servers of the account."""
        servers: list[dict[str, Any]] = []
        while True:
            page = await self._request(
                "GET",
                f"{API_URL}/servers",
                params={"limit": _PAGE_SIZE, "offset": len(servers)},
            )
            servers.extend(page)
            if len(page) < _PAGE_SIZE:
                return servers

    async def get_server(self, server_id: int) -> dict[str, Any]:
        """Return a server including live info (state, disks, interfaces, ...)."""
        return await self._request("GET", f"{API_URL}/servers/{server_id}")

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """GET an arbitrary API path (relative to /api/v1)."""
        return await self._request("GET", f"{API_URL}{path}", params=params)

    async def patch_server(
        self, server_id: int, patch: dict[str, Any], state_option: str | None = None
    ) -> Any:
        """Apply a merge-patch to a server (state, autostart, ...)."""
        return await self._request(
            "PATCH",
            f"{API_URL}/servers/{server_id}",
            params={"stateOption": state_option} if state_option else None,
            json=patch,
            content_type="application/merge-patch+json",
        )

    async def revoke(self) -> None:
        """Revoke the offline refresh token."""
        try:
            async with self._session.post(
                f"{AUTH_URL}/revoke",
                data={
                    "client_id": CLIENT_ID,
                    "token": self.refresh_token,
                    "token_type_hint": "refresh_token",
                },
                timeout=_TIMEOUT,
            ):
                pass
        except (aiohttp.ClientError, TimeoutError) as err:
            raise NetcupError(f"Revoke failed: {err}") from err
