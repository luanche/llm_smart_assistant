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
        title = coordinator.title or config_entry.title or ""
        async_add_entities([
            LLMLastResponseSensor(coordinator, config_entry.entry_id, title),
            LLMDebugRawSensor(coordinator, config_entry.entry_id, title),
            LLMLastInputSensor(coordinator, config_entry.entry_id, title),
        ])
        _LOGGER.info("LLM Smart Assistant sensors added successfully")
    else:
        _LOGGER.error("Coordinator not found for entry %s", config_entry.entry_id)


class LLMLastInputSensor(SensorEntity):
    """Sensor showing the last user input text.

    Updated whenever the coordinator processes any user input (chat panel,
    service call, or voice input sensor). Its state history in the recorder is
    the source for chat history user messages.
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator, entry_id: str, title: str = "") -> None:
        """Initialize the sensor."""
        self.coordinator = coordinator
        self._attr_unique_id = f"{entry_id}_last_input"
        self._attr_name = f"LLM Last Input ({title})" if title else "LLM Last Input"
        self._attr_icon = "mdi:keyboard-outline"

    async def async_added_to_hass(self) -> None:
        """Register coordinator callback for automatic updates."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )

    @property
    def state(self) -> str:
        """Return the last user input text."""
        return self.coordinator.last_input

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return input source metadata."""
        return {
            "source_entity": self.coordinator.last_input_entity,
            "input_time": self.coordinator.last_input_time,
        }


class LLMLastResponseSensor(SensorEntity):
    """Sensor showing the last LLM response text.

    Updates via coordinator callback whenever the LLM response changes.
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator, entry_id: str, title: str = "") -> None:
        """Initialize the sensor."""
        self.coordinator = coordinator
        self._attr_unique_id = f"{entry_id}_last_response"
        # Include the instance title so multi-instance sensors get distinct
        # entity_ids instead of colliding (sensor.llm_last_response_2, ...)
        self._attr_name = f"LLM Last Response ({title})" if title else "LLM Last Response"
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
            "last_input": self.coordinator.last_input,
            "last_input_entity": self.coordinator.last_input_entity,
            "last_input_time": self.coordinator.last_input_time,
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

    def __init__(self, coordinator, entry_id: str, title: str = "") -> None:
        """Initialize the sensor."""
        self.coordinator = coordinator
        self._attr_unique_id = f"{entry_id}_debug_raw"
        self._attr_name = f"LLM Debug Raw ({title})" if title else "LLM Debug Raw"
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
        """Return full raw JSON and the prompt that was sent.

        Truncated so the whole attribute set stays under HA's 16384-byte
        recorder limit (otherwise attributes are silently not stored in
        history). The full prompt can exceed that because the system prompt
        embeds the whole exposed-entities list.
        """
        # Keep the total attribute payload safely under 16 KiB
        max_raw = 8000
        max_prompt = 7000

        raw = self.coordinator.last_response_raw or ""
        if len(raw) > max_raw:
            raw = raw[:max_raw] + f"\n...[truncated, {len(raw) - max_raw} chars omitted]"

        prompt_msgs = self.coordinator.last_prompt_messages
        prompt_preview = ""
        if prompt_msgs:
            # Full system and user prompt (no truncation)
            sys_msg = next((m["content"] for m in prompt_msgs if m["role"] == "system"), "")
            user_msg = next((m["content"] for m in prompt_msgs if m["role"] == "user"), "")
            msg_count = len(prompt_msgs)
            prompt_preview = f"[{msg_count} messages]\n--- SYSTEM ---\n{sys_msg}\n--- USER ---\n{user_msg}"
            if len(prompt_preview) > max_prompt:
                prompt_preview = prompt_preview[:max_prompt] + f"\n...[truncated, {len(prompt_preview) - max_prompt} chars omitted]"
        return {
            "raw": raw,
            "prompt": prompt_preview,
            "in_progress": self.coordinator.in_progress,
            "round": self.coordinator.current_round,
        }
