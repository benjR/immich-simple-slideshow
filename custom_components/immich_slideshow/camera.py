"""Camera entity for Immich Slideshow Live Photos."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    CONF_REFRESH_INTERVAL,
    DEFAULT_REFRESH_INTERVAL,
    DOMAIN,
)
from .hub import ImmichHub

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Immich Slideshow camera entity from a config entry."""
    hub: ImmichHub = hass.data[DOMAIN][config_entry.entry_id]
    manager = hass.data[DOMAIN].get(f"{config_entry.entry_id}_manager")

    if manager is None:
        _LOGGER.warning("SlideshowManager not found, camera entity not created")
        return

    options = config_entry.options
    refresh_interval = options.get(CONF_REFRESH_INTERVAL, DEFAULT_REFRESH_INTERVAL)

    entity = ImmichSlideshowCamera(
        hass=hass,
        hub=hub,
        manager=manager,
        config_entry=config_entry,
        refresh_interval=refresh_interval,
    )

    async_add_entities([entity])


class ImmichSlideshowCamera(Camera):
    """Camera entity that streams Live Photos from Immich."""

    _attr_has_entity_name = True
    _attr_supported_features = CameraEntityFeature.STREAM

    def __init__(
        self,
        hass: HomeAssistant,
        hub: ImmichHub,
        manager: Any,  # SlideshowManager
        config_entry: ConfigEntry,
        refresh_interval: int,
    ) -> None:
        """Initialize the camera entity."""
        super().__init__()
        self.hass = hass
        self._hub = hub
        self._manager = manager
        self._config_entry = config_entry
        self._refresh_interval = refresh_interval

        # Entity naming
        self._attr_name = "Live Photo"
        self._attr_unique_id = f"{config_entry.entry_id}_camera_live"

        # State tracking
        self._current_video_id: str | None = None
        self._current_video_bytes: bytes | None = None
        self._is_streaming = False
        self._unsub_timer = None

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._manager.is_available

    @property
    def is_streaming(self) -> bool:
        """Return True if the camera is streaming."""
        return self._is_streaming

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
        attrs: dict[str, Any] = {
            "has_live_photo": self._manager.has_live_photo,
        }

        if self._manager.has_live_photo:
            attrs["live_photo_video_id"] = self._manager.live_photo_video_id

        # Include current asset info
        asset_attrs = self._manager.get_asset_attrs(self._manager.asset1)
        for key, value in asset_attrs.items():
            attrs[key] = value

        return attrs

    async def async_added_to_hass(self) -> None:
        """Run when entity is added to hass."""
        await super().async_added_to_hass()

        # Preload video if current asset has Live Photo
        await self._update_video()

        # Subscribe to same refresh interval as image entity
        # Note: The manager refresh is driven by the image entity
        # We just need to update our video cache when it changes
        self._unsub_timer = async_track_time_interval(
            self.hass,
            self._async_update_video,
            timedelta(seconds=self._refresh_interval),
        )

    async def async_will_remove_from_hass(self) -> None:
        """Run when entity is removed from hass."""
        if self._unsub_timer:
            self._unsub_timer()
            self._unsub_timer = None
        await super().async_will_remove_from_hass()

    async def _async_update_video(self, _now=None) -> None:
        """Update video cache (called by timer)."""
        await self._update_video()
        self.async_write_ha_state()

    async def _update_video(self) -> None:
        """Update video cache if current asset has Live Photo."""
        video_id = self._manager.live_photo_video_id

        if video_id is None:
            # No Live Photo, clear cache
            self._current_video_id = None
            self._current_video_bytes = None
            self._is_streaming = False
            return

        if video_id == self._current_video_id and self._current_video_bytes:
            # Same video already cached
            return

        # Download new video
        _LOGGER.debug("Downloading Live Photo video: %s", video_id)
        video_bytes = await self._hub.download_video(video_id)

        if video_bytes:
            self._current_video_id = video_id
            self._current_video_bytes = video_bytes
            self._is_streaming = True
            _LOGGER.debug("Live Photo video cached: %d bytes", len(video_bytes))
        else:
            _LOGGER.warning("Failed to download Live Photo video: %s", video_id)
            self._current_video_id = None
            self._current_video_bytes = None
            self._is_streaming = False

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return a still image from the camera.

        For Live Photos, we return the still image from the manager.
        The video is available via stream_source.
        """
        # Return current image from manager
        return self._manager.generate_image(
            width or 1920,
            height or 1080,
        )

    async def stream_source(self) -> str | None:
        """Return the stream source URL.

        Returns the Immich video playback URL for the Live Photo.
        This requires authentication via API key.
        """
        video_id = self._manager.live_photo_video_id

        if video_id is None:
            return None

        # Return streaming URL with API key for authentication
        # Note: This URL requires the x-api-key header
        # For HLS streaming, we'd need a proxy or different approach
        return self._hub.get_video_stream_url(video_id)

    @property
    def frame_interval(self) -> float:
        """Return the interval between frames of the mjpeg stream."""
        # Live Photos are typically 1-3 seconds, loop continuously
        return 0.1  # 10 FPS for smooth playback
