from __future__ import annotations

import aiohttp

import config

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class AIUnavailableError(Exception):
    pass


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
