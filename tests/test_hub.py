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
    """Test successful random search from specific albums (one call per album).

    Workaround for Immich's AND-only albumIds filter: hub fans out one call
    per album and combines results. Each asset is tagged with its source
    album_id (`_album_id`).
    """
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)
    album_ids = ["album-1", "album-2"]

    # Per-album response: hub does ceil(count/n_albums) per call → 5 each here
    mock_assets = [
        {"id": "asset-A", "type": "IMAGE"},
        {"id": "asset-B", "type": "IMAGE"},
        {"id": "asset-C", "type": "IMAGE"},
    ]

    with aioresponses() as mock:
        # repeat=True so the mock answers both parallel POSTs identically
        mock.post(
            f"{MOCK_HOST}/api/search/random",
            payload=mock_assets,
            repeat=True,
        )

        result = await hub.search_random_from_albums(album_ids, count=10)
        # Both album calls returned 3 assets each → 6 total, slice to 10 → 6
        assert len(result) == 6
        ids = {a["id"] for a in result}
        assert ids == {"asset-A", "asset-B", "asset-C"}
        # Every asset must carry the source album tag (one of album-1, album-2)
        assert all(a.get("_album_id") in album_ids for a in result)

    await hub.close()


async def test_search_random_from_albums_count_smaller_than_album_count() -> None:
    """When count < len(album_ids), only a random subset of albums is queried."""
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)
    album_ids = ["album-1", "album-2", "album-3", "album-4"]

    with aioresponses() as mock:
        mock.post(
            f"{MOCK_HOST}/api/search/random",
            payload=[{"id": "x", "type": "IMAGE"}],
            repeat=True,
        )

        result = await hub.search_random_from_albums(album_ids, count=2)
        # Only 2 albums queried (count=2 < 4 albums), 1 photo each → 2 results
        assert len(result) == 2

    await hub.close()


async def test_search_random_from_albums_REGRESSION_one_id_per_call() -> None:
    """REGRESSION: Immich's albumIds filter is AND, not OR.

    Bundling multiple album IDs into a single request body returns 0 assets
    when no asset is in *all* listed albums. The hub MUST issue one call per
    album with a single-element albumIds array. This test inspects every
    captured request body to enforce that contract.
    """
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)
    album_ids = ["album-1", "album-2", "album-3"]

    with aioresponses() as mock:
        mock.post(f"{MOCK_HOST}/api/search/random", payload=[], repeat=True)
        await hub.search_random_from_albums(album_ids, count=10)

        # Inspect every captured request body
        bodies = [
            call.kwargs.get("json", {})
            for (method, _), calls in mock.requests.items()
            if method == "POST"
            for call in calls
        ]
        assert len(bodies) == 3, f"Expected 3 calls (one per album), got {len(bodies)}"
        for body in bodies:
            assert "albumIds" in body
            assert isinstance(body["albumIds"], list)
            assert len(body["albumIds"]) == 1, (
                f"Body must contain a SINGLE-element albumIds (AND-bug regression), "
                f"got {len(body['albumIds'])}: {body['albumIds']}"
            )
        # All three album IDs must each have been queried exactly once
        ids_used = sorted(b["albumIds"][0] for b in bodies)
        assert ids_used == sorted(album_ids)

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
# Search Random By Person Tests
# =============================================================================


async def test_search_random_by_person_success() -> None:
    """Test successful random search by person (single person)."""
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
        # Order is randomized by combine+shuffle; check the set
        assert {a["id"] for a in result} == {"asset-1", "asset-2"}

    await hub.close()


async def test_search_random_by_person_multiple_persons_fans_out() -> None:
    """Multi-person search fans out one call per person (workaround for AND-only API)."""
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)
    person_ids = ["person-1", "person-2"]

    # Mock returns the same payload for both parallel calls. The client-side
    # filter then keeps only assets that contain the queried person.
    mock_assets = [
        {"id": "asset-with-1", "type": "IMAGE", "people": [{"id": "person-1"}]},
        {"id": "asset-with-2", "type": "IMAGE", "people": [{"id": "person-2"}]},
    ]
    with aioresponses() as mock:
        mock.post(
            f"{MOCK_HOST}/api/search/random",
            payload=mock_assets,
            repeat=True,
        )

        result = await hub.search_random_by_person(person_ids, count=4)
        # One call per person, each response filtered to the matching person.
        # Result combines both → both ids present.
        assert {a["id"] for a in result} == {"asset-with-1", "asset-with-2"}

    await hub.close()


async def test_search_random_by_person_REGRESSION_one_id_per_call() -> None:
    """REGRESSION: Immich's personIds filter is AND, not OR.

    Bundling multiple person IDs into a single body returns only assets that
    contain ALL listed persons, which is virtually never the case for a family
    setup → 0 results. The hub MUST issue one call per person with a
    single-element personIds array.
    """
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)
    person_ids = ["p-1", "p-2", "p-3", "p-4"]

    with aioresponses() as mock:
        mock.post(f"{MOCK_HOST}/api/search/random", payload=[], repeat=True)
        await hub.search_random_by_person(person_ids, count=8)

        bodies = [
            call.kwargs.get("json", {})
            for (method, _), calls in mock.requests.items()
            if method == "POST"
            for call in calls
        ]
        assert len(bodies) == 4, f"Expected 4 calls (one per person), got {len(bodies)}"
        for body in bodies:
            assert "personIds" in body
            assert isinstance(body["personIds"], list)
            assert len(body["personIds"]) == 1, (
                f"Body must contain a SINGLE-element personIds (AND-bug regression), "
                f"got {len(body['personIds'])}: {body['personIds']}"
            )
        ids_used = sorted(b["personIds"][0] for b in bodies)
        assert ids_used == sorted(person_ids)

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

        # Should only include assets actually containing person-1.
        # Order is randomized by combine+shuffle; check the set.
        assert {a["id"] for a in result} == {"asset-correct", "asset-also-correct"}

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


# =============================================================================
# Structured search API (Immich 3.2+) vs legacy flat API
# =============================================================================


def _mock_version(mock: aioresponses, major: int, minor: int, patch: int = 0) -> None:
    mock.get(
        f"{MOCK_HOST}/api/server/version",
        payload={"major": major, "minor": minor, "patch": patch},
    )


def _post_bodies(mock: aioresponses) -> list[dict]:
    return [
        call.kwargs.get("json", {})
        for (method, _), calls in mock.requests.items()
        if method == "POST"
        for call in calls
    ]


def _get_urls(mock: aioresponses) -> list[str]:
    return [
        str(url)
        for (method, url), calls in mock.requests.items()
        if method == "GET"
        for _ in calls
    ]


LEGACY_ONLY_KEYS = {
    "type", "takenAfter", "createdAfter", "isFavorite", "albumIds",
    "personIds", "visibility", "isNotInAlbum",
}


async def test_detect_search_api_v2_cached() -> None:
    """Immich >= 3.2.0 → structured API, detected once and cached."""
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)
    assert hub.supports_search_v2 is False

    with aioresponses() as mock:
        _mock_version(mock, 3, 2, 0)
        assert await hub.detect_search_api() is True
        # Second call must not hit the server (version mocked only once)
        assert await hub.detect_search_api() is True
        assert hub.supports_search_v2 is True
        assert len(_get_urls(mock)) == 1

    await hub.close()


async def test_detect_search_api_legacy_version() -> None:
    """Immich 3.1.x → legacy flat API."""
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)

    with aioresponses() as mock:
        _mock_version(mock, 3, 1, 9)
        assert await hub.detect_search_api() is False
        assert hub.supports_search_v2 is False

    await hub.close()


async def test_detect_search_api_unknown_is_retried() -> None:
    """Unknown version → legacy for now, detection retried next time."""
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)

    with aioresponses() as mock:
        mock.get(f"{MOCK_HOST}/api/server/version", status=500)
        assert await hub.detect_search_api() is False
        _mock_version(mock, 3, 2, 0)
        assert await hub.detect_search_api() is True

    await hub.close()


async def test_search_random_recent_v2_body() -> None:
    """Structured API: only `filter`, with exclusions as server-side `none`."""
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)

    with aioresponses() as mock:
        _mock_version(mock, 3, 2, 0)
        mock.post(f"{MOCK_HOST}/api/search/random", payload=[{"id": "a"}])

        result = await hub.search_random_recent(
            days=30,
            count=5,
            favorites_filter="only",
            exclude_album_ids=["album-b", "album-a"],
            exclude_person_ids=["person-x"],
        )
        assert result == [{"id": "a"}]

        [body] = _post_bodies(mock)
        assert not LEGACY_ONLY_KEYS & body.keys()
        assert body["size"] == 5
        assert body["withExif"] is True
        assert body["withPeople"] is True
        f = body["filter"]
        assert f["type"] == {"eq": "IMAGE"}
        assert f["trashedAt"] == {"eq": None}
        assert f["visibility"] == {"in": ["timeline"]}
        assert f["originalFileName"] == {"notLike": ".\\_"}
        assert f["takenAt"]["gte"].endswith("Z")
        assert f["isFavorite"] == {"eq": True}
        assert f["albumIds"] == {"none": ["album-a", "album-b"]}
        assert f["personIds"] == {"none": ["person-x"]}

    await hub.close()


async def test_search_random_recent_v2_include_archived() -> None:
    """Structured API: include_archived widens visibility to archive."""
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)

    with aioresponses() as mock:
        _mock_version(mock, 3, 2, 0)
        mock.post(f"{MOCK_HOST}/api/search/random", payload=[])

        await hub.search_random_recent(days=30, count=5, include_archived=True)
        [body] = _post_bodies(mock)
        assert body["filter"]["visibility"] == {"in": ["timeline", "archive"]}
        assert "albumIds" not in body["filter"]
        assert "personIds" not in body["filter"]
        assert "isFavorite" not in body["filter"]

    await hub.close()


async def test_search_random_recent_legacy_body() -> None:
    """Legacy flat API: flat fields, timeline only unless include_archived."""
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)

    with aioresponses() as mock:
        _mock_version(mock, 3, 1, 0)
        mock.post(f"{MOCK_HOST}/api/search/random", payload=[], repeat=True)

        await hub.search_random_recent(
            days=30, count=5, favorites_filter="exclude",
            exclude_album_ids=["album-a"], exclude_person_ids=["person-x"],
        )
        await hub.search_random_recent(days=30, count=5, include_archived=True)

        default_body, archived_body = _post_bodies(mock)
        assert "filter" not in default_body
        assert default_body["type"] == "IMAGE"
        assert default_body["takenAfter"].endswith("Z")
        assert default_body["isFavorite"] is False
        assert default_body["visibility"] == "timeline"
        assert default_body["withExif"] is True
        assert default_body["withPeople"] is True
        # Exclusions can't be expressed on the flat API (caller filters)
        assert "albumIds" not in default_body
        assert "personIds" not in default_body
        assert "visibility" not in archived_body

    await hub.close()


async def test_search_random_recent_boost_v2_single_or_request() -> None:
    """Structured API: boost is ONE request with or [takenAt, createdAt]."""
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)

    with aioresponses() as mock:
        _mock_version(mock, 3, 2, 0)
        mock.post(
            f"{MOCK_HOST}/api/search/random",
            payload=[{"id": "a"}, {"id": "b"}],
        )

        result = await hub.search_random_recent_boost(days=7, count=10)
        assert [a["id"] for a in result] == ["a", "b"]

        [body] = _post_bodies(mock)
        branches = body["filter"]["or"]
        assert len(branches) == 2
        taken, created = branches
        assert set(taken) == {"takenAt"}
        assert set(created) == {"createdAt"}
        assert taken["takenAt"]["gte"] == created["createdAt"]["gte"]
        assert "takenAt" not in body["filter"]

    await hub.close()


async def test_search_random_recent_boost_legacy_two_requests_dedup() -> None:
    """Legacy flat API: boost = takenAfter + createdAfter merged, deduplicated."""
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)

    with aioresponses() as mock:
        _mock_version(mock, 3, 1, 0)
        mock.post(f"{MOCK_HOST}/api/search/random", payload=[{"id": "a"}, {"id": "b"}])
        mock.post(f"{MOCK_HOST}/api/search/random", payload=[{"id": "b"}, {"id": "c"}])

        result = await hub.search_random_recent_boost(days=7, count=10)
        assert sorted(a["id"] for a in result) == ["a", "b", "c"]

        bodies = _post_bodies(mock)
        assert len(bodies) == 2
        assert {("takenAfter" in b, "createdAfter" in b) for b in bodies} == {
            (True, False),
            (False, True),
        }

    await hub.close()


async def test_search_random_from_albums_v2_merges_any_and_none() -> None:
    """Structured API: per-album `any` and excluded albums share one IdsFilter."""
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)

    with aioresponses() as mock:
        _mock_version(mock, 3, 2, 0)
        mock.post(f"{MOCK_HOST}/api/search/random", payload=[{"id": "a"}])

        result = await hub.search_random_from_albums(
            ["album-1"], count=2, exclude_album_ids=["album-x"],
            exclude_person_ids=["person-x"], include_archived=True,
        )
        assert result[0]["_album_id"] == "album-1"

        [body] = _post_bodies(mock)
        assert body["filter"]["albumIds"] == {"any": ["album-1"], "none": ["album-x"]}
        assert body["filter"]["personIds"] == {"none": ["person-x"]}
        assert body["filter"]["visibility"] == {"in": ["timeline", "archive"]}
        assert not LEGACY_ONLY_KEYS & body.keys()

    await hub.close()


async def test_search_random_by_person_v2_body() -> None:
    """Structured API: one `personIds any` call per person, defensive filter kept."""
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)

    with aioresponses() as mock:
        _mock_version(mock, 3, 2, 0)
        mock.post(
            f"{MOCK_HOST}/api/search/random",
            payload=[
                {"id": "a", "people": [{"id": "person-1"}]},
                {"id": "b", "people": [{"id": "someone-else"}]},
            ],
        )

        result = await hub.search_random_by_person(
            ["person-1"], count=5, exclude_person_ids=["person-x"]
        )
        assert [a["id"] for a in result] == ["a"]

        [body] = _post_bodies(mock)
        assert body["filter"]["personIds"] == {"any": ["person-1"], "none": ["person-x"]}
        assert body["withPeople"] is True

    await hub.close()


async def test_search_400_not_retried_and_warned_once(caplog) -> None:
    """A 400 (e.g. deleted album id) returns [] at once and warns once per id set."""
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)

    with aioresponses() as mock:
        _mock_version(mock, 3, 2, 0)
        mock.post(
            f"{MOCK_HOST}/api/search/random",
            status=400,
            payload={"message": "Not found or no album.read access"},
            repeat=True,
        )

        assert await hub.search_random_from_albums(["gone-album"], count=2) == []
        assert await hub.search_random_from_albums(["gone-album"], count=2) == []

        assert len(_post_bodies(mock)) == 2  # one per call, no retries
        warnings = [
            r for r in caplog.records
            if r.levelname == "WARNING" and "gone-album" in r.getMessage()
        ]
        assert len(warnings) == 1

    await hub.close()


async def test_download_asset_not_found_not_retried() -> None:
    """A 404 (original missing on disk) is not retried."""
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)

    with aioresponses() as mock:
        mock.get(f"{MOCK_HOST}/api/assets/gone/original", status=404, repeat=True)
        assert await hub.download_asset("gone") is None
        assert len(_get_urls(mock)) == 1

    await hub.close()


async def test_download_image_fullsize() -> None:
    """download_image fetches the fullsize rendition."""
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)

    with aioresponses() as mock:
        mock.get(
            f"{MOCK_HOST}/api/assets/a1/thumbnail?size=fullsize",
            body=b"jpeg",
            headers={"content-type": "image/jpeg"},
        )
        assert await hub.download_image("a1") == b"jpeg"

    await hub.close()


async def test_download_image_preview_size() -> None:
    """download_image can request the preview rendition."""
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)

    with aioresponses() as mock:
        mock.get(
            f"{MOCK_HOST}/api/assets/a1/thumbnail?size=preview",
            body=b"small",
            headers={"content-type": "image/jpeg"},
        )
        assert await hub.download_image("a1", size="preview") == b"small"

    await hub.close()


async def test_download_image_403_falls_back_to_original_for_good(caplog) -> None:
    """Missing asset.view → original, remembered for later calls, logged once."""
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)

    with aioresponses() as mock:
        mock.get(
            f"{MOCK_HOST}/api/assets/a1/thumbnail?size=fullsize",
            status=403,
            payload={"message": "Missing required permission: asset.view"},
        )
        for asset_id in ("a1", "a2"):
            mock.get(
                f"{MOCK_HOST}/api/assets/{asset_id}/original",
                body=b"orig-" + asset_id.encode(),
                headers={"content-type": "image/jpeg"},
            )

        assert await hub.download_image("a1") == b"orig-a1"
        assert await hub.download_image("a2") == b"orig-a2"

        urls = _get_urls(mock)
        assert sum("/thumbnail" in u for u in urls) == 1
        assert sum("/original" in u for u in urls) == 2
        infos = [r for r in caplog.records if "asset.view" in r.getMessage()]
        assert len(infos) == 1

    await hub.close()


async def test_download_image_404_no_retry_no_fallback() -> None:
    """A 404 on the rendition returns None at once, without trying /original."""
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)

    with aioresponses() as mock:
        mock.get(
            f"{MOCK_HOST}/api/assets/gone/thumbnail?size=fullsize",
            status=404,
            repeat=True,
        )
        assert await hub.download_image("gone") is None
        urls = _get_urls(mock)
        assert len(urls) == 1
        assert "/original" not in urls[0]

    await hub.close()


# =============================================================================
# Permission probing — asset.view (recommended)
# =============================================================================


def _mock_permission_probes(mock, *, view_status: int) -> None:
    """Mock every endpoint check_permissions touches; only asset.view varies."""
    for _ in range(2):  # the asset.read probe, then the id lookup
        mock.post(f"{MOCK_HOST}/api/search/random", payload=[{"id": "a1"}])
    mock.get(
        f"{MOCK_HOST}/api/assets/a1/original",
        status=206,
        body=b"x",
        headers={"content-type": "image/jpeg"},
    )
    if view_status == 403:
        mock.get(
            f"{MOCK_HOST}/api/assets/a1/thumbnail?size=thumbnail",
            status=403,
            payload={"message": "Missing required permission: asset.view"},
        )
    else:
        mock.get(
            f"{MOCK_HOST}/api/assets/a1/thumbnail?size=thumbnail",
            status=view_status,
            body=b"x",
            headers={"content-type": "image/webp"},
        )
    for path in ("/api/memories", "/api/albums", "/api/people", "/api/users"):
        mock.get(f"{MOCK_HOST}{path}", payload=[])


@pytest.mark.parametrize(("view_status", "expected_ok"), [(200, True), (403, False)])
async def test_check_permissions_probes_asset_view(view_status, expected_ok) -> None:
    """asset.view is probed on the thumbnail endpoint of a real asset."""
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)

    with aioresponses() as mock:
        _mock_permission_probes(mock, view_status=view_status)
        perms = await hub.check_permissions()

    assert perms["asset_view"] == {
        "ok": expected_ok,
        "permission": "asset.view",
        "unknown": False,
    }
    assert perms["asset_download"]["ok"] is True
    await hub.close()


async def test_check_permissions_asset_view_unknown_without_asset() -> None:
    """No asset to probe with → asset.view is unknown, never falsely denied."""
    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)

    with aioresponses() as mock:
        for _ in range(2):
            mock.post(f"{MOCK_HOST}/api/search/random", payload=[])
        for path in ("/api/memories", "/api/albums", "/api/people", "/api/users"):
            mock.get(f"{MOCK_HOST}{path}", payload=[])
        perms = await hub.check_permissions()

    assert perms["asset_view"]["unknown"] is True
    assert perms["asset_download"]["unknown"] is True
    await hub.close()


async def test_get_memories_sends_plain_date_first() -> None:
    """Immich 3.1+ wants YYYY-MM-DD: the first request must use that form."""
    import re

    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)
    with aioresponses() as mock:
        mock.get(
            re.compile(rf"{re.escape(MOCK_HOST)}/api/memories\?.*"), payload=[]
        )
        await hub.get_memories("2026-10-12")

        urls = [str(key[1]) for key in mock.requests]
        assert len(urls) == 1
        assert "for=2026-10-12" in urls[0]
        assert "T00%3A00" not in urls[0] and "T00:00" not in urls[0]

    await hub.close()


async def test_get_memories_plain_date_even_from_datetime_input() -> None:
    """A full datetime passed in is truncated to the plain date."""
    import re

    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)
    with aioresponses() as mock:
        mock.get(
            re.compile(rf"{re.escape(MOCK_HOST)}/api/memories\?.*"), payload=[]
        )
        await hub.get_memories("2026-10-12T09:30:00.000Z")

        urls = [str(key[1]) for key in mock.requests]
        assert "for=2026-10-12" in urls[0]
        assert "09" not in urls[0].split("for=")[1].split("&")[0]

    await hub.close()


async def test_get_memories_falls_back_to_legacy_datetime_on_400() -> None:
    """Older v3 builds reject the plain date: retry at once with UTC datetime."""
    import re

    hub = ImmichHub(MOCK_HOST, MOCK_API_KEY)
    memories = [{"data": {"year": 2020}, "assets": [{"id": "m1", "type": "IMAGE"}]}]
    pattern = re.compile(rf"{re.escape(MOCK_HOST)}/api/memories\?.*")
    with aioresponses() as mock:
        mock.get(pattern, status=400, payload={"message": "Validation failed"})
        mock.get(pattern, payload=memories)

        result = await hub.get_memories("2026-10-12")

        urls = [str(key[1]) for key in mock.requests]
        assert len(urls) == 2
        assert "for=2026-10-12" in urls[0] and "T00" not in urls[0]
        assert "2026-10-12T00" in urls[1]
        assert result == memories

    await hub.close()
