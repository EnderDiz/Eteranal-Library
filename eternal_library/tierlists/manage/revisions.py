import sqlite3

from flask import abort, flash, g, redirect, render_template, url_for

from ...auth.decorators import management_required
from ...database import connect_db
from ..content_repository import get_character, get_game
from ..helpers import require_game_access
from ..revision_repository import (
    capture_entity_snapshot,
    get_revision,
    list_revisions,
    record_revision,
    restore_revision,
)
from . import bp

@bp.get("/manage/games/<int:game_id>/history")
@management_required
def manage_game_history(game_id: int):
    game = require_game_access(game_id)
    return render_template(
        "tierlists/manage/manage_revision_history.html",
        game=game,
        character=None,
        entity_type="game",
        entity_name=game["name"],
        revisions=list_revisions("game", game_id),
        back_url=url_for("tierlists_manage.manage_game_edit", game_id=game_id),
    )


@bp.get("/manage/characters/<int:character_id>/history")
@management_required
def manage_character_history(character_id: int):
    character = get_character(character_id)
    if character is None:
        abort(404)
    game = require_game_access(character["game_id"])
    return render_template(
        "tierlists/manage/manage_revision_history.html",
        game=game,
        character=character,
        entity_type="character",
        entity_name=character["name"],
        revisions=list_revisions("character", character_id),
        back_url=url_for("tierlists_manage.manage_character_edit", character_id=character_id),
    )


@bp.post("/manage/revisions/<int:revision_id>/rollback")
@management_required
def manage_revision_rollback(revision_id: int):
    revision = get_revision(revision_id)
    if revision is None:
        abort(404)

    game = require_game_access(revision["game_id"])
    entity_type = revision["entity_type"]
    entity_id = revision["entity_id"]

    if entity_type == "game":
        if entity_id != game["id"] or get_game(entity_id) is None:
            abort(404)
        redirect_url = url_for("tierlists_manage.manage_game_edit", game_id=entity_id)
    elif entity_type == "character":
        character = get_character(entity_id)
        if character is None or character["game_id"] != game["id"]:
            abort(404)
        redirect_url = url_for("tierlists_manage.manage_character_edit", character_id=entity_id)
    else:
        abort(400)

    try:
        with connect_db() as db:
            current_snapshot = capture_entity_snapshot(db, entity_type, entity_id)
            if current_snapshot is None:
                abort(404)

            record_revision(
                db,
                entity_type=entity_type,
                entity_id=entity_id,
                game_id=game["id"],
                snapshot=current_snapshot,
                user_id=g.user["id"],
                reason="before_rollback",
            )
            restore_revision(db, revision)
            db.commit()
        flash("Версия восстановлена. Текущее состояние сохранено в истории.", "success")
    except (ValueError, sqlite3.IntegrityError) as exc:
        flash(str(exc) or "Не удалось восстановить версию.", "error")

    return redirect(redirect_url)
