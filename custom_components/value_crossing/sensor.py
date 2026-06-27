"""Sensor platform for value_crossing.

Three sensors per pair: the live signed difference, plus two placeholder time
sensors (time-until-crossover, crossover ETA) that report ``unknown`` until
LOGIC-01/02 implement the estimation.
"""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import ValueCrossingConfigEntry
from .const import KEY_DIFFERENCE, KEY_ETA, KEY_TIME_UNTIL
from .entity import ValueCrossingEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ValueCrossingConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the three sensors for this pair."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            DifferenceSensor(coordinator),
            TimeUntilCrossoverSensor(coordinator),
            CrossoverEtaSensor(coordinator),
        ]
    )


class DifferenceSensor(ValueCrossingEntity, SensorEntity):
    """Live signed difference ``A - B`` in the pair's shared unit."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator) -> None:
        """Init the difference sensor."""
        super().__init__(coordinator, KEY_DIFFERENCE)

    @property
    def native_value(self) -> float | None:
        """Current difference, or None when a source is unusable."""
        return self.coordinator.difference()

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Inherit the shared unit from sensor A."""
        return self.coordinator.source_unit

    @property
    def device_class(self) -> SensorDeviceClass | None:
        """Inherit a safe device_class from the source where derivable."""
        dc = self.coordinator.source_device_class
        return SensorDeviceClass(dc) if dc else None


class TimeUntilCrossoverSensor(ValueCrossingEntity, SensorEntity):
    """Seconds until the pair crosses (placeholder until LOGIC-01)."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS

    def __init__(self, coordinator) -> None:
        """Init the time-until-crossover sensor."""
        super().__init__(coordinator, KEY_TIME_UNTIL)

    @property
    def native_value(self) -> float | None:
        """Unknown until estimation lands (LOGIC-01)."""
        return None


class CrossoverEtaSensor(ValueCrossingEntity, SensorEntity):
    """Wall-clock ETA of the crossing (placeholder until LOGIC-01)."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator) -> None:
        """Init the crossover-ETA sensor."""
        super().__init__(coordinator, KEY_ETA)

    @property
    def native_value(self) -> datetime | None:
        """Unknown until estimation lands (LOGIC-01)."""
        return None
