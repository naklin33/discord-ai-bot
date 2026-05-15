"""SQLite 共用儲存層：兩個 bot 同時讀寫 data/bot.db"""
import os
import json
import sqlite3
import threading
from contextlib import contextmanager

DB_PATH = os.getenv("BOT_DB_PATH", "data/bot.db")
_init_lock = threading.Lock()
_initialised = False


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    display_name TEXT PRIMARY KEY,
    language TEXT NOT NULL DEFAULT '繁體中文',
    auto_translate INTEGER NOT NULL DEFAULT 1,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS usage_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    user_key TEXT NOT NULL,
    display_name TEXT,
    command TEXT NOT NULL,
    details TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_usage_user ON usage_logs(user_key);
CREATE INDEX IF NOT EXISTS idx_usage_time ON usage_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_usage_command ON usage_logs(command);
"""


def _migrate_users_json(conn: sqlite3.Connection):
    """首次啟動時，把舊的 users.json 內容搬進 SQLite"""
    legacy = "users.json"
    if not os.path.exists(legacy):
        return
    cur = conn.execute("SELECT COUNT(*) FROM users")
    if cur.fetchone()[0] > 0:
        return
    try:
        with open(legacy, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return
    for name, prefs in data.items():
        conn.execute(
            "INSERT OR IGNORE INTO users (display_name, language, auto_translate) VALUES (?, ?, ?)",
            (
                name,
                prefs.get("語言", "繁體中文"),
                1 if prefs.get("自動翻譯", True) else 0,
            ),
        )
    conn.commit()


def init_db():
    """建立資料表與索引；冪等，可重複呼叫"""
    global _initialised
    with _init_lock:
        if _initialised:
            return
        os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
        with sqlite3.connect(DB_PATH) as conn:
            conn.executescript(SCHEMA)
            _migrate_users_json(conn)
        _initialised = True


@contextmanager
def connect():
    """提供 sqlite3 連線；WAL 模式讓兩個 bot process 同時讀寫"""
    if not _initialised:
        init_db()
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
