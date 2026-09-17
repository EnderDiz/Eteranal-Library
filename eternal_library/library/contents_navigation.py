from __future__ import annotations

import math
from typing import NamedTuple


class PageInfo(NamedTuple):
    page: int
    pages: int
    per_page: int
    offset: int
    start_number: int
    end_number: int
    total: int


def page_info(*, total: int, requested_page: int, per_page: int = 100) -> PageInfo:
    total = max(0, int(total))
    per_page = max(1, min(200, int(per_page)))
    pages = max(1, math.ceil(total / per_page))
    page = min(max(1, int(requested_page or 1)), pages)
    offset = (page - 1) * per_page
    start = offset + 1 if total else 0
    end = min(total, offset + per_page)
    return PageInfo(page, pages, per_page, offset, start, end, total)


def preview_positions(total: int, *, head: int = 3, tail: int = 3) -> list[int]:
    total = max(0, int(total))
    if total <= head + tail:
        return list(range(1, total + 1))
    return list(range(1, head + 1)) + list(range(total - tail + 1, total + 1))
