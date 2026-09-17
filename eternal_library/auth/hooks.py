from __future__ import annotations

import secrets

from flask import abort, g, request, session, url_for

from ..config import BRAND
from ..database import get_user_by_id


def csrf_token() -> str:
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def avatar_url(user) -> str:
    if user and user["avatar_filename"]:
        return url_for("core.media_file", filename=f"avatars/{user['avatar_filename']}")
    return url_for("core.media_file", filename="tierlists/characters/eve.webp")


def role_label(role: str) -> str:
    return {
        "admin": "Администратор",
        "creator": "Редактор",
        "user": "Пользователь",
    }.get(role, role)


def register_auth_hooks(app) -> None:
    @app.before_request
    def load_logged_in_user():
        g.user = None
        user_id = session.get("user_id")
        if user_id is not None:
            g.user = get_user_by_id(int(user_id))
            if g.user is None:
                session.clear()

        if request.method == "POST":
            sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
            expected = session.get("csrf_token")
            if not expected or not sent or not secrets.compare_digest(expected, sent):
                abort(400, description="Некорректный CSRF-токен.")

    @app.context_processor
    def inject_template_globals():
        return {
            "current_user": g.user,
            "brand": BRAND,
        }

    app.jinja_env.globals.update(
        csrf_token=csrf_token,
        avatar_url=avatar_url,
        role_label=role_label,
    )
