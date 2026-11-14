"""Brand image test."""

from __future__ import annotations

from http import HTTPStatus
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

BRAND = Path(__file__).parents[1] / "custom_components/netcup_scp/brand"


async def test_icon_served(hass: HomeAssistant, hass_client) -> None:
    """Home Assistant serves the bundled icon instead of a placeholder."""
    assert await async_setup_component(hass, "brands", {})
    client = await hass_client()
    for image in ("icon.png", "icon@2x.png", "logo.png", "dark_icon.png"):
        resp = await client.get(f"/api/brands/integration/netcup_scp/{image}")
        assert resp.status == HTTPStatus.OK
        expected = "icon@2x.png" if image == "icon@2x.png" else "icon.png"
        assert await resp.read() == (BRAND / expected).read_bytes()
