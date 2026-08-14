import os

from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv(usecwd=True))

BOT_TOKEN = os.environ["BOT_TOKEN"]
DB_PATH = os.environ.get("DB_PATH", "data/bot.db")
TRIGGER_WORDS_FILE = os.environ.get("TRIGGER_WORDS_FILE", "moderation/trigger_words.txt")

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct")
OPENROUTER_MAX_TOKENS = int(os.environ.get("OPENROUTER_MAX_TOKENS", "300"))

TELEGRAM_API_ID = int(os.environ.get("TELEGRAM_API_ID", "0"))
TELEGRAM_API_HASH = os.environ.get("TELEGRAM_API_HASH", "")
TELETHON_SESSION_STRING = os.environ.get("TELETHON_SESSION_STRING", "")
HISTORY_FETCH_LIMIT = int(os.environ.get("HISTORY_FETCH_LIMIT", "1000"))
HISTORY_CACHE_TTL_SECONDS = int(os.environ.get("HISTORY_CACHE_TTL_SECONDS", "120"))
HISTORY_FETCH_TIMEOUT_SECONDS = int(os.environ.get("HISTORY_FETCH_TIMEOUT_SECONDS", "20"))
