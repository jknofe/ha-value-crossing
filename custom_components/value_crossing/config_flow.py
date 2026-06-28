"""Config flow for value_crossing: one config entry per crossing pair.

Two steps so sensor B can be filtered to sensor A's device_class:
  1. ``user``     - pair name + sensor A
  2. ``sensor_b`` - sensor B (filtered) + band (default from the resolved kind)

The two sensors must share a unit_of_measurement, else ``unit_mismatch``.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    CONF_BAND,
    CONF_DAILY_HISTORY,
    CONF_MODEL,
    CONF_NOTIFY,
    CONF_PAIR_NAME,
    CONF_SENSOR_A,
    CONF_SENSOR_B,
    CONF_WINDOW,
    DEFAULT_WINDOW,
    DOMAIN,
    MODEL_AUTO,
    MODEL_EXPONENTIAL,
    MODEL_LINEAR,
    MODEL_POWER,
    NOTIFY_BOTH,
    NOTIFY_FROM_ABOVE,
    NOTIFY_FROM_BELOW,
    NOTIFY_NO,
)
from .kinds import resolve


def _model_window_fields(
    model_default: str,
    window_default: float,
    daily_default: bool = False,
    notify_default: str = NOTIFY_NO,
) -> dict:
    """Schema entries for the per-pair model, window, daily flag + notify mode."""
    return {
        vol.Required(CONF_MODEL, default=model_default): SelectSelector(
            SelectSelectorConfig(
                options=[MODEL_AUTO, MODEL_EXPONENTIAL, MODEL_LINEAR, MODEL_POWER],
                translation_key="model",
                mode=SelectSelectorMode.DROPDOWN,
            )
        ),
        vol.Required(CONF_WINDOW, default=window_default): NumberSelector(
            NumberSelectorConfig(
                mode=NumberSelectorMode.BOX,
                min=60,
                step=60,
                unit_of_measurement="s",
            )
        ),
        vol.Required(
            CONF_DAILY_HISTORY, default=daily_default
        ): BooleanSelector(),
        vol.Required(CONF_NOTIFY, default=notify_default): SelectSelector(
            SelectSelectorConfig(
                options=[
                    NOTIFY_NO,
                    NOTIFY_BOTH,
                    NOTIFY_FROM_BELOW,
                    NOTIFY_FROM_ABOVE,
                ],
                translation_key="notify",
                mode=SelectSelectorMode.DROPDOWN,
            )
        ),
    }


def _unit_of(hass, entity_id: str | None) -> str | None:
    """unit_of_measurement of an entity's current state (or None)."""
    if not entity_id:
        return None
    state = hass.states.get(entity_id)
    return state.attributes.get("unit_of_measurement") if state else None


def _device_class_of(hass, entity_id: str | None) -> str | None:
    """device_class of an entity's current state (or None)."""
    if not entity_id:
        return None
    state = hass.states.get(entity_id)
    return state.attributes.get("device_class") if state else None


class ValueCrossingConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for one crossing pair."""

    VERSION = 1

    def __init__(self) -> None:
        """Hold the step-1 answers while the user picks sensor B."""
        self._name: str = ""
        self._sensor_a: str = ""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 1: pair name and sensor A."""
        if user_input is not None:
            self._name = user_input[CONF_PAIR_NAME]
            self._sensor_a = user_input[CONF_SENSOR_A]
            return await self.async_step_sensor_b()

        schema = vol.Schema(
            {
                vol.Required(CONF_PAIR_NAME): str,
                vol.Required(CONF_SENSOR_A): EntitySelector(
                    EntitySelectorConfig(domain="sensor")
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_sensor_b(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 2: sensor B (filtered to A's device_class) and the band."""
        errors: dict[str, str] = {}
        unit_a = _unit_of(self.hass, self._sensor_a)
        device_class_a = _device_class_of(self.hass, self._sensor_a)
        kind = resolve(unit_a, device_class_a)

        if user_input is not None:
            sensor_b = user_input[CONF_SENSOR_B]
            if _unit_of(self.hass, sensor_b) != unit_a:
                errors["base"] = "unit_mismatch"
            else:
                return self.async_create_entry(
                    title=self._name,
                    data={
                        CONF_PAIR_NAME: self._name,
                        CONF_SENSOR_A: self._sensor_a,
                        CONF_SENSOR_B: sensor_b,
                        CONF_BAND: user_input[CONF_BAND],
                        CONF_MODEL: user_input[CONF_MODEL],
                        CONF_WINDOW: user_input[CONF_WINDOW],
                        CONF_DAILY_HISTORY: user_input[CONF_DAILY_HISTORY],
                        CONF_NOTIFY: user_input[CONF_NOTIFY],
                    },
                )

        b_config = EntitySelectorConfig(domain="sensor")
        if device_class_a:
            b_config["device_class"] = device_class_a
        schema = vol.Schema(
            {
                vol.Required(CONF_SENSOR_B): EntitySelector(b_config),
                vol.Required(CONF_BAND, default=kind.default_band): NumberSelector(
                    NumberSelectorConfig(mode=NumberSelectorMode.BOX, step="any")
                ),
                **_model_window_fields(MODEL_AUTO, kind.default_window),
            }
        )
        return self.async_show_form(
            step_id="sensor_b", data_schema=schema, errors=errors
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit an existing pair (name, both sensors, band) in one form."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            unit_a = _unit_of(self.hass, user_input[CONF_SENSOR_A])
            unit_b = _unit_of(self.hass, user_input[CONF_SENSOR_B])
            if unit_a != unit_b:
                errors["base"] = "unit_mismatch"
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    title=user_input[CONF_PAIR_NAME],
                    data=user_input,
                )

        current = {**entry.data, **(user_input or {})}
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_PAIR_NAME, default=current[CONF_PAIR_NAME]
                ): str,
                vol.Required(
                    CONF_SENSOR_A, default=current[CONF_SENSOR_A]
                ): EntitySelector(EntitySelectorConfig(domain="sensor")),
                vol.Required(
                    CONF_SENSOR_B, default=current[CONF_SENSOR_B]
                ): EntitySelector(EntitySelectorConfig(domain="sensor")),
                vol.Required(
                    CONF_BAND, default=current[CONF_BAND]
                ): NumberSelector(
                    NumberSelectorConfig(mode=NumberSelectorMode.BOX, step="any")
                ),
                **_model_window_fields(
                    current.get(CONF_MODEL, MODEL_AUTO),
                    current.get(CONF_WINDOW, DEFAULT_WINDOW),
                    current.get(CONF_DAILY_HISTORY, False),
                    current.get(CONF_NOTIFY, NOTIFY_NO),
                ),
            }
        )
        return self.async_show_form(
            step_id="reconfigure", data_schema=schema, errors=errors
        )
