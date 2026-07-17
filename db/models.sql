CREATE TABLE IF NOT EXISTS trigger_words (
    chat_id INTEGER NOT NULL,
    word TEXT NOT NULL,
    UNIQUE(chat_id, word)
);

CREATE TABLE IF NOT EXISTS warnings (
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    last_violation_at TEXT,
    PRIMARY KEY (chat_id, user_id)
);

CREATE TABLE IF NOT EXISTS chat_settings (
    chat_id INTEGER PRIMARY KEY,
    broadcast_interval_min INTEGER NOT NULL DEFAULT 0,
    reset_days INTEGER NOT NULL DEFAULT 30,
    warn_message TEXT,
    mute_message TEXT,
    kick_message TEXT,
    saved_permissions_json TEXT,
    last_invite_link TEXT,
    mute_minutes INTEGER NOT NULL DEFAULT 5,
    kick_after_violation INTEGER NOT NULL DEFAULT 3
);

CREATE TABLE IF NOT EXISTS broadcast_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    text TEXT NOT NULL
);
