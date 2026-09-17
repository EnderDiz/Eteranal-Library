from __future__ import annotations

import ast
import os
import re
import sqlite3
from .auth.security import hash_password
from .paths import ADMIN_FILE, DATABASE_PATH, INSTANCE_DIR, SCHEMA_FILE


def connect_db() -> sqlite3.Connection:
    INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db() -> None:
    with connect_db() as db:
        db.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))
        _migrate_schema(db)
        _seed_test_admin(db)
        db.commit()



def _migrate_schema(db: sqlite3.Connection) -> None:
    game_columns = {
        row["name"]
        for row in db.execute("PRAGMA table_info(games)").fetchall()
    }
    if "content_cycle_label" not in game_columns:
        db.execute("ALTER TABLE games ADD COLUMN content_cycle_label TEXT")
    if "content_cycle" not in game_columns:
        db.execute("ALTER TABLE games ADD COLUMN content_cycle INTEGER NOT NULL DEFAULT 1")

    character_columns = {
        row["name"]
        for row in db.execute("PRAGMA table_info(characters)").fetchall()
    }
    if "avatar_background" not in character_columns:
        db.execute(
            """
            ALTER TABLE characters
            ADD COLUMN avatar_background TEXT NOT NULL DEFAULT 'assr'
                CHECK (avatar_background IN ('assr', 'ssr', 'sr', 'r', 'n'))
            """
        )
    if "manual_changed_cycle" not in character_columns:
        db.execute("ALTER TABLE characters ADD COLUMN manual_changed_cycle INTEGER")

    rating_columns = {
        row["name"]
        for row in db.execute("PRAGMA table_info(character_ratings)").fetchall()
    }
    if "previous_tier_value" not in rating_columns:
        db.execute(
            """
            ALTER TABLE character_ratings
            ADD COLUMN previous_tier_value TEXT
                CHECK (previous_tier_value IS NULL OR previous_tier_value IN ('SSS', 'SS', 'S', 'A', 'B', 'C', 'D'))
            """
        )
    if "change_status" not in rating_columns:
        db.execute(
            """
            ALTER TABLE character_ratings
            ADD COLUMN change_status TEXT
                CHECK (change_status IS NULL OR change_status IN ('promoted', 'demoted'))
            """
        )
    if "change_cycle" not in rating_columns:
        db.execute("ALTER TABLE character_ratings ADD COLUMN change_cycle INTEGER")

    book_columns = {
        row["name"] for row in db.execute("PRAGMA table_info(books)").fetchall()
    }
    if "summary" not in book_columns:
        db.execute("ALTER TABLE books ADD COLUMN summary TEXT")
        db.execute("UPDATE books SET summary = description WHERE summary IS NULL")
    if "tags_json" not in book_columns:
        db.execute("ALTER TABLE books ADD COLUMN tags_json TEXT NOT NULL DEFAULT '[]'")
    if "banner_filename" not in book_columns:
        db.execute("ALTER TABLE books ADD COLUMN banner_filename TEXT")
    if "published_at" not in book_columns:
        db.execute("ALTER TABLE books ADD COLUMN published_at TEXT")
        db.execute(
            "UPDATE books SET published_at = COALESCE(updated_at, created_at) "
            "WHERE publication_status = 'published' AND published_at IS NULL"
        )

    chapter_columns = {
        row["name"] for row in db.execute("PRAGMA table_info(book_chapters)").fetchall()
    }
    if "content_markdown" not in chapter_columns:
        db.execute("ALTER TABLE book_chapters ADD COLUMN content_markdown TEXT NOT NULL DEFAULT ''")
        from .library.markdown_tools import html_to_markdown

        legacy_rows = db.execute(
            "SELECT id, content FROM book_chapters WHERE content IS NOT NULL AND content <> ''"
        ).fetchall()
        for row in legacy_rows:
            db.execute(
                "UPDATE book_chapters SET content_markdown = ? WHERE id = ?",
                (html_to_markdown(row["content"]), row["id"]),
            )

    chapter_columns = {
        row["name"] for row in db.execute("PRAGMA table_info(book_chapters)").fetchall()
    }
    if "word_count" not in chapter_columns:
        db.execute("ALTER TABLE book_chapters ADD COLUMN word_count INTEGER NOT NULL DEFAULT 0")
    if "char_count" not in chapter_columns:
        db.execute("ALTER TABLE book_chapters ADD COLUMN char_count INTEGER NOT NULL DEFAULT 0")

    from .library.markdown_tools import markdown_char_count, markdown_word_count
    stat_rows = db.execute(
        "SELECT id, content_markdown FROM book_chapters "
        "WHERE (word_count = 0 OR char_count = 0) AND content_markdown <> ''"
    ).fetchall()
    for row in stat_rows:
        db.execute(
            "UPDATE book_chapters SET word_count = ?, char_count = ? WHERE id = ?",
            (markdown_word_count(row["content_markdown"]), markdown_char_count(row["content_markdown"]), row["id"]),
        )

def _read_admin_file() -> tuple[str | None, str | None]:
    if not ADMIN_FILE.exists():
        return None, None

    text = ADMIN_FILE.read_text(encoding="utf-8")
    values: dict[str, str] = {}

    for key in ("login", "password"):
        match = re.search(rf"^\s*{key}\s*=\s*(.+?)\s*$", text, flags=re.MULTILINE)
        if not match:
            continue
        try:
            value = ast.literal_eval(match.group(1))
        except (ValueError, SyntaxError):
            continue
        if isinstance(value, str):
            values[key] = value

    return values.get("login"), values.get("password")


def _seed_test_admin(db: sqlite3.Connection) -> None:
    existing = db.execute("SELECT id FROM users WHERE role = 'admin' LIMIT 1").fetchone()
    if existing:
        return

    file_login, file_password = _read_admin_file()

    login = os.getenv("ETERNAL_ADMIN_LOGIN") or file_login or "Ender"
    password = os.getenv("ETERNAL_ADMIN_PASSWORD") or file_password
    email = os.getenv("ETERNAL_ADMIN_EMAIL") or f"{login.lower()}@eternallibrary.local"

    if not password:
        raise RuntimeError(
            "Не найден пароль тестового администратора. "
            "Укажите ETERNAL_ADMIN_PASSWORD или instance/test_admin.txt."
        )

    db.execute(
        """
        INSERT INTO users (username, email, password_hash, role, avatar_filename)
        VALUES (?, ?, ?, 'admin', NULL)
        """,
        (login, email, hash_password(password)),
    )


def get_user_by_id(user_id: int):
    with connect_db() as db:
        return db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def get_user_by_identifier(identifier: str):
    with connect_db() as db:
        return db.execute(
            """
            SELECT * FROM users
            WHERE username = ? COLLATE NOCASE
               OR email = ? COLLATE NOCASE
            LIMIT 1
            """,
            (identifier, identifier),
        ).fetchone()
