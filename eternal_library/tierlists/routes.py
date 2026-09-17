from __future__ import annotations

from flask import Blueprint, abort, render_template, request

from .content_repository import (
    TIER_VALUES,
    get_character_editor_data,
    get_character_fields,
    get_game_modules,
    get_game_sidebar_sections,
    get_public_character_by_slug,
    get_public_game_by_slug,
    get_tier_categories,
    list_public_games,
)
from .helpers import (
    apply_public_card_filters,
    build_game_sidebar,
    build_public_character_cards,
)

bp = Blueprint("tierlists", __name__)


@bp.get("/tierlists/")
def home():
    games = list_public_games()
    released_games = [game for game in games if game["release_status"] == "released"]
    upcoming_games = [game for game in games if game["release_status"] == "upcoming"]
    return render_template(
        "tierlists/tier_list_main.html",
        games=games,
        released_games=released_games,
        upcoming_games=upcoming_games,
        featured_games=released_games[:5],
        new_games=released_games[:5],
    )


@bp.get("/games/<game_slug>/tier-list")
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
        "tierlists/tier_list_page.html",
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


@bp.get("/games/<game_slug>/characters")
def public_game_characters(game_slug: str):
    game = get_public_game_by_slug(game_slug)
    if game is None:
        abort(404)
    if not get_game_sidebar_sections(game["id"]).get("characters"):
        abort(404)

    cards, fields, categories = build_public_character_cards(game["id"])
    filtered = apply_public_card_filters(cards, fields)

    return render_template(
        "tierlists/character_list_page.html",
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


@bp.get("/games/<game_slug>/characters/<character_slug>")
def public_character(game_slug: str, character_slug: str):
    game = get_public_game_by_slug(game_slug)
    if game is None:
        abort(404)
    character = get_public_character_by_slug(game["id"], character_slug)
    if character is None:
        abort(404)
    editor_data = get_character_editor_data(character["id"])
    return render_template(
        "tierlists/character_info_page.html",
        game=game,
        character=character,
        sidebar_sections=build_game_sidebar(game["id"]),
        modules=get_game_modules(game["id"]),
        fields=get_character_fields(game["id"]),
        categories=get_tier_categories(game["id"]),
        editor_data=editor_data,
    )


