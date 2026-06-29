"""Shared per-pair state tracker for value_crossing (Bronze ``common-modules``).

One ``PairCoordinator`` per config entry owns the *single* source-state
subscription and the difference/crossed computation. All four entities (3 sensors
+ 1 binary sensor) register a listener instead of each subscribing on their own.
The subscription is started lazily with the first listener and stopped with the
last, so it is tied to entity lifecycle and never leaks.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from functools import partial

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util

from .const import (
    CONF_BAND,
    CONF_DAILY_HISTORY,
    CONF_MODEL,
    CONF_NOTIFY,
    CONF_NOTIFY_TARGETS,
    CONF_PAIR_NAME,
    CONF_SENSOR_A,
    CONF_SENSOR_B,
    CONF_WINDOW,
    DEFAULT_WINDOW,
    DIR_FROM_ABOVE,
    DIR_FROM_BELOW,
    DIR_NONE,
    EVENT_CROSSED,
    INHERITABLE_DEVICE_CLASSES,
    NOTIFY_BOTH,
    NOTIFY_NO,
    PROFILE_HOURS,
    STATUS_INSUFFICIENT_DATA,
    STATUS_OK,
    STATUS_WITHIN_BAND,
)
from .estimation import (
    Estimate,
    RollingBuffer,
    bin_hourly_means,
    effective_model,
    estimate_crossing,
    merge_difference_series,
    profile_range,
    project_daily_crossing,
    project_value,
)
from .kinds import resolve

_LOGGER = logging.getLogger(__name__)


def _as_float(state) -> float | None:
    """Numeric value of a state, or None if missing/unavailable/non-numeric."""
    if state is None or state.state in (None, "unknown", "unavailable"):
        return None
    try:
        return float(state.state)
    except (TypeError, ValueError):
        return None


def _history_points(states) -> list[tuple[float, float]]:
    """Recorder states for one sensor -> ``(epoch, value)``, skipping non-numeric."""
    points: list[tuple[float, float]] = []
    for state in states or []:
        value = _as_float(state)
        if value is None:
            continue
        stamp = getattr(state, "last_changed", None) or getattr(
            state, "last_updated", None
        )
        if stamp is None:
            continue
        points.append((stamp.timestamp(), value))
    return points


Profile = list[float | None]


def _normalize_profile(profile: Profile) -> Profile | None:
    """Treat an all-empty hourly profile as no profile at all."""
    return profile if any(v is not None for v in profile) else None


def _stat_epoch(value) -> float | None:
    """Epoch seconds from a statistics row ``start`` (datetime or float)."""
    if isinstance(value, datetime):
        return value.timestamp()
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _mean_profile_from_stats(rows, now: datetime) -> Profile | None:
    """Hourly-mean profile binned by hour-of-day from statistics rows, or None."""
    points = [
        (_stat_epoch(r.get("start")), r.get("mean"))
        for r in rows or []
        if r.get("mean") is not None and _stat_epoch(r.get("start")) is not None
    ]
    if not points:
        return None
    return _normalize_profile(bin_hourly_means(points, now))


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
        self._daily_history: bool = bool(entry.data.get(CONF_DAILY_HISTORY, False))
        self._notify: str = entry.data.get(CONF_NOTIFY, NOTIFY_NO)
        self._notify_targets: list[str] = list(
            entry.data.get(CONF_NOTIFY_TARGETS, [])
        )
        self._buffer = RollingBuffer(self.window)
        self._a_buffer = RollingBuffer(self.window)
        self._estimate = Estimate(None, None, STATUS_INSUFFICIENT_DATA)
        self._listeners: list[Callable[[], None]] = []
        self._unsub: Callable[[], None] | None = None
        # Cached daily-pattern hourly-mean profiles (LOGIC-05); None until primed.
        self._profile_a: Profile | None = None
        self._profile_b: Profile | None = None
        # Crossing-transition tracking (LOGIC-04): the previous difference and the
        # direction of the last observed crossing (for the direction sensor).
        self._prev_diff: float | None = None
        self._last_cross_direction: str | None = None

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

    @property
    def predicted_crossover_value(self) -> float | None:
        """Value sensor A is projected to hold when the pair crosses.

        Linear projection of sensor A's recent trend to the predicted crossing
        time; at the crossing A and B are within the band, so this is the common
        value where they meet. ``None`` when no crossing is predicted, and the
        live A value when already within the band.
        """
        est = self._estimate
        # The daily-pattern path supplies the meeting value directly (a far-future
        # linear projection of A would be meaningless on that horizon).
        if est.crossover_value is not None:
            return est.crossover_value
        if est.status == STATUS_WITHIN_BAND:
            return _as_float(self.hass.states.get(self.sensor_a))
        if est.seconds_until is None or est.seconds_until <= 0:
            return None
        samples = self._a_buffer.samples()
        if not samples:
            return None
        t0 = samples[0][0]
        rebased = [(t - t0, v) for t, v in samples]
        return project_value(rebased, est.seconds_until)

    # --- crossing direction (LOGIC-04) ------------------------------------

    def _classify_direction(self, diff: float | None) -> str | None:
        """Side an out-of-band difference would approach the band from.

        ``from_above`` when A is above B (``diff > band``), ``from_below`` when A is
        below B (``diff < -band``); ``None`` when within the band or unknown.
        """
        if diff is None:
            return None
        if diff > self.band:
            return DIR_FROM_ABOVE
        if diff < -self.band:
            return DIR_FROM_BELOW
        return None

    def crossing_direction(self) -> str | None:
        """Direction for the sensor: predicted while pending, crossed-from in band.

        ``None`` (entity ``unknown``) when a source is unusable; ``none`` when no
        crossing is predicted; otherwise the approach direction while outside the
        band, or the direction the pair last crossed from while within it.
        """
        diff = self.difference()
        if diff is None:
            return None
        if abs(diff) <= self.band:
            return self._last_cross_direction or DIR_NONE
        if self._estimate.status == STATUS_OK:
            return self._classify_direction(diff) or DIR_NONE
        return DIR_NONE

    # --- daily-pattern prediction (LOGIC-05) ------------------------------

    def _compute_estimate(self, now: datetime) -> Estimate:
        """Build the estimate: daily-pattern when enabled+usable, else base model."""
        if self._daily_history:
            daily = self._daily_estimate(now)
            if daily is not None:
                return daily
        return estimate_crossing(self._buffer.samples(), self.band, self.model_id, now)

    def _daily_estimate(self, now: datetime) -> Estimate | None:
        """Project the higher-variance sensor along its daily profile.

        Returns ``None`` to signal "fall back to the base model" when no profile is
        usable, a source is unavailable, or the profile cannot be anchored at now.
        """
        a = _as_float(self.hass.states.get(self.sensor_a))
        b = _as_float(self.hass.states.get(self.sensor_b))
        if a is None or b is None:
            return None

        # Candidate drivers: (profile, held value, anchor sign, daily range).
        # sign maps the recent mean difference onto the driver: A ~= B + mean(A-B),
        # B ~= A - mean(A-B), so the held sensor + sign*mean_diff is the anchor.
        candidates = []
        if self._profile_a is not None:
            ra = profile_range(self._profile_a)
            candidates.append((self._profile_a, b, 1.0, ra))
        if self._profile_b is not None:
            rb = profile_range(self._profile_b)
            candidates.append((self._profile_b, a, -1.0, rb))
        if not candidates:
            return None
        profile, held, sign, _range = max(candidates, key=lambda c: c[3])

        # Robust anchor (#1): the driver's recent mean, via the difference buffer.
        samples = self._buffer.samples()
        mean_diff = sum(v for _, v in samples) / len(samples) if samples else (a - b)
        anchor = held + sign * mean_diff

        seconds, status = project_daily_crossing(profile, anchor, now, held, self.band)
        if status == STATUS_INSUFFICIENT_DATA:
            return None  # profile not anchorable at now -> base model
        if status == STATUS_WITHIN_BAND:
            eta: datetime | None = now
        elif seconds is not None and seconds > 0:
            eta = now + timedelta(seconds=seconds)
        else:
            eta = None
        # At the crossing the driver enters [held +/- band], so they meet near held.
        value = held if status in (STATUS_OK, STATUS_WITHIN_BAND) else None
        return Estimate(
            seconds_until=seconds, eta=eta, status=status, crossover_value=value
        )

    async def async_prime_daily_profile(self) -> None:
        """Fetch and cache both sensors' 24h hourly profiles when the flag is on.

        Prefers HA long-term statistics (hourly mean); falls back to binning raw
        recorder history for any sensor without statistics. Best effort: guards on
        recorder availability and never raises out of setup.
        """
        if not self._daily_history:
            return
        if "recorder" not in self.hass.config.components:
            return
        try:
            from homeassistant.components.recorder import get_instance, history
            from homeassistant.components.recorder.statistics import (
                statistics_during_period,
            )

            now = dt_util.utcnow()
            start = now - timedelta(hours=PROFILE_HOURS)
            instance = get_instance(self.hass)
            stats = await instance.async_add_executor_job(
                partial(
                    statistics_during_period,
                    self.hass,
                    start,
                    now,
                    {self.sensor_a, self.sensor_b},
                    "hour",
                    None,
                    {"mean"},
                )
            )
            self._profile_a = _mean_profile_from_stats(stats.get(self.sensor_a), now)
            self._profile_b = _mean_profile_from_stats(stats.get(self.sensor_b), now)

            # Fall back to raw history for any sensor lacking statistics.
            missing = [
                s
                for s, p in (
                    (self.sensor_a, self._profile_a),
                    (self.sensor_b, self._profile_b),
                )
                if p is None
            ]
            if missing:
                states = await instance.async_add_executor_job(
                    partial(
                        history.get_significant_states,
                        self.hass,
                        start,
                        now,
                        missing,
                        include_start_time_state=True,
                        significant_changes_only=False,
                        no_attributes=True,
                    )
                )
                if self._profile_a is None:
                    pts_a = _history_points(states.get(self.sensor_a))
                    self._profile_a = _normalize_profile(bin_hourly_means(pts_a, now))
                if self._profile_b is None:
                    pts_b = _history_points(states.get(self.sensor_b))
                    self._profile_b = _normalize_profile(bin_hourly_means(pts_b, now))

            self._estimate = self._compute_estimate(now)
        except Exception:  # noqa: BLE001 - daily profile is best-effort, never fatal
            _LOGGER.debug("Daily profile prime failed for %s", self.name, exc_info=True)

    async def async_prime_from_history(self) -> None:
        """Seed the buffer from recorder history so the estimate is ready early.

        Without this the in-memory buffer is empty after every restart and the
        estimate reports ``insufficient_data`` until enough live updates arrive.
        Degrades silently to the cold-start path if the recorder is unavailable
        or has too little history; never raises out of entry setup.
        """
        # Baseline for crossing detection (LOGIC-04): records the at-setup
        # difference so the first live transition can be classified. No event or
        # notification is emitted here.
        self._prev_diff = self.difference()
        if "recorder" not in self.hass.config.components:
            return
        try:
            from homeassistant.components.recorder import get_instance, history

            now = dt_util.utcnow()
            start = now - timedelta(seconds=self.window)
            states = await get_instance(self.hass).async_add_executor_job(
                partial(
                    history.get_significant_states,
                    self.hass,
                    start,
                    None,
                    [self.sensor_a, self.sensor_b],
                    include_start_time_state=True,
                    significant_changes_only=False,
                    no_attributes=True,
                )
            )
            a_points = _history_points(states.get(self.sensor_a))
            b_points = _history_points(states.get(self.sensor_b))
            for t, diff in merge_difference_series(a_points, b_points):
                self._buffer.add(t, diff)
            for t, value in a_points:
                self._a_buffer.add(t, value)
            self._estimate = estimate_crossing(
                self._buffer.samples(), self.band, self.model_id, now
            )
        except Exception:  # noqa: BLE001 - backfill is best-effort, never fatal
            _LOGGER.debug("History backfill failed for %s", self.name, exc_info=True)

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
        a = _as_float(self.hass.states.get(self.sensor_a))
        if a is not None:
            self._a_buffer.add(now.timestamp(), a)
        self._estimate = self._compute_estimate(now)
        self._maybe_announce_crossing(diff)
        self._prev_diff = diff
        for update in list(self._listeners):
            update()

    def _maybe_announce_crossing(self, diff: float | None) -> None:
        """Fire the event (always) + notification (if enabled) on an into-band cross.

        A crossing is an out-of-band -> in-band transition with a known prior
        difference, so the approach direction is classifiable. Fires once per
        crossing; nothing fires while staying in the band or when the prior
        difference is unknown.
        """
        prev = self._prev_diff
        if prev is None or abs(prev) <= self.band:
            return  # no known out-of-band prior -> not a fresh crossing
        if diff is None or abs(diff) > self.band:
            return  # not inside the band now
        direction = self._classify_direction(prev)
        if direction is None:
            return
        self._last_cross_direction = direction
        crossover_value = self.predicted_crossover_value
        # Slim payload (LOGIC-07): identity + direction + cross-value only. The
        # direction stays the enum token for automation matching / ENUM sensor
        # parity; redundant measurement fields (raw values, diff, band) dropped.
        payload = {
            "entry_id": self.entry.entry_id,
            "name": self.name,
            "sensor_a": self.sensor_a,
            "sensor_b": self.sensor_b,
            "crossover_value": crossover_value,
            "direction": direction,
        }
        self.hass.bus.async_fire(EVENT_CROSSED, payload)
        if self._notify == NOTIFY_NO or self._notify not in (NOTIFY_BOTH, direction):
            return
        title = f"Value Crossing: {self.name}"
        message = self._crossing_message(direction, crossover_value)
        # Dashboard record (kept always when the gate passes).
        persistent_notification.async_create(
            self.hass,
            message,
            title=title,
            notification_id=f"value_crossing_{self.entry.entry_id}",
        )
        # Mobile/native push (LOGIC-06): deliver to any configured notify.*
        # targets in addition to the persistent notification. Best-effort.
        if self._notify_targets:
            self.hass.async_create_task(
                self._async_push(title, message), eager_start=True
            )

    def _crossing_message(self, direction: str, crossover_value: float | None) -> str:
        """Slim human-readable crossing message: name, direction, cross-value."""
        direction_words = direction.replace("_", " ")
        text = f"{self.name}: crossed {direction_words}"
        if crossover_value is not None:
            unit = self.source_unit or ""
            text += f" at {crossover_value:.3g} {unit}".rstrip()
        return text

    async def _async_push(self, title: str, message: str) -> None:
        """Push the crossing message to the configured notify.* entities."""
        try:
            await self.hass.services.async_call(
                "notify",
                "send_message",
                {
                    "entity_id": self._notify_targets,
                    "title": title,
                    "message": message,
                },
                blocking=True,
            )
        except Exception as err:  # noqa: BLE001 - delivery is best-effort
            _LOGGER.warning(
                "value_crossing: notify push failed for %s -> %s: %s",
                self.name,
                self._notify_targets,
                err,
            )
