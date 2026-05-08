"""Tests for Immich Slideshow diagnostic sensors."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.immich_slideshow.const import DOMAIN
from custom_components.immich_slideshow.sensor import (
    ImmichDiagnosticSensor,
    SENSOR_DESCRIPTIONS,
)


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def mock_manager() -> MagicMock:
    """Create a mock SlideshowManager."""
    manager = MagicMock()
    manager._asset_pool = [
        {"id": "1", "_source": "recent"},
        {"id": "2", "_source": "recent"},
        {"id": "3", "_source": "memory"},
    ]
    manager.source = "recent"
    manager._current_asset1 = {"id": "1", "memory_year": None}
    manager._next_img1 = MagicMock()  # Prefetch ready
    manager._next_is_dual = False
    manager._prefetch_task = None
    manager.memory_year = None
    manager.years_ago = None
    return manager


@pytest.fixture
def mock_config_entry() -> MagicMock:
    """Create a mock config entry."""
    entry = MagicMock()
    entry.entry_id = "test_entry_123"
    entry.title = "Test Immich"
    return entry


# =============================================================================
# Pool Size Sensor Tests
# =============================================================================


def test_pool_size_sensor_native_value(mock_config_entry, mock_manager):
    """Test pool size sensor returns correct count."""
    description = SENSOR_DESCRIPTIONS[0]  # pool_size
    sensor = ImmichDiagnosticSensor(
        config_entry=mock_config_entry,
        description=description,
        manager=mock_manager,
    )

    assert sensor.native_value == 3  # 3 items in pool


def test_pool_size_sensor_source_distribution(mock_config_entry, mock_manager):
    """Test pool size sensor includes source distribution."""
    description = SENSOR_DESCRIPTIONS[0]  # pool_size
    sensor = ImmichDiagnosticSensor(
        config_entry=mock_config_entry,
        description=description,
        manager=mock_manager,
    )

    attrs = sensor.extra_state_attributes
    assert "source_distribution" in attrs
    assert attrs["source_distribution"]["recent"] == 2
    assert attrs["source_distribution"]["memory"] == 1
    assert attrs["max_pool_size"] == 200
    assert attrs["refill_threshold"] == 20


def test_pool_size_sensor_empty_pool(mock_config_entry, mock_manager):
    """Test pool size sensor with empty pool."""
    mock_manager._asset_pool = []
    description = SENSOR_DESCRIPTIONS[0]  # pool_size
    sensor = ImmichDiagnosticSensor(
        config_entry=mock_config_entry,
        description=description,
        manager=mock_manager,
    )

    assert sensor.native_value == 0
    assert sensor.extra_state_attributes["source_distribution"] == {}


# =============================================================================
# Current Source Sensor Tests
# =============================================================================


def test_current_source_sensor_native_value(mock_config_entry, mock_manager):
    """Test current source sensor returns source type."""
    description = SENSOR_DESCRIPTIONS[1]  # current_source
    sensor = ImmichDiagnosticSensor(
        config_entry=mock_config_entry,
        description=description,
        manager=mock_manager,
    )

    assert sensor.native_value == "recent"


def test_current_source_sensor_attributes(mock_config_entry, mock_manager):
    """Test current source sensor includes asset ID."""
    mock_manager._current_asset1 = {"id": "asset-123"}
    description = SENSOR_DESCRIPTIONS[1]  # current_source
    sensor = ImmichDiagnosticSensor(
        config_entry=mock_config_entry,
        description=description,
        manager=mock_manager,
    )

    attrs = sensor.extra_state_attributes
    assert attrs["asset_id"] == "asset-123"


def test_current_source_sensor_memory_year(mock_config_entry, mock_manager):
    """Test current source sensor includes memory year when applicable."""
    mock_manager.source = "memory"
    mock_manager.memory_year = 2020
    mock_manager.years_ago = 4
    description = SENSOR_DESCRIPTIONS[1]  # current_source
    sensor = ImmichDiagnosticSensor(
        config_entry=mock_config_entry,
        description=description,
        manager=mock_manager,
    )

    attrs = sensor.extra_state_attributes
    assert attrs["memory_year"] == 2020
    assert attrs["years_ago"] == 4


# =============================================================================
# Prefetch Status Sensor Tests
# =============================================================================


def test_prefetch_status_ready(mock_config_entry, mock_manager):
    """Test prefetch status when image is ready."""
    mock_manager._next_img1 = MagicMock()  # Not None = ready
    description = SENSOR_DESCRIPTIONS[2]  # prefetch_status
    sensor = ImmichDiagnosticSensor(
        config_entry=mock_config_entry,
        description=description,
        manager=mock_manager,
    )

    assert sensor.native_value == "ready"


def test_prefetch_status_fetching(mock_config_entry, mock_manager):
    """Test prefetch status when task is running."""
    mock_manager._next_img1 = None
    mock_task = MagicMock()
    mock_task.done.return_value = False
    mock_manager._prefetch_task = mock_task

    description = SENSOR_DESCRIPTIONS[2]  # prefetch_status
    sensor = ImmichDiagnosticSensor(
        config_entry=mock_config_entry,
        description=description,
        manager=mock_manager,
    )

    assert sensor.native_value == "fetching"


def test_prefetch_status_idle(mock_config_entry, mock_manager):
    """Test prefetch status when no task and no image."""
    mock_manager._next_img1 = None
    mock_manager._prefetch_task = None

    description = SENSOR_DESCRIPTIONS[2]  # prefetch_status
    sensor = ImmichDiagnosticSensor(
        config_entry=mock_config_entry,
        description=description,
        manager=mock_manager,
    )

    assert sensor.native_value == "idle"


def test_prefetch_status_attributes(mock_config_entry, mock_manager):
    """Test prefetch status includes dual portrait flag."""
    mock_manager._next_img1 = MagicMock()
    mock_manager._next_is_dual = True

    description = SENSOR_DESCRIPTIONS[2]  # prefetch_status
    sensor = ImmichDiagnosticSensor(
        config_entry=mock_config_entry,
        description=description,
        manager=mock_manager,
    )

    attrs = sensor.extra_state_attributes
    assert attrs["is_dual_portrait"] is True


# =============================================================================
# Sensor Availability Tests
# =============================================================================


def test_sensor_available_with_manager(mock_config_entry, mock_manager):
    """Test sensor is available when manager exists."""
    description = SENSOR_DESCRIPTIONS[0]
    sensor = ImmichDiagnosticSensor(
        config_entry=mock_config_entry,
        description=description,
        manager=mock_manager,
    )

    assert sensor.available is True


def test_sensor_unavailable_without_manager(mock_config_entry):
    """Test sensor is unavailable when manager is None."""
    description = SENSOR_DESCRIPTIONS[0]
    sensor = ImmichDiagnosticSensor(
        config_entry=mock_config_entry,
        description=description,
        manager=None,
    )

    # Without hass, it can't look up the manager
    assert sensor.available is False


def test_sensor_native_value_none_without_manager(mock_config_entry):
    """Test sensor returns None when manager is None."""
    description = SENSOR_DESCRIPTIONS[0]
    sensor = ImmichDiagnosticSensor(
        config_entry=mock_config_entry,
        description=description,
        manager=None,
    )

    assert sensor.native_value is None


# =============================================================================
# Device Info Tests
# =============================================================================


def test_sensor_device_info(mock_config_entry, mock_manager):
    """Test sensor returns correct device info for grouping."""
    description = SENSOR_DESCRIPTIONS[0]
    sensor = ImmichDiagnosticSensor(
        config_entry=mock_config_entry,
        description=description,
        manager=mock_manager,
    )

    device_info = sensor.device_info
    assert device_info["identifiers"] == {(DOMAIN, "test_entry_123")}
    assert device_info["name"] == "Immich Slideshow"
    assert device_info["manufacturer"] == "Immich"


def test_sensor_unique_id(mock_config_entry, mock_manager):
    """Test sensor has correct unique ID format."""
    description = SENSOR_DESCRIPTIONS[0]  # pool_size
    sensor = ImmichDiagnosticSensor(
        config_entry=mock_config_entry,
        description=description,
        manager=mock_manager,
    )

    assert sensor.unique_id == "test_entry_123_pool_size"
