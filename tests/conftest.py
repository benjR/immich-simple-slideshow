"""Fixtures for Immich Slideshow tests."""
from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, patch

import pytest

from homeassistant.const import CONF_HOST, CONF_API_KEY

# Enable custom integrations for testing
pytest_plugins = ["pytest_homeassistant_custom_component"]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations for all tests."""
    yield

# Test data
MOCK_HOST = "http://immich.local:2283"
MOCK_API_KEY = "test-api-key-12345"

# Step 1: Host URL only
MOCK_HOST_INPUT = {
    CONF_HOST: MOCK_HOST,
}

# Step 2: API key and options
MOCK_API_KEY_INPUT = {
    CONF_API_KEY: MOCK_API_KEY,
}

# Legacy combined input (for backward compatibility in some tests)
MOCK_USER_INPUT = {
    CONF_HOST: MOCK_HOST,
    CONF_API_KEY: MOCK_API_KEY,
}


@pytest.fixture
def mock_hub_authenticate_success() -> Generator[AsyncMock, None, None]:
    """Mock ImmichHub with successful authentication."""
    with patch(
        "custom_components.immich_slideshow.config_flow.ImmichHub"
    ) as mock_hub_class:
        mock_hub = AsyncMock()
        mock_hub.authenticate.return_value = True
        mock_hub.close.return_value = None
        mock_hub_class.return_value = mock_hub
        yield mock_hub


@pytest.fixture
def mock_hub_authenticate_failure() -> Generator[AsyncMock, None, None]:
    """Mock ImmichHub with failed authentication."""
    with patch(
        "custom_components.immich_slideshow.config_flow.ImmichHub"
    ) as mock_hub_class:
        mock_hub = AsyncMock()
        mock_hub.authenticate.return_value = False
        mock_hub.close.return_value = None
        mock_hub_class.return_value = mock_hub
        yield mock_hub


@pytest.fixture
def mock_hub_cannot_connect() -> Generator[AsyncMock, None, None]:
    """Mock ImmichHub that raises CannotConnect."""
    with patch(
        "custom_components.immich_slideshow.config_flow.ImmichHub"
    ) as mock_hub_class:
        from custom_components.immich_slideshow.hub import CannotConnect

        mock_hub = AsyncMock()
        mock_hub.authenticate.side_effect = CannotConnect()
        mock_hub.close.return_value = None
        mock_hub_class.return_value = mock_hub
        yield mock_hub


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock, None, None]:
    """Mock async_setup_entry."""
    with patch(
        "custom_components.immich_slideshow.async_setup_entry",
        return_value=True,
    ) as mock_setup:
        yield mock_setup
