import sqlite3

from flask import flash, g, jsonify, redirect, render_template, request, url_for

from ...auth.decorators import management_required
from ...core.media import save_content_image
from ...database import connect_db
from ...paths import CHARACTER_IMAGE_DIR, GAME_IMAGE_DIR
from ..content_repository import (
    CHARACTER_MODULES,
    SIDEBAR_SECTIONS,
    get_character_fields,
    get_game,
    get_game_modules,
    get_game_sidebar_sections,
    get_tier_categories,
    grant_creator_game_access,
    list_characters,
    unique_game_slug,
)
from ..helpers import autosave_error, is_autosave_request, require_game_access
from ..revision_repository import capture_entity_snapshot, record_revision_if_changed
from . import bp
from .services import save_game_configuration

@bp.route("/manage/games/new", methods=["GET", "POST"])
@management_required
def manage_game_new():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip() or None
        release_status = request.form.get("release_status", "released")
        publication_status = request.form.get("publication_status", "draft")
        release_date = request.form.get("release_date", "").strip() or None
        content_cycle_label = request.form.get("content_cycle_label", "").strip() or None

        if not name:
            flash("У игры должно быть название.", "error")
        elif release_status not in {"released", "upcoming"}:
            flash("Некорректный тип релиза.", "error")
        elif publication_status not in {"draft", "published", "archived"}:
            flash("Некорректный статус публикации.", "error")
        else:
            try:
                image_filename = save_content_image(
                    request.files.get("image"), GAME_IMAGE_DIR, "game"
                )
                slug = unique_game_slug(name)
                with connect_db() as db:
                    cursor = db.execute(
                        """
                        INSERT INTO games
                            (slug, name, description, image_filename, release_status,
                             release_date, content_cycle_label, publication_status, created_by)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            slug,
                            name,
                            description,
                            image_filename,
                            release_status,
                            release_date,
                            content_cycle_label,
                            publication_status,
                            g.user["id"],
                        ),
                    )
                    game_id = cursor.lastrowid
                    save_game_configuration(db, game_id)
                    db.commit()
                if g.user["role"] == "creator":
                    grant_creator_game_access(g.user["id"], game_id)
                flash("Игра создана.", "success")
                return redirect(url_for("tierlists_manage.manage_game", game_id=game_id))
            except ValueError as exc:
                flash(str(exc), "error")
            except sqlite3.IntegrityError:
                flash("Игра с таким названием уже существует.", "error")

    return render_template(
        "tierlists/manage/manage_game_editor.html",
        game=None,
        sidebar_sections={key: key in {"characters", "tier_list"} for key, _ in SIDEBAR_SECTIONS},
        character_modules={key: False for key, _ in CHARACTER_MODULES},
        categories=[],
        character_fields=[],
        sidebar_options=SIDEBAR_SECTIONS,
        module_options=CHARACTER_MODULES,
    )


@bp.get("/manage/games/<int:game_id>")
@management_required
def manage_game(game_id: int):
    game = require_game_access(game_id)
    return render_template(
        "tierlists/manage/manage_game.html",
        game=game,
        sidebar_sections=get_game_sidebar_sections(game_id),
        character_modules=get_game_modules(game_id),
        categories=get_tier_categories(game_id),
        character_fields=get_character_fields(game_id),
        characters=list_characters(game_id),
        sidebar_options=SIDEBAR_SECTIONS,
        module_options=CHARACTER_MODULES,
    )


@bp.route("/manage/games/<int:game_id>/edit", methods=["GET", "POST"])
@management_required
def manage_game_edit(game_id: int):
    game = require_game_access(game_id)
    autosave = is_autosave_request()

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip() or None
        release_status = request.form.get("release_status", "released")
        publication_status = request.form.get("publication_status", "draft")
        release_date = request.form.get("release_date", "").strip() or None
        content_cycle_label = request.form.get("content_cycle_label", "").strip() or None
        current_cycle_label = game["content_cycle_label"] or None
        next_content_cycle = game["content_cycle"] + int(content_cycle_label != current_cycle_label)

        if not name:
            if autosave:
                return autosave_error("У игры должно быть название.")
            flash("У игры должно быть название.", "error")
        elif release_status not in {"released", "upcoming"}:
            if autosave:
                return autosave_error("Некорректный тип релиза.")
            flash("Некорректный тип релиза.", "error")
        elif publication_status not in {"draft", "published", "archived"}:
            if autosave:
                return autosave_error("Некорректный статус публикации.")
            flash("Некорректный статус публикации.", "error")
        else:
            try:
                image_filename = save_content_image(
                    request.files.get("image"), GAME_IMAGE_DIR, "game"
                )
                with connect_db() as db:
                    before_snapshot = capture_entity_snapshot(db, "game", game_id)
                    if image_filename:
                        db.execute(
                            """
                            UPDATE games
                            SET name = ?, description = ?, image_filename = ?, release_status = ?,
                                release_date = ?, content_cycle_label = ?, content_cycle = ?,
                                publication_status = ?, updated_at = CURRENT_TIMESTAMP
                            WHERE id = ?
                            """,
                            (
                                name,
                                description,
                                image_filename,
                                release_status,
                                release_date,
                                content_cycle_label,
                                next_content_cycle,
                                publication_status,
                                game_id,
                            ),
                        )
                    else:
                        db.execute(
                            """
                            UPDATE games
                            SET name = ?, description = ?, release_status = ?, release_date = ?,
                                content_cycle_label = ?, content_cycle = ?,
                                publication_status = ?, updated_at = CURRENT_TIMESTAMP
                            WHERE id = ?
                            """,
                            (
                                name,
                                description,
                                release_status,
                                release_date,
                                content_cycle_label,
                                next_content_cycle,
                                publication_status,
                                game_id,
                            ),
                        )
                    save_game_configuration(db, game_id)
                    after_snapshot = capture_entity_snapshot(db, "game", game_id)
                    record_revision_if_changed(
                        db,
                        entity_type="game",
                        entity_id=game_id,
                        game_id=game_id,
                        before=before_snapshot,
                        after=after_snapshot,
                        user_id=g.user["id"],
                        reason="edit",
                        coalesce_seconds=300 if autosave else None,
                    )
                    db.commit()

                if autosave:
                    categories = get_tier_categories(game_id)
                    character_fields = get_character_fields(game_id)
                    return jsonify(
                        ok=True,
                        message="Изменения сохранены",
                        categories=[
                            {"id": row["id"], "name": row["name"]}
                            for row in categories
                        ],
                        fields=[
                            {"id": row["id"], "label": row["label"]}
                            for row in character_fields
                        ],
                    )

                flash("Настройки игры сохранены.", "success")
                return redirect(url_for("tierlists_manage.manage_game_edit", game_id=game_id))
            except ValueError as exc:
                if autosave:
                    return autosave_error(str(exc))
                flash(str(exc), "error")
            except sqlite3.IntegrityError:
                if autosave:
                    return autosave_error("Игра с таким названием уже существует.", 409)
                flash("Игра с таким названием уже существует.", "error")

    game = get_game(game_id)
    return render_template(
        "tierlists/manage/manage_game_editor.html",
        game=game,
        sidebar_sections=get_game_sidebar_sections(game_id),
        character_modules=get_game_modules(game_id),
        categories=get_tier_categories(game_id),
        character_fields=get_character_fields(game_id),
        sidebar_options=SIDEBAR_SECTIONS,
        module_options=CHARACTER_MODULES,
    )


@bp.post("/manage/games/<int:game_id>/delete")
@management_required
def manage_game_delete(game_id: int):
    game = require_game_access(game_id)

    with connect_db() as db:
        character_images = [
            row["image_filename"]
            for row in db.execute(
                "SELECT image_filename FROM characters WHERE game_id = ?",
                (game_id,),
            ).fetchall()
            if row["image_filename"]
        ]
        game_image = game["image_filename"]

        db.execute("DELETE FROM content_revisions WHERE game_id = ?", (game_id,))
        db.execute("DELETE FROM games WHERE id = ?", (game_id,))
        db.commit()

    if game_image:
        (GAME_IMAGE_DIR / game_image).unlink(missing_ok=True)
    for filename in character_images:
        (CHARACTER_IMAGE_DIR / filename).unlink(missing_ok=True)

    flash("Игра удалена.", "success")
    return redirect(url_for("tierlists_manage.manage_dashboard"))

