"""Config-flow tests for value_crossing (Bronze config-flow-test-coverage)."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.value_crossing.const import (
    CONF_BAND,
    CONF_DAILY_HISTORY,
    CONF_MODEL,
    CONF_NOTIFY,
    CONF_PAIR_NAME,
    CONF_SENSOR_A,
    CONF_SENSOR_B,
    CONF_WINDOW,
    DOMAIN,
    MODEL_AUTO,
    NOTIFY_NO,
)


def _set(hass, entity_id, value, unit, device_class=None):
    attrs = {"unit_of_measurement": unit}
    if device_class:
        attrs["device_class"] = device_class
    hass.states.async_set(entity_id, value, attrs)


async def _start(hass):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


async def test_user_flow_creates_entry(hass: HomeAssistant) -> None:
    _set(hass, "sensor.inside", "20", "°C", "temperature")
    _set(hass, "sensor.outside", "18", "°C", "temperature")

    result = await _start(hass)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_PAIR_NAME: "Indoor vs Outdoor", CONF_SENSOR_A: "sensor.inside"},
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "sensor_b"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_SENSOR_B: "sensor.outside", CONF_BAND: 0.5},
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Indoor vs Outdoor"
    data = result["data"]
    assert data[CONF_PAIR_NAME] == "Indoor vs Outdoor"
    assert data[CONF_SENSOR_A] == "sensor.inside"
    assert data[CONF_SENSOR_B] == "sensor.outside"
    assert data[CONF_BAND] == 0.5
    # Model/window/daily-history/notify default in when not supplied.
    assert data[CONF_MODEL] == MODEL_AUTO
    assert data[CONF_WINDOW] == 3600  # temperature kind's default window
    assert data[CONF_DAILY_HISTORY] is False
    assert data[CONF_NOTIFY] == NOTIFY_NO


async def test_notify_mode_persisted(hass: HomeAssistant) -> None:
    _set(hass, "sensor.inside", "20", "°C", "temperature")
    _set(hass, "sensor.outside", "18", "°C", "temperature")

    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_PAIR_NAME: "p", CONF_SENSOR_A: "sensor.inside"},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_SENSOR_B: "sensor.outside", CONF_BAND: 0.5, CONF_NOTIFY: "from_above"},
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_NOTIFY] == "from_above"


async def test_daily_history_flag_persisted(hass: HomeAssistant) -> None:
    _set(hass, "sensor.inside", "20", "°C", "temperature")
    _set(hass, "sensor.outside", "18", "°C", "temperature")

    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_PAIR_NAME: "p", CONF_SENSOR_A: "sensor.inside"},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_SENSOR_B: "sensor.outside", CONF_BAND: 0.5, CONF_DAILY_HISTORY: True},
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_DAILY_HISTORY] is True


async def test_sensor_b_filtered_by_device_class_and_band_default(
    hass: HomeAssistant,
) -> None:
    _set(hass, "sensor.inside", "20", "°C", "temperature")

    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_PAIR_NAME: "p", CONF_SENSOR_A: "sensor.inside"},
    )

    schema = result["data_schema"].schema
    b_selector = next(v for k, v in schema.items() if k == CONF_SENSOR_B)
    # EntitySelector normalises device_class to a list.
    assert b_selector.config.get("device_class") == ["temperature"]

    band_key = next(k for k in schema if k == CONF_BAND)
    # Temperature kind's default_band (ARCH-01) seeds the field.
    assert band_key.default() == 0.5

    window_key = next(k for k in schema if k == CONF_WINDOW)
    # Temperature kind defaults the fit window to 3600 s (longer = steadier).
    assert window_key.default() == 3600


async def test_unit_mismatch_rejected(hass: HomeAssistant) -> None:
    _set(hass, "sensor.inside", "20", "°C", "temperature")
    _set(hass, "sensor.load", "100", "W", "power")

    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_PAIR_NAME: "p", CONF_SENSOR_A: "sensor.inside"},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_SENSOR_B: "sensor.load", CONF_BAND: 1.0},
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "sensor_b"
    assert result["errors"] == {"base": "unit_mismatch"}


def _existing_entry(hass) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Pair",
        data={
            CONF_PAIR_NAME: "Pair",
            CONF_SENSOR_A: "sensor.inside",
            CONF_SENSOR_B: "sensor.outside",
            CONF_BAND: 0.5,
        },
    )
    entry.add_to_hass(hass)
    return entry


async def test_reconfigure_updates_band(hass: HomeAssistant) -> None:
    _set(hass, "sensor.inside", "20", "°C", "temperature")
    _set(hass, "sensor.outside", "18", "°C", "temperature")
    entry = _existing_entry(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
        },
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_PAIR_NAME: "Pair",
            CONF_SENSOR_A: "sensor.inside",
            CONF_SENSOR_B: "sensor.outside",
            CONF_BAND: 2.0,
        },
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_BAND] == 2.0


async def test_reconfigure_unit_mismatch(hass: HomeAssistant) -> None:
    _set(hass, "sensor.inside", "20", "°C", "temperature")
    _set(hass, "sensor.outside", "18", "°C", "temperature")
    _set(hass, "sensor.load", "100", "W", "power")
    entry = _existing_entry(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
        },
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_PAIR_NAME: "Pair",
            CONF_SENSOR_A: "sensor.inside",
            CONF_SENSOR_B: "sensor.load",
            CONF_BAND: 0.5,
        },
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "unit_mismatch"}


async def test_unitless_pair_allowed(hass: HomeAssistant) -> None:
    # Two sensors with no unit resolve to GenericKind and are allowed.
    hass.states.async_set("sensor.a", "5", {})
    hass.states.async_set("sensor.b", "4", {})

    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_PAIR_NAME: "g", CONF_SENSOR_A: "sensor.a"},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_SENSOR_B: "sensor.b", CONF_BAND: 1.0},
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
