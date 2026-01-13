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
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    CONF_BACKGROUND_PATH,
    CONF_DAYS,
    CONF_DUAL_PORTRAIT,
    CONF_FAVORITES_FILTER,
    CONF_MEMORY_YEARS,
    CONF_MIX_RATIO,
    CONF_REFRESH_INTERVAL,
    CONF_RESOLUTIONS,
    CONF_TARGET_HEIGHT,
    CONF_TARGET_WIDTH,
    CONF_WRITE_FILES,
    DEFAULT_BACKGROUND_PATH,
    DEFAULT_DAYS,
    DEFAULT_DUAL_PORTRAIT,
    DEFAULT_FAVORITES_FILTER,
    DEFAULT_MEMORY_YEARS,
    DEFAULT_MIX_RATIO,
    DEFAULT_REFRESH_INTERVAL,
    DEFAULT_RESOLUTIONS,
    DEFAULT_WRITE_FILES,
    DOMAIN,
    parse_resolutions,
)
from .hub import CannotConnect, ImmichHub, InvalidAuth

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


def migrate_legacy_options(options: dict) -> dict:
    """Migrate old width/height options to new resolutions format."""
    if CONF_RESOLUTIONS in options:
        return options

    # Convert legacy width/height to resolutions string
    width = options.get(CONF_TARGET_WIDTH, 1920)
    height = options.get(CONF_TARGET_HEIGHT, 1080)
    new_options = dict(options)
    new_options[CONF_RESOLUTIONS] = f"{width}x{height}"
    # Remove legacy keys
    new_options.pop(CONF_TARGET_WIDTH, None)
    new_options.pop(CONF_TARGET_HEIGHT, None)
    return new_options


class ImmichSlideshowConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Immich Slideshow."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._host: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step - get Immich URL."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].rstrip("/")
            self._host = host
            # Proceed to API key step
            return await self.async_step_api_key()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST): str,
                }
            ),
            errors=errors,
        )

    async def async_step_api_key(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the API key step with dynamic link to Immich settings."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Validate resolutions format
            resolutions = user_input.get(CONF_RESOLUTIONS, DEFAULT_RESOLUTIONS)
            parsed = parse_resolutions(resolutions)
            if not parsed:
                errors["base"] = "invalid_resolutions"
            else:
                for w, h in parsed:
                    if w < 640 or w > 3840 or h < 480 or h > 2160:
                        errors["base"] = "invalid_resolutions"
                        break

            # Validate background path
            bg_path = user_input.get(CONF_BACKGROUND_PATH, DEFAULT_BACKGROUND_PATH)
            if ".." in bg_path or bg_path.startswith("/"):
                errors["base"] = "invalid_path"

            if not errors:
                hub = ImmichHub(
                    host=self._host,
                    api_key=user_input[CONF_API_KEY],
                )

                try:
                    if await hub.authenticate():
                        await hub.close()

                        # Create the config entry
                        return self.async_create_entry(
                            title="Immich Slideshow and Memories",
                            data={
                                CONF_HOST: self._host,
                                CONF_API_KEY: user_input[CONF_API_KEY],
                            },
                            options={
                                CONF_DAYS: user_input.get(CONF_DAYS, DEFAULT_DAYS),
                                CONF_DUAL_PORTRAIT: user_input.get(
                                    CONF_DUAL_PORTRAIT, DEFAULT_DUAL_PORTRAIT
                                ),
                                CONF_FAVORITES_FILTER: user_input.get(
                                    CONF_FAVORITES_FILTER, DEFAULT_FAVORITES_FILTER
                                ),
                                CONF_RESOLUTIONS: user_input.get(
                                    CONF_RESOLUTIONS, DEFAULT_RESOLUTIONS
                                ),
                                CONF_REFRESH_INTERVAL: user_input.get(
                                    CONF_REFRESH_INTERVAL, DEFAULT_REFRESH_INTERVAL
                                ),
                                CONF_MEMORY_YEARS: user_input.get(
                                    CONF_MEMORY_YEARS, DEFAULT_MEMORY_YEARS
                                ),
                                CONF_MIX_RATIO: user_input.get(
                                    CONF_MIX_RATIO, DEFAULT_MIX_RATIO
                                ),
                                CONF_WRITE_FILES: user_input.get(
                                    CONF_WRITE_FILES, DEFAULT_WRITE_FILES
                                ),
                                CONF_BACKGROUND_PATH: user_input.get(
                                    CONF_BACKGROUND_PATH, DEFAULT_BACKGROUND_PATH
                                ),
                            },
                        )
                    else:
                        errors["base"] = "invalid_auth"
                except CannotConnect:
                    errors["base"] = "cannot_connect"
                except Exception:
                    _LOGGER.exception("Unexpected exception")
                    errors["base"] = "unknown"
                finally:
                    await hub.close()

        # Build the API keys URL for the user's Immich instance
        api_keys_url = f"{self._host}/user-settings?isOpen=api-keys"

        return self.async_show_form(
            step_id="api_key",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_KEY): str,
                    vol.Optional(CONF_MIX_RATIO, default=DEFAULT_MIX_RATIO): NumberSelector(
                        NumberSelectorConfig(
                            min=0, max=100, step=5, mode=NumberSelectorMode.SLIDER, unit_of_measurement="%"
                        )
                    ),
                    vol.Optional(CONF_DAYS, default=DEFAULT_DAYS): NumberSelector(
                        NumberSelectorConfig(
                            min=0, max=365, mode=NumberSelectorMode.BOX
                        )
                    ),
                    vol.Optional(CONF_MEMORY_YEARS, default=DEFAULT_MEMORY_YEARS): NumberSelector(
                        NumberSelectorConfig(
                            min=0, max=20, mode=NumberSelectorMode.BOX
                        )
                    ),
                    vol.Optional(
                        CONF_DUAL_PORTRAIT, default=DEFAULT_DUAL_PORTRAIT
                    ): bool,
                    vol.Optional(
                        CONF_FAVORITES_FILTER, default=DEFAULT_FAVORITES_FILTER
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                {"value": "all", "label": "All photos"},
                                {"value": "only", "label": "Favorites only"},
                                {"value": "exclude", "label": "Exclude favorites"},
                            ],
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Optional(
                        CONF_RESOLUTIONS, default=DEFAULT_RESOLUTIONS
                    ): str,
                    vol.Optional(
                        CONF_REFRESH_INTERVAL, default=DEFAULT_REFRESH_INTERVAL
                    ): vol.All(vol.Coerce(int), vol.Range(min=10, max=3600)),
                    vol.Optional(
                        CONF_WRITE_FILES, default=DEFAULT_WRITE_FILES
                    ): bool,
                    vol.Optional(
                        CONF_BACKGROUND_PATH, default=DEFAULT_BACKGROUND_PATH
                    ): str,
                }
            ),
            errors=errors,
            description_placeholders={"api_keys_url": api_keys_url},
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return ImmichSlideshowOptionsFlow(config_entry)


class ImmichSlideshowOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for Immich Slideshow."""

    def __init__(self, config_entry: config_entries.ConfigEntry | None = None) -> None:
        """Initialize options flow."""
        # For HA < 2024.4, config_entry must be passed and stored manually.
        # For HA >= 2024.4, config_entry is a property set automatically.
        if config_entry is not None:
            self._config_entry = config_entry

    @property
    def config_entry(self) -> config_entries.ConfigEntry:
        """Return config entry (compatibility wrapper)."""
        # Try the new auto-property first, fall back to manually stored
        if hasattr(super(), "config_entry"):
            return super().config_entry
        return self._config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Validate resolutions format
            resolutions = user_input.get(CONF_RESOLUTIONS, DEFAULT_RESOLUTIONS)
            parsed = parse_resolutions(resolutions)
            if not parsed:
                errors["base"] = "invalid_resolutions"
            else:
                for w, h in parsed:
                    if w < 640 or w > 3840 or h < 480 or h > 2160:
                        errors["base"] = "invalid_resolutions"
                        break

            # Validate host/API key if changed
            if not errors:
                new_host = user_input.get(CONF_HOST, "").rstrip("/")
                new_api_key = user_input.get(CONF_API_KEY)
                current_host = self.config_entry.options.get(
                    CONF_HOST, self.config_entry.data.get(CONF_HOST, "")
                )
                current_api_key = self.config_entry.options.get(
                    CONF_API_KEY, self.config_entry.data.get(CONF_API_KEY)
                )
                # Re-validate if host or API key changed
                if (new_host and new_host != current_host) or (new_api_key and new_api_key != current_api_key):
                    hub = ImmichHub(
                        host=new_host or current_host,
                        api_key=new_api_key or current_api_key,
                    )
                    try:
                        if not await hub.authenticate():
                            errors["base"] = "invalid_auth"
                    except CannotConnect:
                        errors["base"] = "cannot_connect"
                    except Exception:
                        _LOGGER.exception("Unexpected exception validating connection")
                        errors["base"] = "unknown"
                    finally:
                        await hub.close()

            if not errors:
                # Save all options
                save_data = {
                    CONF_HOST: user_input.get(CONF_HOST, "").rstrip("/"),
                    CONF_API_KEY: user_input.get(CONF_API_KEY),
                    CONF_MIX_RATIO: user_input.get(CONF_MIX_RATIO, DEFAULT_MIX_RATIO),
                    CONF_DAYS: user_input.get(CONF_DAYS, DEFAULT_DAYS),
                    CONF_MEMORY_YEARS: user_input.get(CONF_MEMORY_YEARS, DEFAULT_MEMORY_YEARS),
                    CONF_DUAL_PORTRAIT: user_input.get(CONF_DUAL_PORTRAIT, DEFAULT_DUAL_PORTRAIT),
                    CONF_FAVORITES_FILTER: user_input.get(CONF_FAVORITES_FILTER, DEFAULT_FAVORITES_FILTER),
                    CONF_RESOLUTIONS: user_input.get(CONF_RESOLUTIONS, DEFAULT_RESOLUTIONS),
                    CONF_REFRESH_INTERVAL: user_input.get(CONF_REFRESH_INTERVAL, DEFAULT_REFRESH_INTERVAL),
                    CONF_WRITE_FILES: user_input.get(CONF_WRITE_FILES, DEFAULT_WRITE_FILES),
                    CONF_BACKGROUND_PATH: user_input.get(CONF_BACKGROUND_PATH, DEFAULT_BACKGROUND_PATH),
                }
                return self.async_create_entry(title="", data=save_data)

        # Migrate legacy options if needed
        options = migrate_legacy_options(dict(self.config_entry.options))

        # Get current values
        current_host = options.get(
            CONF_HOST, self.config_entry.data.get(CONF_HOST, "")
        )
        current_api_key = options.get(
            CONF_API_KEY, self.config_entry.data.get(CONF_API_KEY, "")
        )

        # Build the API keys URL
        host = current_host.rstrip("/")
        api_keys_url = f"{host}/user-settings?isOpen=api-keys"

        # Build schema with all options
        schema_dict = {
            vol.Optional(CONF_HOST, default=current_host): str,
            vol.Optional(CONF_API_KEY, default=current_api_key): str,
            vol.Optional(
                CONF_MIX_RATIO,
                default=options.get(CONF_MIX_RATIO, DEFAULT_MIX_RATIO),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=0, max=100, step=5, mode=NumberSelectorMode.SLIDER, unit_of_measurement="%"
                )
            ),
            vol.Optional(
                CONF_DAYS,
                default=options.get(CONF_DAYS, DEFAULT_DAYS),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=0, max=365, mode=NumberSelectorMode.BOX
                )
            ),
            vol.Optional(
                CONF_MEMORY_YEARS,
                default=options.get(CONF_MEMORY_YEARS, DEFAULT_MEMORY_YEARS),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=0, max=20, mode=NumberSelectorMode.BOX
                )
            ),
            vol.Optional(
                CONF_DUAL_PORTRAIT,
                default=options.get(CONF_DUAL_PORTRAIT, DEFAULT_DUAL_PORTRAIT),
            ): bool,
            vol.Optional(
                CONF_FAVORITES_FILTER,
                default=options.get(CONF_FAVORITES_FILTER, DEFAULT_FAVORITES_FILTER),
            ): SelectSelector(
                SelectSelectorConfig(
                    options=[
                        {"value": "all", "label": "All photos"},
                        {"value": "only", "label": "Favorites only"},
                        {"value": "exclude", "label": "Exclude favorites"},
                    ],
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional(
                CONF_RESOLUTIONS,
                default=options.get(CONF_RESOLUTIONS, DEFAULT_RESOLUTIONS),
            ): str,
            vol.Optional(
                CONF_REFRESH_INTERVAL,
                default=options.get(CONF_REFRESH_INTERVAL, DEFAULT_REFRESH_INTERVAL),
            ): vol.All(vol.Coerce(int), vol.Range(min=10, max=3600)),
            # View Assist options
            vol.Optional(
                CONF_WRITE_FILES,
                default=options.get(CONF_WRITE_FILES, DEFAULT_WRITE_FILES),
            ): bool,
            vol.Optional(
                CONF_BACKGROUND_PATH,
                default=options.get(CONF_BACKGROUND_PATH, DEFAULT_BACKGROUND_PATH),
            ): str,
        }

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(schema_dict),
            errors=errors,
            description_placeholders={"api_keys_url": api_keys_url},
        )
