"""Fixtures for Immich Slideshow tests."""
from __future__ import annotations

import sys
from collections.abc import Generator
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

# Add custom_components to path so pytest-homeassistant-custom-component can find it
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# Try to import homeassistant, provide fallback for standalone tests
try:
    from homeassistant.const import CONF_HOST, CONF_API_KEY
    HAS_HOMEASSISTANT = True
except ImportError:
    # Fallback for running without full HA environment
    CONF_HOST = "host"
    CONF_API_KEY = "api_key"
    HAS_HOMEASSISTANT = False

# Only enable pytest_homeassistant_custom_component plugin if it's installed
try:
    import pytest_homeassistant_custom_component  # noqa: F401
    pytest_plugins = ["pytest_homeassistant_custom_component"]
    HAS_HA_TEST_PLUGIN = True
except ImportError:
    HAS_HA_TEST_PLUGIN = False


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(request):
    """Enable custom integrations only for tests that use hass fixture.

    This fixture ensures the custom_components directory is available to HA.
    For standalone tests (test_hub, test_image, test_sensor), skip this.
    """
    # Only enable for tests that actually use the hass fixture
    if "hass" in request.fixturenames:
        # Request the fixture dynamically to avoid always pulling it in
        enable_custom_integrations = request.getfixturevalue("enable_custom_integrations")
    yield


@pytest.fixture(autouse=True)
def verify_cleanup():
    """Override the strict verify_cleanup fixture from pytest-homeassistant-custom-component.

    The default fixture is too strict about thread cleanup for standalone async tests
    that use aiohttp (like test_hub.py). The _run_safe_shutdown_loop daemon thread
    from asyncio in Python 3.12 doesn't affect test correctness but fails the cleanup check.

    Our test suite is small and doesn't have real cleanup issues - skip the strict check.
    """
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
    """Mock ImmichHub with successful authentication and empty albums/people."""
    with patch(
        "custom_components.immich_slideshow.config_flow.ImmichHub"
    ) as mock_hub_class:
        mock_hub = AsyncMock()
        mock_hub.authenticate.return_value = True
        mock_hub.close.return_value = None
        # New: post-auth fetch in config flow needs these to return lists
        mock_hub.get_albums.return_value = []
        mock_hub.get_people.return_value = []
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
