# Value Crossing

A Home Assistant custom integration that estimates **when two sensors of the
same unit will meet**, and tells you when they have.

## What it does

You pick two sensors that share a physical unit (for example inside vs outside
temperature, or solar power vs house consumption) and a **band** (a tolerance
half-width). Value Crossing tracks the live difference between them and, from
the recent trend, estimates how long until that difference enters the band
(a "crossing"). It is useful for questions like "when will the room reach the
outside temperature?" or "when will production match consumption?".

## Example use cases

### 1. Keep the house cool (sommerliches Lüften)

"Lüften" is the German habit of airing out rooms. In summer you want to open the
windows only while it is cooler outside than inside, to let the heat out without
letting it in.

- **Sensor A:** outside temperature. **Sensor B:** inside temperature.
- **Band:** ~0.5 °C. **Model:** exponential (enable **Use last-day history
  pattern** to anticipate the evening turnaround).
- The **Crossover ETA** tells you when the outside temperature will drop to the
  inside temperature, and **Crossed** turns on at that moment: time to open the
  windows. In the morning, when outside climbs back above inside, it is time to
  close them again.

### 2. Heating flow vs return (Heizung Vorlauf/Rücklauf)

A water heating loop has a "Vorlauf" (flow, the hot water going out) and a
"Rücklauf" (return, the cooler water coming back). As a room or buffer reaches
temperature, the two converge.

- **Sensor A:** Vorlauf temperature. **Sensor B:** Rücklauf temperature.
- **Band:** a few °C (for example 3 °C). **Model:** exponential (the spread
  relaxes toward equilibrium).
- When the difference enters the band, **Crossed** turns on: the loop has given
  off most of its heat / the cycle is finishing, and the **Crossover ETA**
  estimates when that happens. A spread that never closes can flag a circulation
  problem.

### 3. Solar production vs home consumption

Know when your solar output meets the house load: the break-even point where you
stop importing and start exporting (and the reverse in the evening).

- **Sensor A:** solar production (W). **Sensor B:** house consumption (W).
- **Band:** tens of watts (for example 50 W). **Model:** power (robust to the
  spiky, noisy readings typical of electrical signals).
- The **Crossover ETA** predicts when production will meet consumption, so you can
  time heavy appliances; **Crossed** marks the moment they balance.

## Entities (per pair)

| Entity | What it shows | Unit |
| --- | --- | --- |
| Difference | Live signed `A - B` | the sensors' unit |
| Crossover value | Predicted value the sensors meet at | the sensors' unit |
| Crossover ETA | Estimated wall-clock time of crossing | timestamp |
| Crossing direction | Approach/crossed direction (`from_above`/`from_below`/`none`) | enum |
| Crossed | On while the difference is within the band | binary |

The crossover value and ETA report `unknown` when no crossing is predicted;
their `status` attribute explains why (for example `diverging`,
`asymptote_outside_band`, or `insufficient_data`).

## Notifications

When the pair crosses into the band, the integration fires the
`value_crossing_crossed` event (payload: `entry_id`, `name`, `sensor_a`,
`sensor_b`, `direction`, `crossover_value`) so you can drive your own
automations. The event fires on every crossing regardless of the notify setting.

Each pair also has a **Notify on crossing** option (`no` / both directions /
only `from_below` / only `from_above`). When it allows the crossing, the
integration shows a short persistent notification (pair name, direction, and the
crossover value) and, if you select one or more **Push notification targets**,
pushes the same message to them via `notify.send_message`. Pick any `notify.*`
entity, such as your phone's `notify.mobile_app_...` from the Home Assistant
Companion app, to get crossings on mobile devices (persistent notifications stay
in the Home Assistant frontend only). Leave the targets empty for the persistent
notification only.

## Install

The repository layout is a standard custom component
(`custom_components/value_crossing`), so either method works.

### Option A: HACS custom repository

1. In HACS, open the menu and choose **Custom repositories**.
2. Add `https://github.com/jknofe/ha-value-crossing` with category
   **Integration**.
3. Install **Value Crossing** from HACS, then restart Home Assistant.

### Option B: Manual sideload

1. Copy the `custom_components/value_crossing` folder into your Home Assistant
   config directory so you have `<config>/custom_components/value_crossing/`:
   ```bash
   git clone https://github.com/jknofe/ha-value-crossing.git
   cp -r ha-value-crossing/custom_components/value_crossing \
         <config>/custom_components/
   ```
2. Restart Home Assistant.

## Configure

### Add your first pair

After restarting, go to **Settings -> Devices & Services -> Add Integration**
and search for **Value Crossing**. The setup runs in two steps:

1. Name the pair and pick **Sensor A**.
2. Pick **Sensor B** (it must share Sensor A's unit), then set the **band**, the
   **estimation model** (`auto`, `exponential`, or `linear`), the **fit
   window** in seconds (how much recent history feeds the estimate; default
   1800), and optionally **Use last-day history pattern** (project the more
   dynamic sensor along its own shape from the previous 24 hours instead of a
   short straight-line trend; best for daily-cyclic signals like temperature).

### Add more pairs

Each pair is its own config entry (shown as its own device). To add **another
pair you do not install the integration again**. On **Settings -> Devices &
Services**, open the existing **Value Crossing** integration and choose **Add
entry** (the "+" button on the integration's page) to run the same two-step
setup for the new pair. Repeat for as many pairs as you like.

### Edit a pair

To change an existing pair (its sensors, band, model, fit window, or the
last-day-history option), use **Reconfigure** on that pair's entry. There is no
need to delete and recreate it.

## Status and limitations

Early and experimental. The `linear` and `exponential` estimation models work;
the dedicated power model is still in progress. The estimate extrapolates from
the recent trend, so on flat or near-constant signals the predicted ETA can be
noisy or flip between "crossing" and "no crossing"; treat it as a guide, not a
guarantee.

## Requirements

Home Assistant only. No extra Python dependencies (numpy ships with Home
Assistant). Verified on Home Assistant 2026.x.

## Credits

The idea for this integration came from a gist by
[benben](https://gist.github.com/benben/3f19e6d785d5e4040844e5581c4e13db).
Thanks for sharing it.

Related prior art:
[ha-weatherstage](https://github.com/jknofe/ha-weatherstage).
