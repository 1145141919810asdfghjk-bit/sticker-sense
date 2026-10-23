"""SQLite 存储层。

选 SQLite 而不是 JSON 的唯一原因：管理网页和 AI 服务会是两个进程同时写。
JSON 加文件锁在 Windows 上很难做对，SQLite 开 WAL 天然解决。
可读性通过 export 命令导出 JSON 来弥补。
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS stickers (
    id            TEXT PRIMARY KEY,
    file          TEXT NOT NULL,
    sha256        TEXT UNIQUE NOT NULL,
    hashes_coarse TEXT NOT NULL,
    hashes_fine   TEXT NOT NULL,
    color         TEXT NOT NULL,
    width         INTEGER,
    height        INTEGER,
    added_at      TEXT NOT NULL,
    source        TEXT DEFAULT 'import'
);

CREATE TABLE IF NOT EXISTS readings (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    sticker_id   TEXT NOT NULL REFERENCES stickers(id) ON DELETE CASCADE,
    meaning      TEXT NOT NULL,
    context_hint TEXT DEFAULT '',
    confidence   REAL DEFAULT 0.6,
    uses         INTEGER DEFAULT 0,
    origin       TEXT DEFAULT 'user_explained',
    created_at   TEXT NOT NULL,
    last_used_at TEXT
);

CREATE TABLE IF NOT EXISTS aliases (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    sticker_id TEXT NOT NULL REFERENCES stickers(id) ON DELETE CASCADE,
    hashes_fine TEXT NOT NULL,
    color      TEXT NOT NULL,
    note       TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_readings_sticker ON readings(sticker_id);
CREATE INDEX IF NOT EXISTS idx_aliases_sticker  ON aliases(sticker_id);
"""


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def connect(data_dir: str | Path, cross_thread: bool = False) -> sqlite3.Connection:
    """cross_thread=True 时允许跨线程使用（调用方自己负责加锁）。

    管理端用 ThreadingHTTPServer，每个请求一个线程，必须开这个；
    单线程的 CLI / MCP 保持默认，出错时能更早暴露并发问题。
    """
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        data_dir / "library.db", check_same_thread=not cross_thread
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn
