from __future__ import annotations

import os

BRAND = {
    "name": os.getenv("SITE_BRAND_NAME", "Eternal Library"),
    "logo_filename": os.getenv("SITE_BRAND_LOGO", "logo.webp"),
    "favicon_filename": os.getenv("SITE_BRAND_FAVICON", "favicon.webp"),
    "mark": os.getenv("SITE_BRAND_MARK", "EL"),
    "copyright": os.getenv(
        "SITE_BRAND_COPYRIGHT",
        "Copyright © 2026 EternalLibrary.gg",
    ),
    "tagline": os.getenv(
        "SITE_BRAND_TAGLINE",
        "Игры соединяют миры. Мы сохраняем их истории.",
    ),
}
