"""Unit tests for estimation: models, statuses, rolling buffer (LOGIC-01)."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

from custom_components.value_crossing.const import (
    MODEL_AUTO,
    MODEL_EXPONENTIAL,
    MODEL_LINEAR,
    MODEL_POWER,
    STATUS_ASYMPTOTE_OUTSIDE_BAND,
    STATUS_DIVERGING,
    STATUS_INSUFFICIENT_DATA,
    STATUS_OK,
    STATUS_WITHIN_BAND,
)
from custom_components.value_crossing.estimation import (
    RollingBuffer,
    effective_model,
    estimate_crossing,
    get_model,
)
from custom_components.value_crossing.kinds import GenericKind, TemperatureKind

NOW = datetime(2026, 6, 27, 12, 0, 0, tzinfo=UTC)


# --- dispatch + override ----------------------------------------------------


def test_effective_model_override_precedence() -> None:
    temp = TemperatureKind()
    assert effective_model(None, temp) == MODEL_EXPONENTIAL
    assert effective_model(MODEL_AUTO, temp) == MODEL_EXPONENTIAL
    assert effective_model(MODEL_LINEAR, temp) == MODEL_LINEAR
    assert effective_model(MODEL_LINEAR, GenericKind()) == MODEL_LINEAR


def test_get_model_real_and_reserved() -> None:
    linear = get_model(MODEL_LINEAR)
    assert get_model(MODEL_EXPONENTIAL) is not linear  # now a real model
    assert get_model(MODEL_POWER) is linear  # reserved until LOGIC-02
    assert get_model("unknown") is linear


# --- rolling buffer ---------------------------------------------------------


def test_rolling_buffer_trims_by_window() -> None:
    buf = RollingBuffer(window=10)
    buf.add(0, 1.0)
    buf.add(5, 2.0)
    buf.add(11, 3.0)  # cutoff = 1 -> drops t=0
    assert [t for t, _ in buf.samples()] == [5, 11]


def test_rolling_buffer_caps_samples() -> None:
    buf = RollingBuffer(window=10_000, max_samples=2)
    for i in range(5):
        buf.add(i, float(i))
    assert buf.samples() == [(3, 3.0), (4, 4.0)]


# --- linear model -----------------------------------------------------------


def test_linear_crossing() -> None:
    samples = [(float(t), 10.0 - t) for t in range(6)]  # slope -1, last diff 5
    seconds, status = get_model(MODEL_LINEAR)(samples, 1.0)
    assert status == STATUS_OK
    assert abs(seconds - 4.0) < 1e-6


def test_linear_within_band() -> None:
    seconds, status = get_model(MODEL_LINEAR)([(0.0, 0.5), (1.0, 0.4)], 1.0)
    assert (seconds, status) == (0.0, STATUS_WITHIN_BAND)


def test_linear_flat_and_diverging() -> None:
    assert get_model(MODEL_LINEAR)([(0.0, 5.0), (1.0, 5.0)], 1.0) == (
        None,
        STATUS_DIVERGING,
    )
    assert get_model(MODEL_LINEAR)([(0.0, 2.0), (1.0, 3.0)], 1.0) == (
        None,
        STATUS_DIVERGING,
    )


def test_linear_insufficient_data() -> None:
    assert get_model(MODEL_LINEAR)([(0.0, 5.0)], 1.0) == (
        None,
        STATUS_INSUFFICIENT_DATA,
    )


# --- exponential model ------------------------------------------------------


def _exp_series(d_inf, amp, tau, ts):
    return [(float(t), d_inf + amp * math.exp(-t / tau)) for t in ts]


def test_exponential_crosses_within_10pct() -> None:
    d_inf, amp, tau, band = 0.0, 10.0, 300.0, 1.0
    ts = list(range(0, 601, 60))
    samples = _exp_series(d_inf, amp, tau, ts)
    seconds, status = get_model(MODEL_EXPONENTIAL)(samples, band)
    assert status == STATUS_OK
    # ground truth: 10*exp(-t/300)=1 -> t=300*ln(10); from last sample (t=600).
    truth = 300.0 * math.log(10.0) - 600.0
    assert abs(seconds - truth) / truth < 0.10


def test_exponential_asymptote_outside_band() -> None:
    samples = _exp_series(5.0, 10.0, 300.0, range(0, 601, 60))  # d_inf=5 > band
    seconds, status = get_model(MODEL_EXPONENTIAL)(samples, 1.0)
    assert seconds is None
    assert status == STATUS_ASYMPTOTE_OUTSIDE_BAND


def test_exponential_within_band() -> None:
    samples = _exp_series(0.0, 0.4, 300.0, range(0, 601, 60))  # all inside band 1
    assert get_model(MODEL_EXPONENTIAL)(samples, 1.0) == (0.0, STATUS_WITHIN_BAND)


def test_exponential_insufficient_data() -> None:
    samples = _exp_series(0.0, 10.0, 300.0, [0, 60, 120])  # only 3 points
    assert get_model(MODEL_EXPONENTIAL)(samples, 1.0) == (
        None,
        STATUS_INSUFFICIENT_DATA,
    )


def test_exponential_falls_back_to_linear_when_fit_fails() -> None:
    # A clean straight line is not a relaxation; exp fit rejects, linear takes over.
    samples = [(float(t), 10.0 - t) for t in range(8)]  # last diff 3, slope -1
    seconds, status = get_model(MODEL_EXPONENTIAL)(samples, 1.0)
    assert status == STATUS_OK
    assert abs(seconds - 2.0) < 1e-6  # (1 - 3)/-1 = 2


# --- estimate_crossing (ETA + rebasing) ------------------------------------


def test_estimate_crossing_ok_with_large_epoch_times() -> None:
    base = 1_000_000.0
    samples = [(base + t, 10.0 - t) for t in range(6)]
    est = estimate_crossing(samples, 1.0, MODEL_LINEAR, NOW)
    assert est.status == STATUS_OK
    assert abs(est.seconds_until - 4.0) < 1e-6
    assert est.eta == NOW + timedelta(seconds=4.0)


def test_estimate_crossing_within_band_eta_now() -> None:
    est = estimate_crossing([(0.0, 0.5), (1.0, 0.4)], 1.0, MODEL_LINEAR, NOW)
    assert est.status == STATUS_WITHIN_BAND
    assert est.seconds_until == 0.0
    assert est.eta == NOW


def test_estimate_crossing_no_crossing_eta_none() -> None:
    est = estimate_crossing([(0.0, 2.0), (1.0, 3.0)], 1.0, MODEL_LINEAR, NOW)
    assert est.status == STATUS_DIVERGING
    assert est.seconds_until is None
    assert est.eta is None
