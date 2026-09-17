from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "eternal_library" / "library" / "contents_navigation.py"


def load_module():
    spec = importlib.util.spec_from_file_location("contents_navigation", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_page_window_is_bounded_for_thousand_chapters():
    nav = load_module()
    page = nav.page_info(total=1247, requested_page=13, per_page=100)
    assert page.page == 13
    assert page.pages == 13
    assert page.offset == 1200
    assert page.start_number == 1201
    assert page.end_number == 1247


def test_page_window_clamps_out_of_range_requests():
    nav = load_module()
    assert nav.page_info(total=1247, requested_page=0, per_page=100).page == 1
    assert nav.page_info(total=1247, requested_page=999, per_page=100).page == 13
    assert nav.page_info(total=0, requested_page=5, per_page=100).page == 1


def test_preview_positions_shows_start_and_end_without_rendering_every_chapter():
    nav = load_module()
    assert nav.preview_positions(4) == [1, 2, 3, 4]
    assert nav.preview_positions(12) == [1, 2, 3, 10, 11, 12]
