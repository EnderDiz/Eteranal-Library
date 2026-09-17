from __future__ import annotations

import re
import sqlite3
from io import BytesIO

from flask import Blueprint, flash, g, redirect, render_template, request, url_for
from PIL import Image, ImageOps, UnidentifiedImageError

from ..auth.decorators import login_required
from ..auth.security import hash_password, verify_password
from ..core.media import ALLOWED_IMAGE_EXTENSIONS
from ..database import connect_db
from ..paths import AVATAR_DIR

bp = Blueprint("profile", __name__)

USERNAME_RE = re.compile(r"^[A-Za-zА-Яа-яЁё0-9_.-]{3,32}$")


def format_registration_date(value: str) -> str:
    if not value:
        return "—"
    date_part = value.split(" ", 1)[0]
    try:
        year, month, day = [int(part) for part in date_part.split("-")]
    except (TypeError, ValueError):
        return value

    months = [
        "января", "февраля", "марта", "апреля", "мая", "июня",
        "июля", "августа", "сентября", "октября", "ноября", "декабря",
    ]
    return f"{day} {months[month - 1]} {year}"


@bp.get("/profile")
@login_required
def profile():
    active_tab = request.args.get("tab", "profile")
    if active_tab not in {"profile", "settings"}:
        active_tab = "profile"

    return render_template(
        "profile/profile.html",
        active_tab=active_tab,
        registration_date=format_registration_date(g.user["created_at"]),
    )


@bp.post("/profile/account")
@login_required
def update_account():
    username = request.form.get("username", "").strip()
    email = request.form.get("email", "").strip().lower()

    if not USERNAME_RE.fullmatch(username):
        flash(
            "Логин должен содержать 3–32 символа: буквы, цифры, _, . или -.",
            "error",
        )
        return redirect(url_for("profile.profile", tab="settings"))

    if email and ("@" not in email or email.startswith("@") or email.endswith("@")):
        flash("Укажите корректный email.", "error")
        return redirect(url_for("profile.profile", tab="settings"))

    try:
        with connect_db() as db:
            db.execute(
                """
                UPDATE users
                SET username = ?, email = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (username, email or None, g.user["id"]),
            )
            db.commit()
    except sqlite3.IntegrityError:
        flash("Такой логин или email уже используется.", "error")
    else:
        flash("Основные данные сохранены.", "success")

    return redirect(url_for("profile.profile", tab="settings"))


@bp.post("/profile/password")
@login_required
def update_password():
    current_password = request.form.get("current-password", "")
    new_password = request.form.get("new-password", "")
    confirm_password = request.form.get("confirm-password", "")

    if not verify_password(current_password, g.user["password_hash"]):
        flash("Текущий пароль указан неверно.", "error")
    elif len(new_password) < 8:
        flash("Новый пароль должен содержать минимум 8 символов.", "error")
    elif new_password != confirm_password:
        flash("Новые пароли не совпадают.", "error")
    else:
        with connect_db() as db:
            db.execute(
                """
                UPDATE users
                SET password_hash = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (hash_password(new_password), g.user["id"]),
            )
            db.commit()
        flash("Пароль изменён.", "success")

    return redirect(url_for("profile.profile", tab="settings"))


@bp.post("/profile/avatar")
@login_required
def update_avatar():
    uploaded = request.files.get("avatar")
    if not uploaded or not uploaded.filename:
        flash("Выберите изображение.", "error")
        return redirect(url_for("profile.profile", tab="settings"))

    extension = uploaded.filename.rsplit(".", 1)[-1].lower() if "." in uploaded.filename else ""
    if extension not in ALLOWED_IMAGE_EXTENSIONS:
        flash("Допустимы PNG, JPG/JPEG и WEBP.", "error")
        return redirect(url_for("profile.profile", tab="settings"))

    try:
        raw = uploaded.read()
        image = Image.open(BytesIO(raw))
        image.load()
    except (UnidentifiedImageError, OSError):
        flash("Файл не удалось распознать как изображение.", "error")
        return redirect(url_for("profile.profile", tab="settings"))

    image = ImageOps.exif_transpose(image).convert("RGB")
    image = ImageOps.fit(image, (512, 512), method=Image.Resampling.LANCZOS)

    filename = f"user_{g.user['id']}.webp"
    target = AVATAR_DIR / filename
    AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    image.save(target, "WEBP", quality=88, method=6)

    with connect_db() as db:
        db.execute(
            """
            UPDATE users
            SET avatar_filename = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (filename, g.user["id"]),
        )
        db.commit()

    flash("Аватар обновлён.", "success")
    return redirect(url_for("profile.profile", tab="settings"))
