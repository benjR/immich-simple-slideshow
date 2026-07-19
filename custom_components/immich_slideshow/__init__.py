"""The Immich Slideshow integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_API_KEY, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import issue_registry as ir

from .const import (
    DOMAIN,
    required_capabilities,
    MIN_IMMICH_VERSION,
    format_version,
    # v2 config keys
    CONF_SOURCE_RECENT_WEIGHT,
    CONF_SOURCE_MEMORIES_WEIGHT,
    CONF_SOURCE_ALBUMS_WEIGHT,
    CONF_SOURCE_PERSONS_WEIGHT,
    CONF_RECENT_DAYS,
    CONF_RECENT_FAVORITES_FILTER,
    CONF_MEMORIES_MAX_YEARS,
    CONF_ALBUMS_INCLUDE,
    CONF_PERSONS_INCLUDE,
    CONF_EXCLUDE_ALBUMS,
    CONF_EXCLUDE_PERSONS,
    CONF_DUAL_PORTRAIT,
    CONF_RESOLUTIONS,
    CONF_REFRESH_INTERVAL,
    CONF_WRITE_FILES,
    CONF_BACKGROUND_PATH,
    # v1 legacy keys
    CONF_MIX_RATIO,
    CONF_DAYS,
    CONF_MEMORY_YEARS,
    CONF_FAVORITES_FILTER,
    CONF_TARGET_WIDTH,
    CONF_TARGET_HEIGHT,
    # Defaults
    DEFAULT_DUAL_PORTRAIT,
    DEFAULT_RESOLUTIONS,
    DEFAULT_REFRESH_INTERVAL,
    DEFAULT_WRITE_FILES,
    DEFAULT_BACKGROUND_PATH,
    DEFAULT_DAYS,
    DEFAULT_MEMORY_YEARS,
    DEFAULT_FAVORITES_FILTER,
)
from .hub import ImmichHub

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.IMAGE, Platform.SENSOR]


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate old entry to new format."""
    _LOGGER.debug(
        "Migrating Immich Slideshow from version %s.%s",
        config_entry.version,
        config_entry.minor_version,
    )

    if config_entry.version == 1:
        # Migrate v1 → v2
        options = dict(config_entry.options)
        data = dict(config_entry.data)

        # v1 stored api_key in options too (so users could edit it). v2 keeps
        # secrets only in data. If options has a more recent api_key, promote
        # it to data so we don't drop user updates.
        options_api_key = options.pop(CONF_API_KEY, None)
        if options_api_key and options_api_key != data.get(CONF_API_KEY):
            data[CONF_API_KEY] = options_api_key

        # Convert mix_ratio to weighted sources
        # mix_ratio=0 → Recent=100%, Memories=0%
        # mix_ratio=50 → Recent=50%, Memories=50%
        # mix_ratio=100 → Recent=0%, Memories=100%
        mix_ratio = options.pop(CONF_MIX_RATIO, 0)

        # Pop old keys if present
        old_days = options.pop(CONF_DAYS, DEFAULT_DAYS)
        old_memory_years = options.pop(CONF_MEMORY_YEARS, DEFAULT_MEMORY_YEARS)
        old_favorites_filter = options.pop(CONF_FAVORITES_FILTER, DEFAULT_FAVORITES_FILTER)

        # Resolution: prefer existing CONF_RESOLUTIONS, fall back to legacy width/height
        if CONF_RESOLUTIONS in options:
            resolutions = options[CONF_RESOLUTIONS]
            options.pop(CONF_TARGET_WIDTH, None)
            options.pop(CONF_TARGET_HEIGHT, None)
        elif CONF_TARGET_WIDTH in options or CONF_TARGET_HEIGHT in options:
            width = options.pop(CONF_TARGET_WIDTH, 1920)
            height = options.pop(CONF_TARGET_HEIGHT, 1080)
            resolutions = f"{width}x{height}"
        else:
            resolutions = DEFAULT_RESOLUTIONS

        new_options = {
            # Keep existing display/output settings
            CONF_RESOLUTIONS: resolutions,
            CONF_REFRESH_INTERVAL: options.get(CONF_REFRESH_INTERVAL, DEFAULT_REFRESH_INTERVAL),
            CONF_DUAL_PORTRAIT: options.get(CONF_DUAL_PORTRAIT, DEFAULT_DUAL_PORTRAIT),
            CONF_WRITE_FILES: options.get(CONF_WRITE_FILES, DEFAULT_WRITE_FILES),
            CONF_BACKGROUND_PATH: options.get(CONF_BACKGROUND_PATH, DEFAULT_BACKGROUND_PATH),

            # Convert to new weighted source format
            CONF_SOURCE_RECENT_WEIGHT: 100 - mix_ratio,
            CONF_SOURCE_MEMORIES_WEIGHT: mix_ratio,
            CONF_SOURCE_ALBUMS_WEIGHT: 0,  # New, disabled by default
            CONF_SOURCE_PERSONS_WEIGHT: 0,  # New, disabled by default

            # Migrate existing Recent source settings
            CONF_RECENT_DAYS: old_days,
            CONF_RECENT_FAVORITES_FILTER: old_favorites_filter,

            # Migrate existing Memories source settings
            CONF_MEMORIES_MAX_YEARS: old_memory_years,

            # New sources start empty
            CONF_ALBUMS_INCLUDE: [],
            CONF_PERSONS_INCLUDE: [],

            # Global exclusions start empty
            CONF_EXCLUDE_ALBUMS: [],
            CONF_EXCLUDE_PERSONS: [],
        }

        hass.config_entries.async_update_entry(
            config_entry,
            data=data,
            options=new_options,
            version=2,
        )
        _LOGGER.info(
            "Migrated Immich Slideshow config from v1 to v2: mix_ratio=%d → recent=%d%%, memories=%d%%",
            mix_ratio, 100 - mix_ratio, mix_ratio,
        )

    return True


def _permissions_issue_id(entry: ConfigEntry) -> str:
    """Stable repair-issue id for this entry's missing-permissions warning."""
    return f"missing_permissions_{entry.entry_id}"


def _version_issue_id(entry: ConfigEntry) -> str:
    """Stable repair-issue id for this entry's unsupported-version warning."""
    return f"immich_version_{entry.entry_id}"


async def _async_update_version_issue(
    hass: HomeAssistant, entry: ConfigEntry, hub: ImmichHub
) -> None:
    """Create or clear the 'Immich server too old' repair issue.

    Non-blocking: an unknown version (None) is ignored so a transient failure
    or a server that doesn't expose /api/server/version never raises a warning.
    """
    issue_id = _version_issue_id(entry)
    version = await hub.get_server_version()
    if version is not None and version < MIN_IMMICH_VERSION:
        _LOGGER.warning(
            "Immich server v%s is older than the minimum supported v%s; "
            "the slideshow may not work until Immich is updated",
            format_version(version),
            format_version(MIN_IMMICH_VERSION),
        )
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="immich_version_unsupported",
            translation_placeholders={
                "version": format_version(version),
                "minimum": format_version(MIN_IMMICH_VERSION),
            },
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, issue_id)


async def _async_update_permissions_issue(
    hass: HomeAssistant, entry: ConfigEntry, hub: ImmichHub
) -> None:
    """Create or clear the 'missing API-key permissions' repair issue.

    Only permissions actually needed by the current config (core + enabled
    sources) are considered. `unknown` probe results (connection blips) are
    ignored so we don't raise false alarms.
    """
    issue_id = _permissions_issue_id(entry)
    try:
        perms = await hub.check_permissions()
    except Exception:  # noqa: BLE001
        _LOGGER.debug("Permission check failed; skipping issue update", exc_info=True)
        return

    needed = required_capabilities(entry.options)
    missing = sorted(
        {
            perms[cap]["permission"]
            for cap in needed
            if cap in perms and not perms[cap]["ok"] and not perms[cap]["unknown"]
        }
    )

    if missing:
        _LOGGER.warning(
            "Immich API key is missing permissions %s — some slideshow sources "
            "will not work until they are granted",
            ", ".join(missing),
        )
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="missing_permissions",
            translation_placeholders={
                "missing": ", ".join(missing),
                "url": f"{entry.data[CONF_HOST]}/user-settings?isOpen=api-keys",
            },
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, issue_id)


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
        # Immich unreachable (down/restarting): raise ConfigEntryNotReady so HA
        # automatically retries setup with exponential backoff until it recovers,
        # instead of failing permanently. Auth failures above still return False.
        raise ConfigEntryNotReady(f"Error connecting to Immich: {err}") from err

    # Warn (non-blocking) if the Immich server predates the plural REST API we
    # rely on. Runs on every setup, so it also fires if Immich is downgraded.
    await _async_update_version_issue(hass, entry, hub)

    # Surface missing Immich API-key permissions as a repair issue. Immich v3+
    # enforces granular permissions, so an Immich upgrade can silently strip a
    # capability the slideshow relies on (e.g. memory.read for the memories
    # source). Runs on every setup, so it also fires after an Immich update.
    await _async_update_permissions_issue(hass, entry, hub)

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

        # Clean up manager reference
        manager_key = f"{entry.entry_id}_manager"
        if DOMAIN in hass.data and manager_key in hass.data[DOMAIN]:
            hass.data[DOMAIN].pop(manager_key)

    return unload_ok
