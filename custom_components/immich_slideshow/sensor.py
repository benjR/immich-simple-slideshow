"""Diagnostic sensors for Immich Slideshow."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Entity descriptions for diagnostic sensors
SENSOR_DESCRIPTIONS = [
    SensorEntityDescription(
        key="pool_size",
        name="Pool Size",
        icon="mdi:image-multiple",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement="photos",
    ),
    SensorEntityDescription(
        key="current_source",
        name="Current Source",
        icon="mdi:image-filter-hdr",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="prefetch_status",
        name="Prefetch Status",
        icon="mdi:download",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Immich Slideshow diagnostic sensors from a config entry."""
    # Get the manager from hass.data (set by image.py)
    manager = hass.data[DOMAIN].get(f"{config_entry.entry_id}_manager")

    if not manager:
        _LOGGER.warning("Manager not found for sensor setup, will retry")
        # Manager may not be ready yet, sensors will update when it is
        manager = None

    entities = []
    for description in SENSOR_DESCRIPTIONS:
        entities.append(
            ImmichDiagnosticSensor(
                config_entry=config_entry,
                description=description,
                manager=manager,
            )
        )

    async_add_entities(entities)


class ImmichDiagnosticSensor(SensorEntity):
    """Diagnostic sensor for Immich Slideshow."""

    _attr_has_entity_name = True
    _attr_should_poll = True  # Poll to get updated values

    def __init__(
        self,
        config_entry: ConfigEntry,
        description: SensorEntityDescription,
        manager: Any,
    ) -> None:
        """Initialize the sensor."""
        self.entity_description = description
        self._config_entry = config_entry
        self._manager = manager
        self._attr_unique_id = f"{config_entry.entry_id}_{description.key}"

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device info to link to the main device."""
        return {
            "identifiers": {(DOMAIN, self._config_entry.entry_id)},
            "name": "Immich Slideshow",
            "manufacturer": "Immich",
        }

    @property
    def available(self) -> bool:
        """Return True if sensor is available."""
        # Try to get manager from hass.data if not set
        if self._manager is None and self.hass:
            self._manager = self.hass.data.get(DOMAIN, {}).get(
                f"{self._config_entry.entry_id}_manager"
            )
        return self._manager is not None

    @property
    def native_value(self) -> Any:
        """Return the sensor value."""
        if self._manager is None:
            # Try to get manager from hass.data
            if self.hass:
                self._manager = self.hass.data.get(DOMAIN, {}).get(
                    f"{self._config_entry.entry_id}_manager"
                )
            if self._manager is None:
                return None

        key = self.entity_description.key

        if key == "pool_size":
            return len(self._manager._asset_pool)
        elif key == "current_source":
            return self._manager.source
        elif key == "prefetch_status":
            if self._manager._next_img1 is not None:
                return "ready"
            elif self._manager._prefetch_task and not self._manager._prefetch_task.done():
                return "fetching"
            else:
                return "idle"
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        if self._manager is None:
            return {}

        key = self.entity_description.key
        attrs: dict[str, Any] = {}

        if key == "pool_size":
            # Add source distribution in pool
            source_counts: dict[str, int] = {}
            for asset in self._manager._asset_pool:
                source = asset.get("_source", "unknown")
                source_counts[source] = source_counts.get(source, 0) + 1
            attrs["source_distribution"] = source_counts
            attrs["max_pool_size"] = 200
            attrs["refill_threshold"] = 20

        elif key == "current_source":
            if self._manager._current_asset1:
                attrs["asset_id"] = self._manager._current_asset1.get("id")
                if self._manager.memory_year:
                    attrs["memory_year"] = self._manager.memory_year
                    attrs["years_ago"] = self._manager.years_ago

        elif key == "prefetch_status":
            attrs["is_dual_portrait"] = self._manager._next_is_dual if self._manager._next_img1 else None

        return attrs
