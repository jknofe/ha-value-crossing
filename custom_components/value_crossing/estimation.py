"""Crossing-time estimation models, addressed by model id.

A *model* maps a series of ``(t_seconds, difference)`` samples plus a band
half-width to the number of seconds from the last sample until the difference
first enters ``[-band, +band]`` (or ``None`` when no future crossing is implied).

ARCH-01 ships the ``linear`` baseline only. ``exponential`` and ``power`` are
reserved ids that fall back to ``linear`` (with a one-time logged warning) until
LOGIC-01 / LOGIC-02 register real implementations via :func:`register_model`.

This module is free of any ``homeassistant`` import so it can be unit-tested in
isolation. The baseline is pure-Python; later models may use numpy (bundled with
Home Assistant Core).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence

from .const import MODEL_AUTO, MODEL_LINEAR
from .kinds import PhysicalKind

_LOGGER = logging.getLogger(__name__)

Sample = tuple[float, float]
Model = Callable[[Sequence[Sample], float], "float | None"]


def _linear(samples: Sequence[Sample], band: float) -> float | None:
    """Least-squares line fit, extrapolated to the near band edge.

    Returns seconds from the last sample until ``|difference|`` first reaches
    ``band``, ``0.0`` if already within the band, or ``None`` when the trend is
    flat, diverging, or there are too few points.
    """
    n = len(samples)
    if n < 2:
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
    t_last = samples[-1][0]
    v_now = slope * t_last + intercept
    if abs(v_now) <= band:
        return 0.0
    if slope == 0:
        return None
    target = band if v_now > 0 else -band
    seconds = (target - v_now) / slope
    if seconds <= 0:
        # Crossing lies in the past, i.e. the trend moves away from the band.
        return None
    return seconds


_MODELS: dict[str, Model] = {
    MODEL_LINEAR: _linear,
}

# Model ids that have already emitted their not-implemented warning.
_warned: set[str] = set()


def register_model(model_id: str, model: Model) -> None:
    """Register (or override) a model implementation. Used by LOGIC-01/02."""
    _MODELS[model_id] = model


def get_model(model_id: str) -> Model:
    """Return the model for ``model_id``, falling back to ``linear``.

    Unknown / not-yet-implemented ids (``exponential``, ``power`` until
    LOGIC-01/02) log once and resolve to the linear baseline so the integration
    keeps working.
    """
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
    """Resolve the model id for a pair.

    An explicit override wins; ``None`` or :data:`~.const.MODEL_AUTO` means
    "use the resolved kind's default".
    """
    if override and override != MODEL_AUTO:
        return override
    return kind.default_model
