from __future__ import annotations

import json
import re
from collections.abc import Iterable

from ..database import connect_db

TIER_VALUES = ("SSS", "SS", "S", "A", "B", "C", "D")

SIDEBAR_SECTIONS = (
    ("overview", "Об игре"),
    ("news", "Новости"),
    ("characters", "Персонажи"),
    ("items", "Предметы"),
    ("tier_list", "Tier List"),
    ("guides", "Гайды"),
    ("wiki", "Вики"),
)

CHARACTER_MODULES = (
    ("profile", "Профиль"),
    ("skills", "Способности"),
    ("stats", "Характеристики"),
    ("review", "Ревью"),
    ("pros_cons", "Плюсы и минусы"),
    ("other_information", "Дополнительная информация"),
)


def slugify(value: str, fallback: str = "item") -> str:
    value = value.strip().casefold()
    value = re.sub(r"[^\w]+", "-", value, flags=re.UNICODE)
    value = value.strip("-_")
    return value or fallback


def unique_game_slug(name: str, *, exclude_id: int | None = None) -> str:
    base = slugify(name, "game")
    with connect_db() as db:
        return _unique_slug(db, "games", base, exclude_id=exclude_id)


def unique_character_slug(game_id: int, name: str, *, exclude_id: int | None = None) -> str:
    base = slugify(name, "character")
    with connect_db() as db:
        return _unique_slug(db, "characters", base, game_id=game_id, exclude_id=exclude_id)


def _unique_slug(db, table: str, base: str, *, game_id: int | None = None, exclude_id: int | None = None) -> str:
    candidate = base
    suffix = 2
    while True:
        conditions = ["slug = ? COLLATE NOCASE"]
        params: list[object] = [candidate]
        if game_id is not None:
            conditions.append("game_id = ?")
            params.append(game_id)
        if exclude_id is not None:
            conditions.append("id <> ?")
            params.append(exclude_id)
        row = db.execute(
            f"SELECT id FROM {table} WHERE {' AND '.join(conditions)} LIMIT 1",
            params,
        ).fetchone()
        if not row:
            return candidate
        candidate = f"{base}-{suffix}"
        suffix += 1


def get_game(game_id: int):
    with connect_db() as db:
        return db.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()


def get_character(character_id: int):
    with connect_db() as db:
        return db.execute("SELECT * FROM characters WHERE id = ?", (character_id,)).fetchone()


def can_manage_game(user, game_id: int) -> bool:
    if user is None:
        return False
    if user["role"] == "admin":
        return True
    if user["role"] != "creator":
        return False
    with connect_db() as db:
        return db.execute(
            """
            SELECT 1
            FROM creator_game_access
            WHERE user_id = ? AND game_id = ? AND scope = 'tierlists'
            LIMIT 1
            """,
            (user["id"], game_id),
        ).fetchone() is not None


def grant_creator_game_access(user_id: int, game_id: int) -> None:
    with connect_db() as db:
        db.execute(
            """
            INSERT OR IGNORE INTO creator_game_access (user_id, game_id, scope)
            VALUES (?, ?, 'tierlists')
            """,
            (user_id, game_id),
        )
        db.commit()


def list_manageable_games(user):
    if user["role"] == "admin":
        query = """
            SELECT g.*, u.username AS creator_name,
                   (SELECT COUNT(*) FROM characters c WHERE c.game_id = g.id) AS character_count
            FROM games g
            JOIN users u ON u.id = g.created_by
            ORDER BY g.updated_at DESC, g.name COLLATE NOCASE
        """
        params: tuple[object, ...] = ()
    else:
        query = """
            SELECT g.*, u.username AS creator_name,
                   (SELECT COUNT(*) FROM characters c WHERE c.game_id = g.id) AS character_count
            FROM games g
            JOIN users u ON u.id = g.created_by
            JOIN creator_game_access a ON a.game_id = g.id
            WHERE a.user_id = ? AND a.scope = 'tierlists'
            ORDER BY g.updated_at DESC, g.name COLLATE NOCASE
        """
        params = (user["id"],)
    with connect_db() as db:
        return db.execute(query, params).fetchall()



def list_public_games():
    with connect_db() as db:
        return db.execute(
            """
            SELECT g.*, u.username AS creator_name,
                   (SELECT COUNT(*) FROM characters c
                    WHERE c.game_id = g.id AND c.publication_status = 'published') AS character_count
            FROM games g
            JOIN users u ON u.id = g.created_by
            WHERE g.publication_status = 'published'
            ORDER BY g.updated_at DESC, g.name COLLATE NOCASE
            """
        ).fetchall()


def get_public_game_by_slug(slug: str):
    with connect_db() as db:
        return db.execute(
            """
            SELECT * FROM games
            WHERE slug = ? COLLATE NOCASE AND publication_status = 'published'
            LIMIT 1
            """,
            (slug,),
        ).fetchone()

def list_public_characters(game_id: int):
    with connect_db() as db:
        return db.execute(
            """
            SELECT c.*
            FROM characters c
            WHERE c.game_id = ? AND c.publication_status = 'published'
            ORDER BY c.name COLLATE NOCASE
            """,
            (game_id,),
        ).fetchall()


def get_public_character_by_slug(game_id: int, slug: str):
    with connect_db() as db:
        return db.execute(
            """
            SELECT c.*
            FROM characters c
            WHERE c.game_id = ?
              AND c.slug = ? COLLATE NOCASE
              AND c.publication_status = 'published'
            LIMIT 1
            """,
            (game_id, slug),
        ).fetchone()


def get_public_character_values(
    game_id: int,
) -> tuple[
    dict[int, dict[int, str]],
    dict[int, dict[int, str]],
    dict[int, dict[int, str]],
]:

    with connect_db() as db:
        field_rows = db.execute(
            """
            SELECT v.character_id, v.field_id, v.value
            FROM character_field_values v
            JOIN characters c ON c.id = v.character_id
            WHERE c.game_id = ? AND c.publication_status = 'published'
            """,
            (game_id,),
        ).fetchall()
        rating_rows = db.execute(
            """
            SELECT r.character_id, r.category_id, r.tier_value,
                   CASE WHEN r.change_cycle = g.content_cycle THEN r.change_status ELSE NULL END AS change_status
            FROM character_ratings r
            JOIN characters c ON c.id = r.character_id
            JOIN games g ON g.id = c.game_id
            WHERE c.game_id = ?
              AND c.publication_status = 'published'
            """,
            (game_id,),
        ).fetchall()

    fields: dict[int, dict[int, str]] = {}
    ratings: dict[int, dict[int, str]] = {}
    rating_changes: dict[int, dict[int, str]] = {}
    for row in field_rows:
        fields.setdefault(row["character_id"], {})[row["field_id"]] = row["value"]
    for row in rating_rows:
        ratings.setdefault(row["character_id"], {})[row["category_id"]] = row["tier_value"]
        if row["change_status"]:
            rating_changes.setdefault(row["character_id"], {})[row["category_id"]] = row["change_status"]
    return fields, ratings, rating_changes


def get_game_sidebar_sections(game_id: int) -> dict[str, bool]:
    values = {key: False for key, _ in SIDEBAR_SECTIONS}
    with connect_db() as db:
        rows = db.execute(
            "SELECT section_key, enabled FROM game_sidebar_sections WHERE game_id = ?",
            (game_id,),
        ).fetchall()
    for row in rows:
        values[row["section_key"]] = bool(row["enabled"])
    return values


def get_game_modules(game_id: int) -> dict[str, bool]:
    values = {key: False for key, _ in CHARACTER_MODULES}
    with connect_db() as db:
        rows = db.execute(
            "SELECT module_key, enabled FROM game_character_modules WHERE game_id = ?",
            (game_id,),
        ).fetchall()
    for row in rows:
        values[row["module_key"]] = bool(row["enabled"])
    return values


def get_tier_categories(game_id: int):
    with connect_db() as db:
        return db.execute(
            "SELECT * FROM tier_categories WHERE game_id = ? ORDER BY sort_order, id",
            (game_id,),
        ).fetchall()


def get_character_fields(game_id: int):
    with connect_db() as db:
        rows = db.execute(
            "SELECT * FROM game_character_fields WHERE game_id = ? ORDER BY sort_order, id",
            (game_id,),
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        try:
            item["options"] = json.loads(row["options_json"] or "[]")
        except json.JSONDecodeError:
            item["options"] = []
        result.append(item)
    return result


def list_characters(game_id: int):
    with connect_db() as db:
        return db.execute(
            """
            SELECT c.*, u.username AS creator_name
            FROM characters c
            JOIN users u ON u.id = c.created_by
            WHERE c.game_id = ?
            ORDER BY c.updated_at DESC, c.name COLLATE NOCASE
            """,
            (game_id,),
        ).fetchall()


def get_character_editor_data(character_id: int) -> dict:
    with connect_db() as db:
        values = {
            row["field_id"]: row["value"]
            for row in db.execute(
                "SELECT field_id, value FROM character_field_values WHERE character_id = ?",
                (character_id,),
            ).fetchall()
        }
        ratings = {
            row["category_id"]: row["tier_value"]
            for row in db.execute(
                "SELECT category_id, tier_value FROM character_ratings WHERE character_id = ?",
                (character_id,),
            ).fetchall()
        }
        text = db.execute(
            "SELECT * FROM character_text_content WHERE character_id = ?",
            (character_id,),
        ).fetchone()
        skills = db.execute(
            "SELECT * FROM character_skills WHERE character_id = ? ORDER BY sort_order, id",
            (character_id,),
        ).fetchall()
        stats = db.execute(
            "SELECT * FROM character_stats WHERE character_id = ? ORDER BY sort_order, id",
            (character_id,),
        ).fetchall()
        pros = db.execute(
            "SELECT * FROM character_pros_cons WHERE character_id = ? AND kind = 'pro' ORDER BY sort_order, id",
            (character_id,),
        ).fetchall()
        cons = db.execute(
            "SELECT * FROM character_pros_cons WHERE character_id = ? AND kind = 'con' ORDER BY sort_order, id",
            (character_id,),
        ).fetchall()
    return {
        "values": values,
        "ratings": ratings,
        "text": text,
        "skills": skills,
        "stats": stats,
        "pros": pros,
        "cons": cons,
    }


def sync_sidebar_sections(db, game_id: int, enabled_keys: Iterable[str]) -> None:
    enabled = set(enabled_keys)
    for order, (key, _label) in enumerate(SIDEBAR_SECTIONS):
        db.execute(
            """
            INSERT INTO game_sidebar_sections (game_id, section_key, enabled, sort_order)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(game_id, section_key)
            DO UPDATE SET enabled = excluded.enabled, sort_order = excluded.sort_order
            """,
            (game_id, key, int(key in enabled), order),
        )


def sync_character_modules(db, game_id: int, enabled_keys: Iterable[str]) -> None:
    enabled = set(enabled_keys)
    for order, (key, _label) in enumerate(CHARACTER_MODULES):
        db.execute(
            """
            INSERT INTO game_character_modules (game_id, module_key, enabled, sort_order)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(game_id, module_key)
            DO UPDATE SET enabled = excluded.enabled, sort_order = excluded.sort_order
            """,
            (game_id, key, int(key in enabled), order),
        )


def sync_tier_categories(db, game_id: int, ids: list[str], names: list[str]) -> None:
    existing_ids = {
        row["id"]
        for row in db.execute("SELECT id FROM tier_categories WHERE game_id = ?", (game_id,)).fetchall()
    }
    kept: set[int] = set()
    order = 0

    for raw_id, raw_name in zip(ids, names):
        name = raw_name.strip()
        category_id = int(raw_id) if raw_id.isdigit() else None

        if not name:
            if category_id in existing_ids:
                kept.add(category_id)
            continue

        if category_id in existing_ids:
            db.execute(
                "UPDATE tier_categories SET name = ?, sort_order = ? WHERE id = ? AND game_id = ?",
                (name, order, category_id, game_id),
            )
            kept.add(category_id)
        else:
            base = slugify(name, "category")
            slug = _unique_slug(db, "tier_categories", base, game_id=game_id)
            cursor = db.execute(
                "INSERT INTO tier_categories (game_id, name, slug, sort_order) VALUES (?, ?, ?, ?)",
                (game_id, name, slug, order),
            )
            kept.add(cursor.lastrowid)
        order += 1

    for category_id in existing_ids - kept:
        db.execute("DELETE FROM tier_categories WHERE id = ? AND game_id = ?", (category_id, game_id))


def sync_character_fields(
    db,
    game_id: int,
    ids: list[str],
    labels: list[str],
    types: list[str],
    options_values: list[str],
    filterable_values: list[str],
    sortable_values: list[str],
) -> None:
    existing_rows = db.execute(
        "SELECT id, field_key FROM game_character_fields WHERE game_id = ?",
        (game_id,),
    ).fetchall()
    existing = {row["id"]: row["field_key"] for row in existing_rows}
    kept: set[int] = set()
    order = 0

    total = min(len(ids), len(labels), len(types), len(options_values), len(filterable_values), len(sortable_values))
    for index in range(total):
        label = labels[index].strip()
        raw_id = ids[index]
        field_id = int(raw_id) if raw_id.isdigit() else None


        if not label:
            if field_id in existing:
                kept.add(field_id)
            continue

        field_type = types[index] if types[index] in {"text", "number", "select"} else "text"
        options = [item.strip() for item in re.split(r"[,\n]", options_values[index]) if item.strip()]
        if field_type != "select":
            options = []
        options_json = json.dumps(options, ensure_ascii=False)
        filterable = int(filterable_values[index] == "1")
        sortable = int(sortable_values[index] == "1")
        if field_id in existing:
            db.execute(
                """
                UPDATE game_character_fields
                SET label = ?, field_type = ?, options_json = ?, filterable = ?, sortable = ?, sort_order = ?
                WHERE id = ? AND game_id = ?
                """,
                (label, field_type, options_json, filterable, sortable, order, field_id, game_id),
            )
            kept.add(field_id)
        else:
            base = slugify(label, "field")
            field_key = base
            suffix = 2
            while db.execute(
                "SELECT 1 FROM game_character_fields WHERE game_id = ? AND field_key = ? LIMIT 1",
                (game_id, field_key),
            ).fetchone():
                field_key = f"{base}-{suffix}"
                suffix += 1
            cursor = db.execute(
                """
                INSERT INTO game_character_fields
                    (game_id, field_key, label, field_type, options_json, filterable, sortable, sort_order)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (game_id, field_key, label, field_type, options_json, filterable, sortable, order),
            )
            kept.add(cursor.lastrowid)
        order += 1

    for field_id in set(existing) - kept:
        db.execute("DELETE FROM game_character_fields WHERE id = ? AND game_id = ?", (field_id, game_id))
