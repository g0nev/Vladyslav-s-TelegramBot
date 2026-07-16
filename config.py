import os

from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv(usecwd=True))

BOT_TOKEN = os.environ["BOT_TOKEN"]
DB_PATH = os.environ.get("DB_PATH", "data/bot.db")
TRIGGER_WORDS_FILE = os.environ.get("TRIGGER_WORDS_FILE", "moderation/trigger_words.txt")
