from __future__ import annotations

import os
import re
import secrets
import sqlite3
import uuid
from datetime import timedelta
from functools import wraps
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin, urlparse

from flask import (
    Flask,
    abort,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from PIL import Image, ImageOps, UnidentifiedImageError

from database import connect_db, get_user_by_id, get_user_by_identifier, init_db
from security import hash_password, verify_password
from config import BRAND
from revision_repository import (
    capture_entity_snapshot,
    get_revision,
    list_revisions,
    record_revision,
    record_revision_if_changed,
    restore_revision,
)

from content_repository import (
    CHARACTER_MODULES,
    SIDEBAR_SECTIONS,
    TIER_VALUES,
    can_manage_game,
    get_character,
    get_public_character_by_slug,
    get_public_character_values,
    get_public_game_by_slug,
    get_character_editor_data,
    get_character_fields,
    get_game,
    get_game_modules,
    get_game_sidebar_sections,
    get_tier_categories,
    grant_creator_game_access,
    list_characters,
    list_public_characters,
    list_manageable_games,
    list_public_games,
    slugify,
    sync_character_fields,
    sync_character_modules,
    sync_sidebar_sections,
    sync_tier_categories,
    unique_character_slug,
    unique_game_slug,
)

PROJECT_ROOT = Path(__file__).resolve().parent
STYLE_DIR = PROJECT_ROOT / "style"
SCRIPT_DIR = PROJECT_ROOT / "script"
CONTENT_DIR = PROJECT_ROOT / "content"
AVATAR_DIR = CONTENT_DIR / "uploads" / "avatars"
GAME_IMAGE_DIR = CONTENT_DIR / "uploads" / "games"
CHARACTER_IMAGE_DIR = CONTENT_DIR / "uploads" / "characters"

USERNAME_RE = re.compile(r"^[A-Za-zА-Яа-яЁё0-9_.-]{3,32}$")
ALLOWED_AVATAR_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
AVATAR_BACKGROUND_VALUES = ("assr", "ssr", "sr", "r", "n")
RARITY_FIELD_NAMES = {"rarity", "редкость"}


def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder=None)

    app.config.update(
        SECRET_KEY=os.getenv("ETERNAL_SECRET_KEY", "dev-only-change-this-secret-key"),
        MAX_CONTENT_LENGTH=5 * 1024 * 1024,
        PERMANENT_SESSION_LIFETIME=timedelta(days=30),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.getenv("ETERNAL_COOKIE_SECURE", "0") == "1",
    )

    CONTENT_DIR.mkdir(parents=True, exist_ok=True)
    AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    GAME_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    CHARACTER_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    init_db()

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

    def csrf_token() -> str:
        token = session.get("csrf_token")
        if not token:
            token = secrets.token_urlsafe(32)
            session["csrf_token"] = token
        return token

    def avatar_url(user) -> str:
        if user and user["avatar_filename"]:
            return url_for("content_file", filename=f"uploads/avatars/{user['avatar_filename']}")
        return url_for("content_file", filename="eve.webp")

    def role_label(role: str) -> str:
        return {
            "admin": "Администратор",
            "creator": "Креатор",
            "user": "Пользователь",
        }.get(role, role)

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

    app.jinja_env.globals.update(
        csrf_token=csrf_token,
        avatar_url=avatar_url,
        role_label=role_label,
    )

    @app.context_processor
    def inject_template_globals():
        return {
            "current_user": g.user,
            "brand": BRAND,
        }

    def login_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if g.user is None:
                return redirect(url_for("login", next=request.full_path.rstrip("?")))
            return view(*args, **kwargs)
        return wrapped

    def roles_required(*roles):
        def decorator(view):
            @wraps(view)
            @login_required
            def wrapped(*args, **kwargs):
                if g.user["role"] not in roles:
                    abort(403)
                return view(*args, **kwargs)
            return wrapped
        return decorator

    def management_required(view):
        return roles_required("admin", "creator")(view)

    def require_game_access(game_id: int):
        game = get_game(game_id)
        if game is None:
            abort(404)
        if not can_manage_game(g.user, game_id):
            abort(403)
        return game

    def is_autosave_request() -> bool:
        return request.form.get("_autosave") == "1"

    def autosave_error(message: str, status: int = 422):
        return jsonify(ok=False, message=message), status

    def save_content_image(uploaded, directory: Path, prefix: str) -> str | None:
        if not uploaded or not uploaded.filename:
            return None

        extension = uploaded.filename.rsplit(".", 1)[-1].lower() if "." in uploaded.filename else ""
        if extension not in ALLOWED_AVATAR_EXTENSIONS:
            raise ValueError("Допустимы PNG, JPG/JPEG и WEBP.")

        try:
            raw = uploaded.read()
            image = Image.open(BytesIO(raw))
            image.load()
        except (UnidentifiedImageError, OSError) as exc:
            raise ValueError("Файл не удалось распознать как изображение.") from exc

        image = ImageOps.exif_transpose(image)
        if image.mode in ("RGBA", "LA") or "transparency" in image.info:
            image = image.convert("RGBA")
        else:
            image = image.convert("RGB")
        image.thumbnail((1800, 1800), Image.Resampling.LANCZOS)

        directory.mkdir(parents=True, exist_ok=True)
        filename = f"{prefix}_{uuid.uuid4().hex[:16]}.webp"
        image.save(directory / filename, "WEBP", quality=88, method=6)
        return filename

    def game_image_url(game) -> str | None:
        if game and game["image_filename"]:
            return url_for("content_file", filename=f"uploads/games/{game['image_filename']}")
        return None

    def character_image_url(character) -> str | None:
        if character and character["image_filename"]:
            return url_for("content_file", filename=f"uploads/characters/{character['image_filename']}")
        return None

    def find_rarity_field(fields):
        for field in fields:
            field_key = str(field.get("field_key") or "").strip().casefold()
            label = str(field.get("label") or "").strip().casefold()
            if field_key in RARITY_FIELD_NAMES or label in RARITY_FIELD_NAMES:
                return field
        return None

    def normalize_avatar_background(value: str | None) -> str | None:
        normalized = str(value or "").strip().casefold()
        return normalized if normalized in AVATAR_BACKGROUND_VALUES else None

    def tier_change_status(previous_tier: str, new_tier: str) -> str | None:
        if previous_tier not in TIER_VALUES or new_tier not in TIER_VALUES or previous_tier == new_tier:
            return None
        previous_index = TIER_VALUES.index(previous_tier)
        new_index = TIER_VALUES.index(new_tier)
        return "promoted" if new_index < previous_index else "demoted"

    def resolve_avatar_background(character, fields, field_values) -> str:
        rarity_field = find_rarity_field(fields)
        if rarity_field is not None:
            rarity_value = field_values.get(rarity_field["id"])
            rarity_background = normalize_avatar_background(rarity_value)
            if rarity_background:
                return rarity_background

        stored_background = None
        if character is not None:
            try:
                stored_background = character["avatar_background"]
            except (KeyError, IndexError):
                stored_background = None
        return normalize_avatar_background(stored_background) or "assr"

    app.jinja_env.globals.update(
        game_image_url=game_image_url,
        character_image_url=character_image_url,
    )

    def is_safe_redirect_target(target: str | None) -> bool:
        if not target:
            return False
        base = urlparse(request.host_url)
        candidate = urlparse(urljoin(request.host_url, target))
        return candidate.scheme in ("http", "https") and base.netloc == candidate.netloc

    # -------------------- Асеты --------------------

    @app.get("/style/<path:filename>")
    def style_file(filename):
        return send_from_directory(STYLE_DIR, filename)

    @app.get("/script/<path:filename>")
    def script_file(filename):
        return send_from_directory(SCRIPT_DIR, filename)

    @app.get("/content/<path:filename>")
    def content_file(filename):
        return send_from_directory(CONTENT_DIR, filename)

    @app.get("/")
    @app.get("/tier_list_main.html")
    def home():
        games = list_public_games()
        released_games = [game for game in games if game["release_status"] == "released"]
        upcoming_games = [game for game in games if game["release_status"] == "upcoming"]
        return render_template(
            "tier_list_main.html",
            games=games,
            released_games=released_games,
            upcoming_games=upcoming_games,
            featured_games=released_games[:5],
            new_games=released_games[:5],
        )

    def build_game_sidebar(game_id: int) -> list[dict[str, object]]:
        enabled = get_game_sidebar_sections(game_id)
        return [
            {"key": key, "label": label, "enabled": bool(enabled.get(key))}
            for key, label in SIDEBAR_SECTIONS
            if enabled.get(key)
        ]

    def public_game_section_url(game, section_key: str) -> str:
        if section_key == "tier_list":
            return url_for("public_game_tier_list", game_slug=game["slug"])
        if section_key == "characters":
            return url_for("public_game_characters", game_slug=game["slug"])
        return url_for("coming_soon")

    def public_game_landing_url(game) -> str:
        sections = get_game_sidebar_sections(game["id"])
        if sections.get("tier_list"):
            return url_for("public_game_tier_list", game_slug=game["slug"])
        if sections.get("characters"):
            return url_for("public_game_characters", game_slug=game["slug"])
        return url_for("coming_soon")

    app.jinja_env.globals.update(
        public_game_section_url=public_game_section_url,
        public_game_landing_url=public_game_landing_url,
    )

    def build_public_character_cards(game_id: int):
        game = get_game(game_id)
        characters = list_public_characters(game_id)
        field_map, rating_map, rating_change_map = get_public_character_values(game_id)
        fields = get_character_fields(game_id)
        categories = get_tier_categories(game_id)
        cards = []
        for character in characters:
            character_fields = field_map.get(character["id"], {})
            cards.append(
                {
                    "character": character,
                    "fields": character_fields,
                    "ratings": rating_map.get(character["id"], {}),
                    "rating_changes": rating_change_map.get(character["id"], {}),
                    "manual_changed": bool(
                        game and character["manual_changed_cycle"] == game["content_cycle"]
                    ),
                    "avatar_background": resolve_avatar_background(character, fields, character_fields),
                    "field_items": [
                        (field, character_fields.get(field["id"]))
                        for field in fields
                        if character_fields.get(field["id"])
                    ],
                    "rating_items": [
                        (category, rating_map.get(character["id"], {}).get(category["id"]))
                        for category in categories
                        if rating_map.get(character["id"], {}).get(category["id"])
                    ],
                }
            )
        return cards, fields, categories

    def apply_public_card_filters(cards, fields):
        query = request.args.get("q", "").strip()
        filterable_fields = [field for field in fields if field["filterable"]]
        sortable_fields = [field for field in fields if field["sortable"]]

        selected_filters: dict[int, str] = {}
        for field in filterable_fields:
            value = request.args.get(f"field_{field['id']}", "").strip()
            if value:
                selected_filters[field["id"]] = value

        def normalized(value) -> str:
            return " ".join(str(value or "").split()).casefold()

        visible_cards = []
        normalized_query = normalized(query)
        for card in cards:
            character = card["character"]
            if normalized_query and normalized_query not in normalized(character["name"]):
                continue
            if any(
                normalized(card["fields"].get(field_id)) != normalized(value)
                for field_id, value in selected_filters.items()
            ):
                continue
            visible_cards.append(card)

        sort_key = request.args.get("sort", "").strip()
        sort_field = next((field for field in sortable_fields if field["field_key"] == sort_key), None)
        if sort_field:
            def sort_value(card):
                value = card["fields"].get(sort_field["id"], "")
                if sort_field["field_type"] == "number":
                    try:
                        return (0, float(value))
                    except (TypeError, ValueError):
                        return (1, 0)
                return (0, normalized(value))
            visible_cards.sort(key=sort_value)
        else:
            visible_cards.sort(key=lambda card: normalized(card["character"]["name"]))

        filter_options: dict[int, list[str]] = {}
        for field in filterable_fields:
            if field["field_type"] == "select" and field.get("options"):
                options = list(field["options"])
            else:
                options = sorted(
                    {card["fields"].get(field["id"]) for card in cards if card["fields"].get(field["id"])},
                    key=normalized,
                )
            filter_options[field["id"]] = options

        return {
            "cards": visible_cards,
            "filterable_fields": filterable_fields,
            "sortable_fields": sortable_fields,
            "filter_options": filter_options,
            "selected_filters": selected_filters,
            "query": query,
            "sort_key": sort_key,
        }

    @app.get("/games/<game_slug>/tier-list")
    def public_game_tier_list(game_slug: str):
        game = get_public_game_by_slug(game_slug)
        if game is None:
            abort(404)
        if not get_game_sidebar_sections(game["id"]).get("tier_list"):
            abort(404)

        cards, fields, categories = build_public_character_cards(game["id"])
        filtered = apply_public_card_filters(cards, fields)
        visible_cards = filtered["cards"]

        selected_category_slug = request.args.get("category", "").strip()
        selected_category = None
        if categories:
            selected_category = next(
                (category for category in categories if category["slug"] == selected_category_slug),
                categories[0],
            )

        tier_groups = {tier: [] for tier in TIER_VALUES}
        unrated = []
        if selected_category:
            for card in visible_cards:
                automatic_status = card["rating_changes"].get(selected_category["id"])
                card["display_change_status"] = automatic_status or ("changed" if card["manual_changed"] else None)
                tier = card["ratings"].get(selected_category["id"])
                if tier in tier_groups:
                    tier_groups[tier].append(card)
                else:
                    unrated.append(card)
        else:
            for card in visible_cards:
                card["display_change_status"] = "changed" if card["manual_changed"] else None
            unrated = visible_cards

        return render_template(
            "tier_list_page.html",
            game=game,
            sidebar_sections=build_game_sidebar(game["id"]),
            categories=categories,
            selected_category=selected_category,
            fields=fields,
            filterable_fields=filtered["filterable_fields"],
            sortable_fields=filtered["sortable_fields"],
            filter_options=filtered["filter_options"],
            selected_filters=filtered["selected_filters"],
            query=filtered["query"],
            sort_key=filtered["sort_key"],
            tier_values=TIER_VALUES,
            tier_groups=tier_groups,
            unrated_characters=unrated,
        )

    @app.get("/games/<game_slug>/characters")
    def public_game_characters(game_slug: str):
        game = get_public_game_by_slug(game_slug)
        if game is None:
            abort(404)
        if not get_game_sidebar_sections(game["id"]).get("characters"):
            abort(404)

        cards, fields, categories = build_public_character_cards(game["id"])
        filtered = apply_public_card_filters(cards, fields)

        return render_template(
            "character_list_page.html",
            game=game,
            cards=filtered["cards"],
            sidebar_sections=build_game_sidebar(game["id"]),
            fields=fields,
            categories=categories,
            filterable_fields=filtered["filterable_fields"],
            sortable_fields=filtered["sortable_fields"],
            filter_options=filtered["filter_options"],
            selected_filters=filtered["selected_filters"],
            query=filtered["query"],
            sort_key=filtered["sort_key"],
        )

    @app.get("/games/<game_slug>/characters/<character_slug>")
    def public_character(game_slug: str, character_slug: str):
        game = get_public_game_by_slug(game_slug)
        if game is None:
            abort(404)
        character = get_public_character_by_slug(game["id"], character_slug)
        if character is None:
            abort(404)
        editor_data = get_character_editor_data(character["id"])
        return render_template(
            "character_info_page.html",
            game=game,
            character=character,
            sidebar_sections=build_game_sidebar(game["id"]),
            modules=get_game_modules(game["id"]),
            fields=get_character_fields(game["id"]),
            categories=get_tier_categories(game["id"]),
            editor_data=editor_data,
        )

    @app.get("/tier_list_page.html")
    def tier_list():
        for game in list_public_games():
            if game["release_status"] == "released" and get_game_sidebar_sections(game["id"]).get("tier_list"):
                return redirect(url_for("public_game_tier_list", game_slug=game["slug"]))
        return redirect(url_for("home"))

    @app.get("/character_info_page.html")
    def character_info():
        games = list_public_games()
        for game in games:
            characters = list_public_characters(game["id"])
            if characters:
                return redirect(
                    url_for(
                        "public_character",
                        game_slug=game["slug"],
                        character_slug=characters[0]["slug"],
                    )
                )
        return redirect(url_for("home"))

    @app.get("/coming_soon.html")
    def coming_soon():
        return render_template("coming_soon.html")

    # -------------------- Аунтификация --------------------

    @app.route("/login", methods=["GET", "POST"])
    @app.route("/login_page.html", methods=["GET", "POST"])
    def login():
        if g.user is not None and request.method == "GET":
            return redirect(url_for("profile"))

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
                return redirect(url_for("profile"))

        return render_template(
            "login_page.html",
            login_error=error,
            login_value=identifier,
            next_url=request.args.get("next", ""),
        )

    @app.post("/logout")
    @login_required
    def logout():
        session.clear()
        return redirect(url_for("home"))

    # -------------------- Профиль --------------------

    @app.get("/profile")
    @app.get("/profile_page.html")
    @login_required
    def profile():
        active_tab = request.args.get("tab", "profile")
        if active_tab not in {"profile", "settings"}:
            active_tab = "profile"

        return render_template(
            "profile_page.html",
            active_tab=active_tab,
            registration_date=format_registration_date(g.user["created_at"]),
        )

    @app.post("/profile/account")
    @login_required
    def update_account():
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()

        if not USERNAME_RE.fullmatch(username):
            flash(
                "Логин должен содержать 3–32 символа: буквы, цифры, _, . или -.",
                "error",
            )
            return redirect(url_for("profile", tab="settings"))

        if email and ("@" not in email or email.startswith("@") or email.endswith("@")):
            flash("Укажите корректный email.", "error")
            return redirect(url_for("profile", tab="settings"))

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

        return redirect(url_for("profile", tab="settings"))

    @app.post("/profile/password")
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

        return redirect(url_for("profile", tab="settings"))

    @app.post("/profile/avatar")
    @login_required
    def update_avatar():
        uploaded = request.files.get("avatar")
        if not uploaded or not uploaded.filename:
            flash("Выберите изображение.", "error")
            return redirect(url_for("profile", tab="settings"))

        extension = uploaded.filename.rsplit(".", 1)[-1].lower() if "." in uploaded.filename else ""
        if extension not in ALLOWED_AVATAR_EXTENSIONS:
            flash("Допустимы PNG, JPG/JPEG и WEBP.", "error")
            return redirect(url_for("profile", tab="settings"))

        try:
            raw = uploaded.read()
            image = Image.open(BytesIO(raw))
            image.load()
        except (UnidentifiedImageError, OSError):
            flash("Файл не удалось распознать как изображение.", "error")
            return redirect(url_for("profile", tab="settings"))

        image = ImageOps.exif_transpose(image).convert("RGB")
        image = ImageOps.fit(image, (512, 512), method=Image.Resampling.LANCZOS)

        filename = f"user_{g.user['id']}.webp"
        target = AVATAR_DIR / filename
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
        return redirect(url_for("profile", tab="settings"))

    # -------------------- Админка --------------------

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
                        character_id, category_id, tier_value, previous_tier_value,
                        change_status, change_cycle,
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

    @app.get("/manage")
    @app.get("/manage/")
    @management_required
    def manage_dashboard():
        games = list_manageable_games(g.user)
        character_count = sum(game["character_count"] for game in games)
        published_count = sum(1 for game in games if game["publication_status"] == "published")
        upcoming_count = sum(1 for game in games if game["release_status"] == "upcoming")
        return render_template(
            "manage_dashboard.html",
            games=games,
            character_count=character_count,
            published_count=published_count,
            upcoming_count=upcoming_count,
        )

    @app.route("/manage/games/new", methods=["GET", "POST"])
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
                    return redirect(url_for("manage_game", game_id=game_id))
                except ValueError as exc:
                    flash(str(exc), "error")
                except sqlite3.IntegrityError:
                    flash("Игра с таким названием уже существует.", "error")

        return render_template(
            "manage_game_editor.html",
            game=None,
            sidebar_sections={key: key in {"characters", "tier_list"} for key, _ in SIDEBAR_SECTIONS},
            character_modules={key: False for key, _ in CHARACTER_MODULES},
            categories=[],
            character_fields=[],
            sidebar_options=SIDEBAR_SECTIONS,
            module_options=CHARACTER_MODULES,
        )

    @app.get("/manage/games/<int:game_id>")
    @management_required
    def manage_game(game_id: int):
        game = require_game_access(game_id)
        return render_template(
            "manage_game.html",
            game=game,
            sidebar_sections=get_game_sidebar_sections(game_id),
            character_modules=get_game_modules(game_id),
            categories=get_tier_categories(game_id),
            character_fields=get_character_fields(game_id),
            characters=list_characters(game_id),
            sidebar_options=SIDEBAR_SECTIONS,
            module_options=CHARACTER_MODULES,
        )

    @app.route("/manage/games/<int:game_id>/edit", methods=["GET", "POST"])
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
                                    name, description, image_filename, release_status, release_date,
                                    content_cycle_label, next_content_cycle, publication_status, game_id,
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
                                    name, description, release_status, release_date, content_cycle_label,
                                    next_content_cycle, publication_status, game_id,
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
                    return redirect(url_for("manage_game_edit", game_id=game_id))
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
            "manage_game_editor.html",
            game=game,
            sidebar_sections=get_game_sidebar_sections(game_id),
            character_modules=get_game_modules(game_id),
            categories=get_tier_categories(game_id),
            character_fields=get_character_fields(game_id),
            sidebar_options=SIDEBAR_SECTIONS,
            module_options=CHARACTER_MODULES,
        )

    @app.post("/manage/games/<int:game_id>/delete")
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
        return redirect(url_for("manage_dashboard"))

    @app.route("/manage/games/<int:game_id>/characters/new", methods=["GET", "POST"])
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
                            (game_id, name, slug, image_filename, avatar_background, summary, publication_status, g.user["id"]),
                        )
                        character_id = cursor.lastrowid
                        save_character_related_content(db, character_id, game_id, modules)
                        db.execute("UPDATE games SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (game_id,))
                        db.commit()
                    flash("Персонаж сохранён.", "success")
                    if request.form.get("submit_action") == "continue":
                        return redirect(url_for("manage_character_edit", character_id=character_id))
                    return redirect(url_for("manage_game", game_id=game_id))
                except ValueError as exc:
                    flash(str(exc), "error")
                except sqlite3.IntegrityError:
                    flash("Персонаж с таким именем уже существует в этой игре.", "error")

        return render_template(
            "manage_character_editor.html",
            game=game,
            character=None,
            fields=fields,
            categories=categories,
            modules=modules,
            editor_data={"values": {}, "ratings": {}, "text": None, "skills": [], "stats": [], "pros": [], "cons": []},
            tier_values=TIER_VALUES,
            rarity_field=rarity_field,
            avatar_background_values=AVATAR_BACKGROUND_VALUES,
        )

    @app.route("/manage/characters/<int:character_id>/edit", methods=["GET", "POST"])
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
                                    name, image_filename, avatar_background, summary, manual_changed_cycle,
                                    publication_status, character_id,
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
                                (name, avatar_background, summary, manual_changed_cycle, publication_status, character_id),
                            )
                        save_character_related_content(db, character_id, game_id, modules)
                        db.execute("UPDATE games SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (game_id,))
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
                        return redirect(url_for("manage_game", game_id=game_id))
                    return redirect(url_for("manage_character_edit", character_id=character_id))
                except ValueError as exc:
                    if autosave:
                        return autosave_error(str(exc))
                    flash(str(exc), "error")

        character = get_character(character_id)
        return render_template(
            "manage_character_editor.html",
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

    @app.post("/manage/characters/<int:character_id>/delete")
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
        return redirect(url_for("manage_game", game_id=game["id"]))

    @app.get("/manage/games/<int:game_id>/history")
    @management_required
    def manage_game_history(game_id: int):
        game = require_game_access(game_id)
        return render_template(
            "manage_revision_history.html",
            game=game,
            character=None,
            entity_type="game",
            entity_name=game["name"],
            revisions=list_revisions("game", game_id),
            back_url=url_for("manage_game_edit", game_id=game_id),
        )

    @app.get("/manage/characters/<int:character_id>/history")
    @management_required
    def manage_character_history(character_id: int):
        character = get_character(character_id)
        if character is None:
            abort(404)
        game = require_game_access(character["game_id"])
        return render_template(
            "manage_revision_history.html",
            game=game,
            character=character,
            entity_type="character",
            entity_name=character["name"],
            revisions=list_revisions("character", character_id),
            back_url=url_for("manage_character_edit", character_id=character_id),
        )

    @app.post("/manage/revisions/<int:revision_id>/rollback")
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
            redirect_url = url_for("manage_game_edit", game_id=entity_id)
        elif entity_type == "character":
            character = get_character(entity_id)
            if character is None or character["game_id"] != game["id"]:
                abort(404)
            redirect_url = url_for("manage_character_edit", character_id=entity_id)
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

    # -------------------- Тесты / Эндпоинты --------------------

    @app.get("/health")
    def health():
        return jsonify({"ok": True, "service": BRAND["name"]})

    @app.get("/api/me")
    def api_me():
        if g.user is None:
            return jsonify({"authenticated": False}), 401
        return jsonify(
            {
                "authenticated": True,
                "id": g.user["id"],
                "username": g.user["username"],
                "email": g.user["email"],
                "role": g.user["role"],
            }
        )

    @app.get("/api/admin/ping")
    @roles_required("admin")
    def admin_ping():
        return jsonify(
            {
                "ok": True,
                "message": "Admin access granted",
                "username": g.user["username"],
                "role": g.user["role"],
            }
        )

    @app.errorhandler(413)
    def file_too_large(_error):
        flash("Файл слишком большой. Максимальный размер — 5 МБ.", "error")
        if request.path.startswith("/manage") and g.user is not None and g.user["role"] in {"admin", "creator"}:
            return redirect(request.referrer or url_for("manage_dashboard"))
        return redirect(url_for("profile", tab="settings"))

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
