"""Hub for Immich API communication."""
from __future__ import annotations

import asyncio
from collections.abc import Iterable
import logging
import math
import random
from datetime import datetime, timedelta
from typing import Any

import aiohttp

from .const import CAPABILITY_PERMISSION

_LOGGER = logging.getLogger(__name__)

# API settings
API_TIMEOUT = aiohttp.ClientTimeout(total=30, connect=10)
MAX_RETRIES = 3
RETRY_DELAYS = [1, 2, 4]  # Exponential backoff in seconds
# Max parallel calls when fanning out one-call-per-id (multi-album / multi-person
# random search). One call per id keeps exposure balanced across albums/persons
# (a single `any` query would weight each id by its photo count).
API_CONCURRENCY_LIMIT = 5

# Immich 3.2 introduced the structured search API (`filter` tree with AND/OR
# and any/all/none id filters). The flat fields are deprecated (removed in v4)
# and cannot be mixed with `filter` in the same request (HTTP 400).
SEARCH_V2_MIN_VERSION = (3, 2, 0)
# String pattern filters are wrapped server-side as ILIKE '%<pattern>%', and
# `_` is a single-char wildcard: escape it so the pattern means "contains '._'".
# Matches macOS AppleDouble metadata files (`._IMG_0275.JPG`) imported as photos.
APPLEDOUBLE_NAME_PATTERN = ".\\_"
# Statuses that won't change on retry
NO_RETRY_STATUSES = (400, 401, 403, 404)


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
        # None = not detected yet (or version unknown → retried next search)
        self._search_v2: bool | None = None
        self._search_api_lock = asyncio.Lock()
        # Set once /thumbnail answers 401/403 (API key lacks asset.view)
        self._asset_view_denied = False
        # Album id sets already reported as rejected (400), to warn only once
        self._warned_rejected_albums: set[frozenset[str]] = set()

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

    async def get_server_version(self) -> tuple[int, int, int] | None:
        """Return the Immich server version as (major, minor, patch).

        Uses the public /api/server/version endpoint (no permission required).
        Returns None if the version can't be determined (endpoint missing on a
        very old server, connection error, or unexpected payload) — callers
        treat None as "unknown" and don't raise version warnings.
        """
        try:
            session = await self._get_session()
            async with session.get(
                f"{self._host}/api/server/version", headers=self._headers()
            ) as response:
                if response.status != 200:
                    return None
                data = await response.json()
                return (
                    int(data["major"]),
                    int(data["minor"]),
                    int(data["patch"]),
                )
        except (
            aiohttp.ClientError,
            asyncio.TimeoutError,
            KeyError,
            TypeError,
            ValueError,
        ) as err:
            _LOGGER.debug("Could not determine Immich server version: %s", err)
            return None

    async def _probe(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        headers_extra: dict[str, str] | None = None,
    ) -> tuple[int | None, str | None]:
        """Issue one lightweight request for capability probing.

        Returns (status_code, missing_permission). `missing_permission` is
        parsed from Immich's 403 body ({"message": "Missing required
        permission: <perm>"}). `status_code` is None on a connection error so
        callers can treat the verdict as "unknown" rather than "denied".
        """
        headers = self._headers()
        if headers_extra:
            headers = {**headers, **headers_extra}
        try:
            session = await self._get_session()
            async with session.request(
                method, f"{self._host}{path}", json=json_body, headers=headers
            ) as response:
                if response.status == 403:
                    perm = None
                    try:
                        body = await response.json()
                        msg = body.get("message", "") if isinstance(body, dict) else ""
                    except (aiohttp.ClientError, ValueError):
                        msg = ""
                    marker = "Missing required permission:"
                    if marker in msg:
                        perm = msg.split(marker, 1)[1].strip()
                    return response.status, perm
                return response.status, None
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            _LOGGER.debug("Permission probe %s %s failed: %s", method, path, err)
            return None, None

    async def check_permissions(self) -> dict[str, dict[str, Any]]:
        """Probe the API key's capabilities against the live Immich API.

        Returns a mapping ``capability -> {"ok": bool, "permission": str,
        "unknown": bool}``. ``unknown`` is True when the probe could not reach a
        verdict (connection error), so callers don't raise false alarms.

        Capabilities probed: asset_read, asset_download, asset_view,
        memory_read, album_read, person_read, user_read.
        """
        results: dict[str, dict[str, Any]] = {}

        def record(cap: str, status: int | None) -> None:
            results[cap] = {
                "ok": status is not None and status < 400,
                "permission": CAPABILITY_PERMISSION[cap],
                "unknown": status is None,
            }

        # asset.read — via search/random (the slideshow's core call).
        status, _ = await self._probe(
            "POST", "/api/search/random", json_body={"type": "IMAGE", "size": 1}
        )
        record("asset_read", status)

        # asset.download — needs a real asset id. Reuse search/random, then do a
        # 1-byte Range GET on /original so we don't pull a full-res file.
        asset_id: str | None = None
        if status == 200:
            assets = await self._post_search_random({"type": "IMAGE", "size": 1})
            if assets:
                asset_id = assets[0].get("id")
        if asset_id:
            dl_status, _ = await self._probe(
                "GET",
                f"/api/assets/{asset_id}/original",
                headers_extra={"Range": "bytes=0-0"},
            )
            record("asset_download", dl_status)
            # asset.view — renditions endpoint; the tiny "thumbnail" size keeps
            # the probe cheap (Immich may ignore the Range header there).
            view_status, _ = await self._probe(
                "GET",
                f"/api/assets/{asset_id}/thumbnail?size=thumbnail",
                headers_extra={"Range": "bytes=0-0"},
            )
            record("asset_view", view_status)
        else:
            # Couldn't obtain an id (no assets, or asset.read denied): can't
            # verify download/view → mark unknown rather than falsely denied.
            for cap in ("asset_download", "asset_view"):
                results[cap] = {
                    "ok": False,
                    "permission": CAPABILITY_PERMISSION[cap],
                    "unknown": True,
                }

        # Source + attribution capabilities (simple GETs).
        for cap, path in (
            ("memory_read", "/api/memories"),
            ("album_read", "/api/albums"),
            ("person_read", "/api/people"),
            ("user_read", "/api/users"),
        ):
            st, _ = await self._probe("GET", path)
            record(cap, st)

        return results

    @property
    def supports_search_v2(self) -> bool:
        """Return True if the server exposes the structured search API (3.2+).

        False until detection succeeded (see detect_search_api), so callers
        that read it before any search get the conservative legacy answer.
        """
        return bool(self._search_v2)

    async def detect_search_api(self) -> bool:
        """Detect whether the server supports the structured search API.

        True iff the server version is >= SEARCH_V2_MIN_VERSION. The verdict is
        cached; an unknown version (endpoint unreachable, odd payload) falls
        back to the legacy flat API for now and is re-detected next time.
        """
        # A pool refill fans out several searches at once: serialize detection
        # so the version endpoint is queried once, not once per search.
        async with self._search_api_lock:
            if self._search_v2 is not None:
                return self._search_v2
            version = await self.get_server_version()
            if version is None:
                _LOGGER.debug("Immich version unknown, using legacy search API for now")
                return False
            self._search_v2 = version >= SEARCH_V2_MIN_VERSION
            _LOGGER.debug(
                "Immich %s: using %s search API",
                ".".join(str(part) for part in version),
                "structured (filter)" if self._search_v2 else "legacy (flat)",
            )
            return self._search_v2

    async def _ensure_search_api(self) -> bool:
        """Lazily detect the search API flavour before a search."""
        if self._search_v2 is None:
            return await self.detect_search_api()
        return self._search_v2

    @staticmethod
    def _utc_days_ago(days: float) -> str:
        """Return now - days as an ISO-8601 UTC datetime accepted by Immich.

        Immich v3 validates date filters as ISO-8601 UTC datetimes (zod
        .datetime(), trailing 'Z' required). A naive isoformat() with
        microseconds and no 'Z' is rejected with HTTP 400.
        """
        return (datetime.now() - timedelta(days=days)).strftime(
            "%Y-%m-%dT%H:%M:%S.000Z"
        )

    def _build_search_body(
        self,
        count: int,
        *,
        include_archived: bool,
        exclude_album_ids: Iterable[str],
        exclude_person_ids: Iterable[str],
        conditions: dict[str, Any] | None = None,
        legacy_fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build a /api/search/random body for the detected API flavour.

        Structured API (Immich 3.2+): everything goes in `filter` — images only,
        not trashed (no implicit trash filter there), timeline (+ archive when
        include_archived), no AppleDouble junk, the method's `conditions`, and
        the exclusions as server-side `none` id filters.

        Legacy flat API: `legacy_fields` + `visibility: timeline` unless
        include_archived (the flat API returns archived assets by default).
        Exclusions can't be expressed there: callers filter client-side.

        Both flavours ask for exifInfo and people so assets come back complete.
        """
        body: dict[str, Any] = {"size": count, "withExif": True, "withPeople": True}

        if not self.supports_search_v2:
            body["type"] = "IMAGE"
            if not include_archived:
                body["visibility"] = "timeline"
            body.update(legacy_fields or {})
            return body

        search_filter: dict[str, Any] = {
            "type": {"eq": "IMAGE"},
            "trashedAt": {"eq": None},
            "visibility": {
                "in": ["timeline", "archive"] if include_archived else ["timeline"]
            },
            "originalFileName": {"notLike": APPLEDOUBLE_NAME_PATTERN},
        }
        for key, value in (conditions or {}).items():
            search_filter[key] = dict(value) if isinstance(value, dict) else value

        # A key appears once per filter object: merge `none` into an existing
        # IdsFilter (e.g. `albumIds: {any: [a], none: [b]}`).
        for key, ids in (
            ("albumIds", exclude_album_ids),
            ("personIds", exclude_person_ids),
        ):
            ids = sorted(set(ids))
            if ids:
                search_filter.setdefault(key, {})["none"] = ids

        body["filter"] = search_filter
        return body

    @staticmethod
    def _favorite_fields(favorites_filter: str) -> tuple[dict[str, Any], dict[str, Any]]:
        """Return (structured conditions, legacy fields) for a favorites filter."""
        if favorites_filter == "only":
            return {"isFavorite": {"eq": True}}, {"isFavorite": True}
        if favorites_filter == "exclude":
            return {"isFavorite": {"eq": False}}, {"isFavorite": False}
        return {}, {}

    async def search_random_recent(
        self,
        days: int = 90,
        count: int = 10,
        favorites_filter: str = "all",
        *,
        include_archived: bool = False,
        exclude_album_ids: Iterable[str] = (),
        exclude_person_ids: Iterable[str] = (),
    ) -> list[dict[str, Any]]:
        """Get random images taken within the last X days.

        Args:
            days: Number of days to look back
            count: Number of random images to fetch
            favorites_filter: "all" (no filter), "only" (favorites only), "exclude" (no favorites)
            include_archived: Also draw archived assets
            exclude_album_ids: Albums to exclude (server-side on Immich 3.2+)
            exclude_person_ids: Persons to exclude (server-side on Immich 3.2+)

        Returns:
            List of asset dictionaries (with exifInfo and people).
        """
        await self._ensure_search_api()
        taken_after = self._utc_days_ago(days)
        conditions, legacy_fields = self._favorite_fields(favorites_filter)

        body = self._build_search_body(
            count,
            include_archived=include_archived,
            exclude_album_ids=exclude_album_ids,
            exclude_person_ids=exclude_person_ids,
            conditions={**conditions, "takenAt": {"gte": taken_after}},
            legacy_fields={**legacy_fields, "takenAfter": taken_after},
        )
        return await self._post_search_random(body)

    async def search_random_recent_boost(
        self,
        days: int = 7,
        count: int = 10,
        favorites_filter: str = "all",
        *,
        include_archived: bool = False,
        exclude_album_ids: Iterable[str] = (),
        exclude_person_ids: Iterable[str] = (),
    ) -> list[dict[str, Any]]:
        """Get random images taken OR uploaded within the last X days.

        - taken    → EXIF capture date within the window (fresh shots)
        - uploaded → DB record creation = upload/import date within the window
          (old scans imported yesterday). Note: ``importedAfter`` does NOT
          exist — the flat API silently ignores unknown keys.

        Immich 3.2+: one request with ``or: [{takenAt}, {createdAt}]`` (true
        union, verified live). Older servers combine flat filters with AND only,
        so the union is approximated with two parallel requests merged and
        deduplicated.

        Args:
            days: Boost window in days (photos taken or uploaded since then).
            count: Number of random images to return.
            favorites_filter: "all", "only" (favorites only), "exclude".
            include_archived: Also draw archived assets
            exclude_album_ids: Albums to exclude (server-side on Immich 3.2+)
            exclude_person_ids: Persons to exclude (server-side on Immich 3.2+)

        Returns:
            List of asset dicts (size <= count), deduplicated by id. Empty
            list when no photo falls inside the window.
        """
        if days <= 0 or count <= 0:
            return []

        await self._ensure_search_api()
        after = self._utc_days_ago(days)
        conditions, legacy_fields = self._favorite_fields(favorites_filter)
        common = {
            "include_archived": include_archived,
            "exclude_album_ids": exclude_album_ids,
            "exclude_person_ids": exclude_person_ids,
        }

        if self.supports_search_v2:
            body = self._build_search_body(
                count,
                **common,
                conditions={
                    **conditions,
                    "or": [
                        {"takenAt": {"gte": after}},
                        {"createdAt": {"gte": after}},
                    ],
                },
            )
            return await self._post_search_random(body)

        taken_body = self._build_search_body(
            count, **common, legacy_fields={**legacy_fields, "takenAfter": after}
        )
        created_body = self._build_search_body(
            count, **common, legacy_fields={**legacy_fields, "createdAfter": after}
        )

        taken_assets, created_assets = await asyncio.gather(
            self._post_search_random(taken_body),
            self._post_search_random(created_body),
        )

        combined: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for asset in taken_assets + created_assets:
            asset_id = asset.get("id")
            if asset_id and asset_id not in seen_ids:
                seen_ids.add(asset_id)
                combined.append(asset)

        random.shuffle(combined)
        return combined[:count]

    async def _download(
        self, url: str, asset_id: str
    ) -> tuple[int | None, bytes | None]:
        """GET an asset file with retries.

        Returns (last_status, bytes). Statuses that won't change on retry
        (401/403/404...) return immediately; status is None when only
        connection errors occurred.
        """
        status: int | None = None
        for attempt in range(MAX_RETRIES):
            try:
                session = await self._get_session()
                async with session.get(url, headers=self._headers()) as response:
                    status = response.status
                    if response.status == 200:
                        content_type = response.headers.get("content-type", "")
                        if "image" not in content_type:
                            _LOGGER.warning(
                                "Unexpected content type for asset %s: %s",
                                asset_id, content_type
                            )
                            return status, None
                        return status, await response.read()
                    if response.status in NO_RETRY_STATUSES:
                        _LOGGER.debug(
                            "Download of asset %s failed: %s (not retried)",
                            asset_id, response.status
                        )
                        return status, None
                    (_LOGGER.warning if attempt + 1 == MAX_RETRIES else _LOGGER.debug)(
                        "Failed to download asset %s (attempt %d/%d): %s",
                        asset_id, attempt + 1, MAX_RETRIES, response.status
                    )
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                (_LOGGER.warning if attempt + 1 == MAX_RETRIES else _LOGGER.debug)(
                    "Error downloading asset %s (attempt %d/%d): %s",
                    asset_id, attempt + 1, MAX_RETRIES, err
                )

            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)])

        _LOGGER.error("All retries failed for download of asset %s", asset_id)
        return status, None

    async def download_asset(self, asset_id: str, thumbnail: bool = False) -> bytes | None:
        """Download an asset from Immich.

        Args:
            asset_id: The ID of the asset to download
            thumbnail: If True, download thumbnail instead of original

        Returns:
            Image bytes or None if failed (a 404 — e.g. original missing on
            the server's disk — returns None at once, without retries)
        """
        endpoint = "thumbnail" if thumbnail else "original"
        status, data = await self._download(
            f"{self._host}/api/assets/{asset_id}/{endpoint}", asset_id
        )
        if status == 404:
            _LOGGER.warning("Asset %s file not found on the server (404)", asset_id)
        return data

    async def download_image(
        self, asset_id: str, size: str = "fullsize"
    ) -> bytes | None:
        """Download a decodable rendition of an asset for display.

        Uses /api/assets/{id}/thumbnail?size=<size> (needs asset.view):
        - "fullsize": Immich converts non web-compatible formats (HEIC, PSD,
          RAW...) to JPEG when fullsize generation is enabled, else downgrades
          to the preview. Caveat: Immich decides by the file EXTENSION, so a
          web-compatible name (a HEIC saved as .jpg, a 200 MP .jpg panorama)
          is served as the original file.
        - "preview": always a server-generated, downscaled JPEG — the fallback
          when a fullsize/original still can't be decoded.

        If the API key lacks asset.view (401/403), this is remembered, logged
        once, and this and all later calls fall back to /original.

        Returns:
            Image bytes, or None on failure (404 returns None without retries).
        """
        if not self._asset_view_denied:
            status, data = await self._download(
                f"{self._host}/api/assets/{asset_id}/thumbnail?size={size}",
                asset_id,
            )
            if status in (401, 403):
                self._asset_view_denied = True
                _LOGGER.info(
                    "API key lacks the asset.view permission: downloading "
                    "originals instead of converted renditions (HEIC and "
                    "other non-web formats may fail to decode)"
                )
            else:
                if status == 404:
                    _LOGGER.warning(
                        "Asset %s file not found on the server (404)", asset_id
                    )
                return data
        return await self.download_asset(asset_id)

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
        # Candidate formats for the `for` param. Immich v3.1+ validates it as a
        # plain ISO date (YYYY-MM-DD) and rejects datetime strings with HTTP
        # 400, while some earlier v3 builds required a full UTC datetime with
        # trailing 'Z'. Try the modern plain-date form first and fall back to
        # the legacy datetime form on a 400.
        candidates = [for_date[:10], f"{for_date[:10]}T00:00:00.000Z"]

        for attempt in range(MAX_RETRIES):
            params = {"type": "on_this_day", "for": candidates[0]}
            try:
                session = await self._get_session()
                async with session.get(
                    url, headers=self._headers(), params=params
                ) as response:
                    if response.status == 200:
                        return await response.json()
                    if response.status == 400 and len(candidates) > 1:
                        _LOGGER.debug(
                            "Memories 'for=%s' rejected (400), retrying with "
                            "legacy datetime format",
                            candidates[0],
                        )
                        candidates.pop(0)
                        continue  # Retry immediately with the other format
                    (_LOGGER.warning if attempt + 1 == MAX_RETRIES else _LOGGER.debug)(
                        "Failed to fetch memories (attempt %d/%d): %s",
                        attempt + 1, MAX_RETRIES, response.status
                    )
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                (_LOGGER.warning if attempt + 1 == MAX_RETRIES else _LOGGER.debug)(
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
                    (_LOGGER.warning if attempt + 1 == MAX_RETRIES else _LOGGER.debug)(
                        "Failed to fetch albums (attempt %d/%d): %s",
                        attempt + 1, MAX_RETRIES, response.status
                    )
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                (_LOGGER.warning if attempt + 1 == MAX_RETRIES else _LOGGER.debug)(
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
                    (_LOGGER.warning if attempt + 1 == MAX_RETRIES else _LOGGER.debug)(
                        "Failed to fetch people (attempt %d/%d): %s",
                        attempt + 1, MAX_RETRIES, response.status
                    )
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                (_LOGGER.warning if attempt + 1 == MAX_RETRIES else _LOGGER.debug)(
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
                    (_LOGGER.warning if attempt + 1 == MAX_RETRIES else _LOGGER.debug)(
                        "Failed to fetch users (attempt %d/%d): %s",
                        attempt + 1, MAX_RETRIES, response.status
                    )
                    if response.status == 403:
                        # Permission missing — no point retrying
                        return []
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                (_LOGGER.warning if attempt + 1 == MAX_RETRIES else _LOGGER.debug)(
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
                    (_LOGGER.warning if attempt + 1 == MAX_RETRIES else _LOGGER.debug)(
                        "Failed to fetch album %s (attempt %d/%d): %s",
                        album_id, attempt + 1, MAX_RETRIES, response.status
                    )
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                (_LOGGER.warning if attempt + 1 == MAX_RETRIES else _LOGGER.debug)(
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
        """POST /api/search/random with retries. Returns [] on failure.

        A 400 is never transient and isn't retried. On the structured API it
        typically means an album id unknown to the server (deleted album left
        in the options): that is reported once per id set.
        """
        url = f"{self._host}/api/search/random"
        for attempt in range(MAX_RETRIES):
            try:
                session = await self._get_session()
                async with session.post(
                    url, headers=self._headers(), json=body
                ) as response:
                    if response.status == 200:
                        return await response.json()
                    if response.status == 400:
                        try:
                            message = (await response.json()).get("message", "")
                        except (aiohttp.ClientError, ValueError, AttributeError):
                            message = ""
                        self._warn_rejected_search(body, message)
                        return []
                    (_LOGGER.warning if attempt + 1 == MAX_RETRIES else _LOGGER.debug)(
                        "Failed search/random (attempt %d/%d): %s",
                        attempt + 1, MAX_RETRIES, response.status,
                    )
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                (_LOGGER.warning if attempt + 1 == MAX_RETRIES else _LOGGER.debug)(
                    "Error search/random (attempt %d/%d): %s",
                    attempt + 1, MAX_RETRIES, err,
                )
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)])
        _LOGGER.error("All retries failed for search/random")
        return []

    def _warn_rejected_search(self, body: dict[str, Any], message: Any) -> None:
        """Log a rejected (400) search — once per album id set when albums are involved."""
        album_filter = (body.get("filter") or {}).get("albumIds") or {}
        album_ids = frozenset(
            aid
            for op in ("any", "all", "none")
            for aid in album_filter.get(op, [])
        )
        if not album_ids:
            _LOGGER.warning("Immich rejected search/random (400): %s", message)
            return
        if album_ids in self._warned_rejected_albums:
            return
        self._warned_rejected_albums.add(album_ids)
        _LOGGER.warning(
            "Immich rejected search/random (400: %s). An album id may be "
            "deleted or not readable by the API key: %s",
            message,
            ", ".join(sorted(album_ids)),
        )

    async def search_random_from_albums(
        self,
        album_ids: list[str],
        count: int = 50,
        *,
        include_archived: bool = False,
        exclude_album_ids: Iterable[str] = (),
        exclude_person_ids: Iterable[str] = (),
    ) -> list[dict[str, Any]]:
        """Search random images across multiple albums.

        One call per album, in parallel, combined: keeps exposure balanced
        across albums (a single `albumIds: {any: [...]}` query on Immich 3.2+
        would weight albums by size) and allows `_album_id` attribution. On the
        legacy flat API `albumIds` is AND-only anyway.

        For efficiency when count is small relative to len(album_ids), only a
        random subset of albums is queried (e.g. count=1 → 1 album sampled).
        Each refill picks a different random subset, so over time exposure
        across albums stays balanced.

        Each returned asset is tagged with `_album_id` for downstream
        attribution (used to resolve `album_name` in entity attributes).

        Args:
            album_ids: List of album UUIDs to search within.
            count: Total number of random images to return.
            include_archived: Also draw archived assets
            exclude_album_ids: Albums to exclude (server-side on Immich 3.2+)
            exclude_person_ids: Persons to exclude (server-side on Immich 3.2+)

        Returns:
            List of asset dicts (size <= count), each tagged with `_album_id`.
        """
        if not album_ids or count <= 0:
            return []

        await self._ensure_search_api()
        n_to_query = min(count, len(album_ids))
        selected_ids = random.sample(album_ids, n_to_query)
        per_id = math.ceil(count / n_to_query)
        sem = asyncio.Semaphore(API_CONCURRENCY_LIMIT)

        async def fetch_one(aid: str) -> list[dict[str, Any]]:
            body = self._build_search_body(
                per_id,
                include_archived=include_archived,
                exclude_album_ids=exclude_album_ids,
                exclude_person_ids=exclude_person_ids,
                conditions={"albumIds": {"any": [aid]}},
                legacy_fields={"albumIds": [aid]},
            )
            async with sem:
                assets = await self._post_search_random(body)
            for a in assets:
                a["_album_id"] = aid
            return assets

        results = await asyncio.gather(*(fetch_one(aid) for aid in selected_ids))
        combined = [a for r in results for a in r]
        random.shuffle(combined)
        return combined[:count]

    async def search_random_by_person(
        self,
        person_ids: list[str],
        count: int = 50,
        *,
        include_archived: bool = False,
        exclude_album_ids: Iterable[str] = (),
        exclude_person_ids: Iterable[str] = (),
    ) -> list[dict[str, Any]]:
        """Search random images containing any of the given persons.

        One call per person, in parallel, combined: keeps exposure balanced
        across persons (a single `personIds: {any: [...]}` query on Immich 3.2+
        would weight persons by photo count). On the legacy flat API
        `personIds` is AND-only anyway.

        For efficiency when count is small relative to len(person_ids), only a
        random subset of persons is queried (e.g. count=1 → 1 person sampled).
        Each refill picks a different random subset, so over time exposure
        across persons stays balanced.

        Args:
            person_ids: List of person UUIDs to search for.
            count: Total number of random images to return.
            include_archived: Also draw archived assets
            exclude_album_ids: Albums to exclude (server-side on Immich 3.2+)
            exclude_person_ids: Persons to exclude (server-side on Immich 3.2+)

        Returns:
            List of asset dicts (size <= count), each containing at least one
            of the requested persons.
        """
        if not person_ids or count <= 0:
            return []

        await self._ensure_search_api()
        n_to_query = min(count, len(person_ids))
        selected_ids = random.sample(person_ids, n_to_query)
        per_id = math.ceil(count / n_to_query)
        sem = asyncio.Semaphore(API_CONCURRENCY_LIMIT)

        async def fetch_one(pid: str) -> list[dict[str, Any]]:
            body = self._build_search_body(
                per_id,
                include_archived=include_archived,
                exclude_album_ids=exclude_album_ids,
                exclude_person_ids=exclude_person_ids,
                conditions={"personIds": {"any": [pid]}},
                legacy_fields={"personIds": [pid]},
            )
            async with sem:
                assets = await self._post_search_random(body)
            # Client-side verify: keep only assets that actually contain pid.
            # The Immich API has had bugs returning unrelated assets in the past
            # (see GitHub #15010), so this is a defensive filter.
            return [a for a in assets if any(p.get("id") == pid for p in a.get("people", []))]

        results = await asyncio.gather(*(fetch_one(pid) for pid in selected_ids))
        combined = [a for r in results for a in r]
        random.shuffle(combined)
        return combined[:count]
