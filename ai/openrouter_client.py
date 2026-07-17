from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

import aiohttp

import config

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

MAX_TOOL_ROUNDS = 3

READ_TOOLS_REFERENCE = "read_tools_reference"
CALL_TOOL = "call_tool"

META_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": READ_TOOLS_REFERENCE,
            "description": (
                "Показать список доступных команд бота (модерация, триггер-слова, рассылка "
                "и т.п.) с описанием и нужными аргументами. Вызывай это, если пользователь "
                "спрашивает про возможности/команды бота, или перед тем как вызвать "
                "call_tool, чтобы узнать точное имя команды и её аргументы."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": CALL_TOOL,
            "description": (
                "Выполнить конкретную команду бота по её имени из каталога, полученного "
                "через read_tools_reference."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Имя команды из каталога."},
                    "arguments": {
                        "type": "object",
                        "description": "Аргументы команды согласно каталогу.",
                    },
                },
                "required": ["name"],
            },
        },
    },
]

SYSTEM_PROMPT = (
    "Ты — ассистент Telegram-бота модерации. У тебя есть два инструмента: "
    "read_tools_reference() — показывает список доступных команд бота с их аргументами; "
    "call_tool(name, arguments) — выполняет конкретную команду бота. "
    "Если вопрос не требует действий или списка команд — отвечай обычным текстом, не "
    "вызывая инструменты. Если пользователь спрашивает, что ты умеешь или какие есть "
    "команды, либо нужно выполнить модерационное действие (мьют, кик, триггер-слово и "
    "т.п.) — сначала вызови read_tools_reference, затем, если нужно выполнить действие, "
    "call_tool с точным именем команды из каталога."
)


class AIUnavailableError(Exception):
    pass


@dataclass
class AIResponse:
    text: Optional[str] = None
    tool_name: Optional[str] = None
    tool_arguments: dict = field(default_factory=dict)


def build_tools_reference(tools: list[dict]) -> str:
    if not tools:
        return "Нет доступных команд."

    lines: list[str] = []
    for schema in tools:
        function = schema.get("function", {})
        name = function.get("name", "")
        description = function.get("description", "")
        parameters = function.get("parameters") or {}
        properties = parameters.get("properties") or {}
        required = set(parameters.get("required") or [])

        lines.append(f"- {name}: {description}")
        if properties:
            for prop_name, prop_schema in properties.items():
                prop_type = prop_schema.get("type", "any")
                prop_desc = prop_schema.get("description", "")
                mark = " (обязательный)" if prop_name in required else ""
                lines.append(f"    • {prop_name} ({prop_type}){mark}: {prop_desc}")
        else:
            lines.append("    • без аргументов")

    return "\n".join(lines)


def _parse_arguments(raw_args: object) -> dict:
    try:
        arguments = json.loads(raw_args or "{}")
    except (json.JSONDecodeError, TypeError):
        arguments = {}
    return arguments if isinstance(arguments, dict) else {}


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
    """Ask the model, exposing only two lightweight meta-tools by default.

    Full tool schemas are never sent to the model. If it needs the real
    catalog (to answer "what can you do" or to perform a moderation action),
    it calls read_tools_reference first and gets the catalog built from
    `tools` back as a tool result, then decides whether to call call_tool.
    """
    if not config.OPENROUTER_API_KEY:
        raise AIUnavailableError("OPENROUTER_API_KEY is not configured")

    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]

    try:
        async with aiohttp.ClientSession() as session:
            for _ in range(MAX_TOOL_ROUNDS):
                async with session.post(
                    OPENROUTER_URL,
                    headers={"Authorization": f"Bearer {config.OPENROUTER_API_KEY}"},
                    json={
                        "model": config.OPENROUTER_MODEL,
                        "messages": messages,
                        "max_tokens": config.OPENROUTER_MAX_TOKENS,
                        "tools": META_TOOLS,
                        "tool_choice": "auto",
                    },
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as response:
                    if response.status != 200:
                        raise AIUnavailableError(
                            f"OpenRouter returned status {response.status}"
                        )
                    data = await response.json()

                try:
                    message = data["choices"][0]["message"]
                except (KeyError, IndexError, TypeError) as exc:
                    raise AIUnavailableError("Unexpected OpenRouter response shape") from exc

                tool_calls = message.get("tool_calls")
                if not tool_calls:
                    content = message.get("content")
                    if content:
                        return AIResponse(text=content.strip())
                    raise AIUnavailableError("Unexpected OpenRouter response shape")

                call = tool_calls[0]
                function = call.get("function", {})
                name = function.get("name")
                arguments = _parse_arguments(function.get("arguments"))

                if name == CALL_TOOL:
                    tool_arguments = arguments.get("arguments")
                    return AIResponse(
                        tool_name=arguments.get("name"),
                        tool_arguments=tool_arguments if isinstance(tool_arguments, dict) else {},
                    )

                reference_text = (
                    build_tools_reference(tools)
                    if name == READ_TOOLS_REFERENCE
                    else "Неизвестный инструмент."
                )

                messages.append(message)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id", ""),
                        "content": reference_text,
                    }
                )
    except aiohttp.ClientError as exc:
        raise AIUnavailableError(str(exc)) from exc

    raise AIUnavailableError("Tool resolution exceeded max rounds")
