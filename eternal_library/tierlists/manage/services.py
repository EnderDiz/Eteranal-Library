from __future__ import annotations

from flask import request

from ..content_repository import TIER_VALUES, sync_character_fields, sync_character_modules, sync_sidebar_sections, sync_tier_categories
from ..helpers import tier_change_status


def save_game_configuration(db, game_id: int) -> None:
    sync_sidebar_sections(db, game_id, request.form.getlist("sidebar_sections"))
    sync_character_modules(db, game_id, request.form.getlist("character_modules"))

    sync_tier_categories(
        db,
        game_id,
        request.form.getlist("category_id"),
        request.form.getlist("category_name"),
    )

    sync_character_fields(
        db,
        game_id,
        request.form.getlist("field_id"),
        request.form.getlist("field_label"),
        request.form.getlist("field_type"),
        request.form.getlist("field_options"),
        request.form.getlist("field_filterable"),
        request.form.getlist("field_sortable"),
    )


def save_character_related_content(db, character_id: int, game_id: int, modules: dict[str, bool]) -> None:
    fields = db.execute(
        "SELECT id FROM game_character_fields WHERE game_id = ? ORDER BY sort_order, id",
        (game_id,),
    ).fetchall()
    for field in fields:
        value = request.form.get(f"field_{field['id']}", "").strip()
        if value:
            db.execute(
                """
                INSERT INTO character_field_values (character_id, field_id, value)
                VALUES (?, ?, ?)
                ON CONFLICT(character_id, field_id)
                DO UPDATE SET value = excluded.value
                """,
                (character_id, field["id"], value),
            )
        else:
            db.execute(
                "DELETE FROM character_field_values WHERE character_id = ? AND field_id = ?",
                (character_id, field["id"]),
            )

    game_row = db.execute(
        "SELECT content_cycle FROM games WHERE id = ?",
        (game_id,),
    ).fetchone()
    current_cycle = game_row["content_cycle"] if game_row else 1

    categories = db.execute(
        "SELECT id FROM tier_categories WHERE game_id = ? ORDER BY sort_order, id",
        (game_id,),
    ).fetchall()
    for category in categories:
        category_id = category["id"]
        tier_value = request.form.get(f"rating_{category_id}", "").strip()
        existing_rating = db.execute(
            """
            SELECT tier_value, previous_tier_value, change_status, change_cycle
            FROM character_ratings
            WHERE character_id = ? AND category_id = ?
            """,
            (character_id, category_id),
        ).fetchone()

        if tier_value in TIER_VALUES:
            previous_tier_value = None
            change_status = None
            change_cycle = None

            if existing_rating:
                old_tier = existing_rating["tier_value"]
                if old_tier != tier_value:
                    if (
                        existing_rating["change_cycle"] == current_cycle
                        and existing_rating["previous_tier_value"] in TIER_VALUES
                    ):
                        baseline_tier = existing_rating["previous_tier_value"]
                    else:
                        baseline_tier = old_tier

                    status = tier_change_status(baseline_tier, tier_value)
                    if status:
                        previous_tier_value = baseline_tier
                        change_status = status
                        change_cycle = current_cycle
                elif existing_rating["change_cycle"] == current_cycle:
                    previous_tier_value = existing_rating["previous_tier_value"]
                    change_status = existing_rating["change_status"]
                    change_cycle = existing_rating["change_cycle"]

            db.execute(
                """
                INSERT INTO character_ratings
                    (character_id, category_id, tier_value, previous_tier_value, change_status, change_cycle)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(character_id, category_id)
                DO UPDATE SET
                    tier_value = excluded.tier_value,
                    previous_tier_value = excluded.previous_tier_value,
                    change_status = excluded.change_status,
                    change_cycle = excluded.change_cycle
                """,
                (
                    character_id,
                    category_id,
                    tier_value,
                    previous_tier_value,
                    change_status,
                    change_cycle,
                ),
            )
        else:
            db.execute(
                "DELETE FROM character_ratings WHERE character_id = ? AND category_id = ?",
                (character_id, category_id),
            )

    current_text = db.execute(
        "SELECT * FROM character_text_content WHERE character_id = ?",
        (character_id,),
    ).fetchone()
    profile_text = current_text["profile_text"] if current_text else None
    review_text = current_text["review_text"] if current_text else None
    other_text = current_text["other_information_text"] if current_text else None

    if modules.get("profile"):
        profile_text = request.form.get("profile_text", "").strip() or None
    if modules.get("review"):
        review_text = request.form.get("review_text", "").strip() or None
    if modules.get("other_information"):
        other_text = request.form.get("other_information_text", "").strip() or None

    db.execute(
        """
        INSERT INTO character_text_content
            (character_id, profile_text, review_text, other_information_text)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(character_id)
        DO UPDATE SET
            profile_text = excluded.profile_text,
            review_text = excluded.review_text,
            other_information_text = excluded.other_information_text
        """,
        (character_id, profile_text, review_text, other_text),
    )

    if modules.get("skills"):
        db.execute("DELETE FROM character_skills WHERE character_id = ?", (character_id,))
        skill_types = request.form.getlist("skill_type")
        skill_names = request.form.getlist("skill_name")
        skill_descriptions = request.form.getlist("skill_description")
        skill_extra = request.form.getlist("skill_extra")
        total = min(len(skill_types), len(skill_names), len(skill_descriptions), len(skill_extra))
        for index in range(total):
            name = skill_names[index].strip()
            if not name:
                continue
            db.execute(
                """
                INSERT INTO character_skills
                    (character_id, skill_type, name, description, extra_info, sort_order)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    character_id,
                    skill_types[index].strip() or None,
                    name,
                    skill_descriptions[index].strip() or None,
                    skill_extra[index].strip() or None,
                    index,
                ),
            )

    if modules.get("stats"):
        db.execute("DELETE FROM character_stats WHERE character_id = ?", (character_id,))
        labels = request.form.getlist("stat_label")
        values = request.form.getlist("stat_value")
        for index, (label_raw, value_raw) in enumerate(zip(labels, values)):
            label = label_raw.strip()
            value = value_raw.strip()
            if not label or not value:
                continue
            db.execute(
                "INSERT INTO character_stats (character_id, label, value, sort_order) VALUES (?, ?, ?, ?)",
                (character_id, label, value, index),
            )

    if modules.get("pros_cons"):
        db.execute("DELETE FROM character_pros_cons WHERE character_id = ?", (character_id,))
        for kind, form_name in (("pro", "pros"), ("con", "cons")):
            for index, raw_text in enumerate(request.form.getlist(form_name)):
                text = raw_text.strip()
                if text:
                    db.execute(
                        "INSERT INTO character_pros_cons (character_id, kind, text, sort_order) VALUES (?, ?, ?, ?)",
                        (character_id, kind, text, index),
                    )
