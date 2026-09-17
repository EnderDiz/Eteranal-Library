from __future__ import annotations

from flask import Blueprint, flash, g, redirect, render_template, request, send_from_directory, url_for

from ..paths import MEDIA_ROOT

bp = Blueprint("core", __name__)


@bp.get("/")
def home():
    return render_template("core/index.html")



@bp.get("/media/<path:filename>")
def media_file(filename: str):
    return send_from_directory(MEDIA_ROOT, filename)



@bp.app_errorhandler(413)
def file_too_large(_error):
    flash("Файл слишком большой. Максимальный размер — 5 МБ.", "error")
    if g.user is not None and g.user["role"] in {"admin", "creator"}:
        if request.path.startswith("/library/manage"):
            return redirect(request.referrer or url_for("library_manage.dashboard"))
        if request.path.startswith("/manage"):
            return redirect(request.referrer or url_for("tierlists_manage.manage_dashboard"))
    return redirect(url_for("profile.profile", tab="settings"))
