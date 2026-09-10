from __future__ import annotations

import json
from typing import Any

from database import connect_db

REVISION_LIMIT_PER_ENTITY = 50
REVISION_ENTITY_TYPES = {"game", "character"}


def _rows_as_dicts(rows) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def _canonical(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def capture_game_snapshot(db, game_id: int) -> dict[str, Any] | None:
    game = db.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()
    if game is None:
        return None

    game_data = dict(game)
    game_data.pop("updated_at", None)

    sidebar = _rows_as_dicts(
        db.execute(
            """
            SELECT section_key, enabled, sort_order
            FROM game_sidebar_sections
            WHERE game_id = ?
            ORDER BY sort_order, section_key
            """,
            (game_id,),
        ).fetchall()
    )
    modules = _rows_as_dicts(
        db.execute(
            """
            SELECT module_key, enabled, sort_order
            FROM game_character_modules
            WHERE game_id = ?
            ORDER BY sort_order, module_key
            """,
            (game_id,),
        ).fetchall()
    )
    categories = _rows_as_dicts(
        db.execute(
            """
            SELECT name, slug, sort_order
            FROM tier_categories
            WHERE game_id = ?
            ORDER BY sort_order, id
            """,
            (game_id,),
        ).fetchall()
    )
    fields = _rows_as_dicts(
        db.execute(
            """
            SELECT field_key, label, field_type, options_json, filterable, sortable, sort_order
            FROM game_character_fields
            WHERE game_id = ?
            ORDER BY sort_order, id
            """,
            (game_id,),
        ).fetchall()
    )

    field_values = _rows_as_dicts(
        db.execute(
            """
            SELECT v.character_id, f.field_key, v.value
            FROM character_field_values v
            JOIN game_character_fields f ON f.id = v.field_id
            JOIN characters c ON c.id = v.character_id
            WHERE c.game_id = ?
            ORDER BY v.character_id, f.sort_order, f.id
            """,
            (game_id,),
        ).fetchall()
    )
    ratings = _rows_as_dicts(
        db.execute(
            """
            SELECT r.character_id, tc.slug AS category_slug,
                   r.tier_value, r.previous_tier_value, r.change_status, r.change_cycle
            FROM character_ratings r
            JOIN tier_categories tc ON tc.id = r.category_id
            JOIN characters c ON c.id = r.character_id
            WHERE c.game_id = ?
            ORDER BY r.character_id, tc.sort_order, tc.id
            """,
            (game_id,),
        ).fetchall()
    )

    return {
        "game": game_data,
        "sidebar": sidebar,
        "modules": modules,
        "categories": categories,
        "fields": fields,
        "field_values": field_values,
        "ratings": ratings,
    }


def capture_character_snapshot(db, character_id: int) -> dict[str, Any] | None:
    character = db.execute(
        "SELECT * FROM characters WHERE id = ?", (character_id,)
    ).fetchone()
    if character is None:
        return None

    character_data = dict(character)
    character_data.pop("updated_at", None)

    field_values = _rows_as_dicts(
        db.execute(
            """
            SELECT f.field_key, v.value
            FROM character_field_values v
            JOIN game_character_fields f ON f.id = v.field_id
            WHERE v.character_id = ?
            ORDER BY f.sort_order, f.id
            """,
            (character_id,),
        ).fetchall()
    )
    ratings = _rows_as_dicts(
        db.execute(
            """
            SELECT tc.slug AS category_slug,
                   r.tier_value, r.previous_tier_value, r.change_status, r.change_cycle
            FROM character_ratings r
            JOIN tier_categories tc ON tc.id = r.category_id
            WHERE r.character_id = ?
            ORDER BY tc.sort_order, tc.id
            """,
            (character_id,),
        ).fetchall()
    )
    text = db.execute(
        """
        SELECT profile_text, review_text, other_information_text
        FROM character_text_content
        WHERE character_id = ?
        """,
        (character_id,),
    ).fetchone()
    skills = _rows_as_dicts(
        db.execute(
            """
            SELECT skill_type, name, description, extra_info, sort_order
            FROM character_skills
            WHERE character_id = ?
            ORDER BY sort_order, id
            """,
            (character_id,),
        ).fetchall()
    )
    stats = _rows_as_dicts(
        db.execute(
            """
            SELECT label, value, sort_order
            FROM character_stats
            WHERE character_id = ?
            ORDER BY sort_order, id
            """,
            (character_id,),
        ).fetchall()
    )
    pros_cons = _rows_as_dicts(
        db.execute(
            """
            SELECT kind, text, sort_order
            FROM character_pros_cons
            WHERE character_id = ?
            ORDER BY kind, sort_order, id
            """,
            (character_id,),
        ).fetchall()
    )

    return {
        "character": character_data,
        "field_values": field_values,
        "ratings": ratings,
        "text": dict(text) if text else None,
        "skills": skills,
        "stats": stats,
        "pros_cons": pros_cons,
    }


def capture_entity_snapshot(db, entity_type: str, entity_id: int) -> dict[str, Any] | None:
    if entity_type == "game":
        return capture_game_snapshot(db, entity_id)
    if entity_type == "character":
        return capture_character_snapshot(db, entity_id)
    raise ValueError("Unsupported revision entity type")


def record_revision(
    db,
    *,
    entity_type: str,
    entity_id: int,
    game_id: int,
    snapshot: dict[str, Any],
    user_id: int | None,
    reason: str = "edit",
) -> int:
    if entity_type not in REVISION_ENTITY_TYPES:
        raise ValueError("Unsupported revision entity type")

    cursor = db.execute(
        """
        INSERT INTO content_revisions
            (entity_type, entity_id, game_id, snapshot_json, created_by, reason)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            entity_type,
            entity_id,
            game_id,
            json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
            user_id,
            reason,
        ),
    )


    db.execute(
        """
        DELETE FROM content_revisions
        WHERE entity_type = ? AND entity_id = ?
          AND id NOT IN (
              SELECT id
              FROM content_revisions
              WHERE entity_type = ? AND entity_id = ?
              ORDER BY id DESC
              LIMIT ?
          )
        """,
        (
            entity_type,
            entity_id,
            entity_type,
            entity_id,
            REVISION_LIMIT_PER_ENTITY,
        ),
    )
    return int(cursor.lastrowid)


def record_revision_if_changed(
    db,
    *,
    entity_type: str,
    entity_id: int,
    game_id: int,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    user_id: int | None,
    reason: str = "edit",
    coalesce_seconds: int | None = None,
) -> bool:
    if before is None or after is None or _canonical(before) == _canonical(after):
        return False


    if coalesce_seconds and coalesce_seconds > 0:
        recent = db.execute(
            """
            SELECT 1
            FROM (
                SELECT reason, created_by, created_at
                FROM content_revisions
                WHERE entity_type = ? AND entity_id = ?
                ORDER BY id DESC
                LIMIT 1
            ) latest
            WHERE latest.reason = ?
              AND ((latest.created_by = ?) OR (latest.created_by IS NULL AND ? IS NULL))
              AND latest.created_at >= datetime('now', ?)
            """,
            (
                entity_type,
                entity_id,
                reason,
                user_id,
                user_id,
                f"-{int(coalesce_seconds)} seconds",
            ),
        ).fetchone()
        if recent:
            return False

    record_revision(
        db,
        entity_type=entity_type,
        entity_id=entity_id,
        game_id=game_id,
        snapshot=before,
        user_id=user_id,
        reason=reason,
    )
    return True


def list_revisions(entity_type: str, entity_id: int, *, limit: int = 30):
    with connect_db() as db:
        return db.execute(
            """
            SELECT r.*, u.username AS editor_name
            FROM content_revisions r
            LEFT JOIN users u ON u.id = r.created_by
            WHERE r.entity_type = ? AND r.entity_id = ?
            ORDER BY r.id DESC
            LIMIT ?
            """,
            (entity_type, entity_id, limit),
        ).fetchall()


def get_revision(revision_id: int):
    with connect_db() as db:
        return db.execute(
            "SELECT * FROM content_revisions WHERE id = ?", (revision_id,)
        ).fetchone()


def decode_revision_snapshot(revision) -> dict[str, Any]:
    try:
        snapshot = json.loads(revision["snapshot_json"])
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Повреждён снимок ревизии.") from exc
    if not isinstance(snapshot, dict):
        raise ValueError("Повреждён снимок ревизии.")
    return snapshot


def restore_game_snapshot(db, game_id: int, snapshot: dict[str, Any]) -> None:
    game_data = snapshot.get("game") or {}
    current = db.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()
    if current is None:
        raise ValueError("Игра больше не существует.")

    db.execute(
        """
        UPDATE games
        SET slug = ?, name = ?, description = ?, image_filename = ?,
            release_status = ?, release_date = ?, content_cycle_label = ?,
            content_cycle = ?, publication_status = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            game_data.get("slug", current["slug"]),
            game_data.get("name", current["name"]),
            game_data.get("description"),
            game_data.get("image_filename"),
            game_data.get("release_status", current["release_status"]),
            game_data.get("release_date"),
            game_data.get("content_cycle_label"),
            int(game_data.get("content_cycle") or 1),
            game_data.get("publication_status", current["publication_status"]),
            game_id,
        ),
    )

    db.execute("DELETE FROM game_sidebar_sections WHERE game_id = ?", (game_id,))
    for row in snapshot.get("sidebar", []):
        db.execute(
            """
            INSERT INTO game_sidebar_sections (game_id, section_key, enabled, sort_order)
            VALUES (?, ?, ?, ?)
            """,
            (
                game_id,
                row.get("section_key"),
                int(bool(row.get("enabled"))),
                int(row.get("sort_order") or 0),
            ),
        )

    db.execute("DELETE FROM game_character_modules WHERE game_id = ?", (game_id,))
    for row in snapshot.get("modules", []):
        db.execute(
            """
            INSERT INTO game_character_modules (game_id, module_key, enabled, sort_order)
            VALUES (?, ?, ?, ?)
            """,
            (
                game_id,
                row.get("module_key"),
                int(bool(row.get("enabled"))),
                int(row.get("sort_order") or 0),
            ),
        )

    current_categories = {
        row["slug"]: row
        for row in db.execute(
            "SELECT * FROM tier_categories WHERE game_id = ?", (game_id,)
        ).fetchall()
    }
    snapshot_categories = {
        str(row.get("slug")): row
        for row in snapshot.get("categories", [])
        if row.get("slug")
    }
    recreated_category_slugs: set[str] = set()

    for slug, row in snapshot_categories.items():
        if slug in current_categories:
            db.execute(
                """
                UPDATE tier_categories
                SET name = ?, sort_order = ?
                WHERE id = ?
                """,
                (
                    row.get("name") or slug,
                    int(row.get("sort_order") or 0),
                    current_categories[slug]["id"],
                ),
            )
        else:
            db.execute(
                """
                INSERT INTO tier_categories (game_id, name, slug, sort_order)
                VALUES (?, ?, ?, ?)
                """,
                (
                    game_id,
                    row.get("name") or slug,
                    slug,
                    int(row.get("sort_order") or 0),
                ),
            )
            recreated_category_slugs.add(slug)

    for slug, row in current_categories.items():
        if slug not in snapshot_categories:
            db.execute("DELETE FROM tier_categories WHERE id = ?", (row["id"],))

    current_fields = {
        row["field_key"]: row
        for row in db.execute(
            "SELECT * FROM game_character_fields WHERE game_id = ?", (game_id,)
        ).fetchall()
    }
    snapshot_fields = {
        str(row.get("field_key")): row
        for row in snapshot.get("fields", [])
        if row.get("field_key")
    }
    recreated_field_keys: set[str] = set()

    for field_key, row in snapshot_fields.items():
        if field_key in current_fields:
            db.execute(
                """
                UPDATE game_character_fields
                SET label = ?, field_type = ?, options_json = ?,
                    filterable = ?, sortable = ?, sort_order = ?
                WHERE id = ?
                """,
                (
                    row.get("label") or field_key,
                    row.get("field_type") or "text",
                    row.get("options_json") or "[]",
                    int(bool(row.get("filterable"))),
                    int(bool(row.get("sortable"))),
                    int(row.get("sort_order") or 0),
                    current_fields[field_key]["id"],
                ),
            )
        else:
            db.execute(
                """
                INSERT INTO game_character_fields
                    (game_id, field_key, label, field_type, options_json,
                     filterable, sortable, sort_order)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    game_id,
                    field_key,
                    row.get("label") or field_key,
                    row.get("field_type") or "text",
                    row.get("options_json") or "[]",
                    int(bool(row.get("filterable"))),
                    int(bool(row.get("sortable"))),
                    int(row.get("sort_order") or 0),
                ),
            )
            recreated_field_keys.add(field_key)

    for field_key, row in current_fields.items():
        if field_key not in snapshot_fields:
            db.execute("DELETE FROM game_character_fields WHERE id = ?", (row["id"],))


    if recreated_field_keys:
        field_ids = {
            row["field_key"]: row["id"]
            for row in db.execute(
                "SELECT id, field_key FROM game_character_fields WHERE game_id = ?",
                (game_id,),
            ).fetchall()
        }
        for row in snapshot.get("field_values", []):
            field_key = row.get("field_key")
            if field_key not in recreated_field_keys or field_key not in field_ids:
                continue
            if not db.execute(
                "SELECT 1 FROM characters WHERE id = ? AND game_id = ?",
                (row.get("character_id"), game_id),
            ).fetchone():
                continue
            db.execute(
                """
                INSERT INTO character_field_values (character_id, field_id, value)
                VALUES (?, ?, ?)
                ON CONFLICT(character_id, field_id)
                DO UPDATE SET value = excluded.value
                """,
                (row.get("character_id"), field_ids[field_key], row.get("value")),
            )

    if recreated_category_slugs:
        category_ids = {
            row["slug"]: row["id"]
            for row in db.execute(
                "SELECT id, slug FROM tier_categories WHERE game_id = ?", (game_id,)
            ).fetchall()
        }
        for row in snapshot.get("ratings", []):
            slug = row.get("category_slug")
            if slug not in recreated_category_slugs or slug not in category_ids:
                continue
            if not db.execute(
                "SELECT 1 FROM characters WHERE id = ? AND game_id = ?",
                (row.get("character_id"), game_id),
            ).fetchone():
                continue
            db.execute(
                """
                INSERT INTO character_ratings
                    (character_id, category_id, tier_value,
                     previous_tier_value, change_status, change_cycle)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(character_id, category_id)
                DO UPDATE SET
                    tier_value = excluded.tier_value,
                    previous_tier_value = excluded.previous_tier_value,
                    change_status = excluded.change_status,
                    change_cycle = excluded.change_cycle
                """,
                (
                    row.get("character_id"),
                    category_ids[slug],
                    row.get("tier_value"),
                    row.get("previous_tier_value"),
                    row.get("change_status"),
                    row.get("change_cycle"),
                ),
            )


def restore_character_snapshot(db, character_id: int, snapshot: dict[str, Any]) -> None:
    character_data = snapshot.get("character") or {}
    current = db.execute(
        "SELECT * FROM characters WHERE id = ?", (character_id,)
    ).fetchone()
    if current is None:
        raise ValueError("Персонаж больше не существует.")

    game_id = current["game_id"]
    db.execute(
        """
        UPDATE characters
        SET name = ?, slug = ?, image_filename = ?, avatar_background = ?,
            summary = ?, manual_changed_cycle = ?, publication_status = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            character_data.get("name", current["name"]),
            character_data.get("slug", current["slug"]),
            character_data.get("image_filename", current["image_filename"]),
            character_data.get("avatar_background", current["avatar_background"]),
            character_data.get("summary"),
            character_data.get("manual_changed_cycle"),
            character_data.get("publication_status", current["publication_status"]),
            character_id,
        ),
    )

    field_ids = {
        row["field_key"]: row["id"]
        for row in db.execute(
            "SELECT id, field_key FROM game_character_fields WHERE game_id = ?",
            (game_id,),
        ).fetchall()
    }
    db.execute("DELETE FROM character_field_values WHERE character_id = ?", (character_id,))
    for row in snapshot.get("field_values", []):
        field_id = field_ids.get(row.get("field_key"))
        if field_id is not None:
            db.execute(
                """
                INSERT INTO character_field_values (character_id, field_id, value)
                VALUES (?, ?, ?)
                """,
                (character_id, field_id, row.get("value")),
            )

    category_ids = {
        row["slug"]: row["id"]
        for row in db.execute(
            "SELECT id, slug FROM tier_categories WHERE game_id = ?", (game_id,)
        ).fetchall()
    }
    db.execute("DELETE FROM character_ratings WHERE character_id = ?", (character_id,))
    for row in snapshot.get("ratings", []):
        category_id = category_ids.get(row.get("category_slug"))
        if category_id is not None:
            db.execute(
                """
                INSERT INTO character_ratings
                    (character_id, category_id, tier_value,
                     previous_tier_value, change_status, change_cycle)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    character_id,
                    category_id,
                    row.get("tier_value"),
                    row.get("previous_tier_value"),
                    row.get("change_status"),
                    row.get("change_cycle"),
                ),
            )

    db.execute("DELETE FROM character_text_content WHERE character_id = ?", (character_id,))
    text = snapshot.get("text")
    if text:
        db.execute(
            """
            INSERT INTO character_text_content
                (character_id, profile_text, review_text, other_information_text)
            VALUES (?, ?, ?, ?)
            """,
            (
                character_id,
                text.get("profile_text"),
                text.get("review_text"),
                text.get("other_information_text"),
            ),
        )

    db.execute("DELETE FROM character_skills WHERE character_id = ?", (character_id,))
    for row in snapshot.get("skills", []):
        db.execute(
            """
            INSERT INTO character_skills
                (character_id, skill_type, name, description, extra_info, sort_order)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                character_id,
                row.get("skill_type"),
                row.get("name"),
                row.get("description"),
                row.get("extra_info"),
                int(row.get("sort_order") or 0),
            ),
        )

    db.execute("DELETE FROM character_stats WHERE character_id = ?", (character_id,))
    for row in snapshot.get("stats", []):
        db.execute(
            """
            INSERT INTO character_stats (character_id, label, value, sort_order)
            VALUES (?, ?, ?, ?)
            """,
            (
                character_id,
                row.get("label"),
                row.get("value"),
                int(row.get("sort_order") or 0),
            ),
        )

    db.execute("DELETE FROM character_pros_cons WHERE character_id = ?", (character_id,))
    for row in snapshot.get("pros_cons", []):
        db.execute(
            """
            INSERT INTO character_pros_cons (character_id, kind, text, sort_order)
            VALUES (?, ?, ?, ?)
            """,
            (
                character_id,
                row.get("kind"),
                row.get("text"),
                int(row.get("sort_order") or 0),
            ),
        )

    db.execute("UPDATE games SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (game_id,))


def restore_revision(db, revision) -> None:
    snapshot = decode_revision_snapshot(revision)
    if revision["entity_type"] == "game":
        restore_game_snapshot(db, revision["entity_id"], snapshot)
        return
    if revision["entity_type"] == "character":
        restore_character_snapshot(db, revision["entity_id"], snapshot)
        return
    raise ValueError("Неизвестный тип ревизии.")
