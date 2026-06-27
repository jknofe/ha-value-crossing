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

## Entities (per pair)

| Entity | What it shows | Unit |
| --- | --- | --- |
| Difference | Live signed `A - B` | the sensors' unit |
| Time until crossover | Estimated time until crossing | minutes (duration) |
| Crossover ETA | Estimated wall-clock time of crossing | timestamp |
| Crossed | On while the difference is within the band | binary |

The two time estimates report `unknown` when no crossing is predicted; their
`status` attribute explains why (for example `diverging`,
`asymptote_outside_band`, or `insufficient_data`).

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

After restarting, go to **Settings -> Devices & Services -> Add Integration**
and search for **Value Crossing**. The setup runs in two steps:

1. Name the pair and pick **Sensor A**.
2. Pick **Sensor B** (it must share Sensor A's unit), then set the **band**, the
   **estimation model** (`auto`, `exponential`, or `linear`), and the **fit
   window** in seconds (how much recent history feeds the estimate; default
   1800).

Each pair is its own integration entry. You can change any of these later with
**Reconfigure** on the device. Add another pair by adding the integration again.

## Status and limitations

Early and experimental. The `linear` and `exponential` estimation models work;
the dedicated power model is still in progress. The estimate extrapolates from
the recent trend, so on flat or near-constant signals the predicted ETA can be
noisy or flip between "crossing" and "no crossing"; treat it as a guide, not a
guarantee.

## Requirements

Home Assistant only. No extra Python dependencies (numpy ships with Home
Assistant). Verified on Home Assistant 2026.x.
