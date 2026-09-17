from flask import g, render_template

from ...auth.decorators import management_required
from ..content_repository import list_manageable_games
from . import bp

@bp.get("/manage")
@bp.get("/manage/")
@management_required
def manage_dashboard():
    games = list_manageable_games(g.user)
    character_count = sum(game["character_count"] for game in games)
    published_count = sum(1 for game in games if game["publication_status"] == "published")
    upcoming_count = sum(1 for game in games if game["release_status"] == "upcoming")
    return render_template(
        "tierlists/manage/manage_dashboard.html",
        games=games,
        character_count=character_count,
        published_count=published_count,
        upcoming_count=upcoming_count,
    )

