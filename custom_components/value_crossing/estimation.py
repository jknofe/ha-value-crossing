"""Crossing-time estimation, addressed by model id.

A *model* maps ``(t_seconds, difference)`` samples + a band half-width to
``(seconds_until, status)``: the seconds from the last sample until the
difference first enters ``[-band, +band]`` (or ``None`` + a status explaining
why no crossing is predicted).

Models implemented here:
- ``linear``      least-squares slope, extrapolated to the near band edge.
- ``exponential`` Newton's-law-of-cooling relaxation toward an asymptote, fit
  with Jacquelin's regression-of-the-integral method (numpy linear algebra only,
  no scipy / no iterative solver). Falls back to ``linear`` if ill-conditioned.

``power`` (LOGIC-02) stays a reserved id that falls back to ``linear`` until
registered via :func:`register_model`.

Free of any ``homeassistant`` import so it is unit-testable in isolation (uses
numpy, which ships with Home Assistant Core). ``sensor``/``coordinator`` are the
only HA-aware glue.
"""

from __future__ import annotations

import logging
import math
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np

from .const import (
    DAILY_HORIZON_HOURS,
    DAILY_STEP_SECONDS,
    DEFAULT_WINDOW,
    MAX_SAMPLES,
    MIN_SAMPLES_EXPONENTIAL,
    MIN_SAMPLES_LINEAR,
    MODEL_AUTO,
    MODEL_EXPONENTIAL,
    MODEL_LINEAR,
    PROFILE_HOURS,
    STATUS_ASYMPTOTE_OUTSIDE_BAND,
    STATUS_DIVERGING,
    STATUS_FIT_FAILED,
    STATUS_INSUFFICIENT_DATA,
    STATUS_NO_CROSSING_HORIZON,
    STATUS_OK,
    STATUS_WITHIN_BAND,
)
from .kinds import PhysicalKind

_LOGGER = logging.getLogger(__name__)

Sample = tuple[float, float]
Model = Callable[[Sequence[Sample], float], "tuple[float | None, str]"]


@dataclass(frozen=True)
class Estimate:
    """Result of a crossing estimate for one pair."""

    seconds_until: float | None
    eta: datetime | None
    status: str
    # Predicted meeting value, set only by the daily-pattern path (LOGIC-05);
    # left None by the difference models, where the coordinator derives it from a
    # live projection of sensor A instead.
    crossover_value: float | None = None


class RollingBuffer:
    """In-memory ``(t, value)`` buffer trimmed to a time window and a sample cap.

    Empty after restart; refills as source states change.
    """

    def __init__(self, window: float, max_samples: int = MAX_SAMPLES) -> None:
        """Keep at most ``window`` seconds of history (and ``max_samples``)."""
        self.window = window
        self.max_samples = max_samples
        self._samples: deque[Sample] = deque()

    def add(self, t: float, value: float) -> None:
        """Append a sample and drop anything older than the window/cap."""
        self._samples.append((t, value))
        cutoff = t - self.window
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()
        while len(self._samples) > self.max_samples:
            self._samples.popleft()

    def samples(self) -> list[Sample]:
        """Current samples, oldest first."""
        return list(self._samples)


def merge_difference_series(
    a_points: Sequence[Sample], b_points: Sequence[Sample]
) -> list[Sample]:
    """Forward-fill union merge of two ``(t, value)`` series into ``(t, a - b)``.

    At every timestamp where either series has a point, emit a difference sample
    from the most recent value of each side. Nothing is emitted until both sides
    have a known value, so the result mirrors what the live per-change path would
    have accumulated. Output is oldest-first, one sample per distinct timestamp.
    """
    events: dict[float, list[tuple[str, float]]] = {}
    for t, v in a_points:
        events.setdefault(t, []).append(("a", v))
    for t, v in b_points:
        events.setdefault(t, []).append(("b", v))

    last_a: float | None = None
    last_b: float | None = None
    out: list[Sample] = []
    for t in sorted(events):
        for side, v in events[t]:
            if side == "a":
                last_a = v
            else:
                last_b = v
        if last_a is not None and last_b is not None:
            out.append((t, last_a - last_b))
    return out


# --- daily-pattern projection (LOGIC-05) ------------------------------------
#
# A *profile* is a 24-slot list of hourly means indexed by hour-of-day (UTC),
# ``None`` for hours with no data. The hour-of-day of an epoch timestamp is
# ``(t % 86400) / 3600`` so these helpers need no datetime/timezone handling and
# stay pure. ``now`` may be a ``datetime`` or a raw epoch float.

_SECONDS_PER_DAY = 86400.0


def _epoch(now: datetime | float) -> float:
    """Epoch seconds from a datetime or a raw float."""
    return now.timestamp() if isinstance(now, datetime) else float(now)


def bin_hourly_means(
    samples: Sequence[Sample], now: datetime | float
) -> list[float | None]:
    """Bin ``(epoch, value)`` samples of the last 24h into hourly means.

    Returns a 24-slot list indexed by hour-of-day (UTC); a slot is ``None`` when
    no sample fell in that hour. Samples older than ``PROFILE_HOURS`` hours before
    ``now`` are ignored.
    """
    cutoff = _epoch(now) - PROFILE_HOURS * 3600
    sums = [0.0] * PROFILE_HOURS
    counts = [0] * PROFILE_HOURS
    for t, v in samples:
        if t < cutoff:
            continue
        hour = int((t % _SECONDS_PER_DAY) // 3600) % PROFILE_HOURS
        sums[hour] += v
        counts[hour] += 1
    return [sums[h] / counts[h] if counts[h] else None for h in range(PROFILE_HOURS)]


def profile_at(profile: Sequence[float | None], hour_float: float) -> float | None:
    """Linear interpolation of a profile at a fractional hour-of-day (wraps 23->0).

    Returns ``None`` only when both surrounding hourly slots are empty; when just
    one is known that value is used (a gap-tolerant nearest fallback).
    """
    base = math.floor(hour_float)
    frac = hour_float - base
    lo = profile[base % PROFILE_HOURS]
    hi = profile[(base + 1) % PROFILE_HOURS]
    if lo is None and hi is None:
        return None
    if lo is None:
        return hi
    if hi is None:
        return lo
    return lo + (hi - lo) * frac


def profile_range(profile: Sequence[float | None]) -> float:
    """Peak-to-peak span of the known slots (0.0 when none are known).

    Used to pick the driver: the sensor with the larger daily swing is projected.
    """
    known = [v for v in profile if v is not None]
    if not known:
        return 0.0
    return max(known) - min(known)


def project_daily_crossing(
    profile: Sequence[float | None],
    anchor: float,
    now: datetime | float,
    held: float,
    band: float,
) -> tuple[float | None, str]:
    """Project the shifted daily curve forward to the first band entry.

    The profile is shifted additively so it passes through ``anchor`` at ``now``
    (``shift = anchor - profile_at(now)``), then stepped forward up to a 24h
    horizon. Returns ``(seconds_until, status)`` for the first time the shifted
    curve enters ``[held - band, held + band]`` (interpolated to the band edge),
    ``(0.0, within_band)`` if it starts inside, ``(None, no_crossing_horizon)`` if
    it never enters within 24h, and ``(None, insufficient_data)`` when the profile
    cannot be anchored at ``now``.
    """
    now_epoch = _epoch(now)
    base_now = profile_at(profile, (now_epoch % _SECONDS_PER_DAY) / 3600)
    if base_now is None:
        return None, STATUS_INSUFFICIENT_DATA
    shift = anchor - base_now

    lo_edge, hi_edge = held - band, held + band
    if lo_edge <= anchor <= hi_edge:
        return 0.0, STATUS_WITHIN_BAND

    v_prev, s_prev = anchor, 0.0
    horizon = DAILY_HORIZON_HOURS * 3600
    s = DAILY_STEP_SECONDS
    while s <= horizon:
        hour = ((now_epoch + s) % _SECONDS_PER_DAY) / 3600
        slot = profile_at(profile, hour)
        if slot is None:
            s += DAILY_STEP_SECONDS
            continue
        v = slot + shift
        # Near edge relative to where the curve currently sits (outside the band).
        near = hi_edge if v_prev > hi_edge else lo_edge
        if (v_prev - near) * (v - near) <= 0:  # curve reached/crossed the near edge
            frac = (near - v_prev) / (v - v_prev) if v != v_prev else 0.0
            return s_prev + frac * (s - s_prev), STATUS_OK
        v_prev, s_prev = v, s
        s += DAILY_STEP_SECONDS
    return None, STATUS_NO_CROSSING_HORIZON


def _near_edge(v_now: float, band: float) -> float:
    """The band boundary the difference would reach first from outside."""
    return band if v_now > 0 else -band


def _linear(samples: Sequence[Sample], band: float) -> tuple[float | None, str]:
    """Least-squares line fit, extrapolated to the near band edge."""
    n = len(samples)
    if n < MIN_SAMPLES_LINEAR:
        return None, STATUS_INSUFFICIENT_DATA
    sx = sum(t for t, _ in samples)
    sy = sum(v for _, v in samples)
    sxx = sum(t * t for t, _ in samples)
    sxy = sum(t * v for t, v in samples)
    denom = n * sxx - sx * sx
    if denom == 0:
        return None, STATUS_FIT_FAILED
    slope = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n
    t_last = samples[-1][0]
    v_now = slope * t_last + intercept
    if abs(v_now) <= band:
        return 0.0, STATUS_WITHIN_BAND
    if slope == 0:
        return None, STATUS_DIVERGING
    seconds = (_near_edge(v_now, band) - v_now) / slope
    if seconds <= 0:
        return None, STATUS_DIVERGING
    return seconds, STATUS_OK


def project_value(samples: Sequence[Sample], seconds: float) -> float | None:
    """Linear least-squares projection of a value series ``seconds`` ahead.

    Used to estimate the absolute value a sensor holds at the predicted crossing
    time (the "crossover value"). Returns ``None`` with fewer than two samples or
    a singular (vertical-time) fit.
    """
    n = len(samples)
    if n < MIN_SAMPLES_LINEAR:
        return None
    sx = sum(t for t, _ in samples)
    sy = sum(v for _, v in samples)
    sxx = sum(t * t for t, _ in samples)
    sxy = sum(t * v for t, v in samples)
    denom = n * sxx - sx * sx
    if denom == 0:
        return None
    slope = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n
    return slope * (samples[-1][0] + seconds) + intercept


def fit_exponential(samples: Sequence[Sample]) -> tuple[float, float, float] | None:
    """Fit ``diff(t) = d_inf + amp * exp(-(t - t0) / tau)`` (tau > 0).

    Jacquelin's method: a linear regression on the cumulative integral of the
    samples recovers the rate in closed form, then a second linear least squares
    recovers the offset and amplitude. Returns ``(d_inf, amp, tau)`` or ``None``
    when the system is singular or the signal is not a decaying relaxation.
    """
    n = len(samples)
    if n < MIN_SAMPLES_EXPONENTIAL:
        return None
    t0 = samples[0][0]
    xs = [t - t0 for t, _ in samples]
    ys = [v for _, v in samples]

    # Cumulative trapezoidal integral S_k of y over x.
    s = [0.0] * n
    for k in range(1, n):
        s[k] = s[k - 1] + 0.5 * (ys[k] + ys[k - 1]) * (xs[k] - xs[k - 1])

    x1, y1 = xs[0], ys[0]
    sxx = sum((xs[k] - x1) ** 2 for k in range(n))
    sxs = sum((xs[k] - x1) * s[k] for k in range(n))
    sss = sum(s[k] ** 2 for k in range(n))
    sxy = sum((xs[k] - x1) * (ys[k] - y1) for k in range(n))
    ssy = sum(s[k] * (ys[k] - y1) for k in range(n))

    m1 = np.array([[sxx, sxs], [sxs, sss]])
    if abs(np.linalg.det(m1)) < 1e-12:
        return None
    _, c = np.linalg.solve(m1, np.array([sxy, ssy]))
    if c >= 0:  # not a relaxation toward an asymptote
        return None
    tau = -1.0 / c

    # With the rate c known, recover d_inf (a) and amp (b): y = a + b*exp(c*x).
    theta = np.exp(c * np.array(xs))
    st = float(theta.sum())
    stt = float((theta * theta).sum())
    m2 = np.array([[float(n), st], [st, stt]])
    if abs(np.linalg.det(m2)) < 1e-12:
        return None
    sty = float((theta * np.array(ys)).sum())
    a, b = np.linalg.solve(m2, np.array([sum(ys), sty]))
    return float(a), float(b), float(tau)


def _exponential(samples: Sequence[Sample], band: float) -> tuple[float | None, str]:
    """Exponential-relaxation model; falls back to linear if the fit fails."""
    if len(samples) < MIN_SAMPLES_EXPONENTIAL:
        return None, STATUS_INSUFFICIENT_DATA
    fit = fit_exponential(samples)
    if fit is None:
        return _linear(samples, band)  # graceful fallback, linear's status surfaced
    d_inf, amp, tau = fit
    t0 = samples[0][0]
    v_now = d_inf + amp * math.exp(-(samples[-1][0] - t0) / tau)
    if abs(v_now) <= band:
        return 0.0, STATUS_WITHIN_BAND
    denom = v_now - d_inf
    if denom == 0:
        return None, STATUS_ASYMPTOTE_OUTSIDE_BAND
    # diff(t_last + s) = d_inf + denom * exp(-s/tau); solve for the near edge.
    ratio = (_near_edge(v_now, band) - d_inf) / denom
    if 0 < ratio < 1:
        return -tau * math.log(ratio), STATUS_OK
    if ratio <= 0:
        # Asymptote sits outside the band on the same side: never enters.
        return None, STATUS_ASYMPTOTE_OUTSIDE_BAND
    return None, STATUS_DIVERGING  # ratio >= 1: moving away from the band


_MODELS: dict[str, Model] = {
    MODEL_LINEAR: _linear,
    MODEL_EXPONENTIAL: _exponential,
}

_warned: set[str] = set()


def register_model(model_id: str, model: Model) -> None:
    """Register (or override) a model implementation. Used by LOGIC-02."""
    _MODELS[model_id] = model


def get_model(model_id: str) -> Model:
    """Return the model for ``model_id``, falling back to ``linear``."""
    model = _MODELS.get(model_id)
    if model is not None:
        return model
    if model_id not in _warned:
        _LOGGER.warning(
            "Estimation model %r is not implemented yet; falling back to %r",
            model_id,
            MODEL_LINEAR,
        )
        _warned.add(model_id)
    return _MODELS[MODEL_LINEAR]


def effective_model(override: str | None, kind: PhysicalKind) -> str:
    """Resolve the model id: explicit override wins, else the kind default."""
    if override and override != MODEL_AUTO:
        return override
    return kind.default_model


def estimate_crossing(
    samples: Sequence[Sample], band: float, model: str, now: datetime
) -> Estimate:
    """Estimate the crossing for one pair, with an absolute ETA."""
    t0 = samples[0][0] if samples else 0.0
    rebased = [(t - t0, v) for t, v in samples]  # numerically stable fit
    seconds, status = get_model(model)(rebased, band)
    if status == STATUS_WITHIN_BAND:
        eta: datetime | None = now
    elif seconds is not None and seconds > 0:
        eta = now + timedelta(seconds=seconds)
    else:
        eta = None
    return Estimate(seconds_until=seconds, eta=eta, status=status)


def new_buffer(window: float = DEFAULT_WINDOW) -> RollingBuffer:
    """Convenience factory for a window-sized rolling buffer."""
    return RollingBuffer(window)
