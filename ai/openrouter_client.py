from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

import aiohttp

import config
from db.repository import Repository

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

MAX_TOOL_ROUNDS = 3

READ_TOOLS_REFERENCE = "read_tools_reference"
READ_GENERAL_INFO = "read_general_info"
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
            "name": READ_GENERAL_INFO,
            "description": (
                "Показать общую информацию: что за бот и чем занимается, кто разработчик, "
                "как устроена логика модерации (эскалация наказаний), и текущие настройки "
                "этого чата (автосброс предупреждений, интервал рассылки, тексты наказаний). "
                "Вызывай это для вопросов о боте/разработчике/правилах модерации/настройках "
                "чата — а не для вопросов о списке команд (для этого read_tools_reference)."
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
    "Ты — участник этого Telegram-чата, отвечаешь на вопросы по команде /ask. "
    "Общайся неформально и по-дружески, как обычный собеседник в переписке (в духе "
    "ChatGPT/Claude/Gemini), а не как техническая справочная система: живо, коротко по "
    "делу, без канцелярита, можно шутить в тон. Если пользователь спрашивает твоё мнение, "
    "зовёт что-то обсудить или посоветоваться — отвечай от себя своими словами, а не "
    "сухим перечислением.\n\n"
    "За кулисами (пользователь про них не знает и сам их не называет) у тебя есть три "
    "служебные функции: read_tools_reference() — каталог реальных команд бота с "
    "аргументами; read_general_info() — информация о боте, разработчике, логике "
    "модерации и текущих настройках этого чата; call_tool(name, arguments) — выполнение "
    "конкретной команды по её точному имени из каталога.\n\n"
    "Дёргай их только когда пользователь явно просит выполнить действие или прямо "
    "спрашивает про твои возможности/бота/настройки: «что ты умеешь», «какие есть "
    "команды» → read_tools_reference; вопрос про бота/разработчика/правила модерации/"
    "настройки чата → read_general_info; явная просьба выполнить модерационное действие "
    "(замьютить, кикнуть, добавить/удалить триггер-слово и т.п.) → сначала "
    "read_tools_reference, затем call_tool с точным именем команды из каталога.\n\n"
    "Если пользователь не просит действие, а рассуждает или советуется на тему "
    "(например «как думаешь, каких слов не хватает в стоп-листе» или «можно что-то ещё "
    "добавить или и так хватит?») — это не команда: обсуди с ним, предложи свои варианты "
    "обычным текстом и не вызывай ни один инструмент, пока он явно не подтвердит, что "
    "именно сделать. То же самое с простым приветствием («привет», «здарова» и т.п.), "
    "благодарностью или репликой не по делу — просто ответь в тон, без вызова "
    "инструментов и без перечисления своих возможностей по собственной инициативе.\n\n"
    "Результат read_general_info и read_tools_reference — справочные данные для тебя, а "
    "не готовый ответ: после получения отвечай кратко и по существу вопроса своими "
    "словами, не копируя и не пересказывая инструмент целиком, если явно не просили "
    "полную информацию обо всём сразу. Если в сообщении несколько разных вопросов — "
    "ответь на каждый из них, вызвав все нужные инструменты по очереди, прежде чем дать "
    "финальный ответ. Если вопрос можно закрыть, выполнив доступную команду (например "
    "list_trigger_words, чтобы показать реальный список слов) — вызови её через "
    "call_tool и покажи результат, а не объясняй пользователю, как вызвать команду "
    "самому.\n\n"
    "При вызове add_trigger_word никогда не подставляй шаблонные плейсхолдеры вида "
    "«слово_1», «слово_2» вместо реальных слов — указывай настоящие слова каждое "
    "отдельным элементом списка.\n\n"
    "Ответ форматируется как Markdown: имена инструментов и команд (например, "
    "mute_user) всегда оборачивай в обратные кавычки (`mute_user`), иначе символы "
    "подчёркивания в имени сломают отображение."
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


async def build_general_info(chat_id: int, repository: Repository) -> str:
    broadcast_interval, reset_days = await repository.get_chat_settings(chat_id)
    warn_message, mute_message, kick_message = await repository.get_message_templates(chat_id)
    mute_minutes, kick_after = await repository.get_escalation_settings(chat_id)
    persona = await repository.get_persona(chat_id)

    def _template(text: Optional[str]) -> str:
        return text if text else "не задан (используется стандартный)"

    if kick_after <= 2:
        escalation_rule = (
            f"1-е нарушение — предупреждение; {kick_after}-е и далее — кик из чата, "
            "счётчик сбрасывается."
        )
    else:
        escalation_rule = (
            f"1-е нарушение — предупреждение; со 2-го по {kick_after - 1}-е — мьют на "
            f"{mute_minutes} мин.; {kick_after}-е и далее — кик из чата, счётчик сбрасывается."
        )

    return (
        "О боте: это Telegram-бот модерации чата, который также отвечает на вопросы "
        "через ИИ по команде /ask.\n"
        "Разработчик: Владислав Звездаев. Если спросят конкретно, кто такой Владислав "
        "(а не просто кто разработчик) — ему 22 года, он фронтенд-разработчик.\n"
        f"Логика модерации: {escalation_rule}\n"
        "Настройки этого чата:\n"
        f"    • автосброс счётчика предупреждений: {reset_days} дн. (0 = никогда)\n"
        f"    • интервал автоматической рассылки: {broadcast_interval} мин. (0 = выключено)\n"
        f"    • текст предупреждения: {_template(warn_message)}\n"
        f"    • текст мьюта: {_template(mute_message)}\n"
        f"    • текст кика: {_template(kick_message)}\n"
        f"    • характер/стиль общения: {persona if persona else 'не задан (обычный стиль)'}"
    )


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


async def ask_ai_with_tools(
    question: str, tools: list[dict], *, repository: Repository, chat_id: int
) -> AIResponse:
    """Ask the model, exposing only lightweight meta-tools by default.

    Full tool schemas are never sent to the model. If it needs the real
    catalog (to answer "what can you do" or to perform a moderation action),
    it calls read_tools_reference first and gets the catalog built from
    `tools` back as a tool result, then decides whether to call call_tool.
    Questions about the bot/developer/moderation rules/chat settings are
    answered the same way via read_general_info.
    """
    if not config.OPENROUTER_API_KEY:
        raise AIUnavailableError("OPENROUTER_API_KEY is not configured")

    persona = await repository.get_persona(chat_id)
    system_content = SYSTEM_PROMPT
    if persona:
        system_content += (
            "\n\nДополнительно, стиль и характер общения в этом чате задал админ: "
            + persona
        )

    messages: list[dict] = [
        {"role": "system", "content": system_content},
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

                if name == READ_TOOLS_REFERENCE:
                    reference_text = build_tools_reference(tools)
                elif name == READ_GENERAL_INFO:
                    reference_text = await build_general_info(chat_id, repository)
                else:
                    reference_text = "Неизвестный инструмент."

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


_REACTION_TIMEOUT = aiohttp.ClientTimeout(total=10)

_PUNISHMENT_OUTCOMES = {
    "warn": "получил предупреждение",
    "mute": "получил ограничение на отправку сообщений на {minutes} минут",
    "kick": "был удалён из чата",
}


async def generate_violation_reaction(
    persona: str, punishment: str, mute_minutes: int
) -> Optional[str]:
    """Single non-tool completion call for a moderation reaction line.

    Swallows every failure mode (missing key, non-200, network error,
    timeout, malformed/empty response) into None so the caller can fall
    back to the static punishment template without a try/except.
    """
    if not config.OPENROUTER_API_KEY:
        return None

    outcome = _PUNISHMENT_OUTCOMES[punishment].format(minutes=mute_minutes)
    task_prompt = (
        f"Характер бота в этом чате: {persona}\n"
        f"Пользователь нарушил правила чата и {outcome} за мат/оскорбления. "
        "Напиши одну короткую (1-2 предложения) реакцию в чат в этом стиле. "
        "Не обращайся к пользователю по имени и не добавляй никаких упоминаний — "
        "обращение бот добавит сам."
    )

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                OPENROUTER_URL,
                headers={"Authorization": f"Bearer {config.OPENROUTER_API_KEY}"},
                json={
                    "model": config.OPENROUTER_MODEL,
                    "messages": [{"role": "user", "content": task_prompt}],
                    "max_tokens": config.OPENROUTER_MAX_TOKENS,
                },
                timeout=_REACTION_TIMEOUT,
            ) as response:
                if response.status != 200:
                    return None
                data = await response.json()
    except (aiohttp.ClientError, TimeoutError, ValueError):
        return None

    try:
        text = data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError, AttributeError):
        return None

    return text or None
