"""The value_crossing integration.

Each config entry is one crossing pair (two sensors of the same unit). It exposes
the signed difference, a "crossed" binary sensor, and two estimate sensors
(time-until-crossover and ETA). On setup the estimate buffer is primed from
recorder history so the estimate is available shortly after a restart.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import PairCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]

type ValueCrossingConfigEntry = ConfigEntry[PairCoordinator]


async def async_setup_entry(
    hass: HomeAssistant, entry: ValueCrossingConfigEntry
) -> bool:
    """Set up a crossing pair from a config entry."""
    coordinator = PairCoordinator(hass, entry)
    entry.runtime_data = coordinator
    await coordinator.async_prime_from_history()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: ValueCrossingConfigEntry
) -> bool:
    """Unload a config entry and its entities."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(
    hass: HomeAssistant, entry: ValueCrossingConfigEntry
) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)
