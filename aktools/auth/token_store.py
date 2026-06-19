# -*- coding:utf-8 -*-
# !/usr/bin/env python
"""
Date: 2026/06/20 15:00
Desc: API Token 持久化存储 (SQLite)
"""
import os
import secrets
import sqlite3
import threading
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "tokens.db")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class TokenStore:
    """SQLite-backed API token storage (thread-safe)."""

    def __init__(self, db_path: str = DB_PATH):
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        with self._lock, sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS api_tokens (
                    token       TEXT PRIMARY KEY,
                    user_name   TEXT NOT NULL,
                    created_at  TEXT NOT NULL,
                    last_used   TEXT,
                    revoked     INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.commit()

    def create_token(self, user_name: str = "default") -> str:
        """Generate a new token and persist it. Returns the raw token (shown once)."""
        raw = "akt_" + secrets.token_hex(16)  # 35 chars: akt_ + 32 hex
        now = _now()
        with self._lock, sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "INSERT INTO api_tokens (token, user_name, created_at, last_used, revoked) "
                "VALUES (?, ?, ?, ?, 0)",
                (raw, user_name, now, now),
            )
            conn.commit()
        return raw

    def validate(self, token: str) -> str | None:
        """Check if token is valid. Returns user_name or None."""
        with self._lock, sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT user_name FROM api_tokens WHERE token = ? AND revoked = 0",
                (token,),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE api_tokens SET last_used = ? WHERE token = ?",
                (_now(), token),
            )
            conn.commit()
        return row[0]

    def revoke(self, token: str) -> bool:
        """Revoke a token. Returns True if it existed and was active."""
        with self._lock, sqlite3.connect(self._db_path) as conn:
            cur = conn.execute(
                "UPDATE api_tokens SET revoked = 1 WHERE token = ? AND revoked = 0",
                (token,),
            )
            conn.commit()
            return cur.rowcount > 0

    def list_tokens(self) -> list[dict]:
        """Return all tokens with metadata (prefix only, not full token)."""
        with self._lock, sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(
                "SELECT token, user_name, created_at, last_used, revoked "
                "FROM api_tokens ORDER BY created_at DESC"
            ).fetchall()
        return [
            {
                "prefix": row[0][:11] + "…",  # "akt_a1b2c3d…"
                "user_name": row[1],
                "created_at": row[2],
                "last_used": row[3],
                "revoked": bool(row[4]),
            }
            for row in rows
        ]
    def count(self) -> int:
        """Return total number of tokens (including revoked)."""
        with self._lock, sqlite3.connect(self._db_path) as conn:
            row = conn.execute("SELECT COUNT(*) FROM api_tokens").fetchone()
        return row[0] if row else 0


    def import_tokens(self, tokens: list[dict]) -> int:
        """Import pre-configured tokens from a list of {token, user_name} dicts.
        Tokens that already exist are skipped. Returns count of newly imported.
        """
        imported = 0
        now = _now()
        with self._lock, sqlite3.connect(self._db_path) as conn:
            for entry in tokens:
                raw = entry.get("token", "").strip()
                user_name = entry.get("user_name", entry.get("user", "imported"))
                if not raw:
                    continue
                existing = conn.execute(
                    "SELECT 1 FROM api_tokens WHERE token = ?", (raw,)
                ).fetchone()
                if existing:
                    continue
                conn.execute(
                    "INSERT INTO api_tokens (token, user_name, created_at, last_used, revoked) "
                    "VALUES (?, ?, ?, ?, 0)",
                    (raw, user_name, now, now),
                )
                imported += 1
            conn.commit()
        return imported

    def load_from_file(self, path: str) -> int:
        """Load tokens from a JSON file. Returns count of newly imported."""
        import json as _json
        try:
            with open(path, encoding="utf-8") as f:
                data = _json.load(f)
        except FileNotFoundError:
            return 0
        except Exception:
            return 0
        if isinstance(data, list):
            return self.import_tokens(data)
        return 0


# Singleton — auto-create root token on first use
TOKENS_JSON_PATH = os.environ.get("AKTOOLS_TOKENS_FILE", "")


def _bootstrap():
    store = TokenStore()
    # Import pre-configured tokens from JSON file (if configured)
    if TOKENS_JSON_PATH:
        n = store.load_from_file(TOKENS_JSON_PATH)
        if n:
            import logging as _logging
            _logging.getLogger("AKToolsLog").info(
                f"从 {TOKENS_JSON_PATH} 导入了 {n} 个预配置 Token"
            )
    # Auto-create root token if still empty
    if store.count() == 0:
        root = store.create_token("root")
        import logging as _logging
        _log = _logging.getLogger("AKToolsLog")
        _log.warning("=" * 60)
        _log.warning(f" ROOT API TOKEN (shown once): {root}")
        _log.warning(" Save this token — it's required to manage other tokens.")
        _log.warning("=" * 60)
    return store


token_store = _bootstrap()
