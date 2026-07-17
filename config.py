import os

from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv(usecwd=True))

BOT_TOKEN = os.environ["BOT_TOKEN"]
DB_PATH = os.environ.get("DB_PATH", "data/bot.db")
TRIGGER_WORDS_FILE = os.environ.get("TRIGGER_WORDS_FILE", "moderation/trigger_words.txt")

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct")
OPENROUTER_MAX_TOKENS = int(os.environ.get("OPENROUTER_MAX_TOKENS", "300"))
