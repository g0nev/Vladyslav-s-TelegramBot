from __future__ import annotations

import os
from typing import Optional

import aiosqlite

SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "models.sql")


class Repository:
    def __init__(self, connection: aiosqlite.Connection):
        self._conn = connection

    @classmethod
    async def create(cls, db_path: str) -> "Repository":
        directory = os.path.dirname(db_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        conn = await aiosqlite.connect(db_path)
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            await conn.executescript(f.read())
        await conn.commit()
        return cls(conn)

    async def close(self) -> None:
        await self._conn.close()

    async def get_chat_settings(self, chat_id: int) -> tuple[int, int]:
        await self._conn.execute(
            "INSERT OR IGNORE INTO chat_settings (chat_id) VALUES (?)", (chat_id,)
        )
        await self._conn.commit()
        cursor = await self._conn.execute(
            "SELECT broadcast_interval_min, reset_days FROM chat_settings WHERE chat_id = ?",
            (chat_id,),
        )
        row = await cursor.fetchone()
        return (row[0], row[1])

    async def set_broadcast_interval(self, chat_id: int, minutes: int) -> None:
        await self.get_chat_settings(chat_id)
        await self._conn.execute(
            "UPDATE chat_settings SET broadcast_interval_min = ? WHERE chat_id = ?",
            (minutes, chat_id),
        )
        await self._conn.commit()

    async def set_reset_days(self, chat_id: int, days: int) -> None:
        await self.get_chat_settings(chat_id)
        await self._conn.execute(
            "UPDATE chat_settings SET reset_days = ? WHERE chat_id = ?",
            (days, chat_id),
        )
        await self._conn.commit()

    async def add_trigger_word(self, chat_id: int, word: str) -> None:
        await self._conn.execute(
            "INSERT OR IGNORE INTO trigger_words (chat_id, word) VALUES (?, ?)",
            (chat_id, word.lower()),
        )
        await self._conn.commit()

    async def delete_trigger_word(self, chat_id: int, word: str) -> bool:
        cursor = await self._conn.execute(
            "DELETE FROM trigger_words WHERE chat_id = ? AND word = ?",
            (chat_id, word.lower()),
        )
        await self._conn.commit()
        return cursor.rowcount > 0

    async def list_trigger_words(self, chat_id: int) -> list[str]:
        cursor = await self._conn.execute(
            "SELECT word FROM trigger_words WHERE chat_id = ?", (chat_id,)
        )
        rows = await cursor.fetchall()
        return [row[0] for row in rows]

    async def get_warning(self, chat_id: int, user_id: int) -> tuple[int, Optional[str]]:
        cursor = await self._conn.execute(
            "SELECT count, last_violation_at FROM warnings WHERE chat_id = ? AND user_id = ?",
            (chat_id, user_id),
        )
        row = await cursor.fetchone()
        if row is None:
            return (0, None)
        return (row[0], row[1])

    async def set_warning(
        self, chat_id: int, user_id: int, count: int, last_violation_at: str
    ) -> None:
        await self._conn.execute(
            """
            INSERT INTO warnings (chat_id, user_id, count, last_violation_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(chat_id, user_id) DO UPDATE SET
                count = excluded.count,
                last_violation_at = excluded.last_violation_at
            """,
            (chat_id, user_id, count, last_violation_at),
        )
        await self._conn.commit()

    async def reset_warning(self, chat_id: int, user_id: int) -> None:
        await self._conn.execute(
            "DELETE FROM warnings WHERE chat_id = ? AND user_id = ?",
            (chat_id, user_id),
        )
        await self._conn.commit()

    async def add_broadcast_message(self, chat_id: int, text: str) -> int:
        cursor = await self._conn.execute(
            "INSERT INTO broadcast_messages (chat_id, text) VALUES (?, ?)",
            (chat_id, text),
        )
        await self._conn.commit()
        return cursor.lastrowid

    async def delete_broadcast_message(self, chat_id: int, message_id: int) -> bool:
        cursor = await self._conn.execute(
            "DELETE FROM broadcast_messages WHERE chat_id = ? AND id = ?",
            (chat_id, message_id),
        )
        await self._conn.commit()
        return cursor.rowcount > 0

    async def list_broadcast_messages(self, chat_id: int) -> list[tuple[int, str]]:
        cursor = await self._conn.execute(
            "SELECT id, text FROM broadcast_messages WHERE chat_id = ?", (chat_id,)
        )
        rows = await cursor.fetchall()
        return [(row[0], row[1]) for row in rows]

    async def list_active_broadcast_chats(self) -> list[tuple[int, int]]:
        cursor = await self._conn.execute(
            "SELECT chat_id, broadcast_interval_min FROM chat_settings "
            "WHERE broadcast_interval_min > 0"
        )
        rows = await cursor.fetchall()
        return [(row[0], row[1]) for row in rows]
