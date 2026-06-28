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
    CONF_DAILY_HISTORY,
    CONF_NOTIFY,
    CONF_PAIR_NAME,
    CONF_SENSOR_A,
    CONF_SENSOR_B,
    DOMAIN,
    EVENT_CROSSED,
    STATUS_INSUFFICIENT_DATA,
    STATUS_WITHIN_BAND,
)


def _set(hass, entity_id, value, unit="°C", device_class="temperature"):
    hass.states.async_set(
        entity_id, value, {"unit_of_measurement": unit, "device_class": device_class}
    )


def _entry(hass, **extra) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Pair",
        data={
            CONF_PAIR_NAME: "Pair",
            CONF_SENSOR_A: "sensor.a",
            CONF_SENSOR_B: "sensor.b",
            CONF_BAND: 0.5,
            **extra,
        },
    )
    entry.add_to_hass(hass)
    return entry


def _by_suffix(entities, suffix):
    return next(e for e in entities if e.unique_id.endswith(suffix))


async def test_setup_creates_five_entities(hass: HomeAssistant) -> None:
    _set(hass, "sensor.a", "20")
    _set(hass, "sensor.b", "18")
    entry = _entry(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    ent_reg = er.async_get(hass)
    entities = er.async_entries_for_config_entry(ent_reg, entry.entry_id)
    assert len(entities) == 5

    diff = _by_suffix(entities, "_difference")
    assert hass.states.get(diff.entity_id).state == "2.0"

    crossed = _by_suffix(entities, "_crossed")
    assert hass.states.get(crossed.entity_id).state == "off"

    # No crossing predicted yet -> ETA and crossover value unknown, direction none.
    eta = _by_suffix(entities, "_crossover_eta")
    assert hass.states.get(eta.entity_id).state == "unknown"
    value = _by_suffix(entities, "_crossover_value")
    assert hass.states.get(value.entity_id).state == "unknown"
    direction = _by_suffix(entities, "_crossing_direction")
    assert hass.states.get(direction.entity_id).state == "none"


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
    eta = _by_suffix(entities, "_crossover_eta")
    state = hass.states.get(eta.entity_id)
    # Estimate is populated at first render, without any new live update.
    assert state.state != "unknown"
    assert state.attributes["status"] != STATUS_INSUFFICIENT_DATA

    # The crossover value is also projected from the primed A history.
    # Sensor A is constant 20 across the history, so it projects to ~20.
    value = _by_suffix(entities, "_crossover_value")
    vstate = hass.states.get(value.entity_id)
    assert vstate.state != "unknown"
    assert abs(float(vstate.state) - 20.0) < 0.5


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
    eta = _by_suffix(entities, "_crossover_eta")
    state = hass.states.get(eta.entity_id)
    assert state.state == "unknown"
    assert state.attributes["status"] == STATUS_INSUFFICIENT_DATA


def _flat_stats(now, value):
    """24 hourly stat rows of a constant mean: a flat, always-anchorable profile."""
    return [
        {"start": now - timedelta(hours=k), "mean": value, "min": value - 1,
         "max": value + 1}
        for k in range(24)
    ]


async def test_daily_history_drives_estimate(hass: HomeAssistant) -> None:
    # A and B sit within the band; with the daily flag on, the crossover value is
    # the held (B) value. The base-model path would instead report live A, so the
    # value 20.1 (B) rather than 20.0 (A) proves the daily path produced it.
    _set(hass, "sensor.a", "20.0")
    _set(hass, "sensor.b", "20.1")
    hass.config.components.add("recorder")
    entry = _entry(hass, **{CONF_DAILY_HISTORY: True})

    now = dt_util.utcnow()
    stats = {"sensor.a": _flat_stats(now, 19.0), "sensor.b": _flat_stats(now, 18.0)}
    with (
        patch(
            "homeassistant.components.recorder.get_instance",
            return_value=_FakeRecorder(),
        ),
        patch(
            "homeassistant.components.recorder.history.get_significant_states",
            return_value={},
        ),
        patch(
            "homeassistant.components.recorder.statistics.statistics_during_period",
            return_value=stats,
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    ent_reg = er.async_get(hass)
    entities = er.async_entries_for_config_entry(ent_reg, entry.entry_id)
    value = _by_suffix(entities, "_crossover_value")
    vstate = hass.states.get(value.entity_id)
    assert vstate.attributes["status"] == STATUS_WITHIN_BAND
    assert float(vstate.state) == 20.1  # held (B), not live A (20.0)


async def test_daily_history_unavailable_falls_back(hass: HomeAssistant) -> None:
    # Flag on but neither statistics nor history -> no profile -> base model, no
    # crash. With empty buffers the base model reports insufficient_data.
    _set(hass, "sensor.a", "20")
    _set(hass, "sensor.b", "14")
    hass.config.components.add("recorder")
    entry = _entry(hass, **{CONF_DAILY_HISTORY: True})

    with (
        patch(
            "homeassistant.components.recorder.get_instance",
            return_value=_FakeRecorder(),
        ),
        patch(
            "homeassistant.components.recorder.history.get_significant_states",
            return_value={},
        ),
        patch(
            "homeassistant.components.recorder.statistics.statistics_during_period",
            return_value={},
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    ent_reg = er.async_get(hass)
    entities = er.async_entries_for_config_entry(ent_reg, entry.entry_id)
    eta = _by_suffix(entities, "_crossover_eta")
    state = hass.states.get(eta.entity_id)
    assert state.state == "unknown"
    assert state.attributes["status"] == STATUS_INSUFFICIENT_DATA


async def test_daily_driver_is_higher_range_regardless_of_order(
    hass: HomeAssistant,
) -> None:
    # The sensor with the larger daily range drives; the other is held. Which one
    # is labelled A vs B must not change the outcome. crossover_value == held, so
    # it reveals the driver: held is B (20.1) when A drives, A (20.0) when B drives.
    from custom_components.value_crossing.coordinator import PairCoordinator

    ramp = [float(h) for h in range(24)]  # range 23 -> dynamic
    flat = [5.0] * 24  # range 0 -> steady

    def _coord(profile_a, profile_b) -> PairCoordinator:
        _set(hass, "sensor.a", "20.0")
        _set(hass, "sensor.b", "20.1")
        coord = PairCoordinator(hass, _entry(hass, **{CONF_DAILY_HISTORY: True}))
        coord._profile_a = profile_a
        coord._profile_b = profile_b
        return coord

    now = dt_util.utcnow()
    # A is the dynamic one -> A drives -> held is B.
    est = _coord(ramp, flat)._daily_estimate(now)
    assert est is not None and est.crossover_value == 20.1
    # Swap the shapes -> B drives -> held is A. Same geometry, order-independent.
    est = _coord(flat, ramp)._daily_estimate(now)
    assert est is not None and est.crossover_value == 20.0


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
    assert len(entities) == 5


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


# --- LOGIC-04: crossing notifications + direction sensor --------------------

_NOTIFY_PATH = "homeassistant.components.persistent_notification.async_create"


async def _setup_notify(hass, notify, a, b):
    """Set up a pair with a notify mode and an out-of-band starting difference."""
    _set(hass, "sensor.a", str(a))
    _set(hass, "sensor.b", str(b))
    entry = _entry(hass, **{CONF_NOTIFY: notify})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _move(hass, a, b):
    """Move both sources; capture crossing events and notification calls."""
    events: list[dict] = []
    hass.bus.async_listen(EVENT_CROSSED, lambda e: events.append(dict(e.data)))
    with patch(_NOTIFY_PATH) as notify_mock:
        _set(hass, "sensor.a", str(a))
        _set(hass, "sensor.b", str(b))
        await hass.async_block_till_done()
    return events, notify_mock


async def test_crossing_event_always_fires_and_notify_no_suppresses(
    hass: HomeAssistant,
) -> None:
    entry = await _setup_notify(hass, "no", 30, 20)  # A above B -> from_above
    events, notify_mock = await _move(hass, 20.1, 20)  # into the band
    assert len(events) == 1
    ev = events[0]
    assert ev["direction"] == "from_above"
    assert ev["name"] == "Pair"
    assert ev["sensor_a"] == "sensor.a" and ev["sensor_b"] == "sensor.b"
    assert ev["entry_id"] == entry.entry_id
    assert ev["band"] == 0.5
    assert ev["value_a"] == 20.1 and ev["value_b"] == 20.0
    assert abs(ev["difference"] - 0.1) < 1e-9
    assert notify_mock.call_count == 0  # notify=no -> event but no notification


async def test_notify_both_creates_notification(hass: HomeAssistant) -> None:
    entry = await _setup_notify(hass, "both", 30, 20)
    events, notify_mock = await _move(hass, 20.1, 20)
    assert len(events) == 1
    assert notify_mock.call_count == 1
    args, kwargs = notify_mock.call_args
    assert "Pair" in args[1]  # message mentions the pair name
    assert kwargs["notification_id"] == f"value_crossing_{entry.entry_id}"


async def test_notify_direction_filter_suppresses_mismatch(
    hass: HomeAssistant,
) -> None:
    await _setup_notify(hass, "from_below", 30, 20)  # crossing will be from_above
    events, notify_mock = await _move(hass, 20.1, 20)
    assert events[0]["direction"] == "from_above"
    assert notify_mock.call_count == 0  # filtered out


async def test_notify_from_below_matches_below_crossing(
    hass: HomeAssistant,
) -> None:
    await _setup_notify(hass, "from_below", 10, 20)  # A below B -> from_below
    events, notify_mock = await _move(hass, 19.9, 20)
    assert events[0]["direction"] == "from_below"
    assert notify_mock.call_count == 1


async def test_no_refire_while_staying_crossed(hass: HomeAssistant) -> None:
    await _setup_notify(hass, "both", 30, 20)
    events, _ = await _move(hass, 20.1, 20)  # cross
    assert len(events) == 1
    events2, notify2 = await _move(hass, 20.2, 20)  # still in band
    assert len(events2) == 0
    assert notify2.call_count == 0


async def test_unknown_prior_difference_no_fire(hass: HomeAssistant) -> None:
    await _setup_notify(hass, "both", 30, 20)  # baseline prev diff = 10
    hass.states.async_set("sensor.a", "unavailable", {"unit_of_measurement": "°C"})
    await hass.async_block_till_done()  # prev diff becomes unknown
    events, notify_mock = await _move(hass, 20.1, 20)  # into band, prior unknown
    assert len(events) == 0
    assert notify_mock.call_count == 0


async def test_crossing_direction_sensor_crossed_from(hass: HomeAssistant) -> None:
    entry = await _setup_notify(hass, "no", 30, 20)  # from_above side
    await _move(hass, 20.1, 20)  # cross into the band
    ent_reg = er.async_get(hass)
    entities = er.async_entries_for_config_entry(ent_reg, entry.entry_id)
    direction = _by_suffix(entities, "_crossing_direction")
    assert hass.states.get(direction.entity_id).state == "from_above"


async def test_crossing_direction_predicted_while_pending(
    hass: HomeAssistant,
) -> None:
    # Generic unit -> linear model (predicts from 2 samples). A constant, B rising
    # toward it: the difference falls but stays outside the band, so a crossing is
    # predicted and the sensor shows the approach direction (from_above).
    hass.states.async_set("sensor.a", "100", {"unit_of_measurement": "x"})
    hass.states.async_set("sensor.b", "0", {"unit_of_measurement": "x"})
    entry = _entry(hass, **{CONF_NOTIFY: "no"})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    for b in (50, 90):
        hass.states.async_set("sensor.b", str(b), {"unit_of_measurement": "x"})
        await hass.async_block_till_done()
    ent_reg = er.async_get(hass)
    entities = er.async_entries_for_config_entry(ent_reg, entry.entry_id)
    direction = _by_suffix(entities, "_crossing_direction")
    assert hass.states.get(direction.entity_id).state == "from_above"
