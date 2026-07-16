from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

import aiohttp

import config

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class AIUnavailableError(Exception):
    pass


@dataclass
class AIResponse:
    text: Optional[str] = None
    tool_name: Optional[str] = None
    tool_arguments: dict = field(default_factory=dict)


async def ask_ai(question: str) -> str:
    if not config.OPENROUTER_API_KEY:
        raise AIUnavailableError("OPENROUTER_API_KEY is not configured")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                OPENROUTER_URL,
                headers={"Authorization": f"Bearer {config.OPENROUTER_API_KEY}"},
                json={
                    "model": config.OPENROUTER_MODEL,
                    "messages": [{"role": "user", "content": question}],
                    "max_tokens": config.OPENROUTER_MAX_TOKENS,
                },
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                if response.status != 200:
                    raise AIUnavailableError(f"OpenRouter returned status {response.status}")
                data = await response.json()
    except aiohttp.ClientError as exc:
        raise AIUnavailableError(str(exc)) from exc

    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise AIUnavailableError("Unexpected OpenRouter response shape") from exc


async def ask_ai_with_tools(question: str, tools: list[dict]) -> AIResponse:
    if not config.OPENROUTER_API_KEY:
        raise AIUnavailableError("OPENROUTER_API_KEY is not configured")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                OPENROUTER_URL,
                headers={"Authorization": f"Bearer {config.OPENROUTER_API_KEY}"},
                json={
                    "model": config.OPENROUTER_MODEL,
                    "messages": [{"role": "user", "content": question}],
                    "max_tokens": config.OPENROUTER_MAX_TOKENS,
                    "tools": tools,
                    "tool_choice": "auto",
                },
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                if response.status != 200:
                    raise AIUnavailableError(f"OpenRouter returned status {response.status}")
                data = await response.json()
    except aiohttp.ClientError as exc:
        raise AIUnavailableError(str(exc)) from exc

    try:
        message = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise AIUnavailableError("Unexpected OpenRouter response shape") from exc

    tool_calls = message.get("tool_calls")
    if tool_calls:
        function = tool_calls[0].get("function", {})
        name = function.get("name")
        raw_args = function.get("arguments") or "{}"
        try:
            arguments = json.loads(raw_args)
        except (json.JSONDecodeError, TypeError):
            arguments = {}
        if not isinstance(arguments, dict):
            arguments = {}
        return AIResponse(tool_name=name, tool_arguments=arguments)

    content = message.get("content")
    if content:
        return AIResponse(text=content.strip())

    raise AIUnavailableError("Unexpected OpenRouter response shape")
