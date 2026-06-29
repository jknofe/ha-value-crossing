"""Constants for the value_crossing integration.

Kept free of any ``homeassistant`` import so the pure modules (``kinds``,
``estimation``) that read from here stay unit-testable without Home Assistant.
``PLATFORMS`` therefore lives in ``__init__`` (it needs ``homeassistant.const``).
"""

DOMAIN = "value_crossing"

# Config-entry keys (one entry == one crossing pair).
CONF_PAIR_NAME = "name"
CONF_SENSOR_A = "sensor_a"
CONF_SENSOR_B = "sensor_b"
CONF_BAND = "band"
CONF_MODEL = "model"  # estimation-model override; surfaced by LOGIC-01/02
CONF_DAILY_HISTORY = "daily_history"  # opt-in daily-pattern prediction (LOGIC-05)
CONF_NOTIFY = "notify"  # persistent-notification gate + direction filter (LOGIC-04)
CONF_NOTIFY_TARGETS = "notify_targets"  # notify.* entities to push to (LOGIC-06)

# Notify dropdown options (LOGIC-04). Gates only the persistent notification; the
# value_crossing_crossed event fires on every crossing regardless.
NOTIFY_NO = "no"
NOTIFY_BOTH = "both"
NOTIFY_FROM_BELOW = "from_below"
NOTIFY_FROM_ABOVE = "from_above"

# Crossing direction (LOGIC-04): the side the difference approached the band from.
DIR_FROM_ABOVE = "from_above"  # diff was > band (A above B) and fell into the band
DIR_FROM_BELOW = "from_below"  # diff was < -band (A below B) and rose into the band
DIR_NONE = "none"  # no crossing predicted / direction not classifiable

# Bus event fired on every crossing (LOGIC-04).
EVENT_CROSSED = "value_crossing_crossed"

# Entity translation keys (also used to build unique-id suffixes).
KEY_DIFFERENCE = "difference"
KEY_ETA = "crossover_eta"
KEY_CROSSOVER_VALUE = "crossover_value"
KEY_CROSSED = "crossed"
KEY_CROSSING_DIRECTION = "crossing_direction"

# Device-class strings whose measurement makes sense to inherit onto the
# signed difference sensor (a temperature/power difference is still that class).
INHERITABLE_DEVICE_CLASSES = frozenset({"temperature", "power"})

# Estimation model ids.
MODEL_LINEAR = "linear"
MODEL_EXPONENTIAL = "exponential"
MODEL_POWER = "power"

# Sentinel for a per-pair model override meaning "use the resolved kind's default".
MODEL_AUTO = "auto"

# Estimation fit window (LOGIC-01).
CONF_WINDOW = "window"  # seconds of recent history fed to the fit
DEFAULT_WINDOW = 1800  # 30 minutes
MAX_SAMPLES = 600  # hard cap on the rolling buffer
MIN_SAMPLES_LINEAR = 2
MIN_SAMPLES_EXPONENTIAL = 5
MIN_SAMPLES_POWER = 5  # robust slope needs a few points to be meaningful

# Robust power model (LOGIC-02): Theil-Sen + significance gate.
THEILSEN_MAX_POINTS = 100  # subsample cap so pairwise stays ~few-thousand pairs
POWER_TREND_K = 3.0  # trend is real only when |slope*span| > k * MAD(residuals)

# Daily-pattern prediction (LOGIC-05).
PROFILE_HOURS = 24  # hourly-mean buckets in a daily profile
DAILY_HORIZON_HOURS = 24  # how far ahead the daily projection steps
DAILY_STEP_SECONDS = 600  # projection step granularity (10 minutes)

# Estimate status (exposed as the time/ETA sensors' `status` attribute).
STATUS_OK = "ok"  # a future crossing is predicted
STATUS_WITHIN_BAND = "within_band"  # already crossed (time 0 / ETA now)
STATUS_DIVERGING = "diverging"  # trend moves away from / never reaches the band
STATUS_ASYMPTOTE_OUTSIDE_BAND = "asymptote_outside_band"  # exp asymptote outside band
STATUS_INSUFFICIENT_DATA = "insufficient_data"  # not enough samples yet
STATUS_FIT_FAILED = "fit_failed"  # degenerate/ill-conditioned fit
STATUS_NO_CROSSING_HORIZON = "no_crossing_horizon"  # daily curve never crosses in 24h
STATUS_NO_TREND = "no_trend"  # power model: trend indistinguishable from noise
