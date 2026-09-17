from __future__ import annotations

import json
import math
import re
from typing import Iterable

from ..database import connect_db
from .contents_navigation import preview_positions
from .markdown_tools import (
    html_to_markdown,
    markdown_char_count,
    markdown_word_count,
)

MAX_BOOKS = 10
READING_SPEED_WPM = 210


def slugify(value: str, fallback: str = "item") -> str:
    value = value.strip().casefold()
    value = re.sub(r"[^\w]+", "-", value, flags=re.UNICODE)
    value = value.strip("-_")
    return value or fallback


def _unique_slug(table: str, title: str, *, parent_clause: str = "", parent_params: Iterable[object] = (), exclude_id: int | None = None) -> str:
    base = slugify(title, "item")
    candidate = base
    suffix = 2
    with connect_db() as db:
        while True:
            query = f"SELECT id FROM {table} WHERE slug = ? COLLATE NOCASE"
            params: list[object] = [candidate]
            if parent_clause:
                query += f" AND {parent_clause}"
                params.extend(parent_params)
            if exclude_id is not None:
                query += " AND id <> ?"
                params.append(exclude_id)
            query += " LIMIT 1"
            if db.execute(query, params).fetchone() is None:
                return candidate
            candidate = f"{base}-{suffix}"
            suffix += 1


def unique_book_slug(title: str, *, exclude_id: int | None = None) -> str:
    return _unique_slug("books", title, exclude_id=exclude_id)


def unique_chapter_slug(book_id: int, title: str, *, exclude_id: int | None = None) -> str:
    return _unique_slug(
        "book_chapters",
        title,
        parent_clause="book_id = ?",
        parent_params=(book_id,),
        exclude_id=exclude_id,
    )


def normalize_tags(raw: str | Iterable[str] | None, *, limit: int = 12) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        values = re.split(r"[,\n;]+", raw)
    else:
        values = list(raw)
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        tag = str(value).strip().lstrip("#").strip()
        if not tag:
            continue
        tag = tag[:40]
        key = tag.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(tag)
        if len(result) >= limit:
            break
    return result


def tags_to_json(tags: list[str]) -> str:
    return json.dumps(tags, ensure_ascii=False)


def tags_from_json(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(parsed, list):
        return []
    return normalize_tags(parsed)


def reading_minutes(words: int) -> int:
    return max(1, math.ceil(words / READING_SPEED_WPM)) if words else 0


def reading_time_label(words: int) -> str:
    minutes = reading_minutes(words)
    if not minutes:
        return "0 мин"
    if minutes < 60:
        return f"~ {minutes} мин"
    hours = minutes // 60
    rest = minutes % 60
    if rest:
        return f"~ {hours} ч. {rest} мин"
    return f"~ {hours} ч."


def chapter_markdown(chapter) -> str:
    if chapter is None:
        return ""
    keys = set(chapter.keys()) if hasattr(chapter, "keys") else set()
    if "content_markdown" in keys and chapter["content_markdown"]:
        return chapter["content_markdown"]
    return html_to_markdown(chapter["content"] if "content" in keys else "")


def count_books() -> int:
    with connect_db() as db:
        row = db.execute("SELECT COUNT(*) AS total FROM books").fetchone()
        return int(row["total"])


def list_manage_books():
    with connect_db() as db:
        return db.execute(
            """
            SELECT b.*, u.username AS editor_name,
                   COUNT(c.id) AS chapter_count,
                   SUM(CASE WHEN c.publication_status = 'published' THEN 1 ELSE 0 END) AS published_chapter_count
            FROM books b
            LEFT JOIN users u ON u.id = b.created_by
            LEFT JOIN book_chapters c ON c.book_id = b.id
            GROUP BY b.id
            ORDER BY b.updated_at DESC, b.title COLLATE NOCASE
            """
        ).fetchall()


def list_public_books(query: str = ""):
    query = query.strip()
    with connect_db() as db:
        sql = """
            SELECT b.*,
                   COUNT(c.id) AS chapter_count,
                   SUM(CASE WHEN c.publication_status = 'published' THEN 1 ELSE 0 END) AS published_chapter_count
            FROM books b
            LEFT JOIN book_chapters c ON c.book_id = b.id
            WHERE b.publication_status = 'published'
        """
        params: list[object] = []
        if query:
            pattern = f"%{query}%"
            sql += " AND (b.title LIKE ? COLLATE NOCASE OR b.summary LIKE ? COLLATE NOCASE OR b.description LIKE ? COLLATE NOCASE OR b.tags_json LIKE ? COLLATE NOCASE)"
            params.extend((pattern, pattern, pattern, pattern))
        sql += " GROUP BY b.id ORDER BY b.updated_at DESC, b.title COLLATE NOCASE"
        return db.execute(sql, params).fetchall()


def get_book(book_id: int):
    with connect_db() as db:
        return db.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()


def get_book_by_slug(slug: str):
    with connect_db() as db:
        return db.execute("SELECT * FROM books WHERE slug = ? COLLATE NOCASE LIMIT 1", (slug,)).fetchone()


def get_public_book_by_slug(slug: str):
    with connect_db() as db:
        return db.execute(
            """
            SELECT * FROM books
            WHERE slug = ? COLLATE NOCASE AND publication_status = 'published'
            LIMIT 1
            """,
            (slug,),
        ).fetchone()


def list_manage_chapters(book_id: int):
    with connect_db() as db:
        return db.execute(
            """
            SELECT * FROM book_chapters
            WHERE book_id = ?
            ORDER BY sort_order, id
            """,
            (book_id,),
        ).fetchall()


def count_manage_chapters(book_id: int, *, query: str = "", status: str = "") -> int:
    query = query.strip()
    status = status if status in {"draft", "published", "archived"} else ""
    sql = "SELECT COUNT(*) AS total FROM book_chapters WHERE book_id = ?"
    params: list[object] = [book_id]
    if query:
        pattern = f"%{query}%"
        sql += " AND (title LIKE ? COLLATE NOCASE OR summary LIKE ? COLLATE NOCASE)"
        params.extend((pattern, pattern))
    if status:
        sql += " AND publication_status = ?"
        params.append(status)
    with connect_db() as db:
        return int(db.execute(sql, params).fetchone()["total"])


def list_manage_chapter_page(book_id: int, *, query: str = "", status: str = "", limit: int = 100, offset: int = 0):
    query = query.strip()
    status = status if status in {"draft", "published", "archived"} else ""
    sql = """
        WITH ranked AS (
            SELECT *, ROW_NUMBER() OVER (ORDER BY sort_order, id) AS chapter_number
            FROM book_chapters
            WHERE book_id = ?
        )
        SELECT * FROM ranked WHERE 1 = 1
    """
    params: list[object] = [book_id]
    if query:
        pattern = f"%{query}%"
        sql += " AND (title LIKE ? COLLATE NOCASE OR summary LIKE ? COLLATE NOCASE)"
        params.extend((pattern, pattern))
    if status:
        sql += " AND publication_status = ?"
        params.append(status)
    sql += " ORDER BY chapter_number LIMIT ? OFFSET ?"
    params.extend((max(1, min(200, int(limit))), max(0, int(offset))))
    with connect_db() as db:
        return db.execute(sql, params).fetchall()


def manage_chapter_window(book_id: int, chapter_id: int, *, radius: int = 5):
    radius = max(0, min(15, int(radius)))
    with connect_db() as db:
        current = db.execute(
            """
            WITH ranked AS (
                SELECT id, ROW_NUMBER() OVER (ORDER BY sort_order, id) AS chapter_number
                FROM book_chapters WHERE book_id = ?
            )
            SELECT chapter_number FROM ranked WHERE id = ?
            """,
            (book_id, chapter_id),
        ).fetchone()
        if current is None:
            return []
        number = int(current["chapter_number"])
        return db.execute(
            """
            WITH ranked AS (
                SELECT *, ROW_NUMBER() OVER (ORDER BY sort_order, id) AS chapter_number
                FROM book_chapters WHERE book_id = ?
            )
            SELECT * FROM ranked
            WHERE chapter_number BETWEEN ? AND ?
            ORDER BY chapter_number
            """,
            (book_id, max(1, number - radius), number + radius),
        ).fetchall()


def list_public_chapters(book_id: int):
    with connect_db() as db:
        return db.execute(
            """
            SELECT * FROM book_chapters
            WHERE book_id = ? AND publication_status = 'published'
            ORDER BY sort_order, id
            """,
            (book_id,),
        ).fetchall()


def count_public_chapters(book_id: int, query: str = "") -> int:
    query = query.strip()
    sql = """
        SELECT COUNT(*) AS total
        FROM book_chapters
        WHERE book_id = ? AND publication_status = 'published'
    """
    params: list[object] = [book_id]
    if query:
        pattern = f"%{query}%"
        sql += " AND (title LIKE ? COLLATE NOCASE OR summary LIKE ? COLLATE NOCASE)"
        params.extend((pattern, pattern))
    with connect_db() as db:
        row = db.execute(sql, params).fetchone()
        return int(row["total"])


def list_public_chapter_page(book_id: int, *, query: str = "", limit: int = 100, offset: int = 0):
    query = query.strip()
    sql = """
        WITH ranked AS (
            SELECT id, book_id, slug, title, summary, sort_order, published_at, updated_at,
                   ROW_NUMBER() OVER (ORDER BY sort_order, id) AS chapter_number
            FROM book_chapters
            WHERE book_id = ? AND publication_status = 'published'
        )
        SELECT * FROM ranked
    """
    params: list[object] = [book_id]
    if query:
        pattern = f"%{query}%"
        sql += " WHERE title LIKE ? COLLATE NOCASE OR summary LIKE ? COLLATE NOCASE"
        params.extend((pattern, pattern))
    sql += " ORDER BY chapter_number LIMIT ? OFFSET ?"
    params.extend((max(1, min(200, int(limit))), max(0, int(offset))))
    with connect_db() as db:
        return db.execute(sql, params).fetchall()


def list_public_chapter_preview(book_id: int, *, head: int = 3, tail: int = 3):
    total = count_public_chapters(book_id)
    positions = preview_positions(total, head=head, tail=tail)
    if not positions:
        return []
    placeholders = ",".join("?" for _ in positions)
    with connect_db() as db:
        return db.execute(
            f"""
            WITH ranked AS (
                SELECT id, book_id, slug, title, summary, sort_order, published_at, updated_at,
                       ROW_NUMBER() OVER (ORDER BY sort_order, id) AS chapter_number
                FROM book_chapters
                WHERE book_id = ? AND publication_status = 'published'
            )
            SELECT * FROM ranked
            WHERE chapter_number IN ({placeholders})
            ORDER BY chapter_number
            """,
            [book_id, *positions],
        ).fetchall()


def get_public_chapter_by_number(book_id: int, chapter_number: int):
    if chapter_number < 1:
        return None
    with connect_db() as db:
        return db.execute(
            """
            SELECT * FROM book_chapters
            WHERE book_id = ? AND publication_status = 'published'
            ORDER BY sort_order, id
            LIMIT 1 OFFSET ?
            """,
            (book_id, chapter_number - 1),
        ).fetchone()


def public_chapter_window(book_id: int, chapter_id: int, *, radius: int = 3):
    radius = max(0, min(10, int(radius)))
    with connect_db() as db:
        current = db.execute(
            """
            WITH ranked AS (
                SELECT id, ROW_NUMBER() OVER (ORDER BY sort_order, id) AS chapter_number
                FROM book_chapters
                WHERE book_id = ? AND publication_status = 'published'
            )
            SELECT chapter_number FROM ranked WHERE id = ?
            """,
            (book_id, chapter_id),
        ).fetchone()
        if current is None:
            return []
        number = int(current["chapter_number"])
        return db.execute(
            """
            WITH ranked AS (
                SELECT id, book_id, slug, title, summary, sort_order,
                       ROW_NUMBER() OVER (ORDER BY sort_order, id) AS chapter_number
                FROM book_chapters
                WHERE book_id = ? AND publication_status = 'published'
            )
            SELECT * FROM ranked
            WHERE chapter_number BETWEEN ? AND ?
            ORDER BY chapter_number
            """,
            (book_id, max(1, number - radius), number + radius),
        ).fetchall()


def get_chapter(chapter_id: int):
    with connect_db() as db:
        return db.execute("SELECT * FROM book_chapters WHERE id = ?", (chapter_id,)).fetchone()


def get_public_chapter(book_id: int, slug: str):
    with connect_db() as db:
        return db.execute(
            """
            SELECT * FROM book_chapters
            WHERE book_id = ? AND slug = ? COLLATE NOCASE AND publication_status = 'published'
            LIMIT 1
            """,
            (book_id, slug),
        ).fetchone()


def first_public_chapter(book_id: int):
    with connect_db() as db:
        return db.execute(
            """
            SELECT * FROM book_chapters
            WHERE book_id = ? AND publication_status = 'published'
            ORDER BY sort_order, id
            LIMIT 1
            """,
            (book_id,),
        ).fetchone()


def chapter_neighbors(book_id: int, chapter_id: int):
    with connect_db() as db:
        current = db.execute(
            """
            WITH ranked AS (
                SELECT id, ROW_NUMBER() OVER (ORDER BY sort_order, id) AS chapter_number,
                       COUNT(*) OVER () AS chapter_total
                FROM book_chapters
                WHERE book_id = ? AND publication_status = 'published'
            )
            SELECT chapter_number, chapter_total FROM ranked WHERE id = ?
            """,
            (book_id, chapter_id),
        ).fetchone()
        if current is None:
            return None, None, 0, count_public_chapters(book_id)
        number = int(current["chapter_number"])
        total = int(current["chapter_total"])
        previous = get_public_chapter_by_number(book_id, number - 1) if number > 1 else None
        following = get_public_chapter_by_number(book_id, number + 1) if number < total else None
        return previous, following, number, total


def book_stats(book_id: int, *, published_only: bool = False) -> dict[str, int | str]:
    with connect_db() as db:
        if published_only:
            row = db.execute(
                """
                SELECT COUNT(*) AS chapter_count, COUNT(*) AS published_chapter_count,
                       COALESCE(SUM(word_count), 0) AS word_count
                FROM book_chapters
                WHERE book_id = ? AND publication_status = 'published'
                """,
                (book_id,),
            ).fetchone()
        else:
            row = db.execute(
                """
                SELECT COUNT(*) AS chapter_count,
                       COALESCE(SUM(CASE WHEN publication_status = 'published' THEN 1 ELSE 0 END), 0) AS published_chapter_count,
                       COALESCE(SUM(word_count), 0) AS word_count
                FROM book_chapters
                WHERE book_id = ?
                """,
                (book_id,),
            ).fetchone()
    words = int(row["word_count"] or 0)
    return {
        "chapter_count": int(row["chapter_count"] or 0),
        "published_chapter_count": int(row["published_chapter_count"] or 0),
        "word_count": words,
        "reading_minutes": reading_minutes(words),
        "reading_time_label": reading_time_label(words),
    }


def chapter_stats(chapter) -> dict[str, int | str]:
    if chapter is None:
        words = chars = 0
    else:
        keys = set(chapter.keys()) if hasattr(chapter, "keys") else set()
        if "word_count" in keys and "char_count" in keys:
            words = int(chapter["word_count"] or 0)
            chars = int(chapter["char_count"] or 0)
        else:
            source = chapter_markdown(chapter)
            words = markdown_word_count(source)
            chars = markdown_char_count(source)
    return {
        "word_count": words,
        "char_count": chars,
        "reading_minutes": reading_minutes(words),
        "reading_time_label": reading_time_label(words),
    }


def record_activity(db, *, book_id: int, event_type: str, title: str, detail: str | None = None, chapter_id: int | None = None) -> None:
    db.execute(
        """
        INSERT INTO library_activity (book_id, chapter_id, event_type, title, detail)
        VALUES (?, ?, ?, ?, ?)
        """,
        (book_id, chapter_id, event_type, title, detail),
    )


def list_activity(book_id: int, limit: int = 5):
    with connect_db() as db:
        rows = db.execute(
            """
            SELECT a.*, c.slug AS chapter_slug, c.title AS chapter_title
            FROM library_activity a
            LEFT JOIN book_chapters c ON c.id = a.chapter_id
            WHERE a.book_id = ?
              AND a.event_type <> 'chapter_deleted'
              AND (
                    (a.chapter_id IS NULL AND a.event_type LIKE 'book_%')
                    OR c.publication_status = 'published'
                  )
            ORDER BY a.id DESC
            LIMIT ?
            """,
            (book_id, limit),
        ).fetchall()
        if rows:
            return rows
        return db.execute(
            """
            SELECT NULL AS id, b.id AS book_id, NULL AS chapter_id,
                   'book_updated' AS event_type, 'Карточка книги обновлена' AS title,
                   'Последние изменения сохранены.' AS detail, b.updated_at AS created_at,
                   NULL AS chapter_slug, NULL AS chapter_title
            FROM books b WHERE b.id = ?
            UNION ALL
            SELECT NULL, b.id, NULL, 'book_created', 'Книга добавлена',
                   'Создана запись в личной библиотеке.', b.created_at, NULL, NULL
            FROM books b WHERE b.id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (book_id, book_id, limit),
        ).fetchall()
