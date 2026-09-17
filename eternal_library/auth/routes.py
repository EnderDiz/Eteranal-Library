from __future__ import annotations

import secrets
from urllib.parse import urljoin, urlparse

from flask import Blueprint, g, redirect, render_template, request, session, url_for

from ..database import get_user_by_identifier
from .decorators import login_required
from .security import verify_password

bp = Blueprint("auth", __name__)


def is_safe_redirect_target(target: str | None) -> bool:
    if not target:
        return False
    base = urlparse(request.host_url)
    candidate = urlparse(urljoin(request.host_url, target))
    return candidate.scheme in ("http", "https") and base.netloc == candidate.netloc


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user is not None and request.method == "GET":
        return redirect(url_for("profile.profile"))

    identifier = ""
    error = None

    if request.method == "POST":
        identifier = request.form.get("login", "").strip()
        password = request.form.get("password", "")
        remember = request.form.get("remember") == "1"

        user = get_user_by_identifier(identifier) if identifier else None

        if not user or not verify_password(password, user["password_hash"]):
            error = "Неверный логин/email или пароль."
        else:
            session.clear()
            session["user_id"] = user["id"]
            session["csrf_token"] = secrets.token_urlsafe(32)
            session.permanent = remember

            target = request.args.get("next") or request.form.get("next")
            if is_safe_redirect_target(target):
                return redirect(target)
            return redirect(url_for("profile.profile"))

    return render_template(
        "auth/login.html",
        login_error=error,
        login_value=identifier,
        next_url=request.args.get("next", ""),
    )


@bp.post("/logout")
@login_required
def logout():
    session.clear()
    return redirect(url_for("core.home"))
