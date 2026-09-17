from __future__ import annotations

from flask import abort, g, jsonify, request, url_for

from .content_repository import (
    SIDEBAR_SECTIONS,
    TIER_VALUES,
    can_manage_game,
    get_character_fields,
    get_game,
    get_game_sidebar_sections,
    get_public_character_values,
    get_tier_categories,
    list_public_characters,
)

AVATAR_BACKGROUND_VALUES = ("assr", "ssr", "sr", "r", "n")
RARITY_FIELD_NAMES = {"rarity", "редкость"}


def game_image_url(game) -> str | None:
    if game and game["image_filename"]:
        return url_for("core.media_file", filename=f"tierlists/games/{game['image_filename']}")
    return None


def character_image_url(character) -> str | None:
    if character and character["image_filename"]:
        return url_for("core.media_file", filename=f"tierlists/characters/{character['image_filename']}")
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


def build_game_sidebar(game_id: int) -> list[dict[str, object]]:
    enabled = get_game_sidebar_sections(game_id)
    return [
        {"key": key, "label": label, "enabled": bool(enabled.get(key))}
        for key, label in SIDEBAR_SECTIONS
        if enabled.get(key)
    ]


def public_game_section_url(game, section_key: str) -> str:
    if section_key == "tier_list":
        return url_for("tierlists.public_game_tier_list", game_slug=game["slug"])
    if section_key == "characters":
        return url_for("tierlists.public_game_characters", game_slug=game["slug"])
    return url_for("tierlists.home")


def public_game_landing_url(game) -> str:
    sections = get_game_sidebar_sections(game["id"])
    if sections.get("tier_list"):
        return url_for("tierlists.public_game_tier_list", game_slug=game["slug"])
    if sections.get("characters"):
        return url_for("tierlists.public_game_characters", game_slug=game["slug"])
    return url_for("tierlists.home")


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
