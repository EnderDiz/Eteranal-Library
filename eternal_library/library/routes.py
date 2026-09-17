from __future__ import annotations

from datetime import datetime

from flask import Blueprint, abort, redirect, render_template, request, url_for

from .contents_navigation import page_info
from .repository import (
    book_stats,
    chapter_neighbors,
    chapter_stats,
    first_public_chapter,
    get_public_book_by_slug,
    get_public_chapter,
    list_activity,
    list_public_books,
    list_public_chapter_page,
    list_public_chapter_preview,
    count_public_chapters,
    get_public_chapter_by_number,
    public_chapter_window,
    chapter_markdown,
    tags_from_json,
)

from .markdown_tools import render_markdown

bp = Blueprint("library", __name__, url_prefix="/library")


@bp.get("/")
def home():
    query = request.args.get("q", "").strip()
    books = list_public_books(query)
    return render_template("library/index.html", books=books, query=query)


def _format_book_date(value: str | None) -> str:
    if not value:
        return "—"
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)[:10]
    months = (
        "янв.", "февр.", "мар.", "апр.", "мая", "июня",
        "июля", "авг.", "сент.", "окт.", "нояб.", "дек.",
    )
    return f"{parsed.day} {months[parsed.month - 1]} {parsed.year}"


@bp.get("/books/<slug>")
def book(slug: str):
    book_item = get_public_book_by_slug(slug)
    if book_item is None:
        abort(404)

    chapters = list_public_chapter_preview(book_item["id"])
    stats = book_stats(book_item["id"], published_only=True)
    activity = list_activity(book_item["id"], 4)
    first_chapter = chapters[0] if chapters else None
    return render_template(
        "library/book.html",
        book=book_item,
        tags=tags_from_json(book_item["tags_json"]),
        chapters=chapters,
        stats=stats,
        activity=activity,
        first_chapter=first_chapter,
        created_at_label=_format_book_date(book_item["created_at"]),
        published_at_label=_format_book_date(book_item["published_at"] or book_item["created_at"]),
        updated_at_label=_format_book_date(book_item["updated_at"]),
        format_library_date=_format_book_date,
    )


@bp.get("/books/<book_slug>/contents")
def contents(book_slug: str):
    book_item = get_public_book_by_slug(book_slug)
    if book_item is None:
        abort(404)

    query = request.args.get("q", "").strip()
    try:
        requested_page = int(request.args.get("page", "1") or 1)
    except ValueError:
        requested_page = 1

    jump_raw = request.args.get("jump", "").strip()
    jump_error = None
    if jump_raw:
        try:
            jump_number = int(jump_raw)
        except ValueError:
            jump_number = 0
        target = get_public_chapter_by_number(book_item["id"], jump_number) if jump_number > 0 else None
        if target is not None:
            return redirect(url_for("library.reader", book_slug=book_slug, chapter_slug=target["slug"]))
        jump_error = "Главы с таким номером нет."

    matched_total = count_public_chapters(book_item["id"], query)
    pagination = page_info(total=matched_total, requested_page=requested_page, per_page=100)
    chapters = list_public_chapter_page(
        book_item["id"], query=query, limit=pagination.per_page, offset=pagination.offset
    )
    total_chapters = count_public_chapters(book_item["id"])
    first_chapter = get_public_chapter_by_number(book_item["id"], 1) if total_chapters else None
    last_chapter = get_public_chapter_by_number(book_item["id"], total_chapters) if total_chapters else None

    return render_template(
        "library/contents.html",
        book=book_item,
        chapters=chapters,
        query=query,
        pagination=pagination,
        total_chapters=total_chapters,
        first_chapter=first_chapter,
        last_chapter=last_chapter,
        jump_error=jump_error,
    )


@bp.get("/books/<book_slug>/read")
def read_book(book_slug: str):
    book_item = get_public_book_by_slug(book_slug)
    if book_item is None:
        abort(404)
    chapter = first_public_chapter(book_item["id"])
    if chapter is None:
        return redirect(url_for("library.book", slug=book_slug))
    return redirect(url_for("library.reader", book_slug=book_slug, chapter_slug=chapter["slug"]))


@bp.get("/books/<book_slug>/read/<chapter_slug>")
def reader(book_slug: str, chapter_slug: str):
    book_item = get_public_book_by_slug(book_slug)
    if book_item is None:
        abort(404)
    chapter = get_public_chapter(book_item["id"], chapter_slug)
    if chapter is None:
        abort(404)
    chapters = public_chapter_window(book_item["id"], chapter["id"], radius=3)
    previous, following, chapter_number, chapter_total = chapter_neighbors(book_item["id"], chapter["id"])
    stats = chapter_stats(chapter)
    return render_template(
        "library/reader.html",
        book=book_item,
        book_tags=tags_from_json(book_item["tags_json"]),
        chapter=chapter,
        chapter_tags=tags_from_json(chapter["tags_json"]),
        chapters=chapters,
        previous_chapter=previous,
        next_chapter=following,
        chapter_number=chapter_number,
        chapter_total=chapter_total,
        stats=stats,
        chapter_content=render_markdown(chapter_markdown(chapter)),
    )
