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


# =============================================================================
# Get Albums Tests
# =============================================================================


async def test_get_albums_success() -> None:
    """Test successful albums retrieval."""
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)

    mock_albums = [
        {"id": "album-1", "albumName": "Vacation 2024", "assetCount": 50},
        {"id": "album-2", "albumName": "Family", "assetCount": 100},
    ]

    with aioresponses() as mock:
        mock.get(
            f"{MOCK_HOST}/api/albums",
            payload=mock_albums,
        )

        result = await hub.get_albums()
        assert len(result) == 2
        assert result[0]["id"] == "album-1"
        assert result[0]["albumName"] == "Vacation 2024"
        assert result[1]["assetCount"] == 100

    await hub.close()


async def test_get_albums_empty() -> None:
    """Test albums retrieval with no albums."""
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)

    with aioresponses() as mock:
        mock.get(
            f"{MOCK_HOST}/api/albums",
            payload=[],
        )

        result = await hub.get_albums()
        assert result == []

    await hub.close()


async def test_get_albums_server_error() -> None:
    """Test albums retrieval with server error returns empty list after retries."""
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)

    with aioresponses() as mock:
        # Mock 3 failures (MAX_RETRIES)
        mock.get(f"{MOCK_HOST}/api/albums", status=500)
        mock.get(f"{MOCK_HOST}/api/albums", status=500)
        mock.get(f"{MOCK_HOST}/api/albums", status=500)

        result = await hub.get_albums()
        assert result == []

    await hub.close()


# =============================================================================
# Get People Tests
# =============================================================================


async def test_get_people_success() -> None:
    """Test successful people retrieval returns named persons only."""
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)

    mock_response = {
        "people": [
            {"id": "person-1", "name": "Alice", "thumbnailPath": "/thumb/1"},
            {"id": "person-2", "name": "Bob", "thumbnailPath": "/thumb/2"},
        ],
        "total": 2,
    }

    with aioresponses() as mock:
        mock.get(
            f"{MOCK_HOST}/api/people",
            payload=mock_response,
        )

        result = await hub.get_people()
        assert len(result) == 2
        assert result[0]["name"] == "Alice"
        assert result[1]["name"] == "Bob"

    await hub.close()


async def test_get_people_filters_unnamed() -> None:
    """Test that people without names are filtered out."""
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)

    mock_response = {
        "people": [
            {"id": "person-1", "name": "Alice", "thumbnailPath": "/thumb/1"},
            {"id": "person-2", "name": "", "thumbnailPath": "/thumb/2"},  # Empty name
            {"id": "person-3", "thumbnailPath": "/thumb/3"},  # No name field
            {"id": "person-4", "name": None, "thumbnailPath": "/thumb/4"},  # None name
            {"id": "person-5", "name": "Charlie", "thumbnailPath": "/thumb/5"},
        ],
        "total": 5,
    }

    with aioresponses() as mock:
        mock.get(
            f"{MOCK_HOST}/api/people",
            payload=mock_response,
        )

        result = await hub.get_people()
        assert len(result) == 2
        assert result[0]["name"] == "Alice"
        assert result[1]["name"] == "Charlie"

    await hub.close()


async def test_get_people_empty() -> None:
    """Test people retrieval with no people."""
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)

    mock_response = {
        "people": [],
        "total": 0,
    }

    with aioresponses() as mock:
        mock.get(
            f"{MOCK_HOST}/api/people",
            payload=mock_response,
        )

        result = await hub.get_people()
        assert result == []

    await hub.close()


async def test_get_people_server_error() -> None:
    """Test people retrieval with server error returns empty list after retries."""
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)

    with aioresponses() as mock:
        # Mock 3 failures (MAX_RETRIES)
        mock.get(f"{MOCK_HOST}/api/people", status=500)
        mock.get(f"{MOCK_HOST}/api/people", status=500)
        mock.get(f"{MOCK_HOST}/api/people", status=500)

        result = await hub.get_people()
        assert result == []

    await hub.close()


# =============================================================================
# Get Album Assets Tests
# =============================================================================


async def test_get_album_assets_success() -> None:
    """Test successful album assets retrieval."""
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)
    album_id = "album-123"

    mock_album = {
        "id": album_id,
        "albumName": "Test Album",
        "assets": [
            {"id": "asset-1", "type": "IMAGE"},
            {"id": "asset-2", "type": "IMAGE"},
        ],
    }

    with aioresponses() as mock:
        mock.get(
            f"{MOCK_HOST}/api/albums/{album_id}",
            payload=mock_album,
        )

        result = await hub.get_album_assets(album_id)
        assert len(result) == 2
        assert result[0]["id"] == "asset-1"
        assert result[1]["id"] == "asset-2"

    await hub.close()


async def test_get_album_assets_filters_videos() -> None:
    """Test that album assets filters out videos, only returns images."""
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)
    album_id = "album-123"

    mock_album = {
        "id": album_id,
        "albumName": "Mixed Album",
        "assets": [
            {"id": "image-1", "type": "IMAGE"},
            {"id": "video-1", "type": "VIDEO"},
            {"id": "image-2", "type": "IMAGE"},
            {"id": "video-2", "type": "VIDEO"},
        ],
    }

    with aioresponses() as mock:
        mock.get(
            f"{MOCK_HOST}/api/albums/{album_id}",
            payload=mock_album,
        )

        result = await hub.get_album_assets(album_id)
        assert len(result) == 2
        assert all(a["type"] == "IMAGE" for a in result)
        assert result[0]["id"] == "image-1"
        assert result[1]["id"] == "image-2"

    await hub.close()


async def test_get_album_assets_not_found_404() -> None:
    """Test album assets returns empty on 404."""
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)
    album_id = "nonexistent-album"

    with aioresponses() as mock:
        mock.get(
            f"{MOCK_HOST}/api/albums/{album_id}",
            status=404,
        )

        result = await hub.get_album_assets(album_id)
        assert result == []

    await hub.close()


async def test_get_album_assets_server_error() -> None:
    """Test album assets returns empty after retries on server error."""
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)
    album_id = "album-123"

    with aioresponses() as mock:
        # Mock 3 failures (MAX_RETRIES)
        mock.get(f"{MOCK_HOST}/api/albums/{album_id}", status=500)
        mock.get(f"{MOCK_HOST}/api/albums/{album_id}", status=500)
        mock.get(f"{MOCK_HOST}/api/albums/{album_id}", status=500)

        result = await hub.get_album_assets(album_id)
        assert result == []

    await hub.close()


# =============================================================================
# Search Random From Albums Tests
# =============================================================================


async def test_search_random_from_albums_success() -> None:
    """Test successful random search from specific albums."""
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)
    album_ids = ["album-1", "album-2"]

    mock_assets = [
        {"id": "asset-1", "type": "IMAGE"},
        {"id": "asset-2", "type": "IMAGE"},
        {"id": "asset-3", "type": "IMAGE"},
    ]

    with aioresponses() as mock:
        mock.post(
            f"{MOCK_HOST}/api/search/random",
            payload=mock_assets,
        )

        result = await hub.search_random_from_albums(album_ids, count=10)
        assert len(result) == 3
        assert result[0]["id"] == "asset-1"

    await hub.close()


async def test_search_random_from_albums_empty_album_ids() -> None:
    """Test random search with empty album_ids returns empty."""
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)

    # No mock needed - should return early
    result = await hub.search_random_from_albums([], count=10)
    assert result == []

    await hub.close()


async def test_search_random_from_albums_server_error() -> None:
    """Test random search from albums returns empty after retries on server error."""
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)
    album_ids = ["album-1"]

    with aioresponses() as mock:
        # Mock 3 failures (MAX_RETRIES)
        mock.post(f"{MOCK_HOST}/api/search/random", status=500)
        mock.post(f"{MOCK_HOST}/api/search/random", status=500)
        mock.post(f"{MOCK_HOST}/api/search/random", status=500)

        result = await hub.search_random_from_albums(album_ids, count=10)
        assert result == []

    await hub.close()


# =============================================================================
# Search Random In Any Album Tests
# =============================================================================


async def test_search_random_in_any_album_success() -> None:
    """Test successful random search in any album."""
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

        result = await hub.search_random_in_any_album(count=10)
        assert len(result) == 2
        assert result[0]["id"] == "asset-1"

    await hub.close()


async def test_search_random_in_any_album_empty_results() -> None:
    """Test random search in any album with no results."""
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)

    with aioresponses() as mock:
        mock.post(
            f"{MOCK_HOST}/api/search/random",
            payload=[],
        )

        result = await hub.search_random_in_any_album(count=10)
        assert result == []

    await hub.close()


async def test_search_random_in_any_album_server_error() -> None:
    """Test random search in any album returns empty after retries on server error."""
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)

    with aioresponses() as mock:
        # Mock 3 failures (MAX_RETRIES)
        mock.post(f"{MOCK_HOST}/api/search/random", status=500)
        mock.post(f"{MOCK_HOST}/api/search/random", status=500)
        mock.post(f"{MOCK_HOST}/api/search/random", status=500)

        result = await hub.search_random_in_any_album(count=10)
        assert result == []

    await hub.close()


# =============================================================================
# Search Random By Person Tests
# =============================================================================


async def test_search_random_by_person_success() -> None:
    """Test successful random search by person."""
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)
    person_ids = ["person-1"]

    mock_assets = [
        {
            "id": "asset-1",
            "type": "IMAGE",
            "people": [{"id": "person-1", "name": "Alice"}],
        },
        {
            "id": "asset-2",
            "type": "IMAGE",
            "people": [{"id": "person-1", "name": "Alice"}, {"id": "person-2", "name": "Bob"}],
        },
    ]

    with aioresponses() as mock:
        mock.post(
            f"{MOCK_HOST}/api/search/random",
            payload=mock_assets,
        )

        result = await hub.search_random_by_person(person_ids, count=10)
        assert len(result) == 2
        assert result[0]["id"] == "asset-1"
        assert result[1]["id"] == "asset-2"

    await hub.close()


async def test_search_random_by_person_filters_api_bug() -> None:
    """Test that local filtering works to fix Immich API bug (GitHub #15010).

    The Immich API may return assets that don't actually contain the requested
    person. This test verifies the hub correctly filters out those results.
    """
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)
    person_ids = ["person-1"]

    # API returns assets with wrong people (simulating the bug)
    mock_assets = [
        {
            "id": "asset-correct",
            "type": "IMAGE",
            "people": [{"id": "person-1", "name": "Alice"}],
        },
        {
            "id": "asset-wrong",
            "type": "IMAGE",
            "people": [{"id": "person-2", "name": "Bob"}],  # Wrong person!
        },
        {
            "id": "asset-no-people",
            "type": "IMAGE",
            "people": [],  # No people at all
        },
        {
            "id": "asset-also-correct",
            "type": "IMAGE",
            "people": [{"id": "person-1", "name": "Alice"}, {"id": "person-3", "name": "Charlie"}],
        },
    ]

    with aioresponses() as mock:
        mock.post(
            f"{MOCK_HOST}/api/search/random",
            payload=mock_assets,
        )

        result = await hub.search_random_by_person(person_ids, count=10)

        # Should only include assets with person-1
        assert len(result) == 2
        assert result[0]["id"] == "asset-correct"
        assert result[1]["id"] == "asset-also-correct"

    await hub.close()


async def test_search_random_by_person_empty_person_ids() -> None:
    """Test random search with empty person_ids returns empty."""
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)

    # No mock needed - should return early
    result = await hub.search_random_by_person([], count=10)
    assert result == []

    await hub.close()


async def test_search_random_by_person_server_error() -> None:
    """Test random search by person returns empty after retries on server error."""
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)
    person_ids = ["person-1"]

    with aioresponses() as mock:
        # Mock 3 failures (MAX_RETRIES)
        mock.post(f"{MOCK_HOST}/api/search/random", status=500)
        mock.post(f"{MOCK_HOST}/api/search/random", status=500)
        mock.post(f"{MOCK_HOST}/api/search/random", status=500)

        result = await hub.search_random_by_person(person_ids, count=10)
        assert result == []

    await hub.close()
