"""The Immich Slideshow integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_API_KEY, Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .hub import ImmichHub

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.IMAGE]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Immich Slideshow from a config entry."""
    # API key can be updated via options, so check options first, then fall back to data
    api_key = entry.options.get(CONF_API_KEY, entry.data.get(CONF_API_KEY))

    hub = ImmichHub(
        host=entry.data[CONF_HOST],
        api_key=api_key,
    )

    # Verify we can connect
    try:
        if not await hub.authenticate():
            _LOGGER.error("Failed to authenticate with Immich")
            return False
    except Exception as err:
        _LOGGER.error("Error connecting to Immich: %s", err)
        return False

    # Store the hub
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = hub

    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register update listener for options changes
    entry.async_on_unload(entry.add_update_listener(async_update_options))

    return True


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        # Close the hub (with safety check)
        if DOMAIN in hass.data and entry.entry_id in hass.data[DOMAIN]:
            hub: ImmichHub = hass.data[DOMAIN].pop(entry.entry_id)
            await hub.close()

    return unload_ok
