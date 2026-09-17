from __future__ import annotations

import os
from datetime import timedelta

from flask import Flask

from .auth.hooks import register_auth_hooks
from .database import init_db
from .paths import ensure_runtime_directories
from .tierlists.context import register_tierlist_template_helpers


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
        static_url_path="/static",
    )

    app.config.update(
        SECRET_KEY=os.getenv("ETERNAL_SECRET_KEY", "dev-only-change-this-secret-key"),
        MAX_CONTENT_LENGTH=5 * 1024 * 1024,
        PERMANENT_SESSION_LIFETIME=timedelta(days=30),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.getenv("ETERNAL_COOKIE_SECURE", "0") == "1",
    )

    ensure_runtime_directories()
    init_db()
    register_auth_hooks(app)
    register_tierlist_template_helpers(app)
    register_blueprints(app)

    return app


def register_blueprints(app: Flask) -> None:
    from .auth.routes import bp as auth_bp
    from .core.routes import bp as core_bp
    from .profile.routes import bp as profile_bp
    from .library.routes import bp as library_bp
    from .library.manage import bp as library_manage_bp
    from .tierlists.manage import bp as tierlists_manage_bp
    from .tierlists.routes import bp as tierlists_bp

    app.register_blueprint(core_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(profile_bp)
    app.register_blueprint(library_bp)
    app.register_blueprint(library_manage_bp)
    app.register_blueprint(tierlists_bp)
    app.register_blueprint(tierlists_manage_bp)


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=5000, debug=True)
