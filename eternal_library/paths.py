from __future__ import annotations

from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent
INSTANCE_DIR = PROJECT_ROOT / "instance"
DATABASE_PATH = INSTANCE_DIR / "eternal_library.db"
ADMIN_FILE = INSTANCE_DIR / "test_admin.txt"
SCHEMA_FILE = PACKAGE_ROOT / "schema.sql"
MEDIA_ROOT = PROJECT_ROOT / "media"

AVATAR_DIR = MEDIA_ROOT / "avatars"
TIERLIST_MEDIA_DIR = MEDIA_ROOT / "tierlists"
GAME_IMAGE_DIR = TIERLIST_MEDIA_DIR / "games"
CHARACTER_IMAGE_DIR = TIERLIST_MEDIA_DIR / "characters"
AVATAR_BACKGROUND_DIR = TIERLIST_MEDIA_DIR / "avatar_bg"
LIBRARY_MEDIA_DIR = MEDIA_ROOT / "library"
LIBRARY_COVER_DIR = LIBRARY_MEDIA_DIR / "covers"
LIBRARY_BANNER_DIR = LIBRARY_MEDIA_DIR / "banners"


def ensure_runtime_directories() -> None:
    for directory in (
        INSTANCE_DIR,
        AVATAR_DIR,
        GAME_IMAGE_DIR,
        CHARACTER_IMAGE_DIR,
        AVATAR_BACKGROUND_DIR,
        LIBRARY_COVER_DIR,
        LIBRARY_BANNER_DIR,
    ):
        directory.mkdir(parents=True, exist_ok=True)
