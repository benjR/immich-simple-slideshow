"""Tests for Immich Slideshow image entity and SlideshowManager."""
from __future__ import annotations

import asyncio
import io
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from custom_components.immich_slideshow.const import DOMAIN
from custom_components.immich_slideshow.image import (
    ImmichSlideshowImage,
    SlideshowManager,
    is_portrait,
)

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def mock_hub() -> AsyncMock:
    """Create a mock ImmichHub."""
    hub = AsyncMock()
    hub._host = "http://immich.local:2283"
    hub.authenticate.return_value = True
    hub.close.return_value = None
    hub.search_random_recent.return_value = []
    hub.get_memory_assets.return_value = []
    hub.search_random_from_albums.return_value = []
    hub.search_random_in_any_album.return_value = []
    hub.search_random_by_person.return_value = []
    hub.get_asset_info.return_value = None
    hub.download_asset.return_value = None
    return hub


@pytest.fixture
def manager(mock_hub: AsyncMock) -> SlideshowManager:
    """Create a SlideshowManager with default settings."""
    return SlideshowManager(
        hub=mock_hub,
        dual_portrait=True,
        source_recent_weight=50,
        source_memories_weight=50,
        source_albums_weight=0,
        source_persons_weight=0,
        recent_days=90,
        recent_favorites_filter="all",
        memories_max_years=0,
        albums_include=None,
        persons_include=None,
        exclude_albums=None,
        exclude_persons=None,
    )


def create_test_image(width: int, height: int, mode: str = "RGB") -> bytes:
    """Create a test image and return as JPEG bytes."""
    img = Image.new(mode, (width, height), color="red")
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG")
    return buffer.getvalue()


def create_landscape_asset(
    asset_id: str = "asset-1",
    width: int = 4000,
    height: int = 3000,
    orientation: int = 1,
    source: str = "recent",
) -> dict[str, Any]:
    """Create a mock landscape asset dict."""
    return {
        "id": asset_id,
        "type": "IMAGE",
        "originalWidth": width,
        "originalHeight": height,
        "originalFileName": f"{asset_id}.jpg",
        "isFavorite": False,
        "localDateTime": "2024-01-15T12:00:00",
        "exifInfo": {
            "exifImageWidth": width,
            "exifImageHeight": height,
            "orientation": orientation,
            "dateTimeOriginal": "2024-01-15T12:00:00",
            "city": "Paris",
            "country": "France",
            "description": "A beautiful landscape",
        },
        "people": [{"id": "person-1", "name": "John Doe"}],
        "_source": source,
    }


def create_portrait_asset(
    asset_id: str = "portrait-1",
    width: int = 3000,
    height: int = 4000,
    orientation: int = 1,
    source: str = "recent",
) -> dict[str, Any]:
    """Create a mock portrait asset dict."""
    return {
        "id": asset_id,
        "type": "IMAGE",
        "originalWidth": width,
        "originalHeight": height,
        "originalFileName": f"{asset_id}.jpg",
        "isFavorite": True,
        "localDateTime": "2024-01-10T10:00:00",
        "exifInfo": {
            "exifImageWidth": width,
            "exifImageHeight": height,
            "orientation": orientation,
            "dateTimeOriginal": "2024-01-10T10:00:00",
            "city": "London",
            "country": "UK",
        },
        "people": [],
        "_source": source,
    }


# =============================================================================
# is_portrait() Function Tests
# =============================================================================


def test_is_portrait_landscape_image() -> None:
    """Test is_portrait returns False for landscape image (width > height, no rotation)."""
    asset = create_landscape_asset(width=4000, height=3000, orientation=1)
    assert is_portrait(asset) is False


def test_is_portrait_portrait_image() -> None:
    """Test is_portrait returns True for portrait image (height > width, no rotation)."""
    asset = create_portrait_asset(width=3000, height=4000, orientation=1)
    assert is_portrait(asset) is True


def test_is_portrait_missing_dimensions() -> None:
    """Test is_portrait returns False when width=0 or height=0."""
    # Missing width
    asset_no_width = {"originalWidth": 0, "originalHeight": 4000, "exifInfo": {}}
    assert is_portrait(asset_no_width) is False

    # Missing height
    asset_no_height = {"originalWidth": 3000, "originalHeight": 0, "exifInfo": {}}
    assert is_portrait(asset_no_height) is False

    # Both missing
    asset_both_missing = {"originalWidth": 0, "originalHeight": 0, "exifInfo": {}}
    assert is_portrait(asset_both_missing) is False


def test_is_portrait_missing_exif() -> None:
    """Test is_portrait when exifInfo key is missing."""
    asset = {"originalWidth": 3000, "originalHeight": 4000}
    assert is_portrait(asset) is True

    # Also test with exifInfo=None
    asset_none_exif = {"originalWidth": 4000, "originalHeight": 3000, "exifInfo": None}
    assert is_portrait(asset_none_exif) is False


@pytest.mark.parametrize("orientation", [5, 6, 7, 8])
def test_is_portrait_rotated_orientation_5_to_8(orientation: int) -> None:
    """Test 90 degree rotation swaps dimensions for orientations 5-8.

    When orientation is 5-8, a landscape stored image (width > height)
    should be detected as portrait after rotation.
    """
    # Stored as landscape (4000x3000) but rotated 90 degrees
    asset = {
        "originalWidth": 4000,
        "originalHeight": 3000,
        "exifInfo": {"orientation": orientation},
    }
    # After rotation, it becomes portrait
    assert is_portrait(asset) is True

    # Stored as portrait (3000x4000) but rotated 90 degrees
    asset_stored_portrait = {
        "originalWidth": 3000,
        "originalHeight": 4000,
        "exifInfo": {"orientation": orientation},
    }
    # After rotation, it becomes landscape
    assert is_portrait(asset_stored_portrait) is False


def test_is_portrait_invalid_orientation_string() -> None:
    """Test is_portrait with invalid string orientation."""
    asset = {
        "originalWidth": 3000,
        "originalHeight": 4000,
        "exifInfo": {"orientation": "invalid"},
    }
    # Invalid orientation is treated as 0, so no rotation
    assert is_portrait(asset) is True


def test_is_portrait_invalid_orientation_none() -> None:
    """Test is_portrait with None orientation."""
    asset = {
        "originalWidth": 3000,
        "originalHeight": 4000,
        "exifInfo": {"orientation": None},
    }
    # None is treated as 0, so no rotation
    assert is_portrait(asset) is True


def test_is_portrait_square_image() -> None:
    """Test is_portrait returns False for square image."""
    asset = {
        "originalWidth": 4000,
        "originalHeight": 4000,
        "exifInfo": {"orientation": 1},
    }
    assert is_portrait(asset) is False


# =============================================================================
# SlideshowManager Init Tests
# =============================================================================


def test_manager_init_sets_defaults(mock_hub: AsyncMock) -> None:
    """Test SlideshowManager initialization sets all default values."""
    manager = SlideshowManager(
        hub=mock_hub,
        dual_portrait=True,
    )

    assert manager._hub == mock_hub
    assert manager._dual_portrait is True
    assert manager._source_weights == {
        "recent": 50,
        "memories": 50,
        "albums": 0,
        "persons": 0,
    }
    assert manager._recent_days == 90
    assert manager._recent_favorites_filter == "all"
    assert manager._memories_max_years == 0
    assert manager._albums_include == []
    assert manager._persons_include == []
    assert manager._exclude_albums == set()
    assert manager._exclude_persons == set()
    assert manager._asset_pool == []
    assert manager._current_img1 is None
    assert manager._current_img2 is None
    assert manager._is_dual is False
    assert manager._pool_empty is False


# =============================================================================
# SlideshowManager._normalize_weights Tests
# =============================================================================


def test_manager_normalize_weights_all_zero_returns_empty(mock_hub: AsyncMock) -> None:
    """Test _normalize_weights returns empty dict when all weights are 0."""
    manager = SlideshowManager(
        hub=mock_hub,
        dual_portrait=False,
        source_recent_weight=0,
        source_memories_weight=0,
        source_albums_weight=0,
        source_persons_weight=0,
    )

    weights = manager._normalize_weights()
    assert weights == {}


def test_manager_normalize_weights_single_source(mock_hub: AsyncMock) -> None:
    """Test _normalize_weights with only one source enabled."""
    manager = SlideshowManager(
        hub=mock_hub,
        dual_portrait=False,
        source_recent_weight=100,
        source_memories_weight=0,
        source_albums_weight=0,
        source_persons_weight=0,
    )

    weights = manager._normalize_weights()
    assert weights == {"recent": 1.0}


def test_manager_normalize_weights_multiple_sources(mock_hub: AsyncMock) -> None:
    """Test _normalize_weights with multiple sources."""
    manager = SlideshowManager(
        hub=mock_hub,
        dual_portrait=False,
        source_recent_weight=50,
        source_memories_weight=30,
        source_albums_weight=20,
        source_persons_weight=0,  # No persons selected
    )

    weights = manager._normalize_weights()
    # Total = 50 + 30 + 20 = 100
    assert weights == pytest.approx({"recent": 0.5, "memories": 0.3, "albums": 0.2})


def test_manager_normalize_weights_persons_without_selection_excluded(
    mock_hub: AsyncMock,
) -> None:
    """Test persons source is excluded when no persons are selected."""
    manager = SlideshowManager(
        hub=mock_hub,
        dual_portrait=False,
        source_recent_weight=50,
        source_memories_weight=50,
        source_albums_weight=0,
        source_persons_weight=100,  # High weight but...
        persons_include=[],  # ...no persons selected
    )

    weights = manager._normalize_weights()
    # Persons should not appear in weights since persons_include is empty
    assert "persons" not in weights
    assert weights == pytest.approx({"recent": 0.5, "memories": 0.5})


def test_manager_normalize_weights_persons_with_selection(mock_hub: AsyncMock) -> None:
    """Test persons source is included when persons are selected."""
    manager = SlideshowManager(
        hub=mock_hub,
        dual_portrait=False,
        source_recent_weight=40,
        source_memories_weight=30,
        source_albums_weight=0,
        source_persons_weight=30,
        persons_include=["person-1", "person-2"],
    )

    weights = manager._normalize_weights()
    # Total = 40 + 30 + 30 = 100
    assert "persons" in weights
    assert weights == pytest.approx({"recent": 0.4, "memories": 0.3, "persons": 0.3})


# =============================================================================
# SlideshowManager._calculate_source_counts Tests
# =============================================================================


def test_manager_calculate_source_counts_proportional(
    manager: SlideshowManager,
) -> None:
    """Test _calculate_source_counts distributes proportionally."""
    weights = {"recent": 0.5, "memories": 0.3, "albums": 0.2}
    total = 100

    counts = manager._calculate_source_counts(weights, total)

    # Should get approximately proportional distribution
    assert counts["recent"] >= 45  # ~50
    assert counts["memories"] >= 25  # ~30
    assert counts["albums"] >= 15  # ~20

    # Total should equal input
    assert sum(counts.values()) == total


def test_manager_calculate_source_counts_minimum_one(
    manager: SlideshowManager,
) -> None:
    """Test each source gets at least 1 even with tiny weight."""
    weights = {"recent": 0.99, "memories": 0.01}
    total = 10

    counts = manager._calculate_source_counts(weights, total)

    # Both should have at least 1
    assert counts["recent"] >= 1
    assert counts["memories"] >= 1


# =============================================================================
# SlideshowManager._pop_from_pool Tests
# =============================================================================


def test_manager_pop_from_pool_basic(manager: SlideshowManager) -> None:
    """Test basic pop from pool functionality."""
    asset1 = create_landscape_asset("asset-1")
    asset2 = create_landscape_asset("asset-2")
    asset3 = create_landscape_asset("asset-3")
    manager._asset_pool = [asset1, asset2, asset3]

    result = manager._pop_from_pool(count=2)

    assert len(result) == 2
    assert result[0]["id"] == "asset-1"
    assert result[1]["id"] == "asset-2"
    assert len(manager._asset_pool) == 1
    assert manager._asset_pool[0]["id"] == "asset-3"


def test_manager_pop_from_pool_portrait_only(manager: SlideshowManager) -> None:
    """Test pop from pool with portrait_only filter."""
    landscape = create_landscape_asset("landscape-1")
    portrait1 = create_portrait_asset("portrait-1")
    portrait2 = create_portrait_asset("portrait-2")
    manager._asset_pool = [landscape, portrait1, portrait2]

    result = manager._pop_from_pool(count=2, portrait_only=True)

    assert len(result) == 2
    assert result[0]["id"] == "portrait-1"
    assert result[1]["id"] == "portrait-2"
    # Landscape should remain in pool
    assert len(manager._asset_pool) == 1
    assert manager._asset_pool[0]["id"] == "landscape-1"


def test_manager_pop_from_pool_empty_pool(manager: SlideshowManager) -> None:
    """Test pop from empty pool returns empty list."""
    manager._asset_pool = []

    result = manager._pop_from_pool(count=5)

    assert result == []


def test_manager_pop_from_pool_portrait_only_no_portraits(
    manager: SlideshowManager,
) -> None:
    """Test pop portrait_only when pool has no portraits."""
    landscape1 = create_landscape_asset("landscape-1")
    landscape2 = create_landscape_asset("landscape-2")
    manager._asset_pool = [landscape1, landscape2]

    result = manager._pop_from_pool(count=1, portrait_only=True)

    assert result == []
    # All landscapes should remain
    assert len(manager._asset_pool) == 2


# =============================================================================
# SlideshowManager._apply_global_exclusions Tests
# =============================================================================


def test_manager_apply_global_exclusions_by_album(mock_hub: AsyncMock) -> None:
    """Test assets in excluded albums are filtered out."""
    manager = SlideshowManager(
        hub=mock_hub,
        dual_portrait=False,
        exclude_albums=["album-bad"],
    )

    asset_good = create_landscape_asset("asset-1")
    asset_good["albumIds"] = ["album-good"]

    asset_bad = create_landscape_asset("asset-2")
    asset_bad["albumIds"] = ["album-bad"]

    asset_also_bad = create_landscape_asset("asset-3")
    asset_also_bad["_album_id"] = "album-bad"

    assets = [asset_good, asset_bad, asset_also_bad]
    filtered = manager._apply_global_exclusions(assets)

    assert len(filtered) == 1
    assert filtered[0]["id"] == "asset-1"


def test_manager_apply_global_exclusions_by_person(mock_hub: AsyncMock) -> None:
    """Test assets with excluded persons are filtered out."""
    manager = SlideshowManager(
        hub=mock_hub,
        dual_portrait=False,
        exclude_persons=["person-bad"],
    )

    asset_good = create_landscape_asset("asset-1")
    asset_good["people"] = [{"id": "person-good", "name": "Good Person"}]

    asset_bad = create_landscape_asset("asset-2")
    asset_bad["people"] = [{"id": "person-bad", "name": "Bad Person"}]

    assets = [asset_good, asset_bad]
    filtered = manager._apply_global_exclusions(assets)

    assert len(filtered) == 1
    assert filtered[0]["id"] == "asset-1"


def test_manager_apply_global_exclusions_no_exclusions(
    manager: SlideshowManager,
) -> None:
    """Test no filtering when no exclusions are set."""
    asset1 = create_landscape_asset("asset-1")
    asset2 = create_landscape_asset("asset-2")
    assets = [asset1, asset2]

    # Manager has no exclusions by default
    filtered = manager._apply_global_exclusions(assets)

    assert len(filtered) == 2


# =============================================================================
# SlideshowManager.is_available Tests
# =============================================================================


def test_manager_is_available_false_when_pool_empty(
    manager: SlideshowManager,
) -> None:
    """Test is_available returns False when pool is empty."""
    manager._pool_empty = True
    assert manager.is_available is False


def test_manager_is_available_true_when_pool_has_items(
    manager: SlideshowManager,
) -> None:
    """Test is_available returns True when pool has items."""
    manager._pool_empty = False
    assert manager.is_available is True


# =============================================================================
# SlideshowManager.get_asset_attrs Tests
# =============================================================================


def test_manager_get_asset_attrs_full_metadata(manager: SlideshowManager) -> None:
    """Test get_asset_attrs extracts all attributes from fully populated asset."""
    asset = create_landscape_asset("asset-1")
    asset["memory_year"] = 2020

    attrs = manager.get_asset_attrs(asset)

    assert attrs["asset_id"] == "asset-1"
    assert attrs["immich_url"] == "http://immich.local:2283/photos/asset-1"
    assert attrs["original_filename"] == "asset-1.jpg"
    assert attrs["description"] == "A beautiful landscape"
    assert attrs["date_taken"] == "2024-01-15T12:00:00"
    assert attrs["city"] == "Paris"
    assert attrs["country"] == "France"
    assert attrs["people"] == ["John Doe"]
    assert attrs["is_favorite"] is False
    assert attrs["source"] == "recent"
    assert attrs["memory_year"] == 2020
    assert attrs["years_ago"] == datetime.now().year - 2020


def test_manager_get_asset_attrs_minimal_metadata(manager: SlideshowManager) -> None:
    """Test get_asset_attrs with minimal asset data."""
    asset = {"id": "asset-1", "_source": "memory"}

    attrs = manager.get_asset_attrs(asset)

    assert attrs["asset_id"] == "asset-1"
    assert attrs["immich_url"] == "http://immich.local:2283/photos/asset-1"
    assert attrs["source"] == "memory"
    assert "original_filename" not in attrs
    assert "city" not in attrs
    assert "people" not in attrs


def test_manager_get_asset_attrs_none_asset(manager: SlideshowManager) -> None:
    """Test get_asset_attrs returns empty dict for None asset."""
    attrs = manager.get_asset_attrs(None)
    assert attrs == {}


# =============================================================================
# SlideshowManager.generate_image Tests
# =============================================================================


def test_manager_generate_image_no_current_image_returns_none(
    manager: SlideshowManager,
) -> None:
    """Test generate_image returns None when no current image."""
    manager._current_img1 = None

    result = manager.generate_image(1920, 1080)

    assert result is None


def test_manager_generate_image_single_image(manager: SlideshowManager) -> None:
    """Test generate_image with a single landscape image."""
    # Create a test PIL image
    img = Image.new("RGB", (4000, 3000), color="blue")
    manager._current_img1 = img
    manager._current_img2 = None
    manager._is_dual = False

    result = manager.generate_image(1920, 1080)

    assert result is not None
    assert isinstance(result, bytes)
    # Verify it's valid JPEG
    result_img = Image.open(io.BytesIO(result))
    assert result_img.size == (1920, 1080)


def test_manager_generate_image_dual_portrait(manager: SlideshowManager) -> None:
    """Test generate_image with dual portrait mode."""
    img1 = Image.new("RGB", (3000, 4000), color="red")
    img2 = Image.new("RGB", (3000, 4000), color="green")
    manager._current_img1 = img1
    manager._current_img2 = img2
    manager._is_dual = True

    result = manager.generate_image(1920, 1080)

    assert result is not None
    result_img = Image.open(io.BytesIO(result))
    assert result_img.size == (1920, 1080)


# =============================================================================
# SlideshowManager._close_images Tests
# =============================================================================


def test_manager_close_images_handles_none(manager: SlideshowManager) -> None:
    """Test _close_images handles None gracefully."""
    # Should not raise
    manager._close_images(None, None)


def test_manager_close_images_handles_exception(manager: SlideshowManager) -> None:
    """Test _close_images handles exception during close."""
    # Create a mock image that raises on close
    mock_img = MagicMock()
    mock_img.close.side_effect = Exception("Close failed")

    # Should not raise
    manager._close_images(mock_img, None)
    mock_img.close.assert_called_once()


# =============================================================================
# Async SlideshowManager Tests
# =============================================================================


async def test_manager_refill_pool_success(
    mock_hub: AsyncMock, manager: SlideshowManager
) -> None:
    """Test _refill_pool successfully fetches and enriches assets."""
    # Setup mock returns
    mock_assets = [
        {"id": "asset-1", "type": "IMAGE"},
        {"id": "asset-2", "type": "IMAGE"},
    ]
    mock_hub.search_random_recent.return_value = mock_assets

    # Setup asset info return
    def mock_asset_info(asset_id):
        return {
            "id": asset_id,
            "exifInfo": {
                "exifImageWidth": 4000,
                "exifImageHeight": 3000,
                "orientation": 1,
            },
            "originalFileName": f"{asset_id}.jpg",
            "isFavorite": False,
            "localDateTime": "2024-01-15T12:00:00",
            "people": [],
            "albumIds": [],
        }

    mock_hub.get_asset_info.side_effect = mock_asset_info

    await manager._refill_pool()

    assert len(manager._asset_pool) > 0
    mock_hub.search_random_recent.assert_called()
    mock_hub.get_asset_info.assert_called()


async def test_manager_refill_pool_empty_results(
    mock_hub: AsyncMock, manager: SlideshowManager
) -> None:
    """Test _refill_pool handles empty results gracefully."""
    mock_hub.search_random_recent.return_value = []
    mock_hub.get_memory_assets.return_value = []

    await manager._refill_pool()

    assert manager._asset_pool == []


async def test_manager_refill_pool_all_filtered_by_exclusions(
    mock_hub: AsyncMock,
) -> None:
    """Test _refill_pool when all assets are filtered by exclusions."""
    manager = SlideshowManager(
        hub=mock_hub,
        dual_portrait=False,
        source_recent_weight=100,
        source_memories_weight=0,
        exclude_albums=["album-1"],
    )

    # Return assets that will all be filtered
    mock_hub.search_random_recent.return_value = [
        {"id": "asset-1", "type": "IMAGE"},
    ]

    # Asset info shows it's in excluded album
    mock_hub.get_asset_info.return_value = {
        "id": "asset-1",
        "exifInfo": {"exifImageWidth": 4000, "exifImageHeight": 3000},
        "albumIds": ["album-1"],
        "people": [],
    }

    await manager._refill_pool()

    # Pool should be empty since all assets were filtered
    assert manager._asset_pool == []


async def test_manager_fetch_recent_tags_source(
    mock_hub: AsyncMock, manager: SlideshowManager
) -> None:
    """Test _fetch_recent tags assets with _source='recent'."""
    mock_hub.search_random_recent.return_value = [
        {"id": "asset-1", "type": "IMAGE"},
    ]

    result = await manager._fetch_recent(count=10)

    assert len(result) == 1
    assert result[0]["_source"] == "recent"


async def test_manager_fetch_memories_tags_source(
    mock_hub: AsyncMock, manager: SlideshowManager
) -> None:
    """Test _fetch_memories tags assets with _source='memory'."""
    mock_hub.get_memory_assets.return_value = [
        {"id": "memory-1", "type": "IMAGE", "memory_year": 2020},
    ]

    result = await manager._fetch_memories(count=10)

    assert len(result) == 1
    assert result[0]["_source"] == "memory"


async def test_manager_fetch_albums_with_specific_albums(
    mock_hub: AsyncMock,
) -> None:
    """Test _fetch_albums uses search_random_from_albums for specific albums."""
    manager = SlideshowManager(
        hub=mock_hub,
        dual_portrait=False,
        albums_include=["album-1", "album-2"],
    )

    mock_hub.search_random_from_albums.return_value = [
        {"id": "album-asset-1", "type": "IMAGE"},
    ]

    result = await manager._fetch_albums(count=10)

    mock_hub.search_random_from_albums.assert_called_with(
        album_ids=["album-1", "album-2"], count=10
    )
    assert len(result) == 1
    assert result[0]["_source"] == "album"


async def test_manager_fetch_albums_any_album(mock_hub: AsyncMock) -> None:
    """Test _fetch_albums in any-album mode fans out across the cached album list.

    Avoids Immich's broken `isNotInAlbum: false` filter (returns assets that
    aren't actually in any album). Instead, uses the manager's _album_names
    cache as the album pool and lets `search_random_from_albums` do the
    fan-out + per-asset _album_id tagging.
    """
    manager = SlideshowManager(
        hub=mock_hub,
        dual_portrait=False,
        albums_include=[],  # any-album mode
    )
    # Pre-populate the album-names cache as if a previous refill had run.
    manager._album_names = {"album-A": "Album A", "album-B": "Album B"}
    manager._albums_fetched = True

    mock_hub.search_random_from_albums.return_value = [
        {"id": "any-album-asset", "type": "IMAGE", "_album_id": "album-A"},
    ]

    result = await manager._fetch_albums(count=10)

    mock_hub.search_random_from_albums.assert_called_once()
    call_kwargs = mock_hub.search_random_from_albums.call_args.kwargs
    assert set(call_kwargs["album_ids"]) == {"album-A", "album-B"}
    assert call_kwargs["count"] == 10
    # search_random_in_any_album must NOT be called any more
    mock_hub.search_random_in_any_album.assert_not_called()
    assert len(result) == 1
    assert result[0]["_source"] == "album"


async def test_manager_fetch_albums_any_album_empty_cache(
    mock_hub: AsyncMock,
) -> None:
    """If the album cache is empty (e.g. perm missing), _fetch_albums returns []."""
    manager = SlideshowManager(
        hub=mock_hub,
        dual_portrait=False,
        albums_include=[],
    )
    manager._album_names = {}
    manager._albums_fetched = True

    result = await manager._fetch_albums(count=10)

    assert result == []
    mock_hub.search_random_from_albums.assert_not_called()


async def test_manager_fetch_persons_empty_list(
    mock_hub: AsyncMock, manager: SlideshowManager
) -> None:
    """Test _fetch_persons returns empty when no persons selected."""
    # Manager has no persons_include by default
    result = await manager._fetch_persons(count=10)

    assert result == []
    mock_hub.search_random_by_person.assert_not_called()


async def test_manager_fetch_persons_with_selection(mock_hub: AsyncMock) -> None:
    """Test _fetch_persons fetches when persons are selected."""
    manager = SlideshowManager(
        hub=mock_hub,
        dual_portrait=False,
        persons_include=["person-1", "person-2"],
    )

    mock_hub.search_random_by_person.return_value = [
        {"id": "person-asset-1", "type": "IMAGE"},
    ]

    result = await manager._fetch_persons(count=10)

    mock_hub.search_random_by_person.assert_called_with(
        person_ids=["person-1", "person-2"], count=10
    )
    assert len(result) == 1
    assert result[0]["_source"] == "person"


async def test_manager_refresh_with_prefetch_ready(
    mock_hub: AsyncMock, manager: SlideshowManager
) -> None:
    """Test refresh() does instant swap when prefetched image is ready."""
    # Set up prefetched images
    prefetch_img = Image.new("RGB", (4000, 3000), color="green")
    prefetch_asset = create_landscape_asset("prefetched")

    manager._next_img1 = prefetch_img
    manager._next_img2 = None
    manager._next_asset1 = prefetch_asset
    manager._next_asset2 = None
    manager._next_is_dual = False

    # Also set current (to verify swap)
    old_img = Image.new("RGB", (100, 100), color="red")
    manager._current_img1 = old_img
    manager._current_asset1 = create_landscape_asset("old")

    result = await manager.refresh()

    assert result is True
    assert manager._current_img1 == prefetch_img
    assert manager._current_asset1 == prefetch_asset
    # Next should be cleared
    assert manager._next_img1 is None
    assert manager._next_asset1 is None


async def test_manager_refresh_cold_start(
    mock_hub: AsyncMock, manager: SlideshowManager
) -> None:
    """Test refresh() falls back to sync fetch when no prefetch available."""
    # No prefetched images
    manager._next_img1 = None

    # Setup pool and mocks for sync fetch
    manager._asset_pool = [create_landscape_asset("asset-1")]

    test_image_bytes = create_test_image(4000, 3000)
    mock_hub.download_asset.return_value = test_image_bytes

    result = await manager.refresh()

    assert result is True
    mock_hub.download_asset.assert_called()


async def test_manager_prefetch_single_image(
    mock_hub: AsyncMock, manager: SlideshowManager
) -> None:
    """Test _prefetch_next loads a single landscape image."""
    # Setup pool with landscape image
    landscape = create_landscape_asset("landscape-1")
    manager._asset_pool = [landscape]

    test_image_bytes = create_test_image(4000, 3000)
    mock_hub.download_asset.return_value = test_image_bytes

    await manager._prefetch_next()

    assert manager._next_img1 is not None
    assert manager._next_img2 is None
    assert manager._next_is_dual is False
    assert manager._next_asset1["id"] == "landscape-1"


async def test_manager_prefetch_dual_portrait(
    mock_hub: AsyncMock, manager: SlideshowManager
) -> None:
    """Test _prefetch_next combines two portraits for dual mode."""
    # Setup pool with two portrait images
    portrait1 = create_portrait_asset("portrait-1")
    portrait2 = create_portrait_asset("portrait-2")
    manager._asset_pool = [portrait1, portrait2]

    # Create portrait test images
    portrait_bytes = create_test_image(3000, 4000)
    mock_hub.download_asset.return_value = portrait_bytes

    await manager._prefetch_next()

    assert manager._next_img1 is not None
    assert manager._next_img2 is not None
    assert manager._next_is_dual is True
    assert manager._next_asset1["id"] == "portrait-1"
    assert manager._next_asset2["id"] == "portrait-2"


# =============================================================================
# ImmichSlideshowImage Entity Tests
# =============================================================================


@pytest.fixture
def mock_config_entry() -> MagicMock:
    """Create a mock config entry."""
    config_entry = MagicMock()
    config_entry.entry_id = "test_entry_id"
    config_entry.options = {}
    return config_entry


@pytest.fixture
def mock_hass() -> MagicMock:
    """Create a mock Home Assistant instance."""
    hass = MagicMock()
    hass.config.config_dir = "/config"
    hass.async_add_executor_job = MagicMock(return_value=asyncio.Future())
    hass.async_add_executor_job.return_value.set_result(None)
    return hass


@pytest.fixture
def image_entity(
    mock_hass: MagicMock,
    manager: SlideshowManager,
    mock_config_entry: MagicMock,
) -> ImmichSlideshowImage:
    """Create an ImmichSlideshowImage entity for testing."""
    with patch.object(ImmichSlideshowImage, "__init__", lambda self, **kwargs: None):
        entity = ImmichSlideshowImage.__new__(ImmichSlideshowImage)
        entity.hass = mock_hass
        entity._manager = manager
        entity._config_entry = mock_config_entry
        entity._target_width = 1920
        entity._target_height = 1080
        entity._refresh_interval = 30
        entity._is_primary = True
        entity._background_path = "view_assist/images/backgrounds"
        entity._write_files = False
        entity._attr_name = None
        entity._attr_unique_id = f"{mock_config_entry.entry_id}_image"
        entity._current_image_bytes = None
        entity._image_last_updated = None
        entity._unsub_timer = None
        return entity


def test_entity_available_when_manager_available(
    image_entity: ImmichSlideshowImage,
) -> None:
    """Test entity is available when manager has images."""
    image_entity._manager._pool_empty = False
    assert image_entity.available is True


def test_entity_unavailable_when_pool_empty(
    image_entity: ImmichSlideshowImage,
) -> None:
    """Test entity is unavailable when pool is empty."""
    image_entity._manager._pool_empty = True
    assert image_entity.available is False


def test_entity_extra_state_attributes_single_image(
    image_entity: ImmichSlideshowImage,
) -> None:
    """Test extra_state_attributes for single image display."""
    asset = create_landscape_asset("asset-1")
    image_entity._manager._current_asset1 = asset
    image_entity._manager._current_asset2 = None
    image_entity._manager._is_dual = False

    attrs = image_entity.extra_state_attributes

    assert attrs["is_dual_portrait"] is False
    assert attrs["asset_id_1"] == "asset-1"
    assert attrs["city_1"] == "Paris"
    assert attrs["country_1"] == "France"
    assert "asset_id_2" not in attrs


def test_entity_extra_state_attributes_dual_portrait(
    image_entity: ImmichSlideshowImage,
) -> None:
    """Test extra_state_attributes for dual portrait display."""
    asset1 = create_portrait_asset("portrait-1")
    asset1["exifInfo"]["city"] = "Paris"
    asset2 = create_portrait_asset("portrait-2")
    asset2["exifInfo"]["city"] = "London"

    image_entity._manager._current_asset1 = asset1
    image_entity._manager._current_asset2 = asset2
    image_entity._manager._is_dual = True

    attrs = image_entity.extra_state_attributes

    assert attrs["is_dual_portrait"] is True
    assert attrs["asset_id_1"] == "portrait-1"
    assert attrs["city_1"] == "Paris"
    assert attrs["asset_id_2"] == "portrait-2"
    assert attrs["city_2"] == "London"


async def test_entity_async_image_returns_bytes(
    image_entity: ImmichSlideshowImage,
) -> None:
    """Test async_image returns current image bytes."""
    test_bytes = b"fake image bytes"
    image_entity._current_image_bytes = test_bytes

    result = await image_entity.async_image()

    assert result == test_bytes


async def test_entity_async_image_generates_if_none(
    image_entity: ImmichSlideshowImage,
) -> None:
    """Test async_image generates image if none exists."""
    image_entity._current_image_bytes = None

    # Setup manager with an image
    img = Image.new("RGB", (4000, 3000), color="blue")
    image_entity._manager._current_img1 = img
    image_entity._manager._is_dual = False

    result = await image_entity.async_image()

    # Should have generated an image
    assert image_entity._current_image_bytes is not None
    assert result == image_entity._current_image_bytes


def test_entity_device_info_structure(image_entity: ImmichSlideshowImage) -> None:
    """Test device_info returns correct structure."""
    device_info = image_entity.device_info

    assert "identifiers" in device_info
    assert (DOMAIN, "test_entry_id") in device_info["identifiers"]
    assert device_info["name"] == "Immich Slideshow"
    assert device_info["manufacturer"] == "Immich"


# =============================================================================
# SlideshowManager Properties Tests
# =============================================================================


def test_manager_memory_year_property(manager: SlideshowManager) -> None:
    """Test memory_year property returns correct year."""
    asset = create_landscape_asset("asset-1")
    asset["memory_year"] = 2020
    manager._current_asset1 = asset

    assert manager.memory_year == 2020


def test_manager_memory_year_none_when_not_memory(
    manager: SlideshowManager,
) -> None:
    """Test memory_year returns None when not a memory photo."""
    asset = create_landscape_asset("asset-1")
    # No memory_year key
    manager._current_asset1 = asset

    assert manager.memory_year is None


def test_manager_years_ago_property(manager: SlideshowManager) -> None:
    """Test years_ago property calculates correctly."""
    asset = create_landscape_asset("asset-1")
    asset["memory_year"] = datetime.now().year - 5
    manager._current_asset1 = asset

    assert manager.years_ago == 5


def test_manager_asset_id_property(manager: SlideshowManager) -> None:
    """Test asset_id property returns current asset ID."""
    asset = create_landscape_asset("test-asset-123")
    manager._current_asset1 = asset

    assert manager.asset_id == "test-asset-123"


def test_manager_immich_url_property(manager: SlideshowManager) -> None:
    """Test immich_url property returns correct URL."""
    asset = create_landscape_asset("asset-123")
    manager._current_asset1 = asset

    assert manager.immich_url == "http://immich.local:2283/photos/asset-123"


def test_manager_original_filename_property(manager: SlideshowManager) -> None:
    """Test original_filename property."""
    asset = create_landscape_asset("asset-1")
    manager._current_asset1 = asset

    assert manager.original_filename == "asset-1.jpg"


def test_manager_description_property(manager: SlideshowManager) -> None:
    """Test description property from EXIF."""
    asset = create_landscape_asset("asset-1")
    manager._current_asset1 = asset

    assert manager.description == "A beautiful landscape"


def test_manager_date_taken_property(manager: SlideshowManager) -> None:
    """Test date_taken property."""
    asset = create_landscape_asset("asset-1")
    manager._current_asset1 = asset

    assert manager.date_taken == "2024-01-15T12:00:00"


def test_manager_city_property(manager: SlideshowManager) -> None:
    """Test city property."""
    asset = create_landscape_asset("asset-1")
    manager._current_asset1 = asset

    assert manager.city == "Paris"


def test_manager_country_property(manager: SlideshowManager) -> None:
    """Test country property."""
    asset = create_landscape_asset("asset-1")
    manager._current_asset1 = asset

    assert manager.country == "France"


def test_manager_is_favorite_property(manager: SlideshowManager) -> None:
    """Test is_favorite property."""
    asset = create_landscape_asset("asset-1")
    asset["isFavorite"] = True
    manager._current_asset1 = asset

    assert manager.is_favorite is True


def test_manager_people_property(manager: SlideshowManager) -> None:
    """Test people property returns list of names."""
    asset = create_landscape_asset("asset-1")
    manager._current_asset1 = asset

    assert manager.people == ["John Doe"]


def test_manager_source_property(manager: SlideshowManager) -> None:
    """Test source property returns asset source."""
    asset = create_landscape_asset("asset-1", source="memory")
    manager._current_asset1 = asset

    assert manager.source == "memory"


def test_manager_is_dual_property(manager: SlideshowManager) -> None:
    """Test is_dual property."""
    manager._is_dual = True
    assert manager.is_dual is True

    manager._is_dual = False
    assert manager.is_dual is False


def test_manager_asset1_property(manager: SlideshowManager) -> None:
    """Test asset1 property returns current asset."""
    asset = create_landscape_asset("asset-1")
    manager._current_asset1 = asset

    assert manager.asset1 == asset


def test_manager_asset2_property(manager: SlideshowManager) -> None:
    """Test asset2 property returns second asset for dual portrait."""
    asset = create_portrait_asset("portrait-2")
    manager._current_asset2 = asset

    assert manager.asset2 == asset
