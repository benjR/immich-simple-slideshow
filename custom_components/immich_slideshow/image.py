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

from PIL import Image, ImageOps, UnidentifiedImageError

from homeassistant.components.image import ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store

# Pool management constants
MAX_POOL_SIZE = 200  # Maximum assets to keep in pool
REFILL_THRESHOLD = 20  # Refill when pool drops below this
POOL_FETCH_SIZE = 100  # Number of assets to fetch per refill
API_CONCURRENCY_LIMIT = 5  # Max concurrent API calls for asset enrichment
# A failed download may be transient (Immich restarting, network blip), unlike
# a decode failure: only blacklist an asset after this many download failures.
DOWNLOAD_FAILURES_BEFORE_BAD = 2

# Errors Pillow raises on bytes it cannot turn into an image
IMAGE_DECODE_ERRORS = (
    UnidentifiedImageError,
    Image.DecompressionBombError,
    OSError,
    ValueError,
    SyntaxError,
)

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
    CONF_RECENT_BOOST_DAYS,
    CONF_RECENT_BOOST_SHARE,
    CONF_RECENT_BOOST_RESHOW_HOURS,
    # Memories source keys
    CONF_MEMORIES_MAX_YEARS,
    # Albums/Persons source keys
    CONF_ALBUMS_INCLUDE,
    CONF_PERSONS_INCLUDE,
    # Global exclusions
    CONF_EXCLUDE_ALBUMS,
    CONF_EXCLUDE_PERSONS,
    CONF_INCLUDE_ARCHIVED,
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
    DEFAULT_RECENT_BOOST_DAYS,
    DEFAULT_RECENT_BOOST_SHARE,
    DEFAULT_RECENT_BOOST_RESHOW_HOURS,
    DEFAULT_MEMORIES_MAX_YEARS,
    DEFAULT_INCLUDE_ARCHIVED,
    DOMAIN,
    # Anti-repetition ("recently shown") settings
    SHOWN_MEMORY_HOURS,
    SHOWN_SAVE_DELAY_SECONDS,
    SHOWN_STORAGE_KEY,
    SHOWN_STORAGE_VERSION,
    # Undisplayable assets
    BAD_ASSET_TTL_HOURS,
    BAD_ASSETS_STORE_KEY,
    MAX_DISPLAY_ATTEMPTS,
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
        recent_boost_days: int = 7,
        recent_boost_share: int = 40,
        recent_boost_reshow_hours: int = DEFAULT_RECENT_BOOST_RESHOW_HOURS,
        # Memories source config
        memories_max_years: int = 0,
        # Albums/Persons includes
        albums_include: list[str] | None = None,
        persons_include: list[str] | None = None,
        # Global exclusions
        exclude_albums: list[str] | None = None,
        exclude_persons: list[str] | None = None,
        include_archived: bool = False,
        # Anti-repetition persistent store
        shown_store: Store | None = None,
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
            recent_boost_days: Window (days) for the very-recent boost within
                the recent source (0 = boost disabled)
            recent_boost_reshow_hours: Hours before a boosted photo can be
                shown again (regular photos use SHOWN_MEMORY_HOURS)
            recent_boost_share: Percentage of recent-source draws reserved
                for the boost window (0-100)
            memories_max_years: Max years for memories (0 = unlimited)
            albums_include: List of album UUIDs to include
            persons_include: List of person UUIDs to include
            exclude_albums: List of album UUIDs to globally exclude
            exclude_persons: List of person UUIDs to globally exclude
            include_archived: Also draw photos archived in Immich
            shown_store: Store persisting the "recently shown" history
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
        self._recent_boost_days = recent_boost_days
        self._recent_boost_share = recent_boost_share
        self._recent_boost_reshow_hours = max(1, int(recent_boost_reshow_hours))

        # Memories source config
        self._memories_max_years = memories_max_years

        # Albums/Persons includes
        self._albums_include = albums_include or []
        self._persons_include = persons_include or []

        # Global exclusions (as sets for O(1) lookup)
        self._exclude_albums = set(exclude_albums or [])
        self._exclude_persons = set(exclude_persons or [])
        self._include_archived = include_archived
        # Stale album ids (deleted albums) are dropped once the album list is
        # known: Immich's v3.2 search answers 400 to an unknown album id.
        self._albums_include_configured = bool(self._albums_include)
        self._album_ids_sanitized = False

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

        # Anti-repetition: asset_id -> unix timestamp of last display.
        # Persisted via Store so the exclusion window survives HA restarts.
        self._shown_store = shown_store
        self._shown: dict[str, float] = {}
        self._shown_last_save: float = 0.0

        # Undisplayable assets: asset_id -> unix timestamp when marked bad.
        # Persisted in the same Store (reserved key), expires after
        # BAD_ASSET_TTL_HOURS. Download failures are counted in memory first.
        self._bad_assets: dict[str, float] = {}
        self._download_failures: dict[str, int] = {}

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

    def _sanitize_album_ids(self) -> None:
        """Drop configured album ids that no longer exist (once, when known).

        A deleted album left in `albums_include` or `exclude_albums` would make
        every Immich v3.2 search request carrying it fail with HTTP 400. Only
        runs once the album list could be fetched; without `album.read` the ids
        are kept as-is.
        """
        if self._album_ids_sanitized or not self._album_names:
            return
        self._album_ids_sanitized = True
        known = set(self._album_names)
        stale = (set(self._albums_include) | self._exclude_albums) - known
        if not stale:
            return
        _LOGGER.warning(
            "Ignoring %d album id(s) that no longer exist in Immich "
            "(remove them from the integration options): %s",
            len(stale),
            ", ".join(sorted(stale)),
        )
        self._albums_include = [a for a in self._albums_include if a in known]
        self._exclude_albums &= known

    def _search_kwargs(self) -> dict[str, Any]:
        """Filters shared by every search call (server-side on Immich >= 3.2)."""
        return {
            "include_archived": self._include_archived,
            "exclude_album_ids": sorted(self._exclude_albums),
            "exclude_person_ids": sorted(self._exclude_persons),
        }

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

    async def async_load_shown(self) -> None:
        """Load the persisted recently-shown history (call once at setup)."""
        if self._shown_store is None:
            return
        try:
            data = await self._shown_store.async_load()
        except Exception as err:  # Corrupt store must never block the slideshow
            _LOGGER.warning("Could not load shown-history store: %s", err)
            return
        if isinstance(data, dict):
            now = time.time()
            cutoff = now - SHOWN_MEMORY_HOURS * 3600
            # Flat {asset_id: ts} map; the bad-asset map lives under a reserved
            # key whose (dict) value the float filter skips.
            self._shown = {
                asset_id: float(ts)
                for asset_id, ts in data.items()
                if isinstance(ts, (int, float)) and float(ts) >= cutoff
            }
            bad = data.get(BAD_ASSETS_STORE_KEY)
            if isinstance(bad, dict):
                bad_cutoff = now - BAD_ASSET_TTL_HOURS * 3600
                self._bad_assets = {
                    asset_id: float(ts)
                    for asset_id, ts in bad.items()
                    if isinstance(ts, (int, float)) and float(ts) >= bad_cutoff
                }
        _LOGGER.debug(
            "Loaded %d recently-shown and %d bad asset ids",
            len(self._shown),
            len(self._bad_assets),
        )

    def _shown_data_to_save(self) -> dict[str, Any]:
        """Return the serializable shown-history (Store data callback)."""
        data: dict[str, Any] = dict(self._shown)
        if self._bad_assets:
            data[BAD_ASSETS_STORE_KEY] = dict(self._bad_assets)
        return data

    def _purge_shown(self) -> None:
        """Drop history entries older than the exclusion window."""
        cutoff = time.time() - SHOWN_MEMORY_HOURS * 3600
        self._shown = {k: v for k, v in self._shown.items() if v >= cutoff}

    def _is_in_boost_window(self, asset: dict | None) -> bool:
        """Return True if the asset was taken OR uploaded < recent_boost_days ago.

        Checked against the EXIF capture date (dateTimeOriginal /
        localDateTime / fileCreatedAt) and the upload date (createdAt), so an
        old scan imported yesterday counts as boosted too. Always False when
        the boost is disabled (days or share at 0).
        """
        if (
            not asset
            or self._recent_boost_days <= 0
            or self._recent_boost_share <= 0
        ):
            return False
        cutoff = time.time() - self._recent_boost_days * 86400
        exif = asset.get("exifInfo") or {}
        for value in (
            exif.get("dateTimeOriginal"),
            asset.get("localDateTime"),
            asset.get("fileCreatedAt"),
            asset.get("createdAt"),
        ):
            if not value or not isinstance(value, str):
                continue
            try:
                dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                continue
            if dt.tzinfo is None:
                dt = dt.astimezone()
            if dt.timestamp() >= cutoff:
                return True
        return False

    def _is_recently_shown(self, asset: dict | None) -> bool:
        """Return True if this asset was displayed within its exclusion window.

        Assets inside the recent-boost window use the shorter, configurable
        recent_boost_reshow_hours window (they may cycle several times a
        day); everything else uses SHOWN_MEMORY_HOURS.
        """
        if not asset:
            return False
        ts = self._shown.get(asset.get("id") or "")
        if ts is None:
            return False
        window_hours = (
            self._recent_boost_reshow_hours
            if self._is_in_boost_window(asset)
            else SHOWN_MEMORY_HOURS
        )
        return (time.time() - ts) < window_hours * 3600

    def _is_bad_asset(self, asset: dict | None) -> bool:
        """Return True if this asset failed to download/decode recently."""
        if not asset:
            return False
        ts = self._bad_assets.get(asset.get("id") or "")
        return ts is not None and (time.time() - ts) < BAD_ASSET_TTL_HOURS * 3600

    def _mark_bad(self, asset: dict, reason: str) -> None:
        """Remember an undisplayable asset so it is not drawn again for a while."""
        now = time.time()
        cutoff = now - BAD_ASSET_TTL_HOURS * 3600
        self._bad_assets = {k: v for k, v in self._bad_assets.items() if v >= cutoff}
        self._bad_assets[asset["id"]] = now
        self._download_failures.pop(asset["id"], None)
        _LOGGER.warning(
            "Skipping asset %s (%s) for %dh: %s",
            asset["id"],
            asset.get("originalFileName") or "unknown file",
            BAD_ASSET_TTL_HOURS,
            reason,
        )
        if self._shown_store is not None:
            self._shown_store.async_delay_save(self._shown_data_to_save, 5)

    def _mark_shown(self, *assets: dict | None) -> None:
        """Record assets as displayed now; schedule a rate-limited save."""
        now = time.time()
        marked = False
        for asset in assets:
            if asset and asset.get("id"):
                self._shown[asset["id"]] = now
                marked = True
        if not marked:
            return
        self._purge_shown()
        if (
            self._shown_store is not None
            and now - self._shown_last_save >= SHOWN_SAVE_DELAY_SECONDS
        ):
            self._shown_last_save = now
            # Small delay batches the write off the refresh path; the actual
            # rate limiting is the SHOWN_SAVE_DELAY_SECONDS gate above.
            self._shown_store.async_delay_save(self._shown_data_to_save, 5)

    async def refresh(self) -> bool:
        """Load new source images. Returns True if successful."""
        async with self._refresh_lock:
            success = await self._do_refresh()
            if success:
                # Mark what is now on screen (both assets when dual portrait)
                self._mark_shown(self._current_asset1, self._current_asset2)
            return success

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

        # Flush any unsaved shown-history (e.g. integration reload before the
        # delayed save fired)
        if self._shown_store is not None and (self._shown or self._bad_assets):
            self._shown_store.async_delay_save(self._shown_data_to_save, 1)

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

            loaded = await self._load_next_display()
            if loaded is None:
                _LOGGER.debug("Prefetch: no displayable asset this cycle")
                return

            img1, img2, asset1, asset2 = loaded
            self._next_img1 = img1
            self._next_img2 = img2
            self._next_asset1 = asset1
            self._next_asset2 = asset2
            self._next_is_dual = img2 is not None
            _LOGGER.debug(
                "Prefetch complete: %s ready",
                "dual portrait" if img2 is not None else "single image",
            )

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

        loaded = await self._load_next_display()
        if loaded is None:
            _LOGGER.warning("No displayable asset found this cycle")
            return False

        img1, img2, asset1, asset2 = loaded
        self._current_img1 = img1
        self._current_img2 = img2
        self._current_asset1 = asset1
        self._current_asset2 = asset2
        self._is_dual = img2 is not None
        return True

    async def _load_next_display(
        self,
    ) -> tuple[Image.Image, Image.Image | None, dict, dict | None] | None:
        """Pop and decode the next displayable asset(s) from the pool.

        Returns (img1, img2, asset1, asset2) — img2/asset2 are None unless a
        dual portrait could be composed. An asset that cannot be downloaded or
        decoded is skipped (and remembered as bad) and the next pool asset is
        tried, up to MAX_DISPLAY_ATTEMPTS per image, so a broken file costs no
        display slot. For a dual portrait, only the failing asset is dropped:
        the first portrait is kept and another partner is tried, falling back
        to a single image.
        """
        for _ in range(MAX_DISPLAY_ATTEMPTS):
            popped = self._pop_from_pool(count=1)
            if not popped:
                return None
            chosen = popped[0]
            _LOGGER.debug("Selected photo from source: %s", chosen.get("_source", "unknown"))

            img1 = await self._load_asset_image(chosen)
            if img1 is None:
                continue

            # If portrait + dual_portrait enabled → try to get another portrait
            if self._dual_portrait and is_portrait(chosen):
                for _ in range(MAX_DISPLAY_ATTEMPTS):
                    second_list = self._pop_from_pool(count=1, portrait_only=True)
                    if not second_list:
                        break
                    second = second_list[0]
                    img2 = await self._load_asset_image(second)
                    if img2 is not None:
                        return img1, img2, chosen, second

            # Single image (landscape, or portrait without pair available)
            return img1, None, chosen, None
        return None

    async def _load_asset_image(self, asset: dict) -> Image.Image | None:
        """Download and decode one asset. Returns None (and records it) on failure."""
        asset_id = asset["id"]
        image_bytes = await self._hub.download_image(asset_id)
        if not image_bytes:
            failures = self._download_failures.get(asset_id, 0) + 1
            if failures >= DOWNLOAD_FAILURES_BEFORE_BAD:
                self._mark_bad(asset, f"download failed {failures} times")
            else:
                # Bound the in-memory counter (e.g. during an Immich outage)
                if len(self._download_failures) > 1000:
                    self._download_failures.clear()
                self._download_failures[asset_id] = failures
                _LOGGER.debug(
                    "Download failed for asset %s (%s), will retry it later",
                    asset_id,
                    asset.get("originalFileName") or "unknown file",
                )
            return None

        self._download_failures.pop(asset_id, None)
        # Full decode of a multi-megapixel original takes hundreds of ms: keep
        # it off the event loop.
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(None, decode_image, image_bytes)
        except IMAGE_DECODE_ERRORS as err:
            first_error = err

        # Immich serves web-compatible *names* as-is, so a HEIC saved as .jpg
        # or an oversized panorama comes back undecodable: retry once with the
        # server-generated (downscaled) preview JPEG before giving up.
        preview_bytes = await self._hub.download_image(asset_id, size="preview")
        if preview_bytes:
            try:
                img = await loop.run_in_executor(None, decode_image, preview_bytes)
                _LOGGER.debug(
                    "Asset %s (%s) displayed from its preview rendition: %s",
                    asset_id,
                    asset.get("originalFileName") or "unknown file",
                    first_error,
                )
                return img
            except IMAGE_DECODE_ERRORS:
                pass
        self._mark_bad(asset, f"cannot decode image: {first_error}")
        return None

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
        """Fetch recent photos, reserving a share for the very latest ones.

        When the boost is enabled (recent_boost_days > 0 and
        recent_boost_share > 0), ~recent_boost_share% of the requested assets
        come from the boost window (taken OR uploaded < recent_boost_days),
        the rest from the classic recent_days window. The classic query is
        issued at full count so a sparse or empty boost window silently falls
        back to classic recent photos — never a hole in the pool.
        """
        # days=0 means unlimited (use ~100 years)
        days_param = self._recent_days if self._recent_days > 0 else 36500

        boost_count = 0
        if self._recent_boost_days > 0 and self._recent_boost_share > 0:
            boost_count = min(count, round(count * self._recent_boost_share / 100))

        if boost_count <= 0:
            assets = await self._hub.search_random_recent(
                days=days_param,
                count=count,
                favorites_filter=self._recent_favorites_filter,
                **self._search_kwargs(),
            )
        else:
            boost_assets, classic_assets = await asyncio.gather(
                self._hub.search_random_recent_boost(
                    days=self._recent_boost_days,
                    count=boost_count,
                    favorites_filter=self._recent_favorites_filter,
                    **self._search_kwargs(),
                ),
                self._hub.search_random_recent(
                    days=days_param,
                    count=count,
                    favorites_filter=self._recent_favorites_filter,
                    **self._search_kwargs(),
                ),
            )
            # Boost assets first (guarantees their share), then classic as
            # filler, deduplicated by id, truncated to the requested count.
            assets = []
            seen_ids: set[str] = set()
            for asset in boost_assets + classic_assets:
                asset_id = asset.get("id")
                if asset_id and asset_id not in seen_ids:
                    seen_ids.add(asset_id)
                    assets.append(asset)
                if len(assets) >= count:
                    break
            _LOGGER.debug(
                "Recent source: %d boosted (<%s d) + %d classic of %d requested",
                len(boost_assets),
                self._recent_boost_days,
                len(assets) - len(boost_assets),
                count,
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

        Always fans out via `search_random_from_albums`, which issues one call
        per album in parallel and tags each asset with `_album_id`.

        - If specific albums are selected (`albums_include` non-empty), the
          fan-out is restricted to those.
        - Otherwise ("any album" mode), the fan-out targets the user's full
          album list cached in `_album_names`. One call per album keeps the
          exposure balanced across albums (a single `albumIds: {any}` or
          `hasAlbums` query would favour the biggest albums) and keeps the
          `_album_id` attribution.

        If `_album_names` isn't populated (e.g. perm missing), returns []. If
        specific albums were configured but none of them exists any more,
        returns [] rather than silently widening to every album.
        """
        if self._albums_include:
            album_ids = self._albums_include
        elif self._albums_include_configured:
            return []
        else:
            album_ids = list(self._album_names.keys())

        if not album_ids:
            return []

        assets = await self._hub.search_random_from_albums(
            album_ids=album_ids, count=count, **self._search_kwargs()
        )
        for asset in assets:
            asset["_source"] = "album"
        return assets

    async def _fetch_persons(self, count: int) -> list[dict]:
        """Fetch photos containing selected persons."""
        if not self._persons_include:
            return []

        assets = await self._hub.search_random_by_person(
            person_ids=self._persons_include,
            count=count,
            **self._search_kwargs(),
        )
        # Tag source
        for asset in assets:
            asset["_source"] = "person"
        return assets

    def _apply_global_exclusions(self, assets: list[dict]) -> list[dict]:
        """Filter out assets matching global exclusions (client-side net).

        On Immich >= 3.2 the hub already excludes albums and persons
        server-side (`none` filters), so this only catches what the server
        could not: memory assets, and every source on legacy servers.

        Removes assets that:
        - Were drawn from an excluded album (`_album_id`). Immich never returns
          the albums an asset belongs to, so on legacy servers album exclusion
          only covers album-sourced assets; recent/person/memory assets from an
          excluded album can still show up there.
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
        self._sanitize_album_ids()

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
        # Also deduplicate against assets already in the pool, and exclude assets
        # displayed less than SHOWN_MEMORY_HOURS ago (anti-repetition).
        all_assets: list[dict] = []
        recently_shown: list[dict] = []
        seen_ids: set[str] = {a.get("id") for a in self._asset_pool if a.get("id")}
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                _LOGGER.warning("Error fetching from %s: %s", source_order[i], result)
            elif result:
                for asset in result:
                    asset_id = asset.get("id")
                    if asset_id and asset_id not in seen_ids:
                        seen_ids.add(asset_id)
                        if self._is_bad_asset(asset):
                            continue
                        if self._is_recently_shown(asset):
                            recently_shown.append(asset)
                        else:
                            all_assets.append(asset)

        # Anti-famine guard: if every candidate was shown recently (small
        # library / narrow source buckets), fall back to the least recently
        # shown assets instead of starving the slideshow.
        if not all_assets and recently_shown:
            recently_shown.sort(key=lambda a: self._shown.get(a.get("id"), 0.0))
            all_assets = recently_shown
            _LOGGER.info(
                "Anti-repeat: all %d candidates were shown <%dh ago; "
                "falling back to least recently shown",
                len(all_assets),
                SHOWN_MEMORY_HOURS,
            )

        if not all_assets:
            _LOGGER.warning("No assets found from any source")
            return

        # Apply global exclusions
        all_assets = self._apply_global_exclusions(all_assets)

        if not all_assets:
            _LOGGER.warning("All assets filtered out by global exclusions")
            return

        # Enrich assets with full metadata using semaphore for concurrency control.
        # Search results already carry exifInfo + people (withExif/withPeople),
        # so only assets without dimensions (e.g. memories) need a GET. Both
        # payloads come from Immich's same asset mapper, so isFavorite has the
        # same meaning either way: the favorite flag as seen by the API key's
        # user (partner assets report the owner's flag only to the owner).
        semaphore = asyncio.Semaphore(API_CONCURRENCY_LIMIT)

        def apply_info(asset: dict, info: dict) -> dict:
            exif = info.get("exifInfo") or {}
            asset["originalWidth"] = exif.get("exifImageWidth", 0)
            asset["originalHeight"] = exif.get("exifImageHeight", 0)
            asset["exifInfo"] = exif
            asset["originalFileName"] = info.get("originalFileName")
            asset["isFavorite"] = info.get("isFavorite", False)
            asset["localDateTime"] = info.get("localDateTime")
            asset["people"] = info.get("people", [])
            # Live Photo support: store video ID if present
            asset["livePhotoVideoId"] = info.get("livePhotoVideoId")
            return asset

        async def enrich_asset(asset: dict) -> dict | None:
            if has_dimensions(asset):
                return apply_info(asset, asset)
            async with semaphore:
                info = await self._hub.get_asset_info(asset["id"])
                if info:
                    return apply_info(asset, info)
                return None

        # Run enrichment concurrently with limited parallelism
        enriched = await asyncio.gather(*[enrich_asset(a) for a in all_assets])
        enriched_assets = [a for a in enriched if a is not None]

        # Apply exclusions again after enrichment (now memory assets have people)
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
        """Pop assets from the pool.

        Assets shown less than SHOWN_MEMORY_HOURS ago are skipped. Anti-famine
        guard: if only recently-shown assets match, the least recently shown
        ones are used instead of returning nothing.
        """
        result: list[dict] = []
        remaining: list[dict] = []
        recently_shown: list[dict] = []

        for asset in self._asset_pool:
            if self._is_bad_asset(asset):
                continue  # Marked undisplayable since it entered the pool
            if len(result) < count:
                if portrait_only and not is_portrait(asset):
                    remaining.append(asset)
                elif self._is_recently_shown(asset):
                    recently_shown.append(asset)
                else:
                    result.append(asset)
            else:
                remaining.append(asset)

        # Anti-famine: top up from the least recently shown candidates
        if len(result) < count and recently_shown:
            recently_shown.sort(key=lambda a: self._shown.get(a.get("id"), 0.0))
            while len(result) < count and recently_shown:
                result.append(recently_shown.pop(0))

        # Unused recently-shown assets go back to the pool (at the end)
        remaining.extend(recently_shown)
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


def decode_image(image_bytes: bytes) -> Image.Image:
    """Decode bytes into an EXIF-transposed RGB/L image (raises on failure)."""
    img = Image.open(io.BytesIO(image_bytes))
    # Force full decode now: a truncated/unsupported file must fail here, not
    # later while resizing for display.
    img.load()
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    return img


def has_dimensions(asset: dict[str, Any]) -> bool:
    """Return True if the asset already carries EXIF width and height."""
    exif = asset.get("exifInfo") or {}
    return bool(exif.get("exifImageWidth")) and bool(exif.get("exifImageHeight"))


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
    recent_boost_days = options.get(CONF_RECENT_BOOST_DAYS, DEFAULT_RECENT_BOOST_DAYS)
    recent_boost_share = options.get(CONF_RECENT_BOOST_SHARE, DEFAULT_RECENT_BOOST_SHARE)
    recent_boost_reshow_hours = options.get(
        CONF_RECENT_BOOST_RESHOW_HOURS, DEFAULT_RECENT_BOOST_RESHOW_HOURS
    )
    memories_max_years = options.get(CONF_MEMORIES_MAX_YEARS, DEFAULT_MEMORIES_MAX_YEARS)

    # Albums/Persons includes
    albums_include = options.get(CONF_ALBUMS_INCLUDE, [])
    persons_include = options.get(CONF_PERSONS_INCLUDE, [])

    # Global exclusions
    exclude_albums = options.get(CONF_EXCLUDE_ALBUMS, [])
    exclude_persons = options.get(CONF_EXCLUDE_PERSONS, [])
    include_archived = options.get(CONF_INCLUDE_ARCHIVED, DEFAULT_INCLUDE_ARCHIVED)

    resolutions = parse_resolutions(options.get(CONF_RESOLUTIONS, DEFAULT_RESOLUTIONS))
    if not resolutions:
        resolutions = [(1920, 1080)]  # Fallback if parsing fails

    _LOGGER.info(
        "Setting up slideshow: resolutions=%s, weights={recent=%d, memories=%d, albums=%d, persons=%d}",
        resolutions, source_recent_weight, source_memories_weight,
        source_albums_weight, source_persons_weight,
    )

    # Anti-repetition: persistent "recently shown" history for this entry
    # (stored in .storage/immich_slideshow_shown_<entry_id>)
    shown_store: Store = Store(
        hass,
        SHOWN_STORAGE_VERSION,
        f"{SHOWN_STORAGE_KEY}_{config_entry.entry_id}",
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
        recent_boost_days=recent_boost_days,
        recent_boost_share=recent_boost_share,
        recent_boost_reshow_hours=recent_boost_reshow_hours,
        memories_max_years=memories_max_years,
        albums_include=albums_include,
        persons_include=persons_include,
        exclude_albums=exclude_albums,
        exclude_persons=exclude_persons,
        include_archived=include_archived,
        shown_store=shown_store,
    )

    # Load persisted shown-history before the first refresh
    await manager.async_load_shown()

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
                        _LOGGER.debug("Failed to delete old background %s: %s", old_file.name, err)
            if cleanup_errors > 3:
                _LOGGER.debug("Failed to delete %d old background files", cleanup_errors)
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
