"""Sensor platform for LLM Smart Assistant.

Provides diagnostic sensors to monitor the LLM's last response.
Uses coordinator callbacks to update state when new data arrives.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the LLM Smart Assistant sensor platform."""
    coordinator = hass.data[DOMAIN].get(config_entry.entry_id)
    if coordinator:
        async_add_entities([
            LLMLastResponseSensor(coordinator, config_entry.entry_id),
            LLMDebugRawSensor(coordinator, config_entry.entry_id),
        ])
        _LOGGER.info("LLM Smart Assistant sensors added successfully")
    else:
        _LOGGER.error("Coordinator not found for entry %s", config_entry.entry_id)


class LLMLastResponseSensor(SensorEntity):
    """Sensor showing the last LLM response text.

    Updates via coordinator callback whenever the LLM response changes.
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator, entry_id: str) -> None:
        """Initialize the sensor."""
        self.coordinator = coordinator
        self._attr_unique_id = f"{entry_id}_last_response"
        self._attr_name = "LLM Last Response"
        self._attr_icon = "mdi:robot-happy"

    async def async_added_to_hass(self) -> None:
        """Register coordinator callback for automatic updates."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )

    @property
    def state(self) -> str:
        """Return the last response TTS text."""
        if self.coordinator.last_response:
            return self.coordinator.last_response.get("tts_text", "")
        return ""

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes for frontend polling."""
        attrs = {
            "in_progress": self.coordinator.in_progress,
            "round": self.coordinator.current_round,
        }
        if self.coordinator.last_response:
            steps = self.coordinator.last_response.get("steps", [])
            attrs["steps"] = json.dumps(steps, ensure_ascii=False) if steps else "[]"
            attrs["has_steps"] = len(steps) > 0
            attrs["full_response"] = json.dumps(
                self.coordinator.last_response, ensure_ascii=False
            )
        return attrs


class LLMDebugRawSensor(SensorEntity):
    """Sensor showing the raw JSON of the last LLM response."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, entry_id: str) -> None:
        """Initialize the sensor."""
        self.coordinator = coordinator
        self._attr_unique_id = f"{entry_id}_debug_raw"
        self._attr_name = "LLM Debug Raw"
        self._attr_icon = "mdi:code-json"

    async def async_added_to_hass(self) -> None:
        """Register coordinator callback for automatic updates."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )

    @property
    def state(self) -> str:
        """Return the raw JSON string (truncated)."""
        raw = self.coordinator.last_response_raw
        return raw[:255] if raw else ""

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return full raw JSON."""
        return {
            "raw": self.coordinator.last_response_raw,
            "in_progress": self.coordinator.in_progress,
            "round": self.coordinator.current_round,
        }
