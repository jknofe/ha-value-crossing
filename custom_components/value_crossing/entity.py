"""Shared base entity for value_crossing (Bronze ``has-entity-name``).

Every entity gets ``has_entity_name`` + a translation_key, a stable unique id
derived from the entry id, and subscribes to the pair coordinator in its own
lifecycle (Bronze ``entity-event-setup``). No device link: a pair has two source
entities, so we follow the multi-source helper precedent and stay standalone.
"""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .coordinator import PairCoordinator


class ValueCrossingEntity(Entity):
    """Base for all value_crossing entities."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: PairCoordinator, key: str) -> None:
        """Wire the entity to its pair coordinator under translation ``key``."""
        self.coordinator = coordinator
        self._attr_translation_key = key
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{key}"
        # Our own per-pair service device groups the four entities under the
        # pair name (and gives has_entity_name its prefix). This is NOT the
        # source sensors' device.
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name=coordinator.name,
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to source changes for this entity's lifetime."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )
