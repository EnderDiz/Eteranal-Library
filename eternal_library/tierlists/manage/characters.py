import sqlite3

from flask import abort, flash, g, jsonify, redirect, render_template, request, url_for

from ...auth.decorators import management_required
from ...core.media import save_content_image
from ...database import connect_db
from ...paths import CHARACTER_IMAGE_DIR
from ..content_repository import (
    TIER_VALUES,
    get_character,
    get_character_editor_data,
    get_character_fields,
    get_game_modules,
    get_tier_categories,
    unique_character_slug,
)
from ..helpers import (
    AVATAR_BACKGROUND_VALUES,
    autosave_error,
    find_rarity_field,
    is_autosave_request,
    normalize_avatar_background,
    require_game_access,
)
from ..revision_repository import capture_entity_snapshot, record_revision_if_changed
from . import bp
from .services import save_character_related_content

@bp.route("/manage/games/<int:game_id>/characters/new", methods=["GET", "POST"])
@management_required
def manage_character_new(game_id: int):
    game = require_game_access(game_id)
    fields = get_character_fields(game_id)
    categories = get_tier_categories(game_id)
    modules = get_game_modules(game_id)
    rarity_field = find_rarity_field(fields)

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        summary = request.form.get("summary", "").strip() or None
        publication_status = request.form.get("publication_status", "draft")
        image = request.files.get("image")
        avatar_background = normalize_avatar_background(request.form.get("avatar_background")) or "assr"

        if not name:
            flash("Имя персонажа обязательно.", "error")
        elif not image or not image.filename:
            flash("Изображение персонажа обязательно.", "error")
        elif publication_status not in {"draft", "published", "archived"}:
            flash("Некорректный статус публикации.", "error")
        else:
            try:
                image_filename = save_content_image(image, CHARACTER_IMAGE_DIR, "character")
                slug = unique_character_slug(game_id, name)
                with connect_db() as db:
                    cursor = db.execute(
                        """
                        INSERT INTO characters
                            (game_id, name, slug, image_filename, avatar_background, summary, publication_status, created_by)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            game_id,
                            name,
                            slug,
                            image_filename,
                            avatar_background,
                            summary,
                            publication_status,
                            g.user["id"],
                        ),
                    )
                    character_id = cursor.lastrowid
                    save_character_related_content(db, character_id, game_id, modules)
                    db.execute(
                        "UPDATE games SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (game_id,),
                    )
                    db.commit()
                flash("Персонаж сохранён.", "success")
                if request.form.get("submit_action") == "continue":
                    return redirect(
                        url_for("tierlists_manage.manage_character_edit", character_id=character_id)
                    )
                return redirect(url_for("tierlists_manage.manage_game", game_id=game_id))
            except ValueError as exc:
                flash(str(exc), "error")
            except sqlite3.IntegrityError:
                flash("Персонаж с таким именем уже существует в этой игре.", "error")

    return render_template(
        "tierlists/manage/manage_character_editor.html",
        game=game,
        character=None,
        fields=fields,
        categories=categories,
        modules=modules,
        editor_data={
            "values": {},
            "ratings": {},
            "text": None,
            "skills": [],
            "stats": [],
            "pros": [],
            "cons": [],
        },
        tier_values=TIER_VALUES,
        rarity_field=rarity_field,
        avatar_background_values=AVATAR_BACKGROUND_VALUES,
    )


@bp.route("/manage/characters/<int:character_id>/edit", methods=["GET", "POST"])
@management_required
def manage_character_edit(character_id: int):
    character = get_character(character_id)
    if character is None:
        abort(404)
    game = require_game_access(character["game_id"])
    game_id = game["id"]
    fields = get_character_fields(game_id)
    categories = get_tier_categories(game_id)
    modules = get_game_modules(game_id)
    rarity_field = find_rarity_field(fields)
    autosave = is_autosave_request()

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        summary = request.form.get("summary", "").strip() or None
        publication_status = request.form.get("publication_status", "draft")
        avatar_background = normalize_avatar_background(request.form.get("avatar_background")) or "assr"
        manual_changed_cycle = game["content_cycle"] if request.form.get("mark_changed") == "1" else None

        if not name:
            if autosave:
                return autosave_error("Имя персонажа обязательно.")
            flash("Имя персонажа обязательно.", "error")
        elif publication_status not in {"draft", "published", "archived"}:
            if autosave:
                return autosave_error("Некорректный статус публикации.")
            flash("Некорректный статус публикации.", "error")
        else:
            try:
                image_filename = save_content_image(
                    request.files.get("image"), CHARACTER_IMAGE_DIR, "character"
                )
                with connect_db() as db:
                    before_snapshot = capture_entity_snapshot(db, "character", character_id)
                    if image_filename:
                        db.execute(
                            """
                            UPDATE characters
                            SET name = ?, image_filename = ?, avatar_background = ?, summary = ?,
                                manual_changed_cycle = ?, publication_status = ?, updated_at = CURRENT_TIMESTAMP
                            WHERE id = ?
                            """,
                            (
                                name,
                                image_filename,
                                avatar_background,
                                summary,
                                manual_changed_cycle,
                                publication_status,
                                character_id,
                            ),
                        )
                    else:
                        db.execute(
                            """
                            UPDATE characters
                            SET name = ?, avatar_background = ?, summary = ?, manual_changed_cycle = ?,
                                publication_status = ?, updated_at = CURRENT_TIMESTAMP
                            WHERE id = ?
                            """,
                            (
                                name,
                                avatar_background,
                                summary,
                                manual_changed_cycle,
                                publication_status,
                                character_id,
                            ),
                        )
                    save_character_related_content(db, character_id, game_id, modules)
                    db.execute(
                        "UPDATE games SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (game_id,),
                    )
                    after_snapshot = capture_entity_snapshot(db, "character", character_id)
                    record_revision_if_changed(
                        db,
                        entity_type="character",
                        entity_id=character_id,
                        game_id=game_id,
                        before=before_snapshot,
                        after=after_snapshot,
                        user_id=g.user["id"],
                        reason="edit",
                        coalesce_seconds=300 if autosave else None,
                    )
                    db.commit()

                if autosave:
                    return jsonify(ok=True, message="Изменения сохранены")

                flash("Персонаж обновлён.", "success")
                if request.form.get("submit_action") == "back":
                    return redirect(url_for("tierlists_manage.manage_game", game_id=game_id))
                return redirect(
                    url_for("tierlists_manage.manage_character_edit", character_id=character_id)
                )
            except ValueError as exc:
                if autosave:
                    return autosave_error(str(exc))
                flash(str(exc), "error")

    character = get_character(character_id)
    return render_template(
        "tierlists/manage/manage_character_editor.html",
        game=game,
        character=character,
        fields=fields,
        categories=categories,
        modules=modules,
        editor_data=get_character_editor_data(character_id),
        tier_values=TIER_VALUES,
        rarity_field=rarity_field,
        avatar_background_values=AVATAR_BACKGROUND_VALUES,
    )


@bp.post("/manage/characters/<int:character_id>/delete")
@management_required
def manage_character_delete(character_id: int):
    character = get_character(character_id)
    if character is None:
        abort(404)

    game = require_game_access(character["game_id"])
    image_filename = character["image_filename"]

    with connect_db() as db:
        db.execute(
            "DELETE FROM content_revisions WHERE entity_type = 'character' AND entity_id = ?",
            (character_id,),
        )
        db.execute("DELETE FROM characters WHERE id = ?", (character_id,))
        db.execute(
            "UPDATE games SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (game["id"],),
        )
        db.commit()

    if image_filename:
        (CHARACTER_IMAGE_DIR / image_filename).unlink(missing_ok=True)

    flash("Персонаж удалён.", "success")
    return redirect(url_for("tierlists_manage.manage_game", game_id=game["id"]))

