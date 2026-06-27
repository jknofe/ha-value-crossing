"""Binary-sensor platform for value_crossing.

The ``crossed`` entity is the "detect" half: ``on`` while the two sensors are
within the band. It shares the pair coordinator (single source subscription and
difference computation) with the sensor platform.
"""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import ValueCrossingConfigEntry
from .const import KEY_CROSSED
from .entity import ValueCrossingEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ValueCrossingConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the crossed binary sensor for this pair."""
    async_add_entities([CrossedBinarySensor(entry.runtime_data)])


class CrossedBinarySensor(ValueCrossingEntity, BinarySensorEntity):
    """``on`` while ``|A - B| <= band``."""

    def __init__(self, coordinator) -> None:
        """Init the crossed binary sensor."""
        super().__init__(coordinator, KEY_CROSSED)

    @property
    def is_on(self) -> bool | None:
        """Whether the pair is currently within the band (None if unknown)."""
        return self.coordinator.crossed()
