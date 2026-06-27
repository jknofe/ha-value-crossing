"""Shared per-pair state tracker for value_crossing (Bronze ``common-modules``).

One ``PairCoordinator`` per config entry owns the *single* source-state
subscription and the difference/crossed computation. All four entities (3 sensors
+ 1 binary sensor) register a listener instead of each subscribing on their own.
The subscription is started lazily with the first listener and stopped with the
last, so it is tied to entity lifecycle and never leaks.
"""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util

from .const import (
    CONF_BAND,
    CONF_MODEL,
    CONF_PAIR_NAME,
    CONF_SENSOR_A,
    CONF_SENSOR_B,
    CONF_WINDOW,
    DEFAULT_WINDOW,
    INHERITABLE_DEVICE_CLASSES,
    STATUS_INSUFFICIENT_DATA,
)
from .estimation import (
    Estimate,
    RollingBuffer,
    effective_model,
    estimate_crossing,
)
from .kinds import resolve


def _as_float(state) -> float | None:
    """Numeric value of a state, or None if missing/unavailable/non-numeric."""
    if state is None or state.state in (None, "unknown", "unavailable"):
        return None
    try:
        return float(state.state)
    except (TypeError, ValueError):
        return None


class PairCoordinator:
    """Tracks two source sensors and derives the pair's difference."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Read the pair config off the entry."""
        self.hass = hass
        self.entry = entry
        self.name: str = entry.data[CONF_PAIR_NAME]
        self.sensor_a: str = entry.data[CONF_SENSOR_A]
        self.sensor_b: str = entry.data[CONF_SENSOR_B]
        self.band: float = float(entry.data[CONF_BAND])
        self.window: float = float(entry.data.get(CONF_WINDOW, DEFAULT_WINDOW))
        self._model_override: str | None = entry.data.get(CONF_MODEL)
        self._buffer = RollingBuffer(self.window)
        self._estimate = Estimate(None, None, STATUS_INSUFFICIENT_DATA)
        self._listeners: list[Callable[[], None]] = []
        self._unsub: Callable[[], None] | None = None

    # --- derived values ---------------------------------------------------

    def difference(self) -> float | None:
        """Signed ``A - B``, or None if either source is unusable."""
        a = _as_float(self.hass.states.get(self.sensor_a))
        b = _as_float(self.hass.states.get(self.sensor_b))
        if a is None or b is None:
            return None
        return a - b

    def crossed(self) -> bool | None:
        """True while ``|A - B| <= band``; None if the difference is unknown."""
        diff = self.difference()
        if diff is None:
            return None
        return abs(diff) <= self.band

    @property
    def source_unit(self) -> str | None:
        """Unit of measurement inherited from sensor A's current state."""
        state = self.hass.states.get(self.sensor_a)
        return state.attributes.get("unit_of_measurement") if state else None

    @property
    def source_device_class(self) -> str | None:
        """Sensor A's device_class, but only when safe to inherit onto a diff."""
        state = self.hass.states.get(self.sensor_a)
        dc = state.attributes.get("device_class") if state else None
        return dc if dc in INHERITABLE_DEVICE_CLASSES else None

    # --- estimation -------------------------------------------------------

    @property
    def model_id(self) -> str:
        """Effective estimation model: per-pair override, else the kind default."""
        kind = resolve(self.source_unit, self.source_device_class)
        return effective_model(self._model_override, kind)

    @property
    def estimate(self) -> Estimate:
        """Latest crossing estimate (recomputed on every source change)."""
        return self._estimate

    # --- listener plumbing ------------------------------------------------

    @callback
    def async_add_listener(self, update: Callable[[], None]) -> Callable[[], None]:
        """Register an entity update callback; returns an unsubscribe."""
        self._listeners.append(update)
        if self._unsub is None:
            self._unsub = async_track_state_change_event(
                self.hass, [self.sensor_a, self.sensor_b], self._handle_change
            )

        @callback
        def remove() -> None:
            self._listeners.remove(update)
            if not self._listeners and self._unsub is not None:
                self._unsub()
                self._unsub = None

        return remove

    @callback
    def _handle_change(self, _event: Event[EventStateChangedData]) -> None:
        """Append the new difference, re-estimate, and notify entities."""
        now = dt_util.utcnow()
        diff = self.difference()
        if diff is not None:
            self._buffer.add(now.timestamp(), diff)
        self._estimate = estimate_crossing(
            self._buffer.samples(), self.band, self.model_id, now
        )
        for update in list(self._listeners):
            update()
