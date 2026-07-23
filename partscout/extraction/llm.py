# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)

# Explicit tool schema — avoids Pydantic oneOf/anyOf quirks with the Anthropic API
_EXTRACTION_TOOL: dict[str, Any] = {
    "name": "extract_listing",
    "description": "Extract structured listing data from a marketplace post or forum message.",
    "input_schema": {
        "type": "object",
        "properties": {
            "kind": {
                "type": "string",
                "enum": ["wtb", "fs", "other"],
                "description": "wtb=want to buy, fs=for sale, other=not a listing",
            },
            "vehicle": {
                "type": "object",
                "properties": {
                    "make": {"type": ["string", "null"]},
                    "model": {"type": ["string", "null"]},
                    "year_from": {"type": ["integer", "null"]},
                    "year_to": {"type": ["integer", "null"]},
                },
                "required": ["make", "model", "year_from", "year_to"],
            },
            "part": {
                "type": "object",
                "properties": {
                    "name_en": {"type": "string"},
                    "name_original": {"type": "string"},
                    "part_numbers": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["name_en", "name_original", "part_numbers"],
            },
            "condition": {
                "type": "string",
                "enum": ["used", "new", "any", "unknown"],
            },
            "price": {
                "description": "null if price not mentioned",
                "oneOf": [
                    {
                        "type": "object",
                        "properties": {
                            "value": {"type": ["number", "null"]},
                            "currency": {"type": ["string", "null"]},
                        },
                        "required": ["value", "currency"],
                    },
                    {"type": "null"},
                ],
            },
            "location_country": {
                "type": ["string", "null"],
                "description": "ISO 3166-1 alpha-2",
            },
            "confidence": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
            },
        },
        "required": [
            "kind",
            "vehicle",
            "part",
            "condition",
            "price",
            "location_country",
            "confidence",
        ],
    },
}

_VERIFICATION_TOOL: dict[str, Any] = {
    "name": "verify_match",
    "description": "Decide whether a WTB listing matches a FS listing.",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {
                "type": "string",
                "enum": ["match", "likely", "no"],
            },
            "reason": {"type": "string"},
        },
        "required": ["verdict", "reason"],
    },
}


class LLMClient(ABC):
    @abstractmethod
    def call(
        self,
        system: str,
        user: str,
        tool: dict[str, Any],
    ) -> dict[str, Any]:
        """Call the LLM and return the tool-use result as a dict."""


class AnthropicClient(LLMClient):
    def __init__(self, model: str, api_key: str, max_retries: int = 5) -> None:
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key, max_retries=max_retries)
        self._model = model

    def call(
        self,
        system: str,
        user: str,
        tool: dict[str, Any],
    ) -> dict[str, Any]:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": user}],
            tools=[tool],
            tool_choice={"type": "tool", "name": tool["name"]},
        )
        logger.debug(
            "Anthropic tokens: input=%d output=%d model=%s",
            response.usage.input_tokens,
            response.usage.output_tokens,
            self._model,
        )
        for block in response.content:
            if block.type == "tool_use":
                return block.input  # type: ignore[return-value]
        raise RuntimeError(f"No tool_use block in response: {response.content}")


class OpenAICompatibleClient(LLMClient):
    """Works with any OpenAI-compatible endpoint (Gemini, Ollama, etc.)."""

    def __init__(self, model: str, api_key: str, base_url: str) -> None:
        import httpx

        self._model = model
        self._base_url = base_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        self._http = httpx.Client(timeout=60)

    def call(
        self,
        system: str,
        user: str,
        tool: dict[str, Any],
    ) -> dict[str, Any]:
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "tools": [{"type": "function", "function": tool}],
            "tool_choice": {"type": "function", "function": {"name": tool["name"]}},
        }
        resp = self._http.post(f"{self._base_url}/chat/completions", json=payload)
        resp.raise_for_status()
        data = resp.json()
        logger.debug(
            "OpenAI-compat tokens: %s model=%s",
            data.get("usage"),
            self._model,
        )
        args_str = (
            data["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]
        )
        return json.loads(args_str)  # type: ignore[no-any-return]


def build_client(
    provider: str,
    model: str,
    api_key: str,
    base_url: str | None = None,
    max_retries: int = 5,
) -> LLMClient:
    if provider == "anthropic":
        return AnthropicClient(model=model, api_key=api_key, max_retries=max_retries)
    if provider == "openai_compatible":
        if not base_url:
            raise ValueError("base_url required for openai_compatible provider")
        return OpenAICompatibleClient(model=model, api_key=api_key, base_url=base_url)
    raise ValueError(f"Unknown LLM provider: {provider!r}")


EXTRACTION_TOOL = _EXTRACTION_TOOL
VERIFICATION_TOOL = _VERIFICATION_TOOL
