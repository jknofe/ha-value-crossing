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

# Entity translation keys (also used to build unique-id suffixes).
KEY_DIFFERENCE = "difference"
KEY_ETA = "crossover_eta"
KEY_CROSSOVER_VALUE = "crossover_value"
KEY_CROSSED = "crossed"

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

# Estimate status (exposed as the time/ETA sensors' `status` attribute).
STATUS_OK = "ok"  # a future crossing is predicted
STATUS_WITHIN_BAND = "within_band"  # already crossed (time 0 / ETA now)
STATUS_DIVERGING = "diverging"  # trend moves away from / never reaches the band
STATUS_ASYMPTOTE_OUTSIDE_BAND = "asymptote_outside_band"  # exp asymptote outside band
STATUS_INSUFFICIENT_DATA = "insufficient_data"  # not enough samples yet
STATUS_FIT_FAILED = "fit_failed"  # degenerate/ill-conditioned fit
