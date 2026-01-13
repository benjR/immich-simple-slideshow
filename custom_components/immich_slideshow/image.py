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
    CONF_BACKGROUND_PATH,
    CONF_DAYS,
    CONF_DUAL_PORTRAIT,
    CONF_FAVORITES_FILTER,
    CONF_MEMORY_YEARS,
    CONF_MIX_RATIO,
    CONF_REFRESH_INTERVAL,
    CONF_RESOLUTIONS,
    CONF_TARGET_HEIGHT,
    CONF_TARGET_WIDTH,
    CONF_WRITE_FILES,
    DEFAULT_BACKGROUND_PATH,
    DEFAULT_DAYS,
    DEFAULT_DUAL_PORTRAIT,
    DEFAULT_FAVORITES_FILTER,
    DEFAULT_MEMORY_YEARS,
    DEFAULT_MIX_RATIO,
    DEFAULT_REFRESH_INTERVAL,
    DEFAULT_RESOLUTIONS,
    DEFAULT_WRITE_FILES,
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
        days: int,
        dual_portrait: bool,
        memory_years: int = 0,
        mix_ratio: int = 0,
        favorites_filter: str = "all",
    ) -> None:
        """Initialize the manager.

        Args:
            hub: ImmichHub instance for API calls
            days: Days to look back for recent photos (0 = disabled)
            dual_portrait: Whether to combine two portraits side by side
            memory_years: Max years for memories (0 = unlimited)
            mix_ratio: % of memories in pool (0 = recent only, 100 = memories only)
            favorites_filter: "all", "only", or "exclude"
        """
        self._hub = hub
        self._host = hub._host  # Store for building Immich URLs
        self._days = days
        self._dual_portrait = dual_portrait
        self._memory_years = memory_years
        self._mix_ratio = mix_ratio
        self._favorites_filter = favorites_filter
        self._asset_pool: list[dict] = []
        # Current source images (PIL Image objects, already EXIF-transposed)
        self._current_img1: Image.Image | None = None
        self._current_img2: Image.Image | None = None  # For dual portrait
        self._is_dual: bool = False
        # Current asset info for metadata exposure
        self._current_asset1: dict | None = None
        self._current_asset2: dict | None = None
        # Lock for thread-safe pool operations
        self._refresh_lock = asyncio.Lock()
        # Track if pool is empty (for entity availability)
        self._pool_empty = False

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
        """Return the source of the photo: 'memory' or 'recent'."""
        if self._current_asset1:
            if self._current_asset1.get("memory_year"):
                return "memory"
            return "recent"
        return None

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
            attrs["source"] = "memory"
        else:
            attrs["source"] = "recent"

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

    async def _do_refresh(self) -> bool:
        """Internal refresh logic (must be called with lock held)."""
        # Close previous images to prevent memory leak
        if self._current_img1 is not None:
            try:
                self._current_img1.close()
            except Exception:
                pass
            self._current_img1 = None
        if self._current_img2 is not None:
            try:
                self._current_img2.close()
            except Exception:
                pass
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

    async def _refill_pool(self) -> None:
        """Fetch a new batch of assets to refill the pool.

        Uses mix_ratio to determine the split:
        - 0% = recent photos only
        - 100% = memories only
        - 1-99% = mixed (memories + recent to fill remaining)
        """
        # Calculate how many we need (up to POOL_FETCH_SIZE, capped by MAX_POOL_SIZE)
        current_size = len(self._asset_pool)
        space_available = MAX_POOL_SIZE - current_size
        fetch_count = min(POOL_FETCH_SIZE, space_available)

        if fetch_count <= 0:
            return

        memory_count = int(self._mix_ratio * fetch_count / 100)  # Proportional to fetch_count

        # Fetch memories if mix_ratio > 0
        memory_assets: list[dict] = []
        if memory_count > 0:
            memory_assets = await self._hub.get_memory_assets(
                max_years=self._memory_years
            )
            random.shuffle(memory_assets)
            memory_assets = memory_assets[:memory_count]

        # Fetch recent photos to fill remaining slots
        # days=0 means unlimited (fetch all time)
        recent_count = fetch_count - len(memory_assets)
        recent_assets: list[dict] = []
        if recent_count > 0:
            days_param = self._days if self._days > 0 else 36500  # 0 = ~100 years
            recent_assets = await self._hub.search_random_recent(
                days=days_param,
                count=recent_count,
                favorites_filter=self._favorites_filter,
            )

        # Combine and shuffle
        assets = memory_assets + recent_assets
        random.shuffle(assets)

        if not assets:
            _LOGGER.warning("No assets found (mix_ratio=%d, days=%d)", self._mix_ratio, self._days)
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
                    return asset
                return None

        # Run enrichment concurrently with limited parallelism
        enriched = await asyncio.gather(*[enrich_asset(a) for a in assets])
        enriched_assets = [a for a in enriched if a is not None]
        random.shuffle(enriched_assets)
        # Add to existing pool instead of replacing
        self._asset_pool.extend(enriched_assets)
        # Cap pool size
        if len(self._asset_pool) > MAX_POOL_SIZE:
            self._asset_pool = self._asset_pool[:MAX_POOL_SIZE]

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

        buffer = io.BytesIO()
        result.save(buffer, format="JPEG", quality=85, optimize=True)
        return buffer.getvalue()

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

        return img_scaled.crop((left, top, right, bottom))

    def _resize_and_encode(
        self, img: Image.Image, target_w: int, target_h: int
    ) -> bytes:
        """Resize a single image to target dimensions and encode as JPEG."""
        resized = self._resize_and_center_crop(img, target_w, target_h)
        buffer = io.BytesIO()
        resized.save(buffer, format="JPEG", quality=85, optimize=True)
        return buffer.getvalue()


def is_portrait(asset: dict[str, Any]) -> bool:
    """Check if an asset is portrait orientation after EXIF rotation."""
    width = asset.get("originalWidth", 0)
    height = asset.get("originalHeight", 0)
    exif = asset.get("exifInfo", {})
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

    # Get configuration options
    days = config_entry.options.get(CONF_DAYS, DEFAULT_DAYS)
    dual_portrait = config_entry.options.get(CONF_DUAL_PORTRAIT, DEFAULT_DUAL_PORTRAIT)
    refresh_interval = config_entry.options.get(
        CONF_REFRESH_INTERVAL, DEFAULT_REFRESH_INTERVAL
    )
    memory_years = config_entry.options.get(CONF_MEMORY_YEARS, DEFAULT_MEMORY_YEARS)
    mix_ratio = config_entry.options.get(CONF_MIX_RATIO, DEFAULT_MIX_RATIO)
    background_path = config_entry.options.get(CONF_BACKGROUND_PATH, DEFAULT_BACKGROUND_PATH)
    favorites_filter = config_entry.options.get(CONF_FAVORITES_FILTER, DEFAULT_FAVORITES_FILTER)
    write_files = config_entry.options.get(CONF_WRITE_FILES, DEFAULT_WRITE_FILES)

    # Parse resolutions (with legacy migration support)
    resolutions_str = config_entry.options.get(CONF_RESOLUTIONS)
    if not resolutions_str:
        # Legacy: use old width/height
        width = config_entry.options.get(CONF_TARGET_WIDTH, 1920)
        height = config_entry.options.get(CONF_TARGET_HEIGHT, 1080)
        resolutions_str = f"{width}x{height}"

    resolutions = parse_resolutions(resolutions_str)
    if not resolutions:
        resolutions = [(1920, 1080)]  # Fallback if parsing fails
    _LOGGER.info(
        "Setting up slideshow: resolutions=%s, days=%d, mix_ratio=%d%%, memory_years=%d, favorites=%s",
        resolutions, days, mix_ratio, memory_years, favorites_filter
    )

    # Create shared manager
    manager = SlideshowManager(
        hub=hub,
        days=days,
        dual_portrait=dual_portrait,
        memory_years=memory_years,
        mix_ratio=mix_ratio,
        favorites_filter=favorites_filter,
    )

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
