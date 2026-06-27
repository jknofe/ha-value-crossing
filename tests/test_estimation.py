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
    STATUS_NO_CROSSING_HORIZON,
    STATUS_OK,
    STATUS_WITHIN_BAND,
)
from custom_components.value_crossing.estimation import (
    RollingBuffer,
    bin_hourly_means,
    effective_model,
    estimate_crossing,
    get_model,
    merge_difference_series,
    profile_at,
    profile_range,
    project_daily_crossing,
    project_value,
)
from custom_components.value_crossing.kinds import GenericKind, TemperatureKind

NOW = datetime(2026, 6, 27, 12, 0, 0, tzinfo=UTC)


# --- crossover-value projection ---------------------------------------------


def test_project_value_extrapolates_linear_trend() -> None:
    # Rising 1 unit / 10 s; 30 s past the last sample -> +3.
    samples = [(0.0, 10.0), (10.0, 11.0), (20.0, 12.0)]
    assert project_value(samples, 30.0) == 12.0 + 3.0


def test_project_value_flat_series_holds() -> None:
    samples = [(0.0, 20.0), (10.0, 20.0), (20.0, 20.0)]
    assert project_value(samples, 600.0) == 20.0


def test_project_value_insufficient_samples_is_none() -> None:
    assert project_value([(0.0, 5.0)], 60.0) is None
    assert project_value([], 60.0) is None


# --- daily-pattern profiles (LOGIC-05) --------------------------------------

# Hour-of-day is ``(epoch % 86400) / 3600`` (UTC). A whole-day base keeps the
# arithmetic exact: ``now`` sits at hour-of-day 12.
_DAY = 19000
_NOW_EPOCH = _DAY * 86400 + 12 * 3600


def test_bin_hourly_means_buckets_and_drops_old() -> None:
    samples = [
        (_NOW_EPOCH - 2 * 3600, 5.0),  # hour 10
        (_NOW_EPOCH - 2 * 3600 + 60, 7.0),  # hour 10 again -> mean 6
        (_NOW_EPOCH - 22 * 3600, 20.0),  # hour 14 (yesterday), within window
        (_NOW_EPOCH - 30 * 3600, 99.0),  # older than 24h -> ignored
    ]
    profile = bin_hourly_means(samples, _NOW_EPOCH)
    assert len(profile) == 24
    assert profile[10] == 6.0
    assert profile[14] == 20.0
    assert profile[0] is None
    assert profile[12] is None


def test_profile_at_interpolates_and_wraps() -> None:
    profile: list[float | None] = [None] * 24
    profile[10], profile[11] = 10.0, 20.0
    assert profile_at(profile, 10.0) == 10.0
    assert profile_at(profile, 10.5) == 15.0

    wrap: list[float | None] = [None] * 24
    wrap[23], wrap[0] = 4.0, 8.0
    assert profile_at(wrap, 23.5) == 6.0  # 23 -> 0 wrap

    gap: list[float | None] = [None] * 24
    gap[5] = 3.0
    assert profile_at(gap, 5.5) == 3.0  # hi unknown -> lo
    assert profile_at(gap, 4.5) == 3.0  # lo unknown -> hi
    assert profile_at([None] * 24, 12.3) is None


def test_profile_range_peak_to_peak() -> None:
    profile: list[float | None] = [None] * 24
    profile[3], profile[8], profile[15] = 2.0, 9.0, 5.0
    assert profile_range(profile) == 7.0
    assert profile_range([None] * 24) == 0.0


def test_project_daily_within_band_now() -> None:
    ramp = [float(h) for h in range(24)]
    secs, status = project_daily_crossing(
        ramp, anchor=10.0, now=_NOW_EPOCH, held=10.0, band=0.5
    )
    assert status == STATUS_WITHIN_BAND
    assert secs == 0.0


def test_project_daily_finds_crossing() -> None:
    ramp = [float(h) for h in range(24)]
    # anchor==profile_at(12)==12 so shift 0; near edge 14.5 reached at hour 14.5.
    secs, status = project_daily_crossing(
        ramp, anchor=12.0, now=_NOW_EPOCH, held=15.0, band=0.5
    )
    assert status == STATUS_OK
    assert 2.4 * 3600 < secs < 2.6 * 3600


def test_project_daily_anchor_shifts_curve() -> None:
    ramp = [float(h) for h in range(24)]
    # shift = 100 - 12 = 88; near edge 102.5 reached when profile==14.5 (hour 14.5).
    secs, status = project_daily_crossing(
        ramp, anchor=100.0, now=_NOW_EPOCH, held=103.0, band=0.5
    )
    assert status == STATUS_OK
    assert 2.4 * 3600 < secs < 2.6 * 3600


def test_project_daily_no_crossing_in_horizon() -> None:
    flat = [0.0] * 24
    secs, status = project_daily_crossing(
        flat, anchor=0.0, now=_NOW_EPOCH, held=100.0, band=1.0
    )
    assert status == STATUS_NO_CROSSING_HORIZON
    assert secs is None


def test_project_daily_unanchorable_is_insufficient() -> None:
    profile: list[float | None] = [None] * 24
    profile[3] = 5.0  # nothing known near hour 12 -> cannot anchor at now
    secs, status = project_daily_crossing(
        profile, anchor=5.0, now=_NOW_EPOCH, held=5.0, band=0.1
    )
    assert status == STATUS_INSUFFICIENT_DATA
    assert secs is None


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


# --- merge_difference_series (LOGIC-03 backfill) ----------------------------


def test_merge_forward_fills_both_sides() -> None:
    # A at t=0,2; B at t=1,3. Diff emitted once both known, on each event.
    a = [(0.0, 10.0), (2.0, 8.0)]
    b = [(1.0, 4.0), (3.0, 5.0)]
    assert merge_difference_series(a, b) == [
        (1.0, 6.0),  # a=10, b=4
        (2.0, 4.0),  # a=8,  b=4
        (3.0, 3.0),  # a=8,  b=5
    ]


def test_merge_waits_until_both_known() -> None:
    # Only A has points -> never both known -> nothing emitted.
    assert merge_difference_series([(0.0, 1.0), (1.0, 2.0)], []) == []


def test_merge_unsorted_input_is_ordered() -> None:
    a = [(2.0, 8.0), (0.0, 10.0)]
    b = [(0.0, 4.0)]
    assert merge_difference_series(a, b) == [(0.0, 6.0), (2.0, 4.0)]


def test_merge_same_timestamp_both_update_once() -> None:
    # A and B both change at t=1: one combined sample using both new values.
    a = [(0.0, 10.0), (1.0, 7.0)]
    b = [(0.0, 4.0), (1.0, 5.0)]
    assert merge_difference_series(a, b) == [(0.0, 6.0), (1.0, 2.0)]


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
