# Vladyslav Telegram Bot

A Telegram bot for group moderation, administration and AI-assisted workflows.

The project combines Telegram bot commands was will, moderation rules, scheduled actions, chat history access and configurable AI tools through OpenRouter.

## Features

- Group moderation with trigger-word filters
- Mute and kick actions for administrators
- Group administration commands for title, description, photo and permissions
- Pin and unpin message commands
- Invite link management and join request actions
- Scheduled and proactive broadcasts
- AI-assisted `/ask` command
- Optional chat history retrieval through Telethon
- SQLite-backed repository layer

## Project structure

```text
admin/       Administrative commands and permission checks
ai/          OpenRouter client, tools and AI handlers
db/          Database models and repository code
history/     Telegram history access through Telethon
moderation/  Trigger filters and moderation actions
proactive/   Proactive message buffering and delivery
scheduler/   Scheduled broadcasts and jobs
scripts/     Local utility scripts
tests/       Automated tests
```

## Configuration

Copy the example environment file and fill in the values required for your setup:

```bash
cp .env.example .env
```

Required variable:

- `BOT_TOKEN` - token issued by BotFather

Optional variables enable AI responses and Telegram history access:

- `OPENROUTER_API_KEY`
- `TELEGRAM_API_ID`
- `TELEGRAM_API_HASH`
- `TELETHON_SESSION_STRING`
- `HISTORY_FETCH_TIMEOUT_SECONDS`

The bot needs administrator permissions in a group for moderation and management commands. See [docs/RUNBOOK.md](docs/RUNBOOK.md) for the required Telegram permissions.

## Install and run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python bot.py
```

## Tests

Run the test suite with:

```bash
pytest
```

## Security

Never commit `.env`, Telegram session strings, bot tokens or API keys. Use `.env.example` as the safe configuration template.
