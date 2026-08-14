"""Одноразовый скрипт: авторизует личный Telegram-аккаунт для userbot-клиента.

Запускать локально вручную (не на проде) — спросит номер телефона, код из
Telegram и, если включена, 2FA-пароль. В конце печатает session string,
который нужно сохранить в .env как TELETHON_SESSION_STRING.
"""
from telethon import TelegramClient
from telethon.sessions import StringSession


def main() -> None:
    api_id = int(input("API_ID (с my.telegram.org): "))
    api_hash = input("API_HASH (с my.telegram.org): ")

    with TelegramClient(StringSession(), api_id, api_hash) as client:
        print("\nСохраните это значение в .env как TELETHON_SESSION_STRING:\n")
        print(client.session.save())


if __name__ == "__main__":
    main()
