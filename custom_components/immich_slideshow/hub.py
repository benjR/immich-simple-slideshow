"""Hub for Immich API communication."""
from __future__ import annotations

import asyncio
import logging
import math
import random
from datetime import datetime, timedelta
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

# API settings
API_TIMEOUT = aiohttp.ClientTimeout(total=30, connect=10)
MAX_RETRIES = 3
RETRY_DELAYS = [1, 2, 4]  # Exponential backoff in seconds
# Max parallel calls when fanning out one-call-per-id (multi-album / multi-person
# random search). Immich's albumIds/personIds filters are AND-only, so we issue
# one call per id and combine.
API_CONCURRENCY_LIMIT = 5


class CannotConnect(Exception):
    """Error to indicate we cannot connect."""


class InvalidAuth(Exception):
    """Error to indicate there is invalid auth."""


class ImmichHub:
    """Hub for communicating with Immich API."""

    def __init__(self, host: str, api_key: str) -> None:
        """Initialize the hub."""
        self._host = host.rstrip("/")
        self._api_key = api_key
        self._session: aiohttp.ClientSession | None = None
        self._session_lock = asyncio.Lock()

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session with timeout."""
        async with self._session_lock:
            if self._session is None or self._session.closed:
                self._session = aiohttp.ClientSession(timeout=API_TIMEOUT)
            return self._session

    async def close(self) -> None:
        """Close the session."""
        if self._session and not self._session.closed:
            await self._session.close()

    def _headers(self) -> dict[str, str]:
        """Get headers for API requests."""
        return {"x-api-key": self._api_key}

    async def authenticate(self) -> bool:
        """Test if we can authenticate with the host."""
        try:
            session = await self._get_session()
            async with session.post(
                f"{self._host}/api/auth/validateToken",
                headers=self._headers(),
            ) as response:
                if response.status != 200:
                    return False
                data = await response.json()
                return data.get("authStatus", False)
        except aiohttp.ClientError as err:
            _LOGGER.error("Error connecting to Immich: %s", err)
            raise CannotConnect from err

    async def search_random_recent(
        self,
        days: int = 90,
        count: int = 10,
        favorites_filter: str = "all",
    ) -> list[dict[str, Any]]:
        """Get random images from the last X days.

        Args:
            days: Number of days to look back
            count: Number of random images to fetch
            favorites_filter: "all" (no filter), "only" (favorites only), "exclude" (no favorites)

        Returns:
            List of asset dictionaries with id, originalWidth, originalHeight, etc.
        """
        taken_after = (datetime.now() - timedelta(days=days)).isoformat()

        json_body: dict[str, Any] = {
            "takenAfter": taken_after,
            "type": "IMAGE",
            "size": count,
        }

        # Apply favorites filter
        if favorites_filter == "only":
            json_body["isFavorite"] = True
        elif favorites_filter == "exclude":
            json_body["isFavorite"] = False

        url = f"{self._host}/api/search/random"

        for attempt in range(MAX_RETRIES):
            try:
                session = await self._get_session()
                async with session.post(
                    url,
                    headers=self._headers(),
                    json=json_body,
                ) as response:
                    if response.status == 200:
                        return await response.json()
                    _LOGGER.warning(
                        "Failed to fetch random images (attempt %d/%d): %s",
                        attempt + 1, MAX_RETRIES, response.status
                    )
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                _LOGGER.warning(
                    "Error fetching random images (attempt %d/%d): %s",
                    attempt + 1, MAX_RETRIES, err
                )

            # Wait before retry
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)])

        _LOGGER.error("All retries failed for search_random_recent")
        return []

    async def download_asset(self, asset_id: str, thumbnail: bool = False) -> bytes | None:
        """Download an asset from Immich.

        Args:
            asset_id: The ID of the asset to download
            thumbnail: If True, download thumbnail instead of original

        Returns:
            Image bytes or None if failed
        """
        endpoint = "thumbnail" if thumbnail else "original"
        url = f"{self._host}/api/assets/{asset_id}/{endpoint}"

        for attempt in range(MAX_RETRIES):
            try:
                session = await self._get_session()
                async with session.get(url, headers=self._headers()) as response:
                    if response.status != 200:
                        _LOGGER.warning(
                            "Failed to download asset %s (attempt %d/%d): %s",
                            asset_id, attempt + 1, MAX_RETRIES, response.status
                        )
                    else:
                        content_type = response.headers.get("content-type", "")
                        if "image" not in content_type:
                            _LOGGER.warning(
                                "Unexpected content type for asset %s: %s",
                                asset_id, content_type
                            )
                            return None
                        return await response.read()
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                _LOGGER.warning(
                    "Error downloading asset %s (attempt %d/%d): %s",
                    asset_id, attempt + 1, MAX_RETRIES, err
                )

            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)])

        _LOGGER.error("All retries failed for download_asset %s", asset_id)
        return None

    async def download_video(self, asset_id: str) -> bytes | None:
        """Download a video asset from Immich.

        Args:
            asset_id: The ID of the video asset to download

        Returns:
            Video bytes or None if failed
        """
        url = f"{self._host}/api/assets/{asset_id}/original"

        for attempt in range(MAX_RETRIES):
            try:
                session = await self._get_session()
                async with session.get(url, headers=self._headers()) as response:
                    if response.status != 200:
                        _LOGGER.warning(
                            "Failed to download video %s (attempt %d/%d): %s",
                            asset_id, attempt + 1, MAX_RETRIES, response.status
                        )
                    else:
                        content_type = response.headers.get("content-type", "")
                        if "video" not in content_type:
                            _LOGGER.warning(
                                "Unexpected content type for video %s: %s",
                                asset_id, content_type
                            )
                            return None
                        return await response.read()
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                _LOGGER.warning(
                    "Error downloading video %s (attempt %d/%d): %s",
                    asset_id, attempt + 1, MAX_RETRIES, err
                )

            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)])

        _LOGGER.error("All retries failed for download_video %s", asset_id)
        return None

    def get_video_stream_url(self, asset_id: str) -> str:
        """Get the streaming URL for a video asset.

        Args:
            asset_id: The ID of the video asset

        Returns:
            URL for video playback streaming
        """
        return f"{self._host}/api/assets/{asset_id}/video/playback"

    @property
    def api_key(self) -> str:
        """Return the API key for authenticated requests."""
        return self._api_key

    async def get_asset_info(self, asset_id: str) -> dict[str, Any] | None:
        """Get information about an asset.

        Args:
            asset_id: The ID of the asset

        Returns:
            Asset information dictionary or None if failed
        """
        url = f"{self._host}/api/assets/{asset_id}"

        for attempt in range(MAX_RETRIES):
            try:
                session = await self._get_session()
                async with session.get(url, headers=self._headers()) as response:
                    if response.status == 200:
                        return await response.json()
                    # Don't retry on 404 (asset not found)
                    if response.status == 404:
                        return None
            except (aiohttp.ClientError, asyncio.TimeoutError):
                pass  # Silently retry

            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)])

        return None

    async def get_memories(self, for_date: str | None = None) -> list[dict[str, Any]]:
        """Get 'On This Day' memories from Immich.

        Args:
            for_date: ISO date string (YYYY-MM-DD). Defaults to today.

        Returns:
            List of memory objects, each containing assets and year info.
        """
        if for_date is None:
            for_date = datetime.now().strftime("%Y-%m-%d")

        url = f"{self._host}/api/memories"
        params = {"type": "on_this_day", "for": for_date}

        for attempt in range(MAX_RETRIES):
            try:
                session = await self._get_session()
                async with session.get(
                    url, headers=self._headers(), params=params
                ) as response:
                    if response.status == 200:
                        return await response.json()
                    _LOGGER.warning(
                        "Failed to fetch memories (attempt %d/%d): %s",
                        attempt + 1, MAX_RETRIES, response.status
                    )
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                _LOGGER.warning(
                    "Error fetching memories (attempt %d/%d): %s",
                    attempt + 1, MAX_RETRIES, err
                )

            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)])

        _LOGGER.error("All retries failed for get_memories")
        return []

    async def get_memory_assets(
        self, for_date: str | None = None, max_years: int = 0
    ) -> list[dict[str, Any]]:
        """Get all assets from 'On This Day' memories, flattened.

        Args:
            for_date: ISO date string (YYYY-MM-DD). Defaults to today.
            max_years: Maximum years to look back (0 = unlimited).

        Returns:
            List of asset dictionaries with added 'memory_year' field.
        """
        memories = await self.get_memories(for_date)
        current_year = datetime.now().year
        assets = []

        for memory in memories:
            year = memory.get("data", {}).get("year")
            if year is None:
                continue

            # Skip current year - memories should be at least 1 year old
            if year >= current_year:
                continue

            # Filter by max_years if set
            if max_years > 0:
                years_ago = current_year - year
                if years_ago > max_years:
                    continue

            memory_assets = memory.get("assets", [])
            for asset in memory_assets:
                # Filter out videos - only include images
                if asset.get("type") != "IMAGE":
                    continue
                # Add memory year to asset for display purposes
                asset["memory_year"] = year
                assets.append(asset)

        return assets

    async def get_albums(self) -> list[dict[str, Any]]:
        """Get all albums for the user.

        Returns:
            List of album dicts with 'id', 'albumName', 'assetCount'.
        """
        url = f"{self._host}/api/albums"

        for attempt in range(MAX_RETRIES):
            try:
                session = await self._get_session()
                async with session.get(url, headers=self._headers()) as response:
                    if response.status == 200:
                        return await response.json()
                    _LOGGER.warning(
                        "Failed to fetch albums (attempt %d/%d): %s",
                        attempt + 1, MAX_RETRIES, response.status
                    )
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                _LOGGER.warning(
                    "Error fetching albums (attempt %d/%d): %s",
                    attempt + 1, MAX_RETRIES, err
                )

            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)])

        _LOGGER.error("All retries failed for get_albums")
        return []

    async def get_people(self) -> list[dict[str, Any]]:
        """Get all people/persons for the user.

        Returns:
            List of person dicts with 'id', 'name', 'thumbnailPath'.
            Only returns persons with names set.
        """
        url = f"{self._host}/api/people"

        for attempt in range(MAX_RETRIES):
            try:
                session = await self._get_session()
                async with session.get(url, headers=self._headers()) as response:
                    if response.status == 200:
                        data = await response.json()
                        # API returns {"people": [...], "total": N, ...}
                        people = data.get("people", [])
                        # Filter to only named persons
                        return [p for p in people if p.get("name")]
                    _LOGGER.warning(
                        "Failed to fetch people (attempt %d/%d): %s",
                        attempt + 1, MAX_RETRIES, response.status
                    )
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                _LOGGER.warning(
                    "Error fetching people (attempt %d/%d): %s",
                    attempt + 1, MAX_RETRIES, err
                )

            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)])

        _LOGGER.error("All retries failed for get_people")
        return []

    async def get_users(self) -> list[dict[str, Any]]:
        """Get all users (for resolving ownerId to a display name).

        Requires the `user.read` permission on the API key.
        Returns empty list on auth/permission failure (graceful — owner names
        just won't show up in entity attributes).
        """
        url = f"{self._host}/api/users"

        for attempt in range(MAX_RETRIES):
            try:
                session = await self._get_session()
                async with session.get(url, headers=self._headers()) as response:
                    if response.status == 200:
                        return await response.json()
                    _LOGGER.warning(
                        "Failed to fetch users (attempt %d/%d): %s",
                        attempt + 1, MAX_RETRIES, response.status
                    )
                    if response.status == 403:
                        # Permission missing — no point retrying
                        return []
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                _LOGGER.warning(
                    "Error fetching users (attempt %d/%d): %s",
                    attempt + 1, MAX_RETRIES, err
                )

            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)])

        _LOGGER.error("All retries failed for get_users")
        return []

    async def get_albums_for_asset(self, asset_id: str) -> list[dict[str, Any]]:
        """Find which albums contain a given asset.

        Uses /api/albums?assetId=<id> filter. Used to attribute photos to
        an album when fetching in "any album" mode (no specific include filter).

        Returns empty list on auth/permission failure.
        """
        url = f"{self._host}/api/albums?assetId={asset_id}"
        try:
            session = await self._get_session()
            async with session.get(url, headers=self._headers()) as response:
                if response.status == 200:
                    return await response.json()
                if response.status == 403:
                    return []
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            _LOGGER.debug("Error fetching albums for asset %s: %s", asset_id, err)
        return []

    async def get_album_assets(self, album_id: str) -> list[dict[str, Any]]:
        """Get all image assets from a specific album.

        Note: This method fetches the full album. For random sampling,
        use search_random_from_albums() instead.

        Args:
            album_id: The album UUID

        Returns:
            List of asset dicts (images only, videos filtered out).
        """
        url = f"{self._host}/api/albums/{album_id}"

        for attempt in range(MAX_RETRIES):
            try:
                session = await self._get_session()
                async with session.get(url, headers=self._headers()) as response:
                    if response.status == 200:
                        data = await response.json()
                        assets = data.get("assets", [])
                        # Filter to images only
                        return [a for a in assets if a.get("type") == "IMAGE"]
                    if response.status == 404:
                        _LOGGER.warning("Album %s not found", album_id)
                        return []
                    _LOGGER.warning(
                        "Failed to fetch album %s (attempt %d/%d): %s",
                        album_id, attempt + 1, MAX_RETRIES, response.status
                    )
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                _LOGGER.warning(
                    "Error fetching album %s (attempt %d/%d): %s",
                    album_id, attempt + 1, MAX_RETRIES, err
                )

            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)])

        _LOGGER.error("All retries failed for get_album_assets %s", album_id)
        return []

    async def _post_search_random(
        self, body: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """POST /api/search/random with retries. Returns [] on failure."""
        url = f"{self._host}/api/search/random"
        for attempt in range(MAX_RETRIES):
            try:
                session = await self._get_session()
                async with session.post(
                    url, headers=self._headers(), json=body
                ) as response:
                    if response.status == 200:
                        return await response.json()
                    _LOGGER.warning(
                        "Failed search/random (attempt %d/%d): %s",
                        attempt + 1, MAX_RETRIES, response.status,
                    )
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                _LOGGER.warning(
                    "Error search/random (attempt %d/%d): %s",
                    attempt + 1, MAX_RETRIES, err,
                )
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)])
        _LOGGER.error("All retries failed for search/random")
        return []

    async def search_random_from_albums(
        self,
        album_ids: list[str],
        count: int = 50,
    ) -> list[dict[str, Any]]:
        """Search random images across multiple albums.

        Workaround: Immich's `albumIds` filter is AND (intersection), not OR
        (union). To approximate OR semantics, we issue one call per album in
        parallel and combine the results.

        For efficiency when count is small relative to len(album_ids), only a
        random subset of albums is queried (e.g. count=1 → 1 album sampled).
        Each refill picks a different random subset, so over time exposure
        across albums stays balanced.

        Each returned asset is tagged with `_album_id` for downstream
        attribution (used to resolve `album_name` in entity attributes).

        Args:
            album_ids: List of album UUIDs to search within.
            count: Total number of random images to return.

        Returns:
            List of asset dicts (size <= count), each tagged with `_album_id`.
        """
        if not album_ids or count <= 0:
            return []

        n_to_query = min(count, len(album_ids))
        selected_ids = random.sample(album_ids, n_to_query)
        per_id = math.ceil(count / n_to_query)
        sem = asyncio.Semaphore(API_CONCURRENCY_LIMIT)

        async def fetch_one(aid: str) -> list[dict[str, Any]]:
            async with sem:
                assets = await self._post_search_random(
                    {"albumIds": [aid], "type": "IMAGE", "size": per_id}
                )
            for a in assets:
                a["_album_id"] = aid
            return assets

        results = await asyncio.gather(*(fetch_one(aid) for aid in selected_ids))
        combined = [a for r in results for a in r]
        random.shuffle(combined)
        return combined[:count]

    async def search_random_in_any_album(
        self,
        count: int = 50,
    ) -> list[dict[str, Any]]:
        """Search random images that belong to at least one album.

        Uses isNotInAlbum: false to filter for photos in any album,
        without needing to specify album IDs.

        Args:
            count: Number of random images to fetch

        Returns:
            List of asset dictionaries.
        """
        url = f"{self._host}/api/search/random"
        json_body: dict[str, Any] = {
            "isNotInAlbum": False,
            "type": "IMAGE",
            "size": count,
        }

        for attempt in range(MAX_RETRIES):
            try:
                session = await self._get_session()
                async with session.post(
                    url,
                    headers=self._headers(),
                    json=json_body,
                ) as response:
                    if response.status == 200:
                        return await response.json()
                    _LOGGER.warning(
                        "Failed to search any album (attempt %d/%d): %s",
                        attempt + 1, MAX_RETRIES, response.status
                    )
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                _LOGGER.warning(
                    "Error searching any album (attempt %d/%d): %s",
                    attempt + 1, MAX_RETRIES, err
                )

            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)])

        _LOGGER.error("All retries failed for search_random_in_any_album")
        return []

    async def search_random_by_person(
        self,
        person_ids: list[str],
        count: int = 50,
    ) -> list[dict[str, Any]]:
        """Search random images containing any of the given persons.

        Workaround: Immich's `personIds` filter is AND (asset must contain ALL
        listed persons), not OR. To approximate OR semantics, we issue one call
        per person in parallel and combine the results.

        For efficiency when count is small relative to len(person_ids), only a
        random subset of persons is queried (e.g. count=1 → 1 person sampled).
        Each refill picks a different random subset, so over time exposure
        across persons stays balanced.

        Args:
            person_ids: List of person UUIDs to search for.
            count: Total number of random images to return.

        Returns:
            List of asset dicts (size <= count), each containing at least one
            of the requested persons.
        """
        if not person_ids or count <= 0:
            return []

        n_to_query = min(count, len(person_ids))
        selected_ids = random.sample(person_ids, n_to_query)
        per_id = math.ceil(count / n_to_query)
        sem = asyncio.Semaphore(API_CONCURRENCY_LIMIT)

        async def fetch_one(pid: str) -> list[dict[str, Any]]:
            async with sem:
                assets = await self._post_search_random(
                    {"personIds": [pid], "type": "IMAGE", "size": per_id, "withPeople": True}
                )
            # Client-side verify: keep only assets that actually contain pid.
            # The Immich API has had bugs returning unrelated assets in the past
            # (see GitHub #15010), so this is a defensive filter.
            return [a for a in assets if any(p.get("id") == pid for p in a.get("people", []))]

        results = await asyncio.gather(*(fetch_one(pid) for pid in selected_ids))
        combined = [a for r in results for a in r]
        random.shuffle(combined)
        return combined[:count]
