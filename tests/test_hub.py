"""Tests for Immich Hub API client."""
from __future__ import annotations

import pytest
from aioresponses import aioresponses

from custom_components.immich_slideshow.hub import (
    CannotConnect,
    ImmichHub,
)


MOCK_HOST = "http://immich.local:2283"
MOCK_API_KEY = "test-api-key"


# =============================================================================
# Authentication Tests
# =============================================================================


async def test_authenticate_success() -> None:
    """Test successful authentication."""
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)

    with aioresponses() as mock:
        mock.post(
            f"{MOCK_HOST}/api/auth/validateToken",
            payload={"authStatus": True},
        )

        result = await hub.authenticate()
        assert result is True

    await hub.close()


async def test_authenticate_invalid_token() -> None:
    """Test authentication with invalid token."""
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)

    with aioresponses() as mock:
        mock.post(
            f"{MOCK_HOST}/api/auth/validateToken",
            payload={"authStatus": False},
        )

        result = await hub.authenticate()
        assert result is False

    await hub.close()


async def test_authenticate_http_error() -> None:
    """Test authentication with HTTP error."""
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)

    with aioresponses() as mock:
        mock.post(
            f"{MOCK_HOST}/api/auth/validateToken",
            status=401,
        )

        result = await hub.authenticate()
        assert result is False

    await hub.close()


async def test_authenticate_connection_error() -> None:
    """Test authentication when server is unreachable."""
    import aiohttp
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)

    with aioresponses() as mock:
        mock.post(
            f"{MOCK_HOST}/api/auth/validateToken",
            exception=aiohttp.ClientError("Connection refused"),
        )

        with pytest.raises(CannotConnect):
            await hub.authenticate()

    await hub.close()


# =============================================================================
# Search Random Recent Tests
# =============================================================================


async def test_search_random_recent_success() -> None:
    """Test successful random image search."""
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)

    mock_assets = [
        {"id": "asset-1", "type": "IMAGE"},
        {"id": "asset-2", "type": "IMAGE"},
    ]

    with aioresponses() as mock:
        mock.post(
            f"{MOCK_HOST}/api/search/random",
            payload=mock_assets,
        )

        result = await hub.search_random_recent(days=30, count=10)
        assert len(result) == 2
        assert result[0]["id"] == "asset-1"

    await hub.close()


async def test_search_random_recent_empty() -> None:
    """Test random search with no results."""
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)

    with aioresponses() as mock:
        mock.post(
            f"{MOCK_HOST}/api/search/random",
            payload=[],
        )

        result = await hub.search_random_recent(days=30, count=10)
        assert result == []

    await hub.close()


async def test_search_random_recent_error() -> None:
    """Test random search with server error."""
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)

    with aioresponses() as mock:
        mock.post(
            f"{MOCK_HOST}/api/search/random",
            status=500,
            body="Internal Server Error",
        )

        result = await hub.search_random_recent(days=30, count=10)
        assert result == []

    await hub.close()


async def test_search_random_recent_favorites_only() -> None:
    """Test random search with favorites_filter='only'."""
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)

    mock_assets = [
        {"id": "fav-1", "type": "IMAGE", "isFavorite": True},
    ]

    with aioresponses() as mock:
        mock.post(
            f"{MOCK_HOST}/api/search/random",
            payload=mock_assets,
        )

        result = await hub.search_random_recent(days=30, count=10, favorites_filter="only")
        assert len(result) == 1
        assert result[0]["id"] == "fav-1"

    await hub.close()


async def test_search_random_recent_favorites_exclude() -> None:
    """Test random search with favorites_filter='exclude'."""
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)

    mock_assets = [
        {"id": "non-fav-1", "type": "IMAGE", "isFavorite": False},
    ]

    with aioresponses() as mock:
        mock.post(
            f"{MOCK_HOST}/api/search/random",
            payload=mock_assets,
        )

        result = await hub.search_random_recent(days=30, count=10, favorites_filter="exclude")
        assert len(result) == 1
        assert result[0]["id"] == "non-fav-1"

    await hub.close()


async def test_search_random_recent_favorites_all() -> None:
    """Test random search with favorites_filter='all' (default)."""
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)

    mock_assets = [
        {"id": "asset-1", "type": "IMAGE", "isFavorite": True},
        {"id": "asset-2", "type": "IMAGE", "isFavorite": False},
    ]

    with aioresponses() as mock:
        mock.post(
            f"{MOCK_HOST}/api/search/random",
            payload=mock_assets,
        )

        result = await hub.search_random_recent(days=30, count=10, favorites_filter="all")
        assert len(result) == 2

    await hub.close()


# =============================================================================
# Download Asset Tests
# =============================================================================


async def test_download_asset_success() -> None:
    """Test successful asset download."""
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)
    asset_id = "test-asset-123"
    fake_image_bytes = b"\xff\xd8\xff\xe0\x00\x10JFIF"  # JPEG header

    with aioresponses() as mock:
        mock.get(
            f"{MOCK_HOST}/api/assets/{asset_id}/original",
            body=fake_image_bytes,
            headers={"content-type": "image/jpeg"},
        )

        result = await hub.download_asset(asset_id)
        assert result == fake_image_bytes

    await hub.close()


async def test_download_asset_thumbnail() -> None:
    """Test thumbnail download."""
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)
    asset_id = "test-asset-123"
    fake_image_bytes = b"\xff\xd8\xff"

    with aioresponses() as mock:
        mock.get(
            f"{MOCK_HOST}/api/assets/{asset_id}/thumbnail",
            body=fake_image_bytes,
            headers={"content-type": "image/jpeg"},
        )

        result = await hub.download_asset(asset_id, thumbnail=True)
        assert result == fake_image_bytes

    await hub.close()


async def test_download_asset_not_found() -> None:
    """Test download of non-existent asset."""
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)
    asset_id = "nonexistent"

    with aioresponses() as mock:
        mock.get(
            f"{MOCK_HOST}/api/assets/{asset_id}/original",
            status=404,
        )

        result = await hub.download_asset(asset_id)
        assert result is None

    await hub.close()


async def test_download_asset_wrong_content_type() -> None:
    """Test download with unexpected content type."""
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)
    asset_id = "test-asset"

    with aioresponses() as mock:
        mock.get(
            f"{MOCK_HOST}/api/assets/{asset_id}/original",
            body=b"not an image",
            headers={"content-type": "text/plain"},
        )

        result = await hub.download_asset(asset_id)
        assert result is None

    await hub.close()


# =============================================================================
# Get Asset Info Tests
# =============================================================================


async def test_get_asset_info_success() -> None:
    """Test successful asset info retrieval."""
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)
    asset_id = "test-asset-123"

    mock_info = {
        "id": asset_id,
        "type": "IMAGE",
        "exifInfo": {
            "exifImageWidth": 4000,
            "exifImageHeight": 3000,
            "orientation": 1,
        },
    }

    with aioresponses() as mock:
        mock.get(
            f"{MOCK_HOST}/api/assets/{asset_id}",
            payload=mock_info,
        )

        result = await hub.get_asset_info(asset_id)
        assert result["id"] == asset_id
        assert result["exifInfo"]["exifImageWidth"] == 4000

    await hub.close()


async def test_get_asset_info_not_found() -> None:
    """Test asset info for non-existent asset."""
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)
    asset_id = "nonexistent"

    with aioresponses() as mock:
        mock.get(
            f"{MOCK_HOST}/api/assets/{asset_id}",
            status=404,
        )

        result = await hub.get_asset_info(asset_id)
        assert result is None

    await hub.close()


# =============================================================================
# Memories Tests
# =============================================================================


async def test_get_memories_success() -> None:
    """Test successful memories retrieval."""
    import re
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)

    mock_memories = [
        {
            "data": {"year": 2020},
            "assets": [
                {"id": "memory-1", "type": "IMAGE"},
                {"id": "memory-2", "type": "IMAGE"},
            ],
        },
        {
            "data": {"year": 2019},
            "assets": [
                {"id": "memory-3", "type": "IMAGE"},
            ],
        },
    ]

    with aioresponses() as mock:
        # Use pattern to match URL with query params
        mock.get(
            re.compile(rf"{re.escape(MOCK_HOST)}/api/memories\?.*"),
            payload=mock_memories,
        )

        result = await hub.get_memories("2024-01-15")
        assert len(result) == 2
        assert result[0]["data"]["year"] == 2020

    await hub.close()


async def test_get_memory_assets_with_max_years() -> None:
    """Test memory assets with max_years filter."""
    import re
    from datetime import datetime
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)

    current_year = datetime.now().year
    # Memories from recent and old years
    mock_memories = [
        {
            "data": {"year": current_year - 2},  # 2 years ago
            "assets": [{"id": "recent-memory", "type": "IMAGE"}],
        },
        {
            "data": {"year": current_year - 9},  # 9 years ago
            "assets": [{"id": "old-memory", "type": "IMAGE"}],
        },
    ]

    with aioresponses() as mock:
        mock.get(
            re.compile(rf"{re.escape(MOCK_HOST)}/api/memories\?.*"),
            payload=mock_memories,
        )

        # Only get memories from last 5 years
        result = await hub.get_memory_assets(max_years=5)

        # Should only include the recent memory
        assert len(result) == 1
        assert result[0]["id"] == "recent-memory"
        assert result[0]["memory_year"] == current_year - 2

    await hub.close()


async def test_get_memory_assets_filters_videos() -> None:
    """Test that memory assets filters out videos."""
    import re
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)

    mock_memories = [
        {
            "data": {"year": 2022},
            "assets": [
                {"id": "image-1", "type": "IMAGE"},
                {"id": "video-1", "type": "VIDEO"},
                {"id": "image-2", "type": "IMAGE"},
            ],
        },
    ]

    with aioresponses() as mock:
        mock.get(
            re.compile(rf"{re.escape(MOCK_HOST)}/api/memories\?.*"),
            payload=mock_memories,
        )

        result = await hub.get_memory_assets()

        # Should only include images
        assert len(result) == 2
        assert all(a["id"].startswith("image-") for a in result)

    await hub.close()


# =============================================================================
# Edge Cases
# =============================================================================


async def test_host_trailing_slash_stripped() -> None:
    """Test that trailing slash is stripped from host."""
    hub = ImmichHub("http://immich.local:2283/", MOCK_API_KEY)
    assert hub._host == "http://immich.local:2283"
    await hub.close()


async def test_close_session_multiple_times() -> None:
    """Test that closing session multiple times is safe."""
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)

    # Force session creation
    with aioresponses() as mock:
        mock.post(
            f"{MOCK_HOST}/api/auth/validateToken",
            payload={"authStatus": True},
        )
        await hub.authenticate()

    # Close multiple times should not raise
    await hub.close()
    await hub.close()
