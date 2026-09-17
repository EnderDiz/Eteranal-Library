from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "eternal_library" / "library" / "markdown_tools.py"


def load_module():
    spec = importlib.util.spec_from_file_location("markdown_tools", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_render_markdown_supports_writer_features_and_escapes_raw_html():
    tools = load_module()
    source = """# Заголовок

**жирный** *курсив* ~~зачёркнутый~~

- [x] готово
- пункт

| A | B |
|---|---|
| 1 | 2 |

Сноска[^1]

[^1]: Текст сноски

<script>alert('x')</script>
"""
    rendered = tools.render_markdown(source)

    assert "<h1>Заголовок</h1>" in rendered
    assert "<strong>жирный</strong>" in rendered
    assert "<em>курсив</em>" in rendered
    assert "<del>зачёркнутый</del>" in rendered
    assert 'type="checkbox"' in rendered
    assert "<table>" in rendered
    assert "footnote-ref" in rendered
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered


def test_html_to_markdown_preserves_legacy_formatting():
    tools = load_module()
    source = '<h2>Сцена</h2><p>Текст <strong>важный</strong> и <em>тихий</em>.</p><blockquote><p>Реплика</p></blockquote>'
    converted = tools.html_to_markdown(source)

    assert "Сцена" in converted
    assert "**важный**" in converted
    assert "*тихий*" in converted
    assert "> Реплика" in converted


def test_markdown_stats_ignore_markup_syntax():
    tools = load_module()
    source = "## Сцена\n\n**Туман** накрыл *город*.\n\n> Ещё одна строка."

    assert tools.markdown_word_count(source) == 7
    plain = tools.markdown_plain_text(source)
    assert "**" not in plain
    assert "##" not in plain
    assert "Туман" in plain
    assert tools.markdown_char_count(source) == len(plain)


def test_markdown_outline_returns_heading_levels_and_labels():
    tools = load_module()
    source = "# Книга\n\n## Первая сцена\n\n### Разговор\n\n## Финал"

    assert tools.markdown_outline(source) == [
        {"level": 1, "title": "Книга", "line": 1},
        {"level": 2, "title": "Первая сцена", "line": 3},
        {"level": 3, "title": "Разговор", "line": 5},
        {"level": 2, "title": "Финал", "line": 7},
    ]
