from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "eternal_library" / "library" / "chapter_forms.py"


def load_module():
    spec = importlib.util.spec_from_file_location("chapter_forms", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_parse_chapter_update_includes_every_autosaved_field():
    forms = load_module()
    current = {"sort_order": 7}
    payload = forms.parse_chapter_update(
        {
            "title": "  Новое название  ",
            "summary": "  Кратко  ",
            "content_markdown": "Текст\n",
            "notes": "  заметка  ",
            "tags": "туман, город, туман",
            "publication_status": "published",
            "sort_order": "12",
        },
        current,
    )

    assert payload == {
        "title": "Новое название",
        "summary": "Кратко",
        "content_markdown": "Текст",
        "notes": "заметка",
        "tags": ["туман", "город"],
        "publication_status": "published",
        "sort_order": 12,
    }


def test_parse_chapter_update_rejects_empty_title_and_invalid_status():
    forms = load_module()
    try:
        forms.parse_chapter_update(
            {"title": "   ", "publication_status": "hacked", "sort_order": "nope"},
            {"sort_order": 3},
        )
    except ValueError as exc:
        assert "название" in str(exc).lower()
    else:
        raise AssertionError("empty title must fail")


def test_parse_chapter_update_falls_back_to_draft_and_existing_order():
    forms = load_module()
    payload = forms.parse_chapter_update(
        {"title": "Глава", "publication_status": "hacked", "sort_order": "nope"},
        {"sort_order": 3},
    )
    assert payload["publication_status"] == "draft"
    assert payload["sort_order"] == 3


def test_parse_chapter_update_accepts_sqlite_row_like_current():
    class RowLike:
        def keys(self):
            return ["sort_order"]
        def __getitem__(self, key):
            if key == "sort_order":
                return 9
            raise KeyError(key)

    forms = load_module()
    payload = forms.parse_chapter_update({"title": "Глава", "sort_order": "bad"}, RowLike())
    assert payload["sort_order"] == 9
