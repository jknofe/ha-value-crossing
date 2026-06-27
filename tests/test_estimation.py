"""Unit tests for the estimation model dispatch + linear baseline (ARCH-01)."""

from __future__ import annotations

from custom_components.value_crossing import estimation
from custom_components.value_crossing.const import (
    MODEL_AUTO,
    MODEL_EXPONENTIAL,
    MODEL_LINEAR,
    MODEL_POWER,
)
from custom_components.value_crossing.estimation import (
    effective_model,
    get_model,
)
from custom_components.value_crossing.kinds import GenericKind, TemperatureKind


def test_effective_model_override_precedence() -> None:
    temp = TemperatureKind()
    # No / auto override -> kind default.
    assert effective_model(None, temp) == MODEL_EXPONENTIAL
    assert effective_model(MODEL_AUTO, temp) == MODEL_EXPONENTIAL
    # Explicit override wins.
    assert effective_model(MODEL_LINEAR, temp) == MODEL_LINEAR
    assert effective_model(MODEL_LINEAR, GenericKind()) == MODEL_LINEAR


def test_reserved_ids_fall_back_to_linear() -> None:
    linear = get_model(MODEL_LINEAR)
    assert get_model(MODEL_EXPONENTIAL) is linear
    assert get_model(MODEL_POWER) is linear
    assert get_model("totally-unknown") is linear


def test_register_model_overrides_dispatch() -> None:
    sentinel = object()

    def fake(samples, band):  # test stub
        return sentinel

    try:
        estimation.register_model("fake", fake)
        assert get_model("fake") is fake
    finally:
        estimation._MODELS.pop("fake", None)


def test_linear_crossing_time() -> None:
    # diff = 10 - t (slope -1/s); within band=1 when diff <= 1, i.e. at t=9.
    samples = [(float(t), 10.0 - t) for t in range(6)]  # last sample t=5, diff=5
    model = get_model(MODEL_LINEAR)
    seconds = model(samples, 1.0)
    assert seconds is not None
    assert abs(seconds - 4.0) < 1e-6  # from t=5 to t=9 -> 4 s


def test_linear_already_in_band() -> None:
    samples = [(0.0, 0.5), (1.0, 0.4)]
    assert get_model(MODEL_LINEAR)(samples, 1.0) == 0.0


def test_linear_flat_returns_none() -> None:
    samples = [(0.0, 5.0), (1.0, 5.0), (2.0, 5.0)]
    assert get_model(MODEL_LINEAR)(samples, 1.0) is None


def test_linear_diverging_returns_none() -> None:
    samples = [(0.0, 2.0), (1.0, 3.0)]  # moving up, away from band=1
    assert get_model(MODEL_LINEAR)(samples, 1.0) is None


def test_linear_too_few_points_returns_none() -> None:
    assert get_model(MODEL_LINEAR)([(0.0, 5.0)], 1.0) is None
    assert get_model(MODEL_LINEAR)([], 1.0) is None
