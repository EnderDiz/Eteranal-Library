from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WRITER_HTML = ROOT / 'eternal_library/templates/library/writer.html'
WRITER_JS = ROOT / 'eternal_library/static/js/library/writer.js'
WRITER_CSS = ROOT / 'eternal_library/static/css/library/writer.css'
READER_CSS = ROOT / 'eternal_library/static/css/library/reader.css'


def test_writer_exposes_line_number_toggle():
    html = WRITER_HTML.read_text(encoding='utf-8')
    js = WRITER_JS.read_text(encoding='utf-8')
    assert 'data-toggle-line-numbers' in html
    assert "el:writer:lineNumbers" in js
    assert "setOption('lineNumbers'" in js or 'setOption("lineNumbers"' in js


def test_reader_has_no_bottom_fade_overlay_over_text():
    css = READER_CSS.read_text(encoding='utf-8')
    assert '.reader-content::after' not in css


def test_focus_mode_uses_readable_editor_text_and_split_specific_padding():
    css = WRITER_CSS.read_text(encoding='utf-8')
    assert 'body.writer-focus .CodeMirror' in css
    assert 'font-size: 18px' in css
    assert 'body.writer-focus .writer-workspace.is-mode-split .CodeMirror-lines' in css
    assert 'calc((100vw - 920px) / 2)' not in css.split('body.writer-focus .writer-workspace.is-mode-split .CodeMirror-lines', 1)[1].split('}', 1)[0]
