from __future__ import annotations

from .helpers import (
    character_image_url,
    game_image_url,
    public_game_landing_url,
    public_game_section_url,
)


def register_tierlist_template_helpers(app) -> None:
    app.jinja_env.globals.update(
        game_image_url=game_image_url,
        character_image_url=character_image_url,
        public_game_section_url=public_game_section_url,
        public_game_landing_url=public_game_landing_url,
    )
