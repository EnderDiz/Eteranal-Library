from __future__ import annotations

import re
from collections.abc import Mapping

VALID_CHAPTER_STATUSES = {"draft", "published", "archived"}


def _normalize_tags(raw: str | None, *, limit: int = 12) -> list[str]:
    values = re.split(r"[,\n;]+", raw or "")
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        tag = value.strip().lstrip("#").strip()[:40]
        if not tag:
            continue
        key = tag.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(tag)
        if len(result) >= limit:
            break
    return result


def parse_chapter_update(form: Mapping[str, object], current: Mapping[str, object]) -> dict[str, object]:
    title = str(form.get("title", "") or "").strip()
    if not title:
        raise ValueError("У главы должно быть название.")

    summary = str(form.get("summary", "") or "").strip() or None
    content_markdown = str(form.get("content_markdown", "") or "").rstrip()
    notes = str(form.get("notes", "") or "").strip() or None
    tags = _normalize_tags(str(form.get("tags", "") or ""))

    status = str(form.get("publication_status", "draft") or "draft")
    if status not in VALID_CHAPTER_STATUSES:
        status = "draft"

    if hasattr(current, "get"):
        fallback_raw = current.get("sort_order", 0)
    elif hasattr(current, "keys") and "sort_order" in current.keys():
        fallback_raw = current["sort_order"]
    else:
        fallback_raw = 0
    fallback_order = int(fallback_raw or 0)
    try:
        sort_order = max(0, int(str(form.get("sort_order", fallback_order) or fallback_order)))
    except (TypeError, ValueError):
        sort_order = fallback_order

    return {
        "title": title,
        "summary": summary,
        "content_markdown": content_markdown,
        "notes": notes,
        "tags": tags,
        "publication_status": status,
        "sort_order": sort_order,
    }
