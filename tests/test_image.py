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
    hub.supports_search_v2 = True
    hub.search_random_recent.return_value = []
    hub.search_random_recent_boost.return_value = []
    hub.get_memory_assets.return_value = []
    hub.search_random_from_albums.return_value = []
    hub.search_random_by_person.return_value = []
    hub.get_users.return_value = []
    hub.get_albums.return_value = []
    hub.get_asset_info.return_value = None
    hub.download_image.return_value = None
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
    """Assets drawn from an excluded album (`_album_id`) are filtered out.

    Immich never returns the albums an asset belongs to, so the client-side
    net can only rely on the album the asset was drawn from.
    """
    manager = SlideshowManager(
        hub=mock_hub,
        dual_portrait=False,
        exclude_albums=["album-bad"],
    )

    asset_recent = create_landscape_asset("asset-1")

    asset_bad = create_landscape_asset("asset-2")
    asset_bad["_album_id"] = "album-bad"

    asset_other_album = create_landscape_asset("asset-3")
    asset_other_album["_album_id"] = "album-good"

    assets = [asset_recent, asset_bad, asset_other_album]
    filtered = manager._apply_global_exclusions(assets)

    assert [a["id"] for a in filtered] == ["asset-1", "asset-3"]


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
        exclude_persons=["person-1"],
    )

    # Return assets that will all be filtered
    mock_hub.search_random_recent.return_value = [
        {"id": "asset-1", "type": "IMAGE"},
    ]

    # Asset info shows it contains an excluded person
    mock_hub.get_asset_info.return_value = {
        "id": "asset-1",
        "exifInfo": {"exifImageWidth": 4000, "exifImageHeight": 3000},
        "people": [{"id": "person-1", "name": "Excluded"}],
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
        album_ids=["album-1", "album-2"],
        count=10,
        include_archived=False,
        exclude_album_ids=[],
        exclude_person_ids=[],
    )
    assert len(result) == 1
    assert result[0]["_source"] == "album"


async def test_manager_fetch_albums_any_album(mock_hub: AsyncMock) -> None:
    """Test _fetch_albums in any-album mode fans out across the cached album list.

    Uses the manager's _album_names cache as the album pool and lets
    `search_random_from_albums` do the balanced fan-out + per-asset _album_id
    tagging.
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
        person_ids=["person-1", "person-2"],
        count=10,
        include_archived=False,
        exclude_album_ids=[],
        exclude_person_ids=[],
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
    mock_hub.download_image.return_value = test_image_bytes

    result = await manager.refresh()

    assert result is True
    mock_hub.download_image.assert_called()


async def test_manager_prefetch_single_image(
    mock_hub: AsyncMock, manager: SlideshowManager
) -> None:
    """Test _prefetch_next loads a single landscape image."""
    # Setup pool with landscape image
    landscape = create_landscape_asset("landscape-1")
    manager._asset_pool = [landscape]

    test_image_bytes = create_test_image(4000, 3000)
    mock_hub.download_image.return_value = test_image_bytes

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
    mock_hub.download_image.return_value = portrait_bytes

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


# =============================================================================
# Immich 3.2 search filters (include_archived, exclusions, stale album ids)
# =============================================================================


async def test_manager_include_archived_passed_to_recent_searches(
    mock_hub: AsyncMock,
) -> None:
    """include_archived + exclusions reach both the boost and classic queries."""
    manager = SlideshowManager(
        hub=mock_hub,
        dual_portrait=False,
        recent_boost_days=7,
        recent_boost_share=40,
        exclude_albums=["album-z", "album-a"],
        exclude_persons=["person-x"],
        include_archived=True,
    )

    await manager._fetch_recent(count=10)

    expected = {
        "include_archived": True,
        "exclude_album_ids": ["album-a", "album-z"],
        "exclude_person_ids": ["person-x"],
    }
    boost_kwargs = mock_hub.search_random_recent_boost.call_args.kwargs
    classic_kwargs = mock_hub.search_random_recent.call_args.kwargs
    for key, value in expected.items():
        assert boost_kwargs[key] == value
        assert classic_kwargs[key] == value


async def test_manager_include_archived_defaults_to_false(
    mock_hub: AsyncMock, manager: SlideshowManager
) -> None:
    """Archived photos are excluded unless explicitly enabled."""
    manager._recent_boost_days = 0

    await manager._fetch_recent(count=5)

    assert mock_hub.search_random_recent.call_args.kwargs["include_archived"] is False


async def test_manager_exclusions_passed_to_album_search(mock_hub: AsyncMock) -> None:
    """Album fan-out receives the server-side exclusion filters."""
    manager = SlideshowManager(
        hub=mock_hub,
        dual_portrait=False,
        albums_include=["album-1"],
        exclude_albums=["album-2"],
        exclude_persons=["person-9"],
    )

    await manager._fetch_albums(count=5)

    kwargs = mock_hub.search_random_from_albums.call_args.kwargs
    assert kwargs["album_ids"] == ["album-1"]
    assert kwargs["exclude_album_ids"] == ["album-2"]
    assert kwargs["exclude_person_ids"] == ["person-9"]
    assert kwargs["include_archived"] is False


async def test_manager_sanitizes_stale_album_ids_once(
    mock_hub: AsyncMock, caplog: pytest.LogCaptureFixture
) -> None:
    """Deleted albums are dropped from includes and exclusions, warned once."""
    mock_hub.get_albums.return_value = [
        {"id": "album-A", "albumName": "A"},
        {"id": "album-B", "albumName": "B"},
    ]
    manager = SlideshowManager(
        hub=mock_hub,
        dual_portrait=False,
        source_recent_weight=100,
        source_memories_weight=0,
        albums_include=["album-A", "gone-1"],
        exclude_albums=["album-B", "gone-2"],
    )

    await manager._refill_pool()
    await manager._refill_pool()

    assert manager._albums_include == ["album-A"]
    assert manager._exclude_albums == {"album-B"}
    warnings = [r for r in caplog.records if "no longer exist" in r.getMessage()]
    assert len(warnings) == 1
    assert "gone-1" in warnings[0].getMessage()
    assert "gone-2" in warnings[0].getMessage()
    assert mock_hub.search_random_recent.call_args.kwargs["exclude_album_ids"] == ["album-B"]


async def test_manager_keeps_album_ids_when_album_list_unknown(
    mock_hub: AsyncMock,
) -> None:
    """Without album.read (empty album list) configured ids are kept as-is."""
    mock_hub.get_albums.return_value = []
    manager = SlideshowManager(
        hub=mock_hub,
        dual_portrait=False,
        albums_include=["album-1"],
        exclude_albums=["album-2"],
    )

    await manager._refill_pool()

    assert manager._albums_include == ["album-1"]
    assert manager._exclude_albums == {"album-2"}


async def test_manager_fetch_albums_all_selected_albums_deleted(
    mock_hub: AsyncMock,
) -> None:
    """If every selected album is gone, don't silently widen to all albums."""
    manager = SlideshowManager(
        hub=mock_hub,
        dual_portrait=False,
        albums_include=["gone-1"],
    )
    manager._album_names = {"album-A": "A"}
    manager._albums_fetched = True
    manager._sanitize_album_ids()

    result = await manager._fetch_albums(count=10)

    assert result == []
    mock_hub.search_random_from_albums.assert_not_called()


# =============================================================================
# Enrichment skip
# =============================================================================


async def test_manager_refill_skips_enrichment_when_exif_present(
    mock_hub: AsyncMock,
) -> None:
    """Search results carrying exif dimensions need no per-asset GET."""
    manager = SlideshowManager(
        hub=mock_hub,
        dual_portrait=False,
        source_recent_weight=50,
        source_memories_weight=50,
        recent_boost_days=0,
    )
    mock_hub.search_random_recent.return_value = [create_portrait_asset("searched")]
    mock_hub.get_memory_assets.return_value = [
        {"id": "memory-1", "type": "IMAGE", "memory_year": 2020}
    ]
    mock_hub.get_asset_info.return_value = {
        "id": "memory-1",
        "exifInfo": {"exifImageWidth": 4000, "exifImageHeight": 3000},
        "originalFileName": "memory-1.jpg",
        "people": [],
    }

    await manager._refill_pool()

    mock_hub.get_asset_info.assert_called_once_with("memory-1")
    pool = {a["id"]: a for a in manager._asset_pool}
    assert pool["searched"]["originalWidth"] == 3000
    assert pool["searched"]["originalHeight"] == 4000
    assert pool["searched"]["originalFileName"] == "searched.jpg"
    assert pool["memory-1"]["originalWidth"] == 4000


# =============================================================================
# Undisplayable ("bad") assets
# =============================================================================


def _bytes_by_id(mapping: dict[str, bytes | None], previews: dict[str, bytes] | None = None):
    """side_effect for hub.download_image returning bytes per asset id.

    `mapping` answers the default (fullsize) request; `previews` the
    size="preview" retry (defaults to the same bytes as `mapping`).
    """

    async def _download(asset_id: str, size: str = "fullsize") -> bytes | None:
        if size == "preview" and previews is not None:
            return previews.get(asset_id)
        return mapping.get(asset_id)

    return _download


async def test_manager_decode_failure_marks_bad_and_tries_next(
    mock_hub: AsyncMock, manager: SlideshowManager, caplog: pytest.LogCaptureFixture
) -> None:
    """An undecodable file is skipped without losing the display slot."""
    manager._asset_pool = [
        create_landscape_asset("heic-as-jpg"),
        create_landscape_asset("good"),
    ]
    mock_hub.download_image.side_effect = _bytes_by_id(
        {"heic-as-jpg": b"\x00\x00\x00\x18ftypheic", "good": create_test_image(400, 300)}
    )

    await manager._prefetch_next()

    assert manager._next_asset1["id"] == "good"
    assert "heic-as-jpg" in manager._bad_assets
    messages = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert any("heic-as-jpg" in m and "heic-as-jpg.jpg" in m for m in messages)


async def test_manager_decode_failure_uses_preview_rendition(
    mock_hub: AsyncMock, manager: SlideshowManager
) -> None:
    """A file served as-is but undecodable is displayed from its preview."""
    manager._asset_pool = [create_landscape_asset("heic-as-jpg")]
    mock_hub.download_image.side_effect = _bytes_by_id(
        {"heic-as-jpg": b"\x00\x00\x00\x18ftypheic"},
        previews={"heic-as-jpg": create_test_image(400, 300)},
    )

    await manager._prefetch_next()

    assert manager._next_asset1["id"] == "heic-as-jpg"
    assert manager._bad_assets == {}
    sizes = [c.kwargs.get("size", "fullsize") for c in mock_hub.download_image.await_args_list]
    assert sizes == ["fullsize", "preview"]


async def test_manager_decompression_bomb_marks_bad(
    mock_hub: AsyncMock, manager: SlideshowManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A panorama above Pillow's pixel limit is treated as undisplayable."""
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1000)
    manager._asset_pool = [create_landscape_asset("panorama")]
    mock_hub.download_image.side_effect = _bytes_by_id(
        {"panorama": create_test_image(400, 300)}
    )

    result = await manager.refresh()

    assert result is False
    assert "panorama" in manager._bad_assets


async def test_manager_download_failure_needs_two_strikes(
    mock_hub: AsyncMock, manager: SlideshowManager
) -> None:
    """A single failed download may be transient: blacklist on the second."""
    asset = create_landscape_asset("missing-original")
    mock_hub.download_image.return_value = None

    assert await manager._load_asset_image(asset) is None
    assert "missing-original" not in manager._bad_assets
    assert manager._download_failures["missing-original"] == 1

    assert await manager._load_asset_image(asset) is None
    assert "missing-original" in manager._bad_assets
    assert "missing-original" not in manager._download_failures


async def test_manager_download_success_resets_strikes(
    mock_hub: AsyncMock, manager: SlideshowManager
) -> None:
    """A transient failure followed by a success leaves the asset usable."""
    asset = create_landscape_asset("flaky")
    mock_hub.download_image.return_value = None
    await manager._load_asset_image(asset)

    mock_hub.download_image.return_value = create_test_image(400, 300)
    img = await manager._load_asset_image(asset)

    assert img is not None
    assert "flaky" not in manager._download_failures
    assert "flaky" not in manager._bad_assets


async def test_manager_retry_is_bounded(
    mock_hub: AsyncMock, manager: SlideshowManager
) -> None:
    """At most MAX_DISPLAY_ATTEMPTS assets are tried per display slot."""
    from custom_components.immich_slideshow.const import MAX_DISPLAY_ATTEMPTS

    manager._asset_pool = [
        create_landscape_asset(f"broken-{i}") for i in range(MAX_DISPLAY_ATTEMPTS + 2)
    ]
    mock_hub.download_image.return_value = b"garbage"

    loaded = await manager._load_next_display()

    assert loaded is None
    # Each attempt = fullsize download + one preview retry
    assert mock_hub.download_image.await_count == 2 * MAX_DISPLAY_ATTEMPTS
    assert len(manager._asset_pool) == 2


async def test_manager_dual_portrait_partial_failure(
    mock_hub: AsyncMock, manager: SlideshowManager
) -> None:
    """Only the failing portrait is dropped; another partner is used."""
    manager._asset_pool = [
        create_portrait_asset("p1"),
        create_portrait_asset("p2-broken"),
        create_portrait_asset("p3"),
    ]
    portrait = create_test_image(300, 400)
    mock_hub.download_image.side_effect = _bytes_by_id(
        {"p1": portrait, "p2-broken": b"garbage", "p3": portrait}
    )

    await manager._prefetch_next()

    assert manager._next_is_dual is True
    assert manager._next_asset1["id"] == "p1"
    assert manager._next_asset2["id"] == "p3"
    assert set(manager._bad_assets) == {"p2-broken"}


async def test_manager_dual_portrait_falls_back_to_single(
    mock_hub: AsyncMock, manager: SlideshowManager
) -> None:
    """If no partner portrait can be decoded, the first one shows alone."""
    manager._asset_pool = [
        create_portrait_asset("p1"),
        create_portrait_asset("p2-broken"),
    ]
    mock_hub.download_image.side_effect = _bytes_by_id(
        {"p1": create_test_image(300, 400), "p2-broken": b"garbage"}
    )

    await manager._prefetch_next()

    assert manager._next_is_dual is False
    assert manager._next_asset1["id"] == "p1"
    assert manager._next_img2 is None


async def test_manager_bad_assets_excluded_at_refill_and_pop(
    mock_hub: AsyncMock,
) -> None:
    """Known bad assets never enter the pool, and are dropped if already in it."""
    import time as time_mod

    manager = SlideshowManager(
        hub=mock_hub,
        dual_portrait=False,
        source_recent_weight=100,
        source_memories_weight=0,
        recent_boost_days=0,
    )
    manager._bad_assets = {"bad-1": time_mod.time(), "bad-2": time_mod.time()}
    mock_hub.search_random_recent.return_value = [
        create_landscape_asset("bad-1"),
        create_landscape_asset("ok-1"),
    ]

    await manager._refill_pool()
    assert [a["id"] for a in manager._asset_pool] == ["ok-1"]

    manager._asset_pool = [create_landscape_asset("bad-2"), create_landscape_asset("ok-2")]
    popped = manager._pop_from_pool(count=1)
    assert popped[0]["id"] == "ok-2"
    assert manager._asset_pool == []


def test_manager_bad_asset_ttl(manager: SlideshowManager) -> None:
    """Bad-asset entries expire after BAD_ASSET_TTL_HOURS."""
    import time as time_mod

    from custom_components.immich_slideshow.const import BAD_ASSET_TTL_HOURS

    now = time_mod.time()
    manager._bad_assets = {
        "fresh": now - 3600,
        "expired": now - (BAD_ASSET_TTL_HOURS + 1) * 3600,
    }

    assert manager._is_bad_asset({"id": "fresh"}) is True
    assert manager._is_bad_asset({"id": "expired"}) is False
    assert manager._is_bad_asset({"id": "unknown"}) is False


async def test_manager_bad_assets_persisted_with_shown_history(
    mock_hub: AsyncMock,
) -> None:
    """Bad assets live under a reserved key of the shown-history store."""
    import time as time_mod

    from custom_components.immich_slideshow.const import (
        BAD_ASSET_TTL_HOURS,
        BAD_ASSETS_STORE_KEY,
    )

    now = time_mod.time()
    store = MagicMock()
    store.async_load = AsyncMock(
        return_value={
            "shown-1": now - 60,
            BAD_ASSETS_STORE_KEY: {
                "bad-1": now - 60,
                "bad-old": now - (BAD_ASSET_TTL_HOURS + 1) * 3600,
            },
        }
    )
    manager = SlideshowManager(hub=mock_hub, dual_portrait=False, shown_store=store)

    await manager.async_load_shown()

    assert set(manager._shown) == {"shown-1"}
    assert set(manager._bad_assets) == {"bad-1"}

    manager._mark_bad(create_landscape_asset("bad-2"), "cannot decode image")
    store.async_delay_save.assert_called()
    saved = manager._shown_data_to_save()
    assert saved["shown-1"] == pytest.approx(now - 60)
    assert set(saved[BAD_ASSETS_STORE_KEY]) == {"bad-1", "bad-2"}


async def test_manager_loads_legacy_flat_shown_store(mock_hub: AsyncMock) -> None:
    """A store written before bad-asset tracking (flat map) still loads."""
    import time as time_mod

    now = time_mod.time()
    store = MagicMock()
    store.async_load = AsyncMock(return_value={"a": now - 10, "b": now - 20})
    manager = SlideshowManager(hub=mock_hub, dual_portrait=False, shown_store=store)

    await manager.async_load_shown()

    assert set(manager._shown) == {"a", "b"}
    assert manager._bad_assets == {}
    # No reserved key is written while the blacklist is empty
    assert manager._shown_data_to_save() == manager._shown


# =============================================================================
# Anti-repetition window (shown history)
# =============================================================================


def _hours_ago(hours: float) -> float:
    import time as time_mod

    return time_mod.time() - hours * 3600


def _boosted_asset(asset_id: str) -> dict[str, Any]:
    """Asset uploaded 'now' → inside the very-recent boost window."""
    from datetime import datetime, timezone

    asset = create_landscape_asset(asset_id)
    now = datetime.now(timezone.utc).isoformat()
    asset["createdAt"] = now
    asset["exifInfo"]["dateTimeOriginal"] = now
    asset["localDateTime"] = now
    return asset


def test_recently_shown_uses_24h_window_for_regular_assets(
    manager: SlideshowManager,
) -> None:
    """A regular (old) asset is excluded for SHOWN_MEMORY_HOURS, then eligible."""
    from custom_components.immich_slideshow.const import SHOWN_MEMORY_HOURS

    manager._shown = {
        "inside": _hours_ago(SHOWN_MEMORY_HOURS - 1),
        "outside": _hours_ago(SHOWN_MEMORY_HOURS + 1),
    }
    assert manager._is_recently_shown(create_landscape_asset("inside")) is True
    assert manager._is_recently_shown(create_landscape_asset("outside")) is False
    assert manager._is_recently_shown(create_landscape_asset("never")) is False


def test_recently_shown_uses_short_window_for_boosted_assets(
    mock_hub: AsyncMock,
) -> None:
    """Assets in the boost window cycle faster (SHOWN_MEMORY_HOURS_BOOSTED)."""
    from custom_components.immich_slideshow.const import (
        SHOWN_MEMORY_HOURS,
        SHOWN_MEMORY_HOURS_BOOSTED,
    )

    manager = SlideshowManager(
        hub=mock_hub, dual_portrait=False, recent_boost_days=7, recent_boost_share=40
    )
    # Midway between the two windows: excluded for a regular asset, free for a
    # boosted one.
    mid = (SHOWN_MEMORY_HOURS_BOOSTED + SHOWN_MEMORY_HOURS) / 2
    manager._shown = {"fresh": _hours_ago(mid), "old": _hours_ago(mid)}

    assert manager._is_recently_shown(_boosted_asset("fresh")) is False
    assert manager._is_recently_shown(create_landscape_asset("old")) is True

    # Inside the short window the boosted asset is excluded too.
    manager._shown["fresh"] = _hours_ago(SHOWN_MEMORY_HOURS_BOOSTED / 2)
    assert manager._is_recently_shown(_boosted_asset("fresh")) is True


def test_boost_disabled_never_shortens_window(mock_hub: AsyncMock) -> None:
    """recent_boost_days=0 (or share=0) → boosted window never applies."""
    from custom_components.immich_slideshow.const import (
        SHOWN_MEMORY_HOURS,
        SHOWN_MEMORY_HOURS_BOOSTED,
    )

    mid = (SHOWN_MEMORY_HOURS_BOOSTED + SHOWN_MEMORY_HOURS) / 2
    for kwargs in ({"recent_boost_days": 0}, {"recent_boost_share": 0}):
        manager = SlideshowManager(hub=mock_hub, dual_portrait=False, **kwargs)
        manager._shown = {"fresh": _hours_ago(mid)}
        assert manager._is_in_boost_window(_boosted_asset("fresh")) is False
        assert manager._is_recently_shown(_boosted_asset("fresh")) is True


def test_pop_from_pool_skips_recently_shown(manager: SlideshowManager) -> None:
    """Fresh assets are served first; recently shown ones stay in the pool."""
    manager._shown = {"seen": _hours_ago(1)}
    manager._asset_pool = [
        create_landscape_asset("seen"),
        create_landscape_asset("fresh"),
    ]

    result = manager._pop_from_pool(1)

    assert [a["id"] for a in result] == ["fresh"]
    assert [a["id"] for a in manager._asset_pool] == ["seen"]


def test_pop_from_pool_anti_famine_uses_least_recently_shown(
    manager: SlideshowManager,
) -> None:
    """When every asset was shown recently, serve the oldest-shown first."""
    manager._shown = {
        "newest": _hours_ago(1),
        "oldest": _hours_ago(10),
        "middle": _hours_ago(5),
    }
    manager._asset_pool = [
        create_landscape_asset("newest"),
        create_landscape_asset("oldest"),
        create_landscape_asset("middle"),
    ]

    result = manager._pop_from_pool(2)

    assert [a["id"] for a in result] == ["oldest", "middle"]
    assert [a["id"] for a in manager._asset_pool] == ["newest"]


async def test_refill_anti_famine_falls_back_when_all_recently_shown(
    mock_hub: AsyncMock, manager: SlideshowManager
) -> None:
    """The refill must not starve the slideshow if every candidate was shown."""
    manager._shown = {"a": _hours_ago(2), "b": _hours_ago(8)}
    mock_hub.search_random_recent.return_value = [
        create_landscape_asset("a"),
        create_landscape_asset("b"),
    ]

    await manager._refill_pool()

    assert {a["id"] for a in manager._asset_pool} == {"a", "b"}


def test_mark_shown_records_all_assets_and_purges_expired(
    manager: SlideshowManager,
) -> None:
    """Both assets of a dual-portrait pair are stamped; expired entries drop."""
    from custom_components.immich_slideshow.const import SHOWN_MEMORY_HOURS

    manager._shown = {"expired": _hours_ago(SHOWN_MEMORY_HOURS + 1)}

    manager._mark_shown(create_landscape_asset("p1"), create_landscape_asset("p2"))

    assert set(manager._shown) == {"p1", "p2"}


def test_boost_reshow_hours_option_controls_window(mock_hub: AsyncMock) -> None:
    """recent_boost_reshow_hours sets the boosted window (1 h vs 12 h)."""
    for hours, shown_ago, expected in (
        (1, 2, False),    # 1 h window, shown 2 h ago → free
        (12, 2, True),    # 12 h window, shown 2 h ago → still excluded
        (12, 13, False),  # past the 12 h window → free
    ):
        manager = SlideshowManager(
            hub=mock_hub,
            dual_portrait=False,
            recent_boost_days=7,
            recent_boost_share=40,
            recent_boost_reshow_hours=hours,
        )
        manager._shown = {"x": _hours_ago(shown_ago)}
        assert manager._is_recently_shown(_boosted_asset("x")) is expected


def test_boost_reshow_hours_never_below_one(mock_hub: AsyncMock) -> None:
    """A 0 / negative value is clamped to 1 h (no immediate repeats)."""
    manager = SlideshowManager(
        hub=mock_hub, dual_portrait=False, recent_boost_reshow_hours=0
    )
    assert manager._recent_boost_reshow_hours == 1
