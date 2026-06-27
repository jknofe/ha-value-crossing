"""Sensor platform for value_crossing.

Three sensors per pair: the live signed difference, the wall-clock crossover
ETA, and the predicted crossover value (the value the sensors meet at). The ETA
and crossover-value sensors are fed by the estimation model and report
``unknown`` when no crossing is predicted.
"""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import ValueCrossingConfigEntry
from .const import KEY_CROSSOVER_VALUE, KEY_DIFFERENCE, KEY_ETA
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
            CrossoverValueSensor(coordinator),
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


class CrossoverValueSensor(ValueCrossingEntity, SensorEntity):
    """Predicted value the pair meets at, in the pair's shared unit (LOGIC-01)."""

    def __init__(self, coordinator) -> None:
        """Init the crossover-value sensor."""
        super().__init__(coordinator, KEY_CROSSOVER_VALUE)

    @property
    def native_value(self) -> float | None:
        """Projected crossover value, or None when no crossing is predicted."""
        return self.coordinator.predicted_crossover_value

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Inherit the shared unit from sensor A."""
        return self.coordinator.source_unit

    @property
    def device_class(self) -> SensorDeviceClass | None:
        """Inherit a safe device_class from the source where derivable."""
        dc = self.coordinator.source_device_class
        return SensorDeviceClass(dc) if dc else None

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Surface why there is (or isn't) a crossing estimate."""
        return {"status": self.coordinator.estimate.status}


class CrossoverEtaSensor(ValueCrossingEntity, SensorEntity):
    """Wall-clock ETA of the crossing, from the estimation model (LOGIC-01)."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator) -> None:
        """Init the crossover-ETA sensor."""
        super().__init__(coordinator, KEY_ETA)

    @property
    def native_value(self) -> datetime | None:
        """Predicted crossing time, or None when no crossing is predicted."""
        return self.coordinator.estimate.eta

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Surface why there is (or isn't) a crossing estimate."""
        return {"status": self.coordinator.estimate.status}
