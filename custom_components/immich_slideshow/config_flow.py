"""Config flow for Immich Slideshow integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
try:
    from homeassistant.config_entries import ConfigFlowResult
except ImportError:
    from homeassistant.data_entry_flow import FlowResult as ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_API_KEY
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    BooleanSelector,
    TextSelector,
)

from .const import (
    # Core settings
    CONF_BACKGROUND_PATH,
    CONF_DUAL_PORTRAIT,
    CONF_REFRESH_INTERVAL,
    CONF_RESOLUTIONS,
    CONF_WRITE_FILES,
    # Source weights
    CONF_SOURCE_RECENT_WEIGHT,
    CONF_SOURCE_MEMORIES_WEIGHT,
    CONF_SOURCE_ALBUMS_WEIGHT,
    CONF_SOURCE_PERSONS_WEIGHT,
    # Recent source
    CONF_RECENT_DAYS,
    CONF_RECENT_FAVORITES_FILTER,
    # Memories source
    CONF_MEMORIES_MAX_YEARS,
    # Albums source
    CONF_ALBUMS_INCLUDE,
    # Persons source
    CONF_PERSONS_INCLUDE,
    # Global exclusions
    CONF_EXCLUDE_ALBUMS,
    CONF_EXCLUDE_PERSONS,
    # Defaults
    DEFAULT_BACKGROUND_PATH,
    DEFAULT_DUAL_PORTRAIT,
    DEFAULT_REFRESH_INTERVAL,
    DEFAULT_RESOLUTIONS,
    DEFAULT_WRITE_FILES,
    DEFAULT_SOURCE_RECENT_WEIGHT,
    DEFAULT_SOURCE_MEMORIES_WEIGHT,
    DEFAULT_SOURCE_ALBUMS_WEIGHT,
    DEFAULT_SOURCE_PERSONS_WEIGHT,
    DEFAULT_RECENT_DAYS,
    DEFAULT_RECENT_FAVORITES_FILTER,
    DEFAULT_MEMORIES_MAX_YEARS,
    DOMAIN,
    parse_resolutions,
)
from .hub import CannotConnect, ImmichHub

_LOGGER = logging.getLogger(__name__)


def validate_resolutions(value: str) -> str:
    """Validate resolutions string format."""
    parsed = parse_resolutions(value)
    if not parsed:
        raise vol.Invalid("Invalid resolution format. Use WxH, e.g. '1920x1080'")
    for w, h in parsed:
        if w < 640 or w > 3840 or h < 480 or h > 2160:
            raise vol.Invalid(f"Resolution {w}x{h} out of range (640-3840 x 480-2160)")
    return value


def validate_background_path(value: str) -> str:
    """Validate background path to prevent path traversal."""
    if ".." in value:
        raise vol.Invalid("Path cannot contain '..'")
    if value.startswith("/"):
        raise vol.Invalid("Path must be relative (no leading '/')")
    return value


# =============================================================================
# Helpers — shared between config flow (post-auth step) and options flow
# =============================================================================


def _album_options_from_cache(albums: list[dict] | None) -> list[dict]:
    """Convert cached albums to selector options, sorted by photo count."""
    sorted_albums = sorted(albums or [], key=lambda a: a.get("assetCount", 0), reverse=True)
    return [
        {"value": a["id"], "label": f"{a.get('albumName', 'Unknown')} ({a.get('assetCount', 0)})"}
        for a in sorted_albums
    ]


def _person_options_from_cache(people: list[dict] | None) -> list[dict]:
    """Convert cached people to selector options, sorted alphabetically."""
    sorted_people = sorted(people or [], key=lambda p: p.get("name", "").lower())
    return [
        {"value": p["id"], "label": p.get("name", "Unknown")}
        for p in sorted_people
    ]


def _build_settings_schema(
    options: dict[str, Any],
    album_options: list[dict],
    person_options: list[dict],
    *,
    include_connection: bool = False,
    current_host: str = "",
    current_api_key: str = "",
) -> dict:
    """Build the settings schema with collapsible sections.

    Used by both config flow (settings step, post-auth) and options flow (init).

    Args:
        options: current options dict (defaults populated from this)
        album_options: precomputed selector options from albums cache
        person_options: precomputed selector options from people cache
        include_connection: if True, prepend host + api_key fields
        current_host: prefilled value for connection fields
        current_api_key: prefilled value for connection fields
    """
    schema_dict: dict = {}

    if include_connection:
        schema_dict[vol.Required(CONF_HOST, default=current_host)] = TextSelector()
        schema_dict[vol.Required(CONF_API_KEY, default=current_api_key)] = TextSelector()

    # Source Weights (expanded by default)
    schema_dict[vol.Required("source_weights")] = section(
        vol.Schema({
            vol.Optional(
                CONF_SOURCE_RECENT_WEIGHT,
                default=options.get(CONF_SOURCE_RECENT_WEIGHT, DEFAULT_SOURCE_RECENT_WEIGHT),
            ): NumberSelector(
                NumberSelectorConfig(min=0, max=100, step=5, mode=NumberSelectorMode.SLIDER)
            ),
            vol.Optional(
                CONF_SOURCE_MEMORIES_WEIGHT,
                default=options.get(CONF_SOURCE_MEMORIES_WEIGHT, DEFAULT_SOURCE_MEMORIES_WEIGHT),
            ): NumberSelector(
                NumberSelectorConfig(min=0, max=100, step=5, mode=NumberSelectorMode.SLIDER)
            ),
            vol.Optional(
                CONF_SOURCE_ALBUMS_WEIGHT,
                default=options.get(CONF_SOURCE_ALBUMS_WEIGHT, DEFAULT_SOURCE_ALBUMS_WEIGHT),
            ): NumberSelector(
                NumberSelectorConfig(min=0, max=100, step=5, mode=NumberSelectorMode.SLIDER)
            ),
            vol.Optional(
                CONF_SOURCE_PERSONS_WEIGHT,
                default=options.get(CONF_SOURCE_PERSONS_WEIGHT, DEFAULT_SOURCE_PERSONS_WEIGHT),
            ): NumberSelector(
                NumberSelectorConfig(min=0, max=100, step=5, mode=NumberSelectorMode.SLIDER)
            ),
        }),
        {"collapsed": False},
    )

    # Recent Photos
    schema_dict[vol.Required("recent_source")] = section(
        vol.Schema({
            vol.Optional(
                CONF_RECENT_DAYS,
                default=options.get(CONF_RECENT_DAYS, DEFAULT_RECENT_DAYS),
            ): NumberSelector(
                NumberSelectorConfig(min=0, max=365, mode=NumberSelectorMode.BOX)
            ),
            vol.Optional(
                CONF_RECENT_FAVORITES_FILTER,
                default=options.get(CONF_RECENT_FAVORITES_FILTER, DEFAULT_RECENT_FAVORITES_FILTER),
            ): SelectSelector(
                SelectSelectorConfig(
                    options=[
                        {"value": "all", "label": "All photos"},
                        {"value": "only", "label": "Favorites only"},
                        {"value": "exclude", "label": "Exclude favorites"},
                    ],
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key="recent_favorites_filter",
                )
            ),
        }),
        {"collapsed": True},
    )

    # Memories
    schema_dict[vol.Required("memories_source")] = section(
        vol.Schema({
            vol.Optional(
                CONF_MEMORIES_MAX_YEARS,
                default=options.get(CONF_MEMORIES_MAX_YEARS, DEFAULT_MEMORIES_MAX_YEARS),
            ): NumberSelector(
                NumberSelectorConfig(min=0, max=50, mode=NumberSelectorMode.BOX)
            ),
        }),
        {"collapsed": True},
    )

    # Albums (only if user's Immich has any)
    if album_options:
        schema_dict[vol.Required("albums_source")] = section(
            vol.Schema({
                vol.Optional(
                    CONF_ALBUMS_INCLUDE,
                    default=options.get(CONF_ALBUMS_INCLUDE, []),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=album_options,
                        multiple=True,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
            }),
            {"collapsed": True},
        )

    # Persons (only if user's Immich has any named persons)
    if person_options:
        schema_dict[vol.Required("persons_source")] = section(
            vol.Schema({
                vol.Optional(
                    CONF_PERSONS_INCLUDE,
                    default=options.get(CONF_PERSONS_INCLUDE, []),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=person_options,
                        multiple=True,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
            }),
            {"collapsed": True},
        )

    # Advanced (exclusions + display + file output)
    advanced_schema_dict: dict = {}
    if album_options:
        advanced_schema_dict[vol.Optional(
            CONF_EXCLUDE_ALBUMS,
            default=options.get(CONF_EXCLUDE_ALBUMS, []),
        )] = SelectSelector(
            SelectSelectorConfig(
                options=album_options,
                multiple=True,
                mode=SelectSelectorMode.DROPDOWN,
            )
        )
    if person_options:
        advanced_schema_dict[vol.Optional(
            CONF_EXCLUDE_PERSONS,
            default=options.get(CONF_EXCLUDE_PERSONS, []),
        )] = SelectSelector(
            SelectSelectorConfig(
                options=person_options,
                multiple=True,
                mode=SelectSelectorMode.DROPDOWN,
            )
        )
    advanced_schema_dict[vol.Optional(
        CONF_RESOLUTIONS,
        default=options.get(CONF_RESOLUTIONS, DEFAULT_RESOLUTIONS),
    )] = TextSelector()
    advanced_schema_dict[vol.Optional(
        CONF_REFRESH_INTERVAL,
        default=options.get(CONF_REFRESH_INTERVAL, DEFAULT_REFRESH_INTERVAL),
    )] = NumberSelector(
        NumberSelectorConfig(min=10, max=3600, mode=NumberSelectorMode.BOX)
    )
    advanced_schema_dict[vol.Optional(
        CONF_DUAL_PORTRAIT,
        default=options.get(CONF_DUAL_PORTRAIT, DEFAULT_DUAL_PORTRAIT),
    )] = BooleanSelector()
    advanced_schema_dict[vol.Optional(
        CONF_WRITE_FILES,
        default=options.get(CONF_WRITE_FILES, DEFAULT_WRITE_FILES),
    )] = BooleanSelector()
    advanced_schema_dict[vol.Optional(
        CONF_BACKGROUND_PATH,
        default=options.get(CONF_BACKGROUND_PATH, DEFAULT_BACKGROUND_PATH),
    )] = TextSelector()

    schema_dict[vol.Required("advanced")] = section(
        vol.Schema(advanced_schema_dict),
        {"collapsed": True},
    )

    return schema_dict


def _validate_settings_input(user_input: dict[str, Any]) -> dict[str, str]:
    """Validate user_input against settings schema. Returns errors dict.

    Does NOT validate connection fields — caller is responsible for that.
    """
    errors: dict[str, str] = {}
    advanced = user_input.get("advanced", {})
    weights = user_input.get("source_weights", {})
    persons = user_input.get("persons_source", {})

    # Resolutions
    resolutions = advanced.get(CONF_RESOLUTIONS, DEFAULT_RESOLUTIONS)
    parsed = parse_resolutions(resolutions)
    if not parsed:
        errors["base"] = "invalid_resolutions"
    else:
        for w, h in parsed:
            if w < 640 or w > 3840 or h < 480 or h > 2160:
                errors["base"] = "invalid_resolutions"
                break

    # Background path
    bg_path = advanced.get(CONF_BACKGROUND_PATH, DEFAULT_BACKGROUND_PATH)
    if ".." in bg_path or bg_path.startswith("/"):
        errors["base"] = "invalid_path"

    # At least one source enabled
    total_weight = (
        weights.get(CONF_SOURCE_RECENT_WEIGHT, 0)
        + weights.get(CONF_SOURCE_MEMORIES_WEIGHT, 0)
        + weights.get(CONF_SOURCE_ALBUMS_WEIGHT, 0)
        + weights.get(CONF_SOURCE_PERSONS_WEIGHT, 0)
    )
    if total_weight == 0:
        errors["base"] = "no_sources_enabled"

    # Persons source enabled but no person selected
    if weights.get(CONF_SOURCE_PERSONS_WEIGHT, 0) > 0:
        if not persons.get(CONF_PERSONS_INCLUDE, []):
            errors["base"] = "persons_source_no_selection"

    return errors


def _flatten_settings_input(user_input: dict[str, Any]) -> dict[str, Any]:
    """Flatten section-grouped user_input into a flat options dict."""
    advanced = user_input.get("advanced", {})
    weights = user_input.get("source_weights", {})
    recent = user_input.get("recent_source", {})
    memories = user_input.get("memories_source", {})
    albums = user_input.get("albums_source", {})
    persons = user_input.get("persons_source", {})

    return {
        CONF_SOURCE_RECENT_WEIGHT: weights.get(CONF_SOURCE_RECENT_WEIGHT, DEFAULT_SOURCE_RECENT_WEIGHT),
        CONF_SOURCE_MEMORIES_WEIGHT: weights.get(CONF_SOURCE_MEMORIES_WEIGHT, DEFAULT_SOURCE_MEMORIES_WEIGHT),
        CONF_SOURCE_ALBUMS_WEIGHT: weights.get(CONF_SOURCE_ALBUMS_WEIGHT, DEFAULT_SOURCE_ALBUMS_WEIGHT),
        CONF_SOURCE_PERSONS_WEIGHT: weights.get(CONF_SOURCE_PERSONS_WEIGHT, DEFAULT_SOURCE_PERSONS_WEIGHT),
        CONF_RECENT_DAYS: recent.get(CONF_RECENT_DAYS, DEFAULT_RECENT_DAYS),
        CONF_RECENT_FAVORITES_FILTER: recent.get(CONF_RECENT_FAVORITES_FILTER, DEFAULT_RECENT_FAVORITES_FILTER),
        CONF_MEMORIES_MAX_YEARS: memories.get(CONF_MEMORIES_MAX_YEARS, DEFAULT_MEMORIES_MAX_YEARS),
        CONF_ALBUMS_INCLUDE: albums.get(CONF_ALBUMS_INCLUDE, []),
        CONF_PERSONS_INCLUDE: persons.get(CONF_PERSONS_INCLUDE, []),
        CONF_EXCLUDE_ALBUMS: advanced.get(CONF_EXCLUDE_ALBUMS, []),
        CONF_EXCLUDE_PERSONS: advanced.get(CONF_EXCLUDE_PERSONS, []),
        CONF_DUAL_PORTRAIT: advanced.get(CONF_DUAL_PORTRAIT, DEFAULT_DUAL_PORTRAIT),
        CONF_RESOLUTIONS: advanced.get(CONF_RESOLUTIONS, DEFAULT_RESOLUTIONS),
        CONF_REFRESH_INTERVAL: advanced.get(CONF_REFRESH_INTERVAL, DEFAULT_REFRESH_INTERVAL),
        CONF_WRITE_FILES: advanced.get(CONF_WRITE_FILES, DEFAULT_WRITE_FILES),
        CONF_BACKGROUND_PATH: advanced.get(CONF_BACKGROUND_PATH, DEFAULT_BACKGROUND_PATH),
    }


async def _fetch_immich_options(host: str, api_key: str) -> tuple[list[dict], list[dict]]:
    """Fetch albums + people from Immich, return as selector option lists.

    Always returns lists (empty on failure). Caller decides UX based on emptiness.
    """
    hub = ImmichHub(host=host, api_key=api_key)
    try:
        albums = await hub.get_albums()
        people = await hub.get_people()
    finally:
        await hub.close()
    return _album_options_from_cache(albums), _person_options_from_cache(people)


# =============================================================================
# Config flow
# =============================================================================


class ImmichSlideshowConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Immich Slideshow."""

    VERSION = 2  # Bumped for v2 schema

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._host: str | None = None
        self._api_key: str | None = None
        self._album_options: list[dict] = []
        self._person_options: list[dict] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 1: Immich URL."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._host = user_input[CONF_HOST].rstrip("/")
            return await self.async_step_api_key()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_HOST): str}),
            errors=errors,
        )

    async def async_step_api_key(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 2: validate API key, then advance to settings step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            api_key = user_input[CONF_API_KEY]
            hub = ImmichHub(host=self._host, api_key=api_key)
            try:
                if await hub.authenticate():
                    self._api_key = api_key
                    await hub.close()
                    # Pre-fetch albums + people now while we're authenticated.
                    # If permissions are missing, lists come back empty and the
                    # corresponding sections just won't render (graceful).
                    self._album_options, self._person_options = (
                        await _fetch_immich_options(self._host, self._api_key)
                    )
                    return await self.async_step_settings()
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            finally:
                await hub.close()

        api_keys_url = f"{self._host}/user-settings?isOpen=api-keys"
        return self.async_show_form(
            step_id="api_key",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): str}),
            errors=errors,
            description_placeholders={"api_keys_url": api_keys_url},
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 3: full slideshow settings (sources, weights, filters, display, etc.)."""
        errors: dict[str, str] = {}

        if user_input is not None:
            errors = _validate_settings_input(user_input)
            if not errors:
                return self.async_create_entry(
                    title="Immich Slideshow",
                    data={
                        CONF_HOST: self._host,
                        CONF_API_KEY: self._api_key,
                    },
                    options=_flatten_settings_input(user_input),
                )

        # Defaults (no existing options on first install)
        schema_dict = _build_settings_schema(
            options={},
            album_options=self._album_options,
            person_options=self._person_options,
        )

        return self.async_show_form(
            step_id="settings",
            data_schema=vol.Schema(schema_dict),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return ImmichSlideshowOptionsFlow()


# =============================================================================
# Options flow
# =============================================================================


class ImmichSlideshowOptionsFlow(config_entries.OptionsFlow):
    """Handle menu-based options flow for Immich Slideshow.

    HA 2024.4+ pattern: no __init__ args, config_entry is auto-set as a property
    by the parent class.
    """

    def __init__(self) -> None:
        """Initialize options flow."""
        self._album_options: list[dict] | None = None
        self._person_options: list[dict] | None = None

    async def _ensure_immich_options(self) -> None:
        """Lazily fetch and cache album/people selector options for this flow."""
        if self._album_options is not None and self._person_options is not None:
            return
        self._album_options, self._person_options = await _fetch_immich_options(
            host=self.config_entry.data.get(CONF_HOST, ""),
            api_key=self.config_entry.data.get(CONF_API_KEY, ""),
        )

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show full configuration with collapsible sections (incl. connection re-auth)."""
        options = dict(self.config_entry.options)
        errors: dict[str, str] = {}

        await self._ensure_immich_options()

        if user_input is not None:
            new_host = user_input.get(CONF_HOST, "").rstrip("/")
            new_api_key = user_input.get(CONF_API_KEY, "")
            current_host = self.config_entry.data.get(CONF_HOST, "")
            current_api_key = self.config_entry.data.get(CONF_API_KEY, "")

            # Re-validate auth if connection changed
            if new_host != current_host or new_api_key != current_api_key:
                hub = ImmichHub(host=new_host, api_key=new_api_key)
                try:
                    if not await hub.authenticate():
                        errors["base"] = "invalid_auth"
                except CannotConnect:
                    errors["base"] = "cannot_connect"
                except Exception:  # noqa: BLE001
                    _LOGGER.exception("Unexpected exception validating connection")
                    errors["base"] = "unknown"
                finally:
                    await hub.close()

            if not errors:
                errors = _validate_settings_input(user_input)

            if not errors:
                if new_host != current_host or new_api_key != current_api_key:
                    self.hass.config_entries.async_update_entry(
                        self.config_entry,
                        data={CONF_HOST: new_host, CONF_API_KEY: new_api_key},
                    )
                return self.async_create_entry(
                    title="", data=_flatten_settings_input(user_input)
                )

        current_host = self.config_entry.data.get(CONF_HOST, "")
        current_api_key = self.config_entry.data.get(CONF_API_KEY, "")
        schema_dict = _build_settings_schema(
            options=options,
            album_options=self._album_options or [],
            person_options=self._person_options or [],
            include_connection=True,
            current_host=current_host,
            current_api_key=current_api_key,
        )

        host_for_url = current_host.rstrip("/") if current_host else ""
        api_keys_url = (
            f"{host_for_url}/user-settings?isOpen=api-keys" if host_for_url else ""
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(schema_dict),
            errors=errors,
            description_placeholders={"api_keys_url": api_keys_url},
        )
