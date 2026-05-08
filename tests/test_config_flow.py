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
    CONF_SOURCE_RECENT_WEIGHT,
    CONF_SOURCE_MEMORIES_WEIGHT,
    CONF_RECENT_DAYS,
    CONF_RECENT_FAVORITES_FILTER,
    CONF_RESOLUTIONS,
    CONF_REFRESH_INTERVAL,
    CONF_BACKGROUND_PATH,
    DEFAULT_RESOLUTIONS,
    DOMAIN,
)

from .conftest import MOCK_API_KEY, MOCK_HOST, MOCK_HOST_INPUT, MOCK_API_KEY_INPUT


# =============================================================================
# Config Flow: User Step Tests
# =============================================================================


async def test_user_flow_success(
    hass: HomeAssistant,
    mock_hub_authenticate_success: AsyncMock,
    mock_setup_entry: AsyncMock,
) -> None:
    """Test successful 3-step user config flow: URL → API key → settings → entry."""
    # Step 1: URL
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=MOCK_HOST_INPUT
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "api_key"

    # Step 2: API key (auth + fetch albums/people)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=MOCK_API_KEY_INPUT
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "settings"

    # Step 3: Submit settings (defaults are sufficient — at least one source has weight)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            "source_weights": {
                "source_recent_weight": 50,
                "source_memories_weight": 50,
                "source_albums_weight": 0,
                "source_persons_weight": 0,
            },
            "recent_source": {},
            "memories_source": {},
            "advanced": {},
        },
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Immich Slideshow"
    assert result["data"][CONF_HOST] == MOCK_HOST
    assert result["data"][CONF_API_KEY] == MOCK_API_KEY
    # New: options carry the v2 schema, populated from the settings step
    assert result["options"]["source_recent_weight"] == 50
    assert result["options"]["source_memories_weight"] == 50


async def test_user_flow_invalid_auth(
    hass: HomeAssistant,
    mock_hub_authenticate_failure: AsyncMock,
) -> None:
    """Test config flow with invalid authentication."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input=MOCK_HOST_INPUT,
    )
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
    """Test config flow when cannot connect to host."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input=MOCK_HOST_INPUT,
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input=MOCK_API_KEY_INPUT,
    )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "api_key"
    assert result["errors"] == {"base": "cannot_connect"}


# =============================================================================
# Helper Function Tests
# =============================================================================


def test_parse_resolutions_valid():
    """Test parsing valid resolution strings."""
    from custom_components.immich_slideshow.const import parse_resolutions

    # Single resolution
    assert parse_resolutions("1920x1080") == [(1920, 1080)]

    # Multiple resolutions
    result = parse_resolutions("1920x1080, 2560x1440")
    assert result == [(1920, 1080), (2560, 1440)]

    # With extra whitespace
    result = parse_resolutions("  1920x1080  ,  2560x1440  ")
    assert result == [(1920, 1080), (2560, 1440)]


def test_parse_resolutions_invalid_format():
    """Test parsing invalid resolution format returns empty list."""
    from custom_components.immich_slideshow.const import parse_resolutions

    # parse_resolutions returns empty list for invalid formats
    assert parse_resolutions("invalid") == []
    assert parse_resolutions("1920-1080") == []
    assert parse_resolutions("") == []
    assert parse_resolutions("not a resolution") == []


def test_parse_resolutions_partial_valid():
    """Test parsing mixed valid/invalid resolutions keeps only valid ones."""
    from custom_components.immich_slideshow.const import parse_resolutions

    # parse_resolutions skips invalid parts and keeps valid ones
    result = parse_resolutions("1920x1080, invalid, 2560x1440")
    assert result == [(1920, 1080), (2560, 1440)]

    # All values are parsed regardless of range (range validation is separate)
    result = parse_resolutions("100x100")
    assert result == [(100, 100)]


# =============================================================================
# Migration Tests (v1 → v2)
# =============================================================================


async def test_migrate_v1_to_v2_basic(hass: HomeAssistant) -> None:
    """Test v1 → v2 migration: mix_ratio splits into recent/memories weights."""
    from custom_components.immich_slideshow import async_migrate_entry
    from custom_components.immich_slideshow.const import (
        CONF_DAYS,
        CONF_FAVORITES_FILTER,
        CONF_MEMORIES_MAX_YEARS,
        CONF_MEMORY_YEARS,
        CONF_MIX_RATIO,
        CONF_RECENT_DAYS,
        CONF_RECENT_FAVORITES_FILTER,
        CONF_SOURCE_ALBUMS_WEIGHT,
        CONF_SOURCE_MEMORIES_WEIGHT,
        CONF_SOURCE_PERSONS_WEIGHT,
        CONF_SOURCE_RECENT_WEIGHT,
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        version=1,
        data={CONF_HOST: MOCK_HOST, CONF_API_KEY: MOCK_API_KEY},
        options={
            CONF_MIX_RATIO: 30,
            CONF_DAYS: 60,
            CONF_MEMORY_YEARS: 5,
            CONF_FAVORITES_FILTER: "only",
        },
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry) is True
    assert entry.version == 2

    opts = entry.options
    assert opts[CONF_SOURCE_RECENT_WEIGHT] == 70
    assert opts[CONF_SOURCE_MEMORIES_WEIGHT] == 30
    assert opts[CONF_SOURCE_ALBUMS_WEIGHT] == 0
    assert opts[CONF_SOURCE_PERSONS_WEIGHT] == 0
    assert opts[CONF_RECENT_DAYS] == 60
    assert opts[CONF_RECENT_FAVORITES_FILTER] == "only"
    assert opts[CONF_MEMORIES_MAX_YEARS] == 5
    # Legacy keys must be purged
    assert CONF_MIX_RATIO not in opts
    assert CONF_DAYS not in opts
    assert CONF_MEMORY_YEARS not in opts
    assert CONF_FAVORITES_FILTER not in opts


async def test_migrate_v1_to_v2_defaults(hass: HomeAssistant) -> None:
    """Test v1 → v2 migration with empty options applies sensible defaults."""
    from custom_components.immich_slideshow import async_migrate_entry
    from custom_components.immich_slideshow.const import (
        CONF_SOURCE_MEMORIES_WEIGHT,
        CONF_SOURCE_RECENT_WEIGHT,
        DEFAULT_RESOLUTIONS,
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        version=1,
        data={CONF_HOST: MOCK_HOST, CONF_API_KEY: MOCK_API_KEY},
        options={},
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry) is True
    assert entry.version == 2

    opts = entry.options
    # mix_ratio defaults to 0 → 100% recent
    assert opts[CONF_SOURCE_RECENT_WEIGHT] == 100
    assert opts[CONF_SOURCE_MEMORIES_WEIGHT] == 0
    assert opts[CONF_RESOLUTIONS] == DEFAULT_RESOLUTIONS


async def test_migrate_v1_to_v2_legacy_width_height(hass: HomeAssistant) -> None:
    """Test v1 → v2 migration converts target_width/target_height into resolutions string."""
    from custom_components.immich_slideshow import async_migrate_entry
    from custom_components.immich_slideshow.const import (
        CONF_RESOLUTIONS,
        CONF_TARGET_HEIGHT,
        CONF_TARGET_WIDTH,
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        version=1,
        data={CONF_HOST: MOCK_HOST, CONF_API_KEY: MOCK_API_KEY},
        options={CONF_TARGET_WIDTH: 2560, CONF_TARGET_HEIGHT: 1440},
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry) is True
    opts = entry.options
    assert opts[CONF_RESOLUTIONS] == "2560x1440"
    assert CONF_TARGET_WIDTH not in opts
    assert CONF_TARGET_HEIGHT not in opts


async def test_migrate_v1_to_v2_resolutions_takes_priority(hass: HomeAssistant) -> None:
    """Test v1 → v2 migration: existing CONF_RESOLUTIONS wins over legacy width/height."""
    from custom_components.immich_slideshow import async_migrate_entry
    from custom_components.immich_slideshow.const import (
        CONF_RESOLUTIONS,
        CONF_TARGET_HEIGHT,
        CONF_TARGET_WIDTH,
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        version=1,
        data={CONF_HOST: MOCK_HOST, CONF_API_KEY: MOCK_API_KEY},
        options={
            CONF_RESOLUTIONS: "1920x1080,3840x2160",
            CONF_TARGET_WIDTH: 1024,  # stale legacy values
            CONF_TARGET_HEIGHT: 768,
        },
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry) is True
    opts = entry.options
    assert opts[CONF_RESOLUTIONS] == "1920x1080,3840x2160"
    assert CONF_TARGET_WIDTH not in opts
    assert CONF_TARGET_HEIGHT not in opts


async def test_migrate_v1_to_v2_promotes_options_api_key_to_data(hass: HomeAssistant) -> None:
    """Test v1 → v2 migration: api_key in options is promoted to data and dropped from options."""
    from custom_components.immich_slideshow import async_migrate_entry

    # User updated api_key via v1 options flow → options has newer key than data
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=1,
        data={CONF_HOST: MOCK_HOST, CONF_API_KEY: "old-key-in-data"},
        options={CONF_API_KEY: "new-key-in-options"},
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry) is True
    # Newer options key promoted to data
    assert entry.data[CONF_API_KEY] == "new-key-in-options"
    # Removed from options (secrets live in data only post-v2)
    assert CONF_API_KEY not in entry.options


async def test_migrate_v1_to_v2_keeps_data_api_key_when_matching(hass: HomeAssistant) -> None:
    """Test v1 → v2 migration: identical api_key in data and options leaves data untouched."""
    from custom_components.immich_slideshow import async_migrate_entry

    entry = MockConfigEntry(
        domain=DOMAIN,
        version=1,
        data={CONF_HOST: MOCK_HOST, CONF_API_KEY: "same-key"},
        options={CONF_API_KEY: "same-key"},
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry) is True
    assert entry.data[CONF_API_KEY] == "same-key"
    assert CONF_API_KEY not in entry.options


async def test_migrate_v2_is_noop(hass: HomeAssistant) -> None:
    """Test that an already-v2 entry is left untouched."""
    from custom_components.immich_slideshow import async_migrate_entry
    from custom_components.immich_slideshow.const import (
        CONF_SOURCE_MEMORIES_WEIGHT,
        CONF_SOURCE_RECENT_WEIGHT,
    )

    v2_options = {
        CONF_SOURCE_RECENT_WEIGHT: 75,
        CONF_SOURCE_MEMORIES_WEIGHT: 25,
    }
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        data={CONF_HOST: MOCK_HOST, CONF_API_KEY: MOCK_API_KEY},
        options=v2_options,
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry) is True
    assert entry.version == 2
    assert entry.options[CONF_SOURCE_RECENT_WEIGHT] == 75
    assert entry.options[CONF_SOURCE_MEMORIES_WEIGHT] == 25
