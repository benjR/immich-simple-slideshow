"""Tests for Immich Slideshow config flow."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_API_KEY
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.immich_slideshow.const import (
    CONF_BACKGROUND_PATH,
    CONF_DAYS,
    CONF_DUAL_PORTRAIT,
    CONF_FAVORITES_FILTER,
    CONF_MEMORY_YEARS,
    CONF_MIX_RATIO,
    CONF_REFRESH_INTERVAL,
    CONF_RESOLUTIONS,
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
)

from .conftest import MOCK_API_KEY, MOCK_HOST, MOCK_HOST_INPUT, MOCK_API_KEY_INPUT, MOCK_USER_INPUT


# =============================================================================
# Config Flow: User Step Tests
# =============================================================================


async def test_user_flow_success(
    hass: HomeAssistant,
    mock_hub_authenticate_success: AsyncMock,
    mock_setup_entry: AsyncMock,
) -> None:
    """Test successful user config flow (two-step)."""
    # Start the flow - Step 1: Enter host URL
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}

    # Submit host URL - should proceed to API key step
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input=MOCK_HOST_INPUT,
    )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "api_key"
    # Verify description_placeholders contains the API keys URL
    assert "api_keys_url" in result["description_placeholders"]
    assert MOCK_HOST in result["description_placeholders"]["api_keys_url"]

    # Step 2: Submit API key
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input=MOCK_API_KEY_INPUT,
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Immich Slideshow and Memories"
    assert result["data"] == {
        CONF_HOST: MOCK_HOST,
        CONF_API_KEY: MOCK_API_KEY,
    }
    assert result["options"] == {
        CONF_DAYS: DEFAULT_DAYS,
        CONF_DUAL_PORTRAIT: DEFAULT_DUAL_PORTRAIT,
        CONF_FAVORITES_FILTER: DEFAULT_FAVORITES_FILTER,
        CONF_RESOLUTIONS: DEFAULT_RESOLUTIONS,
        CONF_REFRESH_INTERVAL: DEFAULT_REFRESH_INTERVAL,
        CONF_MEMORY_YEARS: DEFAULT_MEMORY_YEARS,
        CONF_MIX_RATIO: DEFAULT_MIX_RATIO,
        CONF_WRITE_FILES: DEFAULT_WRITE_FILES,
        CONF_BACKGROUND_PATH: DEFAULT_BACKGROUND_PATH,
    }

    # Verify hub was called correctly
    mock_hub_authenticate_success.authenticate.assert_called_once()
    mock_hub_authenticate_success.close.assert_called()


async def test_user_flow_with_custom_options(
    hass: HomeAssistant,
    mock_hub_authenticate_success: AsyncMock,
    mock_setup_entry: AsyncMock,
) -> None:
    """Test user config flow with custom options."""
    # Step 1: Host URL
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input=MOCK_HOST_INPUT,
    )

    # Step 2: API key with custom options
    custom_input = {
        CONF_API_KEY: MOCK_API_KEY,
        CONF_DAYS: 30,
        CONF_MIX_RATIO: 50,
        CONF_MEMORY_YEARS: 5,
        CONF_DUAL_PORTRAIT: False,
        CONF_RESOLUTIONS: "2560x1440",
        CONF_REFRESH_INTERVAL: 60,
        CONF_BACKGROUND_PATH: "custom/path",
    }

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input=custom_input,
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["options"][CONF_DAYS] == 30
    assert result["options"][CONF_MIX_RATIO] == 50
    assert result["options"][CONF_MEMORY_YEARS] == 5
    assert result["options"][CONF_DUAL_PORTRAIT] is False
    assert result["options"][CONF_RESOLUTIONS] == "2560x1440"
    assert result["options"][CONF_REFRESH_INTERVAL] == 60
    assert result["options"][CONF_BACKGROUND_PATH] == "custom/path"


async def test_user_flow_invalid_auth(
    hass: HomeAssistant,
    mock_hub_authenticate_failure: AsyncMock,
) -> None:
    """Test config flow with invalid authentication."""
    # Step 1: Host URL
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input=MOCK_HOST_INPUT,
    )

    # Step 2: Invalid API key
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input=MOCK_API_KEY_INPUT,
    )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "api_key"
    assert result["errors"] == {"base": "invalid_auth"}


async def test_user_flow_cannot_connect(
    hass: HomeAssistant,
    mock_hub_cannot_connect: AsyncMock,
) -> None:
    """Test config flow when cannot connect to Immich."""
    # Step 1: Host URL
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input=MOCK_HOST_INPUT,
    )

    # Step 2: API key - connection fails
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input=MOCK_API_KEY_INPUT,
    )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "api_key"
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_invalid_resolution_format(
    hass: HomeAssistant,
) -> None:
    """Test config flow with invalid resolution format."""
    # Step 1: Host URL
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input=MOCK_HOST_INPUT,
    )

    # Step 2: Invalid resolution
    invalid_input = {
        CONF_API_KEY: MOCK_API_KEY,
        CONF_RESOLUTIONS: "not-a-resolution",
    }

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input=invalid_input,
    )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_resolutions"}


async def test_user_flow_resolution_out_of_range(
    hass: HomeAssistant,
) -> None:
    """Test config flow with resolution out of allowed range."""
    # Step 1: Host URL
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input=MOCK_HOST_INPUT,
    )

    # Step 2: 8K resolution - too large
    invalid_input = {
        CONF_API_KEY: MOCK_API_KEY,
        CONF_RESOLUTIONS: "7680x4320",
    }

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input=invalid_input,
    )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_resolutions"}


async def test_user_flow_multiple_resolutions(
    hass: HomeAssistant,
    mock_hub_authenticate_success: AsyncMock,
    mock_setup_entry: AsyncMock,
) -> None:
    """Test config flow with multiple resolutions."""
    # Step 1: Host URL
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input=MOCK_HOST_INPUT,
    )

    # Step 2: Multiple resolutions
    multi_res_input = {
        CONF_API_KEY: MOCK_API_KEY,
        CONF_RESOLUTIONS: "1920x1080, 2560x1440, 1280x720",
    }

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input=multi_res_input,
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["options"][CONF_RESOLUTIONS] == "1920x1080, 2560x1440, 1280x720"


async def test_user_flow_with_favorites_filter(
    hass: HomeAssistant,
    mock_hub_authenticate_success: AsyncMock,
    mock_setup_entry: AsyncMock,
) -> None:
    """Test config flow with favorites filter option."""
    # Step 1: Host URL
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input=MOCK_HOST_INPUT,
    )

    # Step 2: Test with favorites_filter = "only"
    custom_input = {
        CONF_API_KEY: MOCK_API_KEY,
        CONF_FAVORITES_FILTER: "only",
    }

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input=custom_input,
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["options"][CONF_FAVORITES_FILTER] == "only"


async def test_user_flow_favorites_filter_exclude(
    hass: HomeAssistant,
    mock_hub_authenticate_success: AsyncMock,
    mock_setup_entry: AsyncMock,
) -> None:
    """Test config flow with favorites filter set to exclude."""
    # Step 1: Host URL
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input=MOCK_HOST_INPUT,
    )

    # Step 2: Exclude favorites
    custom_input = {
        CONF_API_KEY: MOCK_API_KEY,
        CONF_FAVORITES_FILTER: "exclude",
    }

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input=custom_input,
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["options"][CONF_FAVORITES_FILTER] == "exclude"


# =============================================================================
# Options Flow Tests
# =============================================================================


async def test_options_flow_success(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
) -> None:
    """Test successful options flow."""
    # Create a config entry
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_HOST: MOCK_HOST,
            CONF_API_KEY: MOCK_API_KEY,
        },
        options={
            CONF_DAYS: DEFAULT_DAYS,
            CONF_DUAL_PORTRAIT: DEFAULT_DUAL_PORTRAIT,
            CONF_RESOLUTIONS: DEFAULT_RESOLUTIONS,
            CONF_REFRESH_INTERVAL: DEFAULT_REFRESH_INTERVAL,
            CONF_MEMORY_YEARS: DEFAULT_MEMORY_YEARS,
            CONF_MIX_RATIO: DEFAULT_MIX_RATIO,
            CONF_BACKGROUND_PATH: DEFAULT_BACKGROUND_PATH,
        },
    )
    entry.add_to_hass(hass)

    # Start options flow
    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"

    # Submit new options (keep same API key)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_API_KEY: MOCK_API_KEY,
            CONF_DAYS: 60,
            CONF_MIX_RATIO: 25,
            CONF_MEMORY_YEARS: 10,
            CONF_DUAL_PORTRAIT: False,
            CONF_RESOLUTIONS: "2560x1440",
            CONF_REFRESH_INTERVAL: 45,
            CONF_BACKGROUND_PATH: "new/path",
        },
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_DAYS] == 60
    assert result["data"][CONF_MIX_RATIO] == 25
    assert result["data"][CONF_BACKGROUND_PATH] == "new/path"


async def test_options_flow_change_api_key_success(
    hass: HomeAssistant,
    mock_hub_authenticate_success: AsyncMock,
    mock_setup_entry: AsyncMock,
) -> None:
    """Test options flow with valid new API key."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_HOST: MOCK_HOST,
            CONF_API_KEY: MOCK_API_KEY,
        },
        options={
            CONF_DAYS: DEFAULT_DAYS,
            CONF_DUAL_PORTRAIT: DEFAULT_DUAL_PORTRAIT,
            CONF_RESOLUTIONS: DEFAULT_RESOLUTIONS,
            CONF_REFRESH_INTERVAL: DEFAULT_REFRESH_INTERVAL,
            CONF_MEMORY_YEARS: DEFAULT_MEMORY_YEARS,
            CONF_MIX_RATIO: DEFAULT_MIX_RATIO,
            CONF_BACKGROUND_PATH: DEFAULT_BACKGROUND_PATH,
        },
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)

    # Change to new API key
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_API_KEY: "new-api-key-67890",
            CONF_DAYS: DEFAULT_DAYS,
            CONF_MIX_RATIO: DEFAULT_MIX_RATIO,
            CONF_MEMORY_YEARS: DEFAULT_MEMORY_YEARS,
            CONF_DUAL_PORTRAIT: DEFAULT_DUAL_PORTRAIT,
            CONF_RESOLUTIONS: DEFAULT_RESOLUTIONS,
            CONF_REFRESH_INTERVAL: DEFAULT_REFRESH_INTERVAL,
            CONF_BACKGROUND_PATH: DEFAULT_BACKGROUND_PATH,
        },
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    # Verify the hub was called to validate new API key
    mock_hub_authenticate_success.authenticate.assert_called_once()


async def test_options_flow_change_api_key_invalid(
    hass: HomeAssistant,
    mock_hub_authenticate_failure: AsyncMock,
) -> None:
    """Test options flow with invalid new API key."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_HOST: MOCK_HOST,
            CONF_API_KEY: MOCK_API_KEY,
        },
        options={
            CONF_DAYS: DEFAULT_DAYS,
            CONF_DUAL_PORTRAIT: DEFAULT_DUAL_PORTRAIT,
            CONF_RESOLUTIONS: DEFAULT_RESOLUTIONS,
            CONF_REFRESH_INTERVAL: DEFAULT_REFRESH_INTERVAL,
            CONF_MEMORY_YEARS: DEFAULT_MEMORY_YEARS,
            CONF_MIX_RATIO: DEFAULT_MIX_RATIO,
            CONF_BACKGROUND_PATH: DEFAULT_BACKGROUND_PATH,
        },
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_API_KEY: "invalid-new-key",
            CONF_DAYS: DEFAULT_DAYS,
            CONF_MIX_RATIO: DEFAULT_MIX_RATIO,
            CONF_MEMORY_YEARS: DEFAULT_MEMORY_YEARS,
            CONF_DUAL_PORTRAIT: DEFAULT_DUAL_PORTRAIT,
            CONF_RESOLUTIONS: DEFAULT_RESOLUTIONS,
            CONF_REFRESH_INTERVAL: DEFAULT_REFRESH_INTERVAL,
            CONF_BACKGROUND_PATH: DEFAULT_BACKGROUND_PATH,
        },
    )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_options_flow_invalid_resolution(
    hass: HomeAssistant,
) -> None:
    """Test options flow with invalid resolution."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_HOST: MOCK_HOST,
            CONF_API_KEY: MOCK_API_KEY,
        },
        options={
            CONF_DAYS: DEFAULT_DAYS,
            CONF_DUAL_PORTRAIT: DEFAULT_DUAL_PORTRAIT,
            CONF_RESOLUTIONS: DEFAULT_RESOLUTIONS,
            CONF_REFRESH_INTERVAL: DEFAULT_REFRESH_INTERVAL,
            CONF_MEMORY_YEARS: DEFAULT_MEMORY_YEARS,
            CONF_MIX_RATIO: DEFAULT_MIX_RATIO,
            CONF_BACKGROUND_PATH: DEFAULT_BACKGROUND_PATH,
        },
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_API_KEY: MOCK_API_KEY,
            CONF_DAYS: DEFAULT_DAYS,
            CONF_MIX_RATIO: DEFAULT_MIX_RATIO,
            CONF_MEMORY_YEARS: DEFAULT_MEMORY_YEARS,
            CONF_DUAL_PORTRAIT: DEFAULT_DUAL_PORTRAIT,
            CONF_RESOLUTIONS: "invalid",
            CONF_REFRESH_INTERVAL: DEFAULT_REFRESH_INTERVAL,
            CONF_BACKGROUND_PATH: DEFAULT_BACKGROUND_PATH,
        },
    )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_resolutions"}


# =============================================================================
# Helper Function Tests
# =============================================================================


def test_parse_resolutions() -> None:
    """Test resolution string parsing."""
    from custom_components.immich_slideshow.const import parse_resolutions

    # Single resolution
    assert parse_resolutions("1920x1080") == [(1920, 1080)]

    # Multiple resolutions
    assert parse_resolutions("1920x1080, 2560x1440") == [(1920, 1080), (2560, 1440)]

    # With extra spaces
    assert parse_resolutions("  1920x1080  ,  1280x720  ") == [(1920, 1080), (1280, 720)]

    # Invalid format returns empty list (for validation to catch)
    assert parse_resolutions("invalid") == []

    # Empty string returns empty list
    assert parse_resolutions("") == []


def test_migrate_legacy_options() -> None:
    """Test migration of legacy width/height to resolutions."""
    from custom_components.immich_slideshow.config_flow import migrate_legacy_options
    from custom_components.immich_slideshow.const import (
        CONF_TARGET_WIDTH,
        CONF_TARGET_HEIGHT,
    )

    # Legacy format with width/height
    legacy_options = {
        CONF_TARGET_WIDTH: 2560,
        CONF_TARGET_HEIGHT: 1440,
        CONF_DAYS: 90,
    }

    migrated = migrate_legacy_options(legacy_options)

    assert CONF_RESOLUTIONS in migrated
    assert migrated[CONF_RESOLUTIONS] == "2560x1440"
    assert CONF_TARGET_WIDTH not in migrated
    assert CONF_TARGET_HEIGHT not in migrated
    assert migrated[CONF_DAYS] == 90

    # New format should pass through unchanged
    new_options = {
        CONF_RESOLUTIONS: "1920x1080",
        CONF_DAYS: 60,
    }

    result = migrate_legacy_options(new_options)
    assert result == new_options
