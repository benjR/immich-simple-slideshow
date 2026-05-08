"""Image entity for Immich Slideshow with multi-resolution support."""
from __future__ import annotations

import asyncio
import io
import logging
import random
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from homeassistant.components.image import ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval

# Pool management constants
MAX_POOL_SIZE = 200  # Maximum assets to keep in pool
REFILL_THRESHOLD = 20  # Refill when pool drops below this
POOL_FETCH_SIZE = 100  # Number of assets to fetch per refill
API_CONCURRENCY_LIMIT = 5  # Max concurrent API calls for asset enrichment

from .const import (
    # Core config keys
    CONF_BACKGROUND_PATH,
    CONF_DUAL_PORTRAIT,
    CONF_REFRESH_INTERVAL,
    CONF_RESOLUTIONS,
    CONF_WRITE_FILES,
    # Source weight keys
    CONF_SOURCE_RECENT_WEIGHT,
    CONF_SOURCE_MEMORIES_WEIGHT,
    CONF_SOURCE_ALBUMS_WEIGHT,
    CONF_SOURCE_PERSONS_WEIGHT,
    # Recent source keys
    CONF_RECENT_DAYS,
    CONF_RECENT_FAVORITES_FILTER,
    # Memories source keys
    CONF_MEMORIES_MAX_YEARS,
    # Albums/Persons source keys
    CONF_ALBUMS_INCLUDE,
    CONF_PERSONS_INCLUDE,
    # Global exclusions
    CONF_EXCLUDE_ALBUMS,
    CONF_EXCLUDE_PERSONS,
    # Defaults
    DEFAULT_BACKGROUND_PATH,
    DEFAULT_DUAL_PORTRAIT,
    DEFAULT_REFRESH_INTERVAL,
    DEFAULT_RESOLUTIONS,
    DEFAULT_WRITE_FILES,
    DEFAULT_SOURCE_RECENT_WEIGHT,
    DEFAULT_SOURCE_MEMORIES_WEIGHT,
    DEFAULT_SOURCE_ALBUMS_WEIGHT,
    DEFAULT_SOURCE_PERSONS_WEIGHT,
    DEFAULT_RECENT_DAYS,
    DEFAULT_RECENT_FAVORITES_FILTER,
    DEFAULT_MEMORIES_MAX_YEARS,
    DOMAIN,
    parse_resolutions,
)
from .hub import ImmichHub

_LOGGER = logging.getLogger(__name__)


class SlideshowManager:
    """Manages shared state for all slideshow image entities."""

    def __init__(
        self,
        hub: ImmichHub,
        dual_portrait: bool,
        # Source weights (0-100)
        source_recent_weight: int = 50,
        source_memories_weight: int = 50,
        source_albums_weight: int = 0,
        source_persons_weight: int = 0,
        # Recent source config
        recent_days: int = 90,
        recent_favorites_filter: str = "all",
        # Memories source config
        memories_max_years: int = 0,
        # Albums/Persons includes
        albums_include: list[str] | None = None,
        persons_include: list[str] | None = None,
        # Global exclusions
        exclude_albums: list[str] | None = None,
        exclude_persons: list[str] | None = None,
    ) -> None:
        """Initialize the manager.

        Args:
            hub: ImmichHub instance for API calls
            dual_portrait: Whether to combine two portraits side by side
            source_recent_weight: Weight for recent photos source (0-100)
            source_memories_weight: Weight for memories source (0-100)
            source_albums_weight: Weight for albums source (0-100)
            source_persons_weight: Weight for persons source (0-100)
            recent_days: Days to look back for recent photos (0 = unlimited)
            recent_favorites_filter: "all", "only", or "exclude"
            memories_max_years: Max years for memories (0 = unlimited)
            albums_include: List of album UUIDs to include
            persons_include: List of person UUIDs to include
            exclude_albums: List of album UUIDs to globally exclude
            exclude_persons: List of person UUIDs to globally exclude
        """
        self._hub = hub
        self._host = hub._host  # Store for building Immich URLs
        self._dual_portrait = dual_portrait

        # Source weights (normalized at fetch time)
        self._source_weights = {
            "recent": source_recent_weight,
            "memories": source_memories_weight,
            "albums": source_albums_weight,
            "persons": source_persons_weight,
        }

        # Recent source config
        self._recent_days = recent_days
        self._recent_favorites_filter = recent_favorites_filter

        # Memories source config
        self._memories_max_years = memories_max_years

        # Albums/Persons includes
        self._albums_include = albums_include or []
        self._persons_include = persons_include or []

        # Global exclusions (as sets for O(1) lookup)
        self._exclude_albums = set(exclude_albums or [])
        self._exclude_persons = set(exclude_persons or [])

        self._asset_pool: list[dict] = []
        # Current source images (PIL Image objects, already EXIF-transposed)
        self._current_img1: Image.Image | None = None
        self._current_img2: Image.Image | None = None  # For dual portrait
        self._is_dual: bool = False
        # Current asset info for metadata exposure
        self._current_asset1: dict | None = None
        self._current_asset2: dict | None = None

        # Pre-fetched next images (double buffering for instant swap)
        self._next_img1: Image.Image | None = None
        self._next_img2: Image.Image | None = None
        self._next_is_dual: bool = False
        self._next_asset1: dict | None = None
        self._next_asset2: dict | None = None
        self._prefetch_task: asyncio.Task | None = None

        # Lock for thread-safe pool operations
        self._refresh_lock = asyncio.Lock()
        # Track if pool is empty (for entity availability)
        self._pool_empty = False

        # Mappings populated once at first refill (requires user.read / album.read).
        # If perms missing → empty dict, integration must be reloaded after granting them.
        self._user_names: dict[str, str] = {}
        self._users_fetched: bool = False
        self._album_names: dict[str, str] = {}
        self._albums_fetched: bool = False

    async def _ensure_user_names(self) -> None:
        """Lazily fetch the ownerId → name mapping. Once-per-manager-lifetime."""
        if self._users_fetched:
            return
        users = await self._hub.get_users()
        # Mark fetched AFTER call (so transient errors during boot don't permanently
        # disable owner_name; flag is set only once the call has had a chance to run)
        self._users_fetched = True
        if users:
            self._user_names = {
                u["id"]: u.get("name") or u.get("email") or ""
                for u in users
                if u.get("id")
            }

    async def _ensure_album_names(self) -> None:
        """Lazily fetch the albumId → albumName mapping. Once-per-manager-lifetime."""
        if self._albums_fetched:
            return
        albums = await self._hub.get_albums()
        self._albums_fetched = True
        if albums:
            self._album_names = {a["id"]: a.get("albumName", "") for a in albums if a.get("id")}

    @property
    def memory_year(self) -> int | None:
        """Return the year of the current memory photo, or None if not a memory."""
        if self._current_asset1:
            return self._current_asset1.get("memory_year")
        return None

    @property
    def years_ago(self) -> int | None:
        """Return how many years ago the current photo was taken, or None."""
        if self.memory_year is not None:
            return datetime.now().year - self.memory_year
        return None

    @property
    def is_dual(self) -> bool:
        """Return True if currently showing dual portrait."""
        return self._is_dual

    @property
    def asset_id(self) -> str | None:
        """Return the current asset ID."""
        if self._current_asset1:
            return self._current_asset1.get("id")
        return None

    @property
    def immich_url(self) -> str | None:
        """Return URL to open the photo in Immich."""
        if self._current_asset1 and self._current_asset1.get("id"):
            return f"{self._host}/photos/{self._current_asset1['id']}"
        return None

    @property
    def original_filename(self) -> str | None:
        """Return the original filename."""
        if self._current_asset1:
            return self._current_asset1.get("originalFileName")
        return None

    @property
    def description(self) -> str | None:
        """Return the EXIF description if available."""
        if self._current_asset1:
            exif = self._current_asset1.get("exifInfo", {})
            return exif.get("description") if exif else None
        return None

    @property
    def date_taken(self) -> str | None:
        """Return the date the photo was taken."""
        if self._current_asset1:
            exif = self._current_asset1.get("exifInfo", {})
            if exif and exif.get("dateTimeOriginal"):
                return exif["dateTimeOriginal"]
            # Fallback to localDateTime from asset
            return self._current_asset1.get("localDateTime")
        return None

    @property
    def city(self) -> str | None:
        """Return the city where the photo was taken."""
        if self._current_asset1:
            exif = self._current_asset1.get("exifInfo", {})
            return exif.get("city") if exif else None
        return None

    @property
    def country(self) -> str | None:
        """Return the country where the photo was taken."""
        if self._current_asset1:
            exif = self._current_asset1.get("exifInfo", {})
            return exif.get("country") if exif else None
        return None

    @property
    def is_favorite(self) -> bool | None:
        """Return True if the photo is a favorite."""
        if self._current_asset1:
            return self._current_asset1.get("isFavorite")
        return None

    @property
    def people(self) -> list[str] | None:
        """Return list of people detected in the photo."""
        if self._current_asset1:
            people_list = self._current_asset1.get("people", [])
            if people_list:
                return [p.get("name") for p in people_list if p.get("name")]
        return None

    @property
    def source(self) -> str | None:
        """Return the source of the photo: 'recent', 'memory', 'album', or 'person'."""
        if self._current_asset1:
            return self._current_asset1.get("_source", "recent")
        return None

    @property
    def live_photo_video_id(self) -> str | None:
        """Return the Live Photo video ID if this is a Live Photo."""
        if self._current_asset1:
            return self._current_asset1.get("livePhotoVideoId")
        return None

    @property
    def has_live_photo(self) -> bool:
        """Return True if current photo is a Live Photo."""
        return self.live_photo_video_id is not None

    def get_asset_attrs(self, asset: dict | None) -> dict[str, Any]:
        """Extract attributes from an asset dict."""
        if not asset:
            return {}

        attrs: dict[str, Any] = {}
        exif = asset.get("exifInfo", {}) or {}

        # Asset identification
        if asset.get("id"):
            attrs["asset_id"] = asset["id"]
            attrs["immich_url"] = f"{self._host}/photos/{asset['id']}"

        # File info
        if asset.get("originalFileName"):
            attrs["original_filename"] = asset["originalFileName"]
        if exif.get("description"):
            attrs["description"] = exif["description"]

        # Date & Memory info
        date_taken = exif.get("dateTimeOriginal") or asset.get("localDateTime")
        if date_taken:
            attrs["date_taken"] = date_taken
        if asset.get("memory_year") is not None:
            attrs["memory_year"] = asset["memory_year"]
            attrs["years_ago"] = datetime.now().year - asset["memory_year"]

        # Source tracking (recent, memory, album, person)
        attrs["source"] = asset.get("_source", "recent")

        # Owner / uploader name (resolved from ownerId via cached user mapping)
        owner_id = asset.get("ownerId")
        if owner_id:
            owner_name = self._user_names.get(owner_id)
            if owner_name:
                attrs["owner_name"] = owner_name

        # Album name (only when source is "album" and a single source album is known)
        album_id = asset.get("_album_id")
        if album_id:
            album_name = self._album_names.get(album_id)
            if album_name:
                attrs["album_name"] = album_name

        # Location
        if exif.get("city"):
            attrs["city"] = exif["city"]
        if exif.get("country"):
            attrs["country"] = exif["country"]

        # People
        people_list = asset.get("people", [])
        if people_list:
            names = [p.get("name") for p in people_list if p.get("name")]
            if names:
                attrs["people"] = names

        # Favorite
        if asset.get("isFavorite") is not None:
            attrs["is_favorite"] = asset["isFavorite"]

        # Live Photo support
        live_photo_video_id = asset.get("livePhotoVideoId")
        attrs["has_live_photo"] = live_photo_video_id is not None
        if live_photo_video_id:
            attrs["live_photo_video_id"] = live_photo_video_id

        return attrs

    @property
    def asset1(self) -> dict | None:
        """Return current asset 1."""
        return self._current_asset1

    @property
    def asset2(self) -> dict | None:
        """Return current asset 2 (for dual portrait)."""
        return self._current_asset2

    @property
    def is_available(self) -> bool:
        """Return True if images are available."""
        return not self._pool_empty

    async def refresh(self) -> bool:
        """Load new source images. Returns True if successful."""
        async with self._refresh_lock:
            return await self._do_refresh()

    def _close_images(self, img1: Image.Image | None, img2: Image.Image | None) -> None:
        """Close PIL images to free memory."""
        if img1 is not None:
            try:
                img1.close()
            except Exception:
                pass
        if img2 is not None:
            try:
                img2.close()
            except Exception:
                pass

    def cleanup(self) -> None:
        """Clean up all images, cancel prefetch, and clear pool."""
        # Cancel any running prefetch task
        if self._prefetch_task and not self._prefetch_task.done():
            self._prefetch_task.cancel()

        # Close all current and prefetched images
        self._close_images(self._current_img1, self._current_img2)
        self._close_images(self._next_img1, self._next_img2)

        # Clear references
        self._current_img1 = None
        self._current_img2 = None
        self._next_img1 = None
        self._next_img2 = None
        self._current_asset1 = None
        self._current_asset2 = None
        self._next_asset1 = None
        self._next_asset2 = None

        # Clear pool
        self._asset_pool.clear()
        _LOGGER.debug("SlideshowManager cleanup complete")

    async def _do_refresh(self) -> bool:
        """Internal refresh logic with double buffering.

        If a pre-fetched image is ready, swap it in instantly.
        Otherwise, fall back to synchronous fetch (cold start).
        Then start background prefetch for next image.
        """
        # Check if we have a pre-fetched image ready (instant swap)
        if self._next_img1 is not None:
            # Close old current images
            self._close_images(self._current_img1, self._current_img2)

            # Swap next → current (instant, no network delay!)
            self._current_img1 = self._next_img1
            self._current_img2 = self._next_img2
            self._current_asset1 = self._next_asset1
            self._current_asset2 = self._next_asset2
            self._is_dual = self._next_is_dual

            # Clear next slots
            self._next_img1 = None
            self._next_img2 = None
            self._next_asset1 = None
            self._next_asset2 = None
            self._next_is_dual = False

            # Start background prefetch for the following image
            self._start_prefetch()
            return True

        # No pre-fetched image (cold start or prefetch failed)
        # Fall back to synchronous fetch
        _LOGGER.debug("No prefetched image, doing synchronous fetch")
        success = await self._fetch_image_sync()

        if success:
            # Start prefetch for next image
            self._start_prefetch()

        return success

    def _start_prefetch(self) -> None:
        """Start background prefetch for next image."""
        # Cancel any existing prefetch task
        if self._prefetch_task and not self._prefetch_task.done():
            self._prefetch_task.cancel()
            # Clean up any images from cancelled prefetch
            self._close_images(self._next_img1, self._next_img2)
            self._next_img1 = None
            self._next_img2 = None
            self._next_asset1 = None
            self._next_asset2 = None
            self._next_is_dual = False

        # Start new prefetch (fire and forget)
        self._prefetch_task = asyncio.create_task(self._prefetch_next())

    async def _prefetch_next(self) -> None:
        """Prefetch next image in background (non-blocking).

        This runs during the display interval, hiding network latency.
        """
        try:
            # Refill pool if below threshold
            if len(self._asset_pool) < REFILL_THRESHOLD:
                await self._refill_pool()

            if not self._asset_pool:
                _LOGGER.debug("Prefetch: pool empty, skipping")
                return

            # Pop one image from the pool
            popped = self._pop_from_pool(count=1)
            if not popped:
                return

            chosen = popped[0]
            chosen_is_portrait = is_portrait(chosen)
            _LOGGER.debug("Prefetching photo from source: %s", chosen.get("_source", "unknown"))

            # If portrait + dual_portrait enabled → try to get another portrait
            if self._dual_portrait and chosen_is_portrait:
                second_list = self._pop_from_pool(count=1, portrait_only=True)
                if second_list:
                    second = second_list[0]
                    img1_bytes = await self._hub.download_asset(chosen["id"])
                    img2_bytes = await self._hub.download_asset(second["id"])

                    if img1_bytes and img2_bytes:
                        try:
                            img1 = Image.open(io.BytesIO(img1_bytes))
                            img1 = ImageOps.exif_transpose(img1)
                            if img1.mode not in ("RGB", "L"):
                                img1 = img1.convert("RGB")

                            img2 = Image.open(io.BytesIO(img2_bytes))
                            img2 = ImageOps.exif_transpose(img2)
                            if img2.mode not in ("RGB", "L"):
                                img2 = img2.convert("RGB")

                            self._next_img1 = img1
                            self._next_img2 = img2
                            self._next_asset1 = chosen
                            self._next_asset2 = second
                            self._next_is_dual = True
                            _LOGGER.debug("Prefetch complete: dual portrait ready")
                            return
                        except Exception as err:
                            _LOGGER.warning("Prefetch: failed to load dual portrait: %s", err)

            # Single image (landscape, or portrait without pair available)
            image_bytes = await self._hub.download_asset(chosen["id"])
            if not image_bytes:
                _LOGGER.warning("Prefetch: failed to download asset %s", chosen["id"])
                return

            try:
                img = Image.open(io.BytesIO(image_bytes))
                img = ImageOps.exif_transpose(img)
                if img.mode not in ("RGB", "L"):
                    img = img.convert("RGB")

                self._next_img1 = img
                self._next_img2 = None
                self._next_asset1 = chosen
                self._next_asset2 = None
                self._next_is_dual = False
                _LOGGER.debug("Prefetch complete: single image ready")
            except Exception as err:
                _LOGGER.warning("Prefetch: failed to open image: %s", err)

        except asyncio.CancelledError:
            _LOGGER.debug("Prefetch task cancelled")
            # Clean up any partially prefetched images
            self._close_images(self._next_img1, self._next_img2)
            self._next_img1 = None
            self._next_img2 = None
            self._next_asset1 = None
            self._next_asset2 = None
            self._next_is_dual = False
            raise
        except Exception as err:
            _LOGGER.warning("Prefetch failed: %s", err)

    async def _fetch_image_sync(self) -> bool:
        """Fetch image synchronously (used for cold start or when prefetch failed)."""
        # Close previous images to prevent memory leak
        self._close_images(self._current_img1, self._current_img2)
        self._current_img1 = None
        self._current_img2 = None

        # Refill pool if below threshold
        if len(self._asset_pool) < REFILL_THRESHOLD:
            await self._refill_pool()

        if not self._asset_pool:
            _LOGGER.warning("Pool is empty, no images available")
            self._pool_empty = True
            return False

        self._pool_empty = False

        # Pop one image from the pool
        popped = self._pop_from_pool(count=1)
        if not popped:
            return False

        chosen = popped[0]
        chosen_is_portrait = is_portrait(chosen)
        _LOGGER.debug("Selected photo from source: %s", chosen.get("_source", "unknown"))

        # Store current asset info for metadata exposure
        self._current_asset1 = chosen
        self._current_asset2 = None

        # If portrait + dual_portrait enabled → try to get another portrait
        if self._dual_portrait and chosen_is_portrait:
            second_list = self._pop_from_pool(count=1, portrait_only=True)
            if second_list:
                second = second_list[0]
                img1_bytes = await self._hub.download_asset(chosen["id"])
                img2_bytes = await self._hub.download_asset(second["id"])

                if img1_bytes and img2_bytes:
                    try:
                        img1 = Image.open(io.BytesIO(img1_bytes))
                        img1 = ImageOps.exif_transpose(img1)
                        if img1.mode not in ("RGB", "L"):
                            img1 = img1.convert("RGB")

                        img2 = Image.open(io.BytesIO(img2_bytes))
                        img2 = ImageOps.exif_transpose(img2)
                        if img2.mode not in ("RGB", "L"):
                            img2 = img2.convert("RGB")

                        self._current_img1 = img1
                        self._current_img2 = img2
                        self._current_asset2 = second  # Store second asset for metadata
                        self._is_dual = True
                        return True
                    except Exception as err:
                        _LOGGER.warning("Failed to load dual portrait: %s", err)

        # Single image (landscape, or portrait without pair available)
        image_bytes = await self._hub.download_asset(chosen["id"])
        if not image_bytes:
            _LOGGER.warning("Failed to download asset %s", chosen["id"])
            return False

        try:
            img = Image.open(io.BytesIO(image_bytes))
            img = ImageOps.exif_transpose(img)
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            self._current_img1 = img
            self._current_img2 = None
            self._is_dual = False
            return True
        except Exception as err:
            _LOGGER.error("Failed to open image: %s", err)
            return False

    def _normalize_weights(self) -> dict[str, float]:
        """Normalize source weights to sum to 1.0.

        Returns dict of source_name -> normalized_weight.
        Only includes sources with weight > 0 that are properly configured.
        """
        weights: dict[str, float] = {}

        # Recent: always available if weight > 0
        if self._source_weights["recent"] > 0:
            weights["recent"] = self._source_weights["recent"]

        # Memories: always available if weight > 0
        if self._source_weights["memories"] > 0:
            weights["memories"] = self._source_weights["memories"]

        # Albums: enabled if weight > 0 (uses specific albums if selected, otherwise any album)
        if self._source_weights["albums"] > 0:
            weights["albums"] = self._source_weights["albums"]

        # Persons: only if persons_include has selections
        if self._source_weights["persons"] > 0 and self._persons_include:
            weights["persons"] = self._source_weights["persons"]

        # Normalize to sum to 1.0
        total = sum(weights.values())
        if total > 0:
            return {k: v / total for k, v in weights.items()}
        return {}

    def _calculate_source_counts(
        self, weights: dict[str, float], total_count: int
    ) -> dict[str, int]:
        """Calculate how many assets to fetch from each source.

        Uses weights to distribute total_count proportionally.
        Ensures at least 1 per source if weight > 0.
        """
        counts: dict[str, int] = {}
        remaining = total_count

        # First pass: assign proportional counts
        for source, weight in weights.items():
            count = max(1, int(weight * total_count))
            counts[source] = min(count, remaining)
            remaining -= counts[source]

        # Distribute any remaining to largest source
        if remaining > 0 and counts:
            largest = max(counts, key=counts.get)
            counts[largest] += remaining

        return counts

    async def _fetch_recent(self, count: int) -> list[dict]:
        """Fetch recent photos."""
        # days=0 means unlimited (use ~100 years)
        days_param = self._recent_days if self._recent_days > 0 else 36500
        assets = await self._hub.search_random_recent(
            days=days_param,
            count=count,
            favorites_filter=self._recent_favorites_filter,
        )
        # Tag source
        for asset in assets:
            asset["_source"] = "recent"
        return assets

    async def _fetch_memories(self, count: int) -> list[dict]:
        """Fetch 'On This Day' memory photos."""
        assets = await self._hub.get_memory_assets(
            max_years=self._memories_max_years
        )
        random.shuffle(assets)
        assets = assets[:count]
        # Tag source (memory assets already have memory_year)
        for asset in assets:
            asset["_source"] = "memory"
        return assets

    async def _fetch_albums(self, count: int) -> list[dict]:
        """Fetch random photos from albums.

        If specific albums are selected, fetches from those albums only.
        If no albums are selected, fetches from ANY album (isNotInAlbum: false).
        """
        if self._albums_include:
            # Use efficient search/random with specific albumIds
            assets = await self._hub.search_random_from_albums(
                album_ids=self._albums_include,
                count=count,
            )
        else:
            # No specific albums selected: fetch from any album
            assets = await self._hub.search_random_in_any_album(count=count)

        # Tag source — attribute album_id when possible so the entity can expose
        # the album name. Three cases:
        #   1. Exactly one album in albums_include  → cheap, attribute directly
        #   2. Multiple albums in albums_include    → resolve per-asset via API
        #   3. Mode "any album" (empty include)     → resolve per-asset via API
        single_album_id = (
            self._albums_include[0]
            if len(self._albums_include) == 1
            else None
        )
        for asset in assets:
            asset["_source"] = "album"
            if single_album_id:
                asset["_album_id"] = single_album_id

        if not single_album_id and assets:
            # Per-asset album lookup, parallel with bounded concurrency
            sem = asyncio.Semaphore(API_CONCURRENCY_LIMIT)

            async def resolve(asset: dict) -> None:
                async with sem:
                    found = await self._hub.get_albums_for_asset(asset["id"])
                if found:
                    # First album wins for display attribution
                    asset["_album_id"] = found[0].get("id")

            await asyncio.gather(*(resolve(a) for a in assets), return_exceptions=True)

        return assets

    async def _fetch_persons(self, count: int) -> list[dict]:
        """Fetch photos containing selected persons."""
        if not self._persons_include:
            return []

        assets = await self._hub.search_random_by_person(
            person_ids=self._persons_include,
            count=count,
        )
        # Tag source
        for asset in assets:
            asset["_source"] = "person"
        return assets

    def _apply_global_exclusions(self, assets: list[dict]) -> list[dict]:
        """Filter out assets matching global exclusions.

        Removes assets that:
        - Are in excluded albums
        - Contain excluded persons
        """
        if not self._exclude_albums and not self._exclude_persons:
            return assets

        filtered: list[dict] = []
        for asset in assets:
            # Check album exclusion
            if self._exclude_albums:
                # Check _album_id (set by _fetch_albums)
                if asset.get("_album_id") in self._exclude_albums:
                    continue
                # Also check albumIds if present in asset data
                album_ids = set(asset.get("albumIds", []))
                if album_ids & self._exclude_albums:
                    continue

            # Check person exclusion
            if self._exclude_persons:
                people_ids = {p.get("id") for p in asset.get("people", []) if p.get("id")}
                if people_ids & self._exclude_persons:
                    continue

            filtered.append(asset)
        return filtered

    async def _refill_pool(self) -> None:
        """Fetch a new batch of assets from weighted sources.

        Sources are: recent, memories, albums, persons.
        Each source has a weight (0-100) that determines its proportion in the pool.
        """
        # One-shot: fetch user mapping (ownerId → name) and album mapping (id → name)
        await self._ensure_user_names()
        await self._ensure_album_names()

        # Calculate how many we need (up to POOL_FETCH_SIZE, capped by MAX_POOL_SIZE)
        current_size = len(self._asset_pool)
        space_available = MAX_POOL_SIZE - current_size
        fetch_count = min(POOL_FETCH_SIZE, space_available)

        if fetch_count <= 0:
            return

        # Get normalized weights for enabled sources
        weights = self._normalize_weights()
        if not weights:
            _LOGGER.warning("No sources enabled (all weights are 0 or unconfigured)")
            return

        # Calculate count per source
        source_counts = self._calculate_source_counts(weights, fetch_count)

        _LOGGER.debug(
            "Refilling pool: weights=%s, counts=%s",
            {k: f"{v:.1%}" for k, v in weights.items()},
            source_counts,
        )

        # Fetch from each source in parallel
        tasks: list[asyncio.Task] = []
        source_order: list[str] = []

        if source_counts.get("recent", 0) > 0:
            tasks.append(asyncio.create_task(self._fetch_recent(source_counts["recent"])))
            source_order.append("recent")
        if source_counts.get("memories", 0) > 0:
            tasks.append(asyncio.create_task(self._fetch_memories(source_counts["memories"])))
            source_order.append("memories")
        if source_counts.get("albums", 0) > 0:
            tasks.append(asyncio.create_task(self._fetch_albums(source_counts["albums"])))
            source_order.append("albums")
        if source_counts.get("persons", 0) > 0:
            tasks.append(asyncio.create_task(self._fetch_persons(source_counts["persons"])))
            source_order.append("persons")

        # Wait for all fetches
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Merge results with deduplication (same photo can appear in multiple sources)
        # Also deduplicate against assets already in the pool to avoid repetition
        all_assets: list[dict] = []
        seen_ids: set[str] = {a.get("id") for a in self._asset_pool if a.get("id")}
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                _LOGGER.warning("Error fetching from %s: %s", source_order[i], result)
            elif result:
                for asset in result:
                    asset_id = asset.get("id")
                    if asset_id and asset_id not in seen_ids:
                        all_assets.append(asset)
                        seen_ids.add(asset_id)

        if not all_assets:
            _LOGGER.warning("No assets found from any source")
            return

        # Apply global exclusions
        all_assets = self._apply_global_exclusions(all_assets)

        if not all_assets:
            _LOGGER.warning("All assets filtered out by global exclusions")
            return

        # Enrich assets with full metadata using semaphore for concurrency control
        semaphore = asyncio.Semaphore(API_CONCURRENCY_LIMIT)

        async def enrich_asset(asset: dict) -> dict | None:
            async with semaphore:
                info = await self._hub.get_asset_info(asset["id"])
                if info:
                    exif = info.get("exifInfo", {})
                    asset["originalWidth"] = exif.get("exifImageWidth", 0)
                    asset["originalHeight"] = exif.get("exifImageHeight", 0)
                    asset["exifInfo"] = exif
                    asset["originalFileName"] = info.get("originalFileName")
                    asset["isFavorite"] = info.get("isFavorite", False)
                    asset["localDateTime"] = info.get("localDateTime")
                    asset["people"] = info.get("people", [])
                    asset["albumIds"] = info.get("albumIds", [])
                    # Live Photo support: store video ID if present
                    asset["livePhotoVideoId"] = info.get("livePhotoVideoId")
                    return asset
                return None

        # Run enrichment concurrently with limited parallelism
        enriched = await asyncio.gather(*[enrich_asset(a) for a in all_assets])
        enriched_assets = [a for a in enriched if a is not None]

        # Apply exclusions again after enrichment (now we have albumIds and people)
        enriched_assets = self._apply_global_exclusions(enriched_assets)

        random.shuffle(enriched_assets)
        # Add to existing pool instead of replacing
        self._asset_pool.extend(enriched_assets)
        # Cap pool size
        if len(self._asset_pool) > MAX_POOL_SIZE:
            self._asset_pool = self._asset_pool[:MAX_POOL_SIZE]

        _LOGGER.debug("Pool refilled: %d assets", len(self._asset_pool))

    def _pop_from_pool(
        self, count: int = 1, portrait_only: bool = False
    ) -> list[dict]:
        """Pop assets from the pool."""
        result = []
        remaining = []

        for asset in self._asset_pool:
            if len(result) < count:
                if portrait_only:
                    if is_portrait(asset):
                        result.append(asset)
                    else:
                        remaining.append(asset)
                else:
                    result.append(asset)
            else:
                remaining.append(asset)

        self._asset_pool = remaining
        return result

    def generate_image(self, target_w: int, target_h: int) -> bytes | None:
        """Generate image at specified resolution from current source images."""
        if self._current_img1 is None:
            return None

        if self._is_dual and self._current_img2 is not None:
            return self._compose_side_by_side(
                self._current_img1, self._current_img2, target_w, target_h
            )
        else:
            return self._resize_and_encode(self._current_img1, target_w, target_h)

    def _compose_side_by_side(
        self,
        img1: Image.Image,
        img2: Image.Image,
        target_w: int,
        target_h: int,
    ) -> bytes:
        """Compose 2 portrait images side by side at specified resolution."""
        half_w = target_w // 2

        img1_resized = self._resize_and_center_crop(img1, half_w, target_h)
        img2_resized = self._resize_and_center_crop(img2, half_w, target_h)

        result = Image.new("RGB", (target_w, target_h))
        result.paste(img1_resized, (0, 0))
        result.paste(img2_resized, (half_w, 0))

        # Close intermediate images after paste (paste copies pixel data)
        img1_resized.close()
        img2_resized.close()

        buffer = io.BytesIO()
        result.save(buffer, format="JPEG", quality=85, optimize=True)
        data = buffer.getvalue()
        result.close()
        return data

    def _resize_and_center_crop(
        self, img: Image.Image, target_w: int, target_h: int
    ) -> Image.Image:
        """Resize image to cover target size, then center crop."""
        src_w, src_h = img.size
        target_ratio = target_w / target_h
        src_ratio = src_w / src_h

        if src_ratio > target_ratio:
            scale = target_h / src_h
        else:
            scale = target_w / src_w

        new_w = int(src_w * scale)
        new_h = int(src_h * scale)
        img_scaled = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

        left = (new_w - target_w) // 2
        top = int((new_h - target_h) * 0.3)
        right = left + target_w
        bottom = top + target_h

        cropped = img_scaled.crop((left, top, right, bottom))
        img_scaled.close()  # Free intermediate scaled image
        return cropped

    def _resize_and_encode(
        self, img: Image.Image, target_w: int, target_h: int
    ) -> bytes:
        """Resize a single image to target dimensions and encode as JPEG."""
        resized = self._resize_and_center_crop(img, target_w, target_h)
        buffer = io.BytesIO()
        resized.save(buffer, format="JPEG", quality=85, optimize=True)
        data = buffer.getvalue()
        resized.close()  # Free resized image after encoding
        return data


def is_portrait(asset: dict[str, Any]) -> bool:
    """Check if an asset is portrait orientation after EXIF rotation."""
    width = asset.get("originalWidth", 0)
    height = asset.get("originalHeight", 0)
    exif = asset.get("exifInfo") or {}  # Handle both missing and None
    orientation = exif.get("orientation")

    # Orientation can be string or int from Immich API
    try:
        orientation_int = int(orientation) if orientation else 0
    except (ValueError, TypeError):
        orientation_int = 0

    # Orientations 5-8 indicate 90° rotation (portrait photos stored as landscape)
    rotated = orientation_int in (5, 6, 7, 8)

    if width > 0 and height > 0:
        if rotated:
            return width > height
        return height > width
    return False


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Immich Slideshow image entities from a config entry."""
    hub: ImmichHub = hass.data[DOMAIN][config_entry.entry_id]
    options = config_entry.options

    # Core display settings
    dual_portrait = options.get(CONF_DUAL_PORTRAIT, DEFAULT_DUAL_PORTRAIT)
    refresh_interval = options.get(CONF_REFRESH_INTERVAL, DEFAULT_REFRESH_INTERVAL)
    background_path = options.get(CONF_BACKGROUND_PATH, DEFAULT_BACKGROUND_PATH)
    write_files = options.get(CONF_WRITE_FILES, DEFAULT_WRITE_FILES)

    # Source weights (v2 schema, populated by async_migrate_entry for v1 entries)
    source_recent_weight = options.get(CONF_SOURCE_RECENT_WEIGHT, DEFAULT_SOURCE_RECENT_WEIGHT)
    source_memories_weight = options.get(CONF_SOURCE_MEMORIES_WEIGHT, DEFAULT_SOURCE_MEMORIES_WEIGHT)
    source_albums_weight = options.get(CONF_SOURCE_ALBUMS_WEIGHT, DEFAULT_SOURCE_ALBUMS_WEIGHT)
    source_persons_weight = options.get(CONF_SOURCE_PERSONS_WEIGHT, DEFAULT_SOURCE_PERSONS_WEIGHT)
    recent_days = options.get(CONF_RECENT_DAYS, DEFAULT_RECENT_DAYS)
    recent_favorites_filter = options.get(CONF_RECENT_FAVORITES_FILTER, DEFAULT_RECENT_FAVORITES_FILTER)
    memories_max_years = options.get(CONF_MEMORIES_MAX_YEARS, DEFAULT_MEMORIES_MAX_YEARS)

    # Albums/Persons includes
    albums_include = options.get(CONF_ALBUMS_INCLUDE, [])
    persons_include = options.get(CONF_PERSONS_INCLUDE, [])

    # Global exclusions
    exclude_albums = options.get(CONF_EXCLUDE_ALBUMS, [])
    exclude_persons = options.get(CONF_EXCLUDE_PERSONS, [])

    resolutions = parse_resolutions(options.get(CONF_RESOLUTIONS, DEFAULT_RESOLUTIONS))
    if not resolutions:
        resolutions = [(1920, 1080)]  # Fallback if parsing fails

    _LOGGER.info(
        "Setting up slideshow: resolutions=%s, weights={recent=%d, memories=%d, albums=%d, persons=%d}",
        resolutions, source_recent_weight, source_memories_weight,
        source_albums_weight, source_persons_weight,
    )

    # Create shared manager
    manager = SlideshowManager(
        hub=hub,
        dual_portrait=dual_portrait,
        source_recent_weight=source_recent_weight,
        source_memories_weight=source_memories_weight,
        source_albums_weight=source_albums_weight,
        source_persons_weight=source_persons_weight,
        recent_days=recent_days,
        recent_favorites_filter=recent_favorites_filter,
        memories_max_years=memories_max_years,
        albums_include=albums_include,
        persons_include=persons_include,
        exclude_albums=exclude_albums,
        exclude_persons=exclude_persons,
    )

    # Store manager in hass.data for diagnostic sensors to access
    hass.data[DOMAIN][f"{config_entry.entry_id}_manager"] = manager

    # Create one entity per resolution
    entities = []
    for width, height in resolutions:
        entity = ImmichSlideshowImage(
            hass=hass,
            manager=manager,
            config_entry=config_entry,
            target_width=width,
            target_height=height,
            refresh_interval=refresh_interval,
            is_primary=(width, height) == resolutions[0],
            background_path=background_path,
            write_files=write_files,
        )
        entities.append(entity)

    async_add_entities(entities)


class ImmichSlideshowImage(ImageEntity):
    """Image entity that shows random Immich photos at a specific resolution."""

    _attr_has_entity_name = True
    _attr_content_type = "image/jpeg"
    _attr_should_poll = False

    def __init__(
        self,
        hass: HomeAssistant,
        manager: SlideshowManager,
        config_entry: ConfigEntry,
        target_width: int,
        target_height: int,
        refresh_interval: int,
        is_primary: bool,
        background_path: str,
        write_files: bool = False,
    ) -> None:
        """Initialize the image entity."""
        super().__init__(hass)
        self._manager = manager
        self._config_entry = config_entry
        self._target_width = target_width
        self._target_height = target_height
        self._refresh_interval = refresh_interval
        self._is_primary = is_primary
        self._background_path = background_path
        self._write_files = write_files

        # Entity naming
        res_str = f"{target_width}x{target_height}"
        if is_primary:
            self._attr_name = None  # Use device name only
            self._attr_unique_id = f"{config_entry.entry_id}_image"
        else:
            self._attr_name = res_str
            self._attr_unique_id = f"{config_entry.entry_id}_image_{res_str}"

        self._current_image_bytes: bytes | None = None
        self._image_last_updated: datetime | None = None
        self._unsub_timer = None

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._manager.is_available

    async def async_added_to_hass(self) -> None:
        """Run when entity is added to hass."""
        await super().async_added_to_hass()

        # Only primary entity triggers refresh (others follow)
        if self._is_primary:
            await self._do_refresh()
            self._unsub_timer = async_track_time_interval(
                self.hass,
                self._async_refresh,
                timedelta(seconds=self._refresh_interval),
            )
        else:
            # Non-primary: just generate from current manager state
            self._generate_image()

    async def async_will_remove_from_hass(self) -> None:
        """Run when entity is removed from hass."""
        if self._unsub_timer:
            self._unsub_timer()
            self._unsub_timer = None
        # Clean up manager resources when primary entity is removed
        if self._is_primary:
            self._manager.cleanup()
        await super().async_will_remove_from_hass()

    async def _async_refresh(self, _now: datetime) -> None:
        """Refresh triggered by timer (primary entity only)."""
        await self._do_refresh()

    async def _do_refresh(self) -> None:
        """Load new images and notify all entities."""
        success = await self._manager.refresh()
        if success:
            # Generate for this entity
            self._generate_image()
            self.async_write_ha_state()

            # Other entities will regenerate when their async_image is called
            # by HA's state machine (no explicit notification needed)

    def _generate_image(self) -> None:
        """Generate image at this entity's resolution."""
        try:
            image_bytes = self._manager.generate_image(
                self._target_width, self._target_height
            )
            if image_bytes:
                self._current_image_bytes = image_bytes
                self._image_last_updated = datetime.now()
                self._attr_image_last_updated = self._image_last_updated
                # Save to file system only if write_files is enabled (for View Assist)
                if self._write_files:
                    self._save_to_va_background(image_bytes)
        except Exception as err:
            _LOGGER.error("Error generating image: %s", err)

    def _save_to_va_background(self, image_bytes: bytes) -> None:
        """Save image to View Assist background folder for local access."""
        # Schedule file write in executor to avoid blocking event loop
        self.hass.async_add_executor_job(
            self._write_va_background_file, image_bytes
        )

    def _write_va_background_file(self, image_bytes: bytes) -> None:
        """Write image bytes to file with unique name (runs in executor)."""
        try:
            va_path = Path(self.hass.config.config_dir) / self._background_path
            va_path.mkdir(parents=True, exist_ok=True)

            # Generate unique filename with timestamp
            timestamp = int(time.time() * 1000)  # milliseconds for uniqueness
            filename = f"immich_{self._target_width}x{self._target_height}_{timestamp}.jpg"
            filepath = va_path / filename
            filepath.write_bytes(image_bytes)

            # Delete old immich files AFTER writing new one, keep enough for VA rotation
            pattern = f"immich_{self._target_width}x{self._target_height}_*.jpg"
            old_files = sorted(va_path.glob(pattern), key=lambda f: f.stat().st_mtime, reverse=True)
            cleanup_errors = 0
            for old_file in old_files[100:]:  # Keep last 100 (~8 min at 5s refresh)
                try:
                    old_file.unlink()
                except Exception as err:
                    cleanup_errors += 1
                    if cleanup_errors <= 3:  # Log first 3 errors only
                        _LOGGER.warning("Failed to delete old background %s: %s", old_file.name, err)
            if cleanup_errors > 3:
                _LOGGER.warning("Failed to delete %d old background files", cleanup_errors)
        except Exception as err:
            _LOGGER.warning("Failed to save VA background: %s", err)

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device info."""
        return {
            "identifiers": {(DOMAIN, self._config_entry.entry_id)},
            "name": "Immich Slideshow",
            "manufacturer": "Immich",
        }

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        attrs: dict[str, Any] = {}
        attrs["is_dual_portrait"] = self._manager.is_dual

        # Always use _1 suffix for first image (consistent naming)
        asset1_attrs = self._manager.get_asset_attrs(self._manager.asset1)
        for key, value in asset1_attrs.items():
            attrs[f"{key}_1"] = value

        # Add _2 suffix only when dual portrait
        if self._manager.is_dual:
            asset2_attrs = self._manager.get_asset_attrs(self._manager.asset2)
            for key, value in asset2_attrs.items():
                attrs[f"{key}_2"] = value

        return attrs

    async def async_image(self) -> bytes | None:
        """Return bytes of image."""
        # Regenerate if we don't have an image yet
        if self._current_image_bytes is None:
            self._generate_image()
        return self._current_image_bytes
