"""Sensor platform for value_crossing.

Three sensors per pair: the live signed difference, the time-until-crossover
(shown as ``H:MM``), and the wall-clock crossover ETA. The two time sensors are
fed by the estimation model and report ``unknown`` when no crossing is predicted.
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


def _format_hm(seconds: float | None) -> str | None:
    """Render a duration in seconds as ``H:MM`` (hours may exceed 24)."""
    if seconds is None:
        return None
    total_minutes = round(seconds / 60)
    return f"{total_minutes // 60}:{total_minutes % 60:02d}"


class TimeUntilCrossoverSensor(ValueCrossingEntity, SensorEntity):
    """Time until the pair crosses, shown as ``H:MM`` (estimation model)."""

    def __init__(self, coordinator) -> None:
        """Init the time-until-crossover sensor."""
        super().__init__(coordinator, KEY_TIME_UNTIL)

    @property
    def native_value(self) -> str | None:
        """``H:MM`` until crossing, or None when no crossing is predicted."""
        return _format_hm(self.coordinator.estimate.seconds_until)

    @property
    def extra_state_attributes(self) -> dict[str, str | float]:
        """Surface the estimate status and the raw seconds for automations."""
        estimate = self.coordinator.estimate
        attrs: dict[str, str | float] = {"status": estimate.status}
        if estimate.seconds_until is not None:
            attrs["seconds"] = estimate.seconds_until
        return attrs


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
