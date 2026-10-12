"""Tests for the repair issues raised at setup."""
from __future__ import annotations

from unittest.mock import AsyncMock

from homeassistant.const import CONF_API_KEY, CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.immich_slideshow import _async_update_permissions_issue
from custom_components.immich_slideshow.const import CAPABILITY_PERMISSION, DOMAIN


def _perms(**denied: bool) -> dict[str, dict]:
    """All capabilities granted, except those passed as cap=True (denied)."""
    return {
        cap: {"ok": not denied.get(cap, False), "permission": perm, "unknown": False}
        for cap, perm in CAPABILITY_PERMISSION.items()
    }


def _entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: "http://immich.local:2283", CONF_API_KEY: "key"},
        options={},
        version=2,
    )
    entry.add_to_hass(hass)
    return entry


async def test_missing_asset_view_raises_recommended_issue_only(hass: HomeAssistant) -> None:
    """asset.view missing → soft 'recommended' issue, not the 'sources broken' one."""
    entry = _entry(hass)
    hub = AsyncMock()
    hub.check_permissions.return_value = _perms(asset_view=True)

    await _async_update_permissions_issue(hass, entry, hub)

    registry = ir.async_get(hass)
    issue = registry.async_get_issue(
        DOMAIN, f"missing_recommended_permissions_{entry.entry_id}"
    )
    assert issue is not None
    assert issue.severity == ir.IssueSeverity.WARNING
    assert issue.translation_key == "missing_recommended_permissions"
    assert issue.translation_placeholders["missing"] == "asset.view"
    assert registry.async_get_issue(DOMAIN, f"missing_permissions_{entry.entry_id}") is None


async def test_recommended_issue_cleared_once_granted(hass: HomeAssistant) -> None:
    """Granting asset.view clears the issue on the next setup/reload."""
    entry = _entry(hass)
    hub = AsyncMock()
    hub.check_permissions.return_value = _perms(asset_view=True)
    await _async_update_permissions_issue(hass, entry, hub)

    hub.check_permissions.return_value = _perms()
    await _async_update_permissions_issue(hass, entry, hub)

    assert (
        ir.async_get(hass).async_get_issue(
            DOMAIN, f"missing_recommended_permissions_{entry.entry_id}"
        )
        is None
    )


async def test_unknown_asset_view_raises_nothing(hass: HomeAssistant) -> None:
    """A probe that couldn't conclude (no asset, connection blip) is not a denial."""
    entry = _entry(hass)
    perms = _perms()
    perms["asset_view"] = {"ok": False, "permission": "asset.view", "unknown": True}
    hub = AsyncMock()
    hub.check_permissions.return_value = perms

    await _async_update_permissions_issue(hass, entry, hub)

    assert (
        ir.async_get(hass).async_get_issue(
            DOMAIN, f"missing_recommended_permissions_{entry.entry_id}"
        )
        is None
    )
