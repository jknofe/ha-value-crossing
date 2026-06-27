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
KEY_TIME_UNTIL = "time_until_crossover"
KEY_ETA = "crossover_eta"
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
