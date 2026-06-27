"""Setup/entity/teardown tests for value_crossing."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.value_crossing.const import (
    CONF_BAND,
    CONF_PAIR_NAME,
    CONF_SENSOR_A,
    CONF_SENSOR_B,
    DOMAIN,
    STATUS_INSUFFICIENT_DATA,
)


def _set(hass, entity_id, value, unit="°C", device_class="temperature"):
    hass.states.async_set(
        entity_id, value, {"unit_of_measurement": unit, "device_class": device_class}
    )


def _entry(hass) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Pair",
        data={
            CONF_PAIR_NAME: "Pair",
            CONF_SENSOR_A: "sensor.a",
            CONF_SENSOR_B: "sensor.b",
            CONF_BAND: 0.5,
        },
    )
    entry.add_to_hass(hass)
    return entry


def _by_suffix(entities, suffix):
    return next(e for e in entities if e.unique_id.endswith(suffix))


async def test_setup_creates_four_entities(hass: HomeAssistant) -> None:
    _set(hass, "sensor.a", "20")
    _set(hass, "sensor.b", "18")
    entry = _entry(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    ent_reg = er.async_get(hass)
    entities = er.async_entries_for_config_entry(ent_reg, entry.entry_id)
    assert len(entities) == 4

    diff = _by_suffix(entities, "_difference")
    assert hass.states.get(diff.entity_id).state == "2.0"

    crossed = _by_suffix(entities, "_crossed")
    assert hass.states.get(crossed.entity_id).state == "off"

    # Placeholders are unknown this change.
    eta = _by_suffix(entities, "_crossover_eta")
    assert hass.states.get(eta.entity_id).state == "unknown"
    until = _by_suffix(entities, "_time_until_crossover")
    assert hass.states.get(until.entity_id).state == "unknown"


def test_time_until_formats_as_hours_minutes() -> None:
    from custom_components.value_crossing.sensor import _format_hm

    assert _format_hm(None) is None
    assert _format_hm(0) == "0:00"
    assert _format_hm(12688) == "3:31"  # the live 3.5h example
    assert _format_hm(3599) == "1:00"  # rounds up to a full hour
    assert _format_hm(90000) == "25:00"  # hours may exceed 24


class _FakeRecorder:
    """Runs the executor job inline so backfill needs no real recorder thread."""

    async def async_add_executor_job(self, func, *args):
        return func(*args)


def _hist(entity_id, points, now):
    """Build recorder-style State objects at ``now - offset`` seconds."""
    return [
        State(entity_id, str(v), last_changed=now - timedelta(seconds=off))
        for off, v in points
    ]


async def test_backfill_primes_estimate_from_history(hass: HomeAssistant) -> None:
    _set(hass, "sensor.a", "20")
    _set(hass, "sensor.b", "14")
    hass.config.components.add("recorder")
    entry = _entry(hass)

    now = dt_util.utcnow()
    # 6 evenly-spaced points so diff = a - b is a clean line 10 -> 6 heading
    # toward the band (>= the exponential model's 5-sample minimum; the straight
    # line makes the exp fit reject and fall back to linear -> a real ETA).
    offs = [600, 480, 360, 240, 120, 0]
    b_vals = [10.0, 10.8, 11.6, 12.4, 13.2, 14.0]
    history = {
        "sensor.a": _hist("sensor.a", [(o, 20.0) for o in offs], now),
        "sensor.b": _hist("sensor.b", list(zip(offs, b_vals, strict=True)), now),
    }

    with (
        patch(
            "homeassistant.components.recorder.get_instance",
            return_value=_FakeRecorder(),
        ),
        patch(
            "homeassistant.components.recorder.history.get_significant_states",
            return_value=history,
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    ent_reg = er.async_get(hass)
    entities = er.async_entries_for_config_entry(ent_reg, entry.entry_id)
    until = _by_suffix(entities, "_time_until_crossover")
    state = hass.states.get(until.entity_id)
    # Estimate is populated at first render, without any new live update.
    assert state.state != "unknown"
    assert state.attributes["status"] != STATUS_INSUFFICIENT_DATA


async def test_backfill_absent_recorder_stays_insufficient(
    hass: HomeAssistant,
) -> None:
    # No "recorder" component -> backfill is skipped, estimate stays cold.
    _set(hass, "sensor.a", "20")
    _set(hass, "sensor.b", "14")
    entry = _entry(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    ent_reg = er.async_get(hass)
    entities = er.async_entries_for_config_entry(ent_reg, entry.entry_id)
    until = _by_suffix(entities, "_time_until_crossover")
    state = hass.states.get(until.entity_id)
    assert state.state == "unknown"
    assert state.attributes["status"] == STATUS_INSUFFICIENT_DATA


async def test_difference_and_crossed_update_live(hass: HomeAssistant) -> None:
    _set(hass, "sensor.a", "20")
    _set(hass, "sensor.b", "18")
    entry = _entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    ent_reg = er.async_get(hass)
    entities = er.async_entries_for_config_entry(ent_reg, entry.entry_id)
    diff = _by_suffix(entities, "_difference")
    crossed = _by_suffix(entities, "_crossed")

    # Move B to within the band: 20 - 19.5 = 0.5 <= 0.5 -> crossed on.
    _set(hass, "sensor.b", "19.5")
    await hass.async_block_till_done()
    assert hass.states.get(diff.entity_id).state == "0.5"
    assert hass.states.get(crossed.entity_id).state == "on"

    # A source going unavailable -> difference + crossed unknown.
    hass.states.async_set("sensor.a", "unavailable")
    await hass.async_block_till_done()
    assert hass.states.get(diff.entity_id).state == "unknown"
    assert hass.states.get(crossed.entity_id).state == "unknown"


async def test_reload_has_no_duplicate_entities(hass: HomeAssistant) -> None:
    _set(hass, "sensor.a", "20")
    _set(hass, "sensor.b", "18")
    entry = _entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    ent_reg = er.async_get(hass)
    entities = er.async_entries_for_config_entry(ent_reg, entry.entry_id)
    assert len(entities) == 4


async def test_unload_makes_entities_unavailable(hass: HomeAssistant) -> None:
    _set(hass, "sensor.a", "20")
    _set(hass, "sensor.b", "18")
    entry = _entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    ent_reg = er.async_get(hass)
    diff = _by_suffix(
        er.async_entries_for_config_entry(ent_reg, entry.entry_id), "_difference"
    )

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    # Unload leaves the registry entry but the state goes unavailable.
    assert hass.states.get(diff.entity_id).state == "unavailable"


async def test_remove_entry_deletes_entities(hass: HomeAssistant) -> None:
    _set(hass, "sensor.a", "20")
    _set(hass, "sensor.b", "18")
    entry = _entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    ent_reg = er.async_get(hass)
    diff = _by_suffix(
        er.async_entries_for_config_entry(ent_reg, entry.entry_id), "_difference"
    )

    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert er.async_entries_for_config_entry(ent_reg, entry.entry_id) == []
    assert hass.states.get(diff.entity_id) is None
