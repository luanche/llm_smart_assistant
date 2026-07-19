"""Action execution engine with whitelist interceptor for LLM Smart Assistant.

Parses LLM response steps and executes them safely through HA service calls.
Enforces domain/entity whitelisting and blocks restricted operations.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant

from .const import (
    ACTION_CALL_SERVICE,
    ACTION_CREATE_AUTOMATION,
    ACTION_GET_STATES,
    ACTION_TTS_SPEAK,
    ACTION_UPDATE_AUTOMATION_PROMPT,
    RESTRICTED_DOMAINS,
    RESTRICTED_SERVICES,
)

_LOGGER = logging.getLogger(__name__)


class StepInterceptionError(Exception):
    """Raised when a step is intercepted by the whitelist."""


class ServicesExecutor:
    """Executes parsed LLM action steps with whitelist enforcement."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator,
    ) -> None:
        self.hass = hass
        self.coordinator = coordinator

    async def async_execute_steps(self, steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Execute a list of action steps.

        Each step is validated against the whitelist before execution.
        Returns a list of step results.
        """
        results = []

        for step in steps:
            action = step.get("action", "")
            try:
                result = await self._async_execute_step(step)
                results.append({"action": action, "success": True, "result": result})
            except StepInterceptionError as exc:
                _LOGGER.warning("Step intercepted: %s", exc)
                results.append({"action": action, "success": False, "error": str(exc)})
            except Exception as exc:
                _LOGGER.error("Step execution failed: %s - %s", action, exc)
                results.append({"action": action, "success": False, "error": str(exc)})

        return results

    async def _async_execute_step(self, step: dict[str, Any]) -> Any:
        """Execute a single step after validation."""
        action = step.get("action", "")

        if action == ACTION_CALL_SERVICE:
            return await self._async_call_service(step)
        elif action == ACTION_CREATE_AUTOMATION:
            return await self._async_create_automation(step)
        elif action == ACTION_UPDATE_AUTOMATION_PROMPT:
            return self._handle_update_automation_prompt(step)
        elif action == ACTION_TTS_SPEAK:
            return await self._async_tts_speak(step)
        elif action == ACTION_GET_STATES:
            return await self._async_get_states(step)
        else:
            _LOGGER.warning("Unknown action type: %s", action)
            return None

    # ------------------------------------------------------------------
    # Whitelist Validation
    # ------------------------------------------------------------------

    def _validate_service_call(
        self, domain: str, service: str, target: dict[str, Any] | None
    ) -> None:
        """Validate that a service call is allowed by the whitelist."""
        # Block restricted domains
        if domain in RESTRICTED_DOMAINS:
            raise StepInterceptionError(
                f"Domain '{domain}' is restricted and cannot be controlled by LLM"
            )

        # Block restricted services
        full_service = f"{domain}.{service}"
        if full_service in RESTRICTED_SERVICES:
            raise StepInterceptionError(
                f"Service '{full_service}' is restricted"
            )

        # Check domain whitelist
        allowed_domains = self.coordinator.domains_whitelist
        if allowed_domains and domain not in allowed_domains:
            raise StepInterceptionError(
                f"Domain '{domain}' is not in the whitelist. "
                f"Allowed domains: {', '.join(allowed_domains)}"
            )

        # Check entity whitelist
        allowed_entities = self.coordinator.entities_whitelist
        if allowed_entities and target:
            target_entities = target.get("entity_id", [])
            if isinstance(target_entities, str):
                target_entities = [target_entities]
            for entity_id in target_entities:
                if entity_id not in allowed_entities:
                    raise StepInterceptionError(
                        f"Entity '{entity_id}' is not in the entity whitelist"
                    )

    # ------------------------------------------------------------------
        # Action Handlers
    # ------------------------------------------------------------------

    async def _async_call_service(self, step: dict[str, Any]) -> dict[str, Any]:
        """Execute a call_service action step."""
        domain = step.get("domain", "")
        service = step.get("service", "")
        target = step.get("target")
        service_data = step.get("service_data", {})

        if not domain or not service:
            raise ValueError("call_service requires 'domain' and 'service' fields")

        # Validate against whitelist
        self._validate_service_call(domain, service, target)

        # Build service call data
        call_data: dict[str, Any] = {}
        if target:
            call_data["entity_id"] = target.get("entity_id")
        call_data.update(service_data)

        # Log the action
        _LOGGER.info(
            "Executing service call: %s.%s with data: %s",
            domain,
            service,
            call_data,
        )

        # Execute via HA service call
        await self.hass.services.async_call(
            domain,
            service,
            call_data,
            blocking=True,
        )

        return {
            "domain": domain,
            "service": service,
            "target": target,
            "service_data": service_data,
        }

    async def _async_create_automation(self, step: dict[str, Any]) -> dict[str, Any]:
        """Handle create_automation action: create a dynamic automation."""
        if not self.coordinator.allow_automation:
            raise StepInterceptionError(
                "Dynamic automation creation is disabled in configuration"
            )

        entity_id = step.get("entity_id", "")
        condition = step.get("condition", "")
        prompt = step.get("prompt", "")

        if not entity_id or not condition:
            raise ValueError(
                "create_automation requires 'entity_id' and 'condition' fields"
            )

        automation_id = await self.coordinator.async_create_automation(
            entity_id=entity_id,
            condition=condition,
            prompt=prompt or self.coordinator.prompt_automation,
            description=step.get("description", ""),
        )

        if automation_id:
            _LOGGER.info(
                "Dynamic automation created: %s (entity=%s, condition=%s)",
                automation_id,
                entity_id,
                condition,
            )

        return {
            "automation_id": automation_id,
            "entity_id": entity_id,
            "condition": condition,
        }

    def _handle_update_automation_prompt(self, step: dict[str, Any]) -> dict[str, Any]:
        """Handle update_automation_prompt action."""
        # This would update the automation prompt for future queries
        # Since prompts are stored in options, we'd need to persist via config entry
        _LOGGER.warning(
            "update_automation_prompt action is not yet fully implemented"
        )
        return {"status": "not_implemented"}

    async def _async_tts_speak(self, step: dict[str, Any]) -> dict[str, Any]:
        """Handle tts_speak action: speak text via TTS."""
        text = step.get("text", "")

        if not text:
            raise ValueError("tts_speak requires 'text' field")

        await self.coordinator._async_speak_tts(text)

        return {"text": text}

    def _validate_get_states(self, entities: list[str]) -> None:
        """Validate that get_states entities are allowed by whitelist."""
        allowed_domains = self.coordinator.domains_whitelist
        allowed_entities = self.coordinator.entities_whitelist

        for entity_id in entities:
            domain = entity_id.split(".")[0] if "." in entity_id else entity_id

            # Check entity whitelist first
            if allowed_entities and entity_id not in allowed_entities:
                raise StepInterceptionError(
                    f"Entity '{entity_id}' is not in the entity whitelist"
                )

            # Check domain whitelist
            if allowed_domains and domain not in allowed_domains:
                raise StepInterceptionError(
                    f"Domain '{domain}' is not in the whitelist. "
                    f"Allowed domains: {', '.join(allowed_domains)}"
                )

    async def _async_get_states(self, step: dict[str, Any]) -> dict[str, Any]:
        """Handle get_states action: read entity states for the LLM to observe."""
        entities = step.get("entities", [])
        if isinstance(entities, str):
            entities = [entities]

        if not entities:
            raise ValueError("get_states requires 'entities' field with a list of entity_ids")

        # Enforce whitelist (same as call_service)
        self._validate_get_states(entities)

        observed = []
        for entity_id in entities:
            try:
                state_obj = self.hass.states.get(entity_id)
                if state_obj:
                    observed.append({
                        "entity_id": entity_id,
                        "state": state_obj.state,
                        "attributes": {
                            k: v for k, v in state_obj.attributes.items()
                            if k in ("friendly_name", "unit_of_measurement", "icon", "device_class")
                        },
                    })
                else:
                    observed.append({
                        "entity_id": entity_id,
                        "state": None,
                        "error": "Entity not found",
                    })
            except Exception as exc:
                observed.append({
                    "entity_id": entity_id,
                    "state": None,
                    "error": str(exc),
                })

        _LOGGER.debug("Observed states: %s", observed)
        return {"observed": observed}
