from __future__ import annotations

import os
import sqlite3
from typing import Optional

import aiosqlite

SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "models.sql")

_MIGRATION_COLUMNS = {
    "warn_message": "TEXT",
    "mute_message": "TEXT",
    "kick_message": "TEXT",
    "saved_permissions_json": "TEXT",
    "last_invite_link": "TEXT",
    "mute_minutes": "INTEGER NOT NULL DEFAULT 5",
    "kick_after_violation": "INTEGER NOT NULL DEFAULT 3",
    "persona": "TEXT",
    "proactive_mode": "TEXT NOT NULL DEFAULT 'off'",
    "proactive_interval_min": "INTEGER NOT NULL DEFAULT 0",
    "proactive_probability": "REAL NOT NULL DEFAULT 0.0",
    "proactive_context_size": "INTEGER NOT NULL DEFAULT 3",
    "max_tokens": "INTEGER NOT NULL DEFAULT 300",
}


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
        for column, column_type in _MIGRATION_COLUMNS.items():
            try:
                await conn.execute(
                    f"ALTER TABLE chat_settings ADD COLUMN {column} {column_type}"
                )
            except sqlite3.OperationalError:
                pass
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

    async def get_message_templates(
        self, chat_id: int
    ) -> tuple[Optional[str], Optional[str], Optional[str]]:
        await self.get_chat_settings(chat_id)
        cursor = await self._conn.execute(
            "SELECT warn_message, mute_message, kick_message FROM chat_settings WHERE chat_id = ?",
            (chat_id,),
        )
        row = await cursor.fetchone()
        return (row[0], row[1], row[2])

    async def set_warn_message(self, chat_id: int, text: Optional[str]) -> None:
        await self.get_chat_settings(chat_id)
        await self._conn.execute(
            "UPDATE chat_settings SET warn_message = ? WHERE chat_id = ?", (text, chat_id)
        )
        await self._conn.commit()

    async def set_mute_message(self, chat_id: int, text: Optional[str]) -> None:
        await self.get_chat_settings(chat_id)
        await self._conn.execute(
            "UPDATE chat_settings SET mute_message = ? WHERE chat_id = ?", (text, chat_id)
        )
        await self._conn.commit()

    async def set_kick_message(self, chat_id: int, text: Optional[str]) -> None:
        await self.get_chat_settings(chat_id)
        await self._conn.execute(
            "UPDATE chat_settings SET kick_message = ? WHERE chat_id = ?", (text, chat_id)
        )
        await self._conn.commit()

    async def reset_message_templates(self, chat_id: int) -> None:
        await self.get_chat_settings(chat_id)
        await self._conn.execute(
            "UPDATE chat_settings SET warn_message = NULL, mute_message = NULL, "
            "kick_message = NULL WHERE chat_id = ?",
            (chat_id,),
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

    async def get_saved_permissions(self, chat_id: int) -> Optional[str]:
        await self.get_chat_settings(chat_id)
        cursor = await self._conn.execute(
            "SELECT saved_permissions_json FROM chat_settings WHERE chat_id = ?", (chat_id,)
        )
        row = await cursor.fetchone()
        return row[0]

    async def set_saved_permissions(self, chat_id: int, permissions_json: Optional[str]) -> None:
        await self.get_chat_settings(chat_id)
        await self._conn.execute(
            "UPDATE chat_settings SET saved_permissions_json = ? WHERE chat_id = ?",
            (permissions_json, chat_id),
        )
        await self._conn.commit()

    async def get_last_invite_link(self, chat_id: int) -> Optional[str]:
        await self.get_chat_settings(chat_id)
        cursor = await self._conn.execute(
            "SELECT last_invite_link FROM chat_settings WHERE chat_id = ?", (chat_id,)
        )
        row = await cursor.fetchone()
        return row[0]

    async def set_last_invite_link(self, chat_id: int, link: Optional[str]) -> None:
        await self.get_chat_settings(chat_id)
        await self._conn.execute(
            "UPDATE chat_settings SET last_invite_link = ? WHERE chat_id = ?",
            (link, chat_id),
        )
        await self._conn.commit()

    async def get_escalation_settings(self, chat_id: int) -> tuple[int, int]:
        await self.get_chat_settings(chat_id)
        cursor = await self._conn.execute(
            "SELECT mute_minutes, kick_after_violation FROM chat_settings WHERE chat_id = ?",
            (chat_id,),
        )
        row = await cursor.fetchone()
        return (row[0], row[1])

    async def set_mute_minutes(self, chat_id: int, minutes: int) -> None:
        await self.get_chat_settings(chat_id)
        await self._conn.execute(
            "UPDATE chat_settings SET mute_minutes = ? WHERE chat_id = ?", (minutes, chat_id)
        )
        await self._conn.commit()

    async def set_kick_after(self, chat_id: int, violations: int) -> None:
        await self.get_chat_settings(chat_id)
        await self._conn.execute(
            "UPDATE chat_settings SET kick_after_violation = ? WHERE chat_id = ?",
            (violations, chat_id),
        )
        await self._conn.commit()

    async def get_max_tokens(self, chat_id: int) -> int:
        await self.get_chat_settings(chat_id)
        cursor = await self._conn.execute(
            "SELECT max_tokens FROM chat_settings WHERE chat_id = ?", (chat_id,)
        )
        row = await cursor.fetchone()
        return row[0]

    async def set_max_tokens(self, chat_id: int, tokens: int) -> None:
        await self.get_chat_settings(chat_id)
        await self._conn.execute(
            "UPDATE chat_settings SET max_tokens = ? WHERE chat_id = ?", (tokens, chat_id)
        )
        await self._conn.commit()

    async def get_persona(self, chat_id: int) -> Optional[str]:
        await self.get_chat_settings(chat_id)
        cursor = await self._conn.execute(
            "SELECT persona FROM chat_settings WHERE chat_id = ?", (chat_id,)
        )
        row = await cursor.fetchone()
        return row[0]

    async def set_persona(self, chat_id: int, text: Optional[str]) -> None:
        await self.get_chat_settings(chat_id)
        await self._conn.execute(
            "UPDATE chat_settings SET persona = ? WHERE chat_id = ?", (text, chat_id)
        )
        await self._conn.commit()

    async def get_proactive_settings(self, chat_id: int) -> tuple[str, int, float, int]:
        await self.get_chat_settings(chat_id)
        cursor = await self._conn.execute(
            "SELECT proactive_mode, proactive_interval_min, proactive_probability, "
            "proactive_context_size FROM chat_settings WHERE chat_id = ?",
            (chat_id,),
        )
        row = await cursor.fetchone()
        return (row[0], row[1], row[2], row[3])

    async def set_proactive_off(self, chat_id: int) -> None:
        await self.get_chat_settings(chat_id)
        await self._conn.execute(
            "UPDATE chat_settings SET proactive_mode = 'off', proactive_interval_min = 0, "
            "proactive_probability = 0.0 WHERE chat_id = ?",
            (chat_id,),
        )
        await self._conn.commit()

    async def set_proactive_interval(self, chat_id: int, minutes: int) -> None:
        await self.get_chat_settings(chat_id)
        await self._conn.execute(
            "UPDATE chat_settings SET proactive_mode = 'interval', "
            "proactive_interval_min = ?, proactive_probability = 0.0 WHERE chat_id = ?",
            (minutes, chat_id),
        )
        await self._conn.commit()

    async def set_proactive_probability(self, chat_id: int, probability: float) -> None:
        await self.get_chat_settings(chat_id)
        await self._conn.execute(
            "UPDATE chat_settings SET proactive_mode = 'probability', "
            "proactive_probability = ?, proactive_interval_min = 0 WHERE chat_id = ?",
            (probability, chat_id),
        )
        await self._conn.commit()

    async def set_proactive_context_size(self, chat_id: int, size: int) -> None:
        await self.get_chat_settings(chat_id)
        await self._conn.execute(
            "UPDATE chat_settings SET proactive_context_size = ? WHERE chat_id = ?",
            (size, chat_id),
        )
        await self._conn.commit()

    async def list_active_proactive_interval_chats(self) -> list[tuple[int, int]]:
        cursor = await self._conn.execute(
            "SELECT chat_id, proactive_interval_min FROM chat_settings "
            "WHERE proactive_mode = 'interval' AND proactive_interval_min > 0"
        )
        rows = await cursor.fetchall()
        return [(row[0], row[1]) for row in rows]
