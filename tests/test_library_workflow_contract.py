from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_public_book_contents_button_uses_real_contents_route():
    template = read("eternal_library/templates/library/book.html")
    assert "url_for('library.contents'" in template
    assert 'href="#contents">☷ Оглавление' not in template


def test_writer_has_no_manual_save_submit_button():
    template = read("eternal_library/templates/library/writer.html")
    assert 'type="submit">Сохранить' not in template
    assert "data-save-state" in template


def test_writer_autosaves_all_chapter_fields():
    script = read("eternal_library/static/js/library/writer.js")
    for field in ("title", "summary", "tags", "notes", "publication_status", "sort_order"):
        assert f"'{field}'" in script
    assert "content_markdown" in script
    assert "navigator.sendBeacon" in script


def test_new_chapter_is_created_by_post_before_editor_opens():
    routes = read("eternal_library/library/manage/routes.py")
    assert '@bp.post("/books/<int:book_id>/chapters/new")' in routes
    writer = read("eternal_library/templates/library/writer.html")
    assert 'id="new-chapter-form" method="post"' in writer
