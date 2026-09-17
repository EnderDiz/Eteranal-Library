from __future__ import annotations

import sqlite3

from flask import abort, flash, g, jsonify, redirect, render_template, request, url_for

from ...auth.decorators import management_required
from ...core.media import save_content_image
from ...database import connect_db
from ...paths import LIBRARY_BANNER_DIR, LIBRARY_COVER_DIR
from ..chapter_forms import parse_chapter_update
from ..contents_navigation import page_info
from ..repository import (
    MAX_BOOKS,
    book_stats,
    chapter_stats,
    count_books,
    count_manage_chapters,
    get_book,
    get_chapter,
    list_manage_books,
    list_manage_chapter_page,
    manage_chapter_window,
    normalize_tags,
    record_activity,
    chapter_markdown,
    tags_from_json,
    tags_to_json,
    unique_book_slug,
    unique_chapter_slug,
)
from ..markdown_tools import markdown_char_count, markdown_word_count, render_markdown
from . import bp

VALID_STATUSES = {"draft", "published", "archived"}


def _status_from_form() -> str:
    status = request.form.get("publication_status", "draft")
    return status if status in VALID_STATUSES else "draft"


def _delete_media(directory, filename: str | None) -> None:
    if filename:
        (directory / filename).unlink(missing_ok=True)


@bp.get("/")
@management_required
def dashboard():
    books = list_manage_books()
    published_count = sum(1 for book in books if book["publication_status"] == "published")
    draft_count = sum(1 for book in books if book["publication_status"] == "draft")
    return render_template(
        "library/manage/dashboard.html",
        books=books,
        published_count=published_count,
        draft_count=draft_count,
        max_books=MAX_BOOKS,
    )


@bp.route("/books/new", methods=["GET", "POST"])
@management_required
def book_new():
    if count_books() >= MAX_BOOKS:
        flash(f"В библиотеке может быть не больше {MAX_BOOKS} книг.", "error")
        return redirect(url_for("library_manage.dashboard"))

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        summary = request.form.get("summary", "").strip() or None
        description = request.form.get("description", "").strip() or None
        tags = normalize_tags(request.form.get("tags", ""))
        status = _status_from_form()
        if not title:
            flash("У книги должно быть название.", "error")
        else:
            cover_filename = None
            banner_filename = None
            try:
                cover_filename = save_content_image(request.files.get("cover"), LIBRARY_COVER_DIR, "book")
                banner_filename = save_content_image(request.files.get("banner"), LIBRARY_BANNER_DIR, "book_banner")
                slug = unique_book_slug(title)
                with connect_db() as db:
                    cursor = db.execute(
                        """
                        INSERT INTO books
                            (slug, title, summary, description, tags_json, cover_filename,
                             banner_filename, publication_status, published_at, created_by)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?,
                                CASE WHEN ? = 'published' THEN CURRENT_TIMESTAMP ELSE NULL END, ?)
                        """,
                        (
                            slug, title, summary, description, tags_to_json(tags), cover_filename,
                            banner_filename, status, status, g.user["id"],
                        ),
                    )
                    book_id = int(cursor.lastrowid)
                    record_activity(
                        db,
                        book_id=book_id,
                        event_type="book_created",
                        title="Книга создана",
                        detail="Создана карточка книги в личной библиотеке.",
                    )
                    if status == "published":
                        record_activity(
                            db,
                            book_id=book_id,
                            event_type="book_published",
                            title="Книга опубликована",
                            detail="Книга стала доступна для чтения.",
                        )
                    db.commit()
                flash("Книга создана. Теперь можно добавлять главы.", "success")
                return redirect(url_for("library_manage.book_edit", book_id=book_id))
            except ValueError as exc:
                _delete_media(LIBRARY_COVER_DIR, cover_filename)
                _delete_media(LIBRARY_BANNER_DIR, banner_filename)
                flash(str(exc), "error")
            except sqlite3.IntegrityError:
                _delete_media(LIBRARY_COVER_DIR, cover_filename)
                _delete_media(LIBRARY_BANNER_DIR, banner_filename)
                flash("Не удалось создать книгу: проверьте введённые данные.", "error")

    return render_template(
        "library/manage/book_editor.html",
        book=None,
        chapters=[],
        stats=None,
        tags=normalize_tags(request.form.get("tags", "")) if request.method == "POST" else [],
    )


@bp.route("/books/<int:book_id>/edit", methods=["GET", "POST"])
@management_required
def book_edit(book_id: int):
    book = get_book(book_id)
    if book is None:
        abort(404)

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        summary = request.form.get("summary", "").strip() or None
        description = request.form.get("description", "").strip() or None
        tags = normalize_tags(request.form.get("tags", ""))
        status = _status_from_form()

        if not title:
            flash("У книги должно быть название.", "error")
        else:
            new_cover = new_banner = None
            try:
                new_cover = save_content_image(request.files.get("cover"), LIBRARY_COVER_DIR, "book")
                new_banner = save_content_image(request.files.get("banner"), LIBRARY_BANNER_DIR, "book_banner")
                cover_filename = book["cover_filename"]
                banner_filename = book["banner_filename"]
                old_cover = old_banner = None

                if new_cover:
                    old_cover, cover_filename = cover_filename, new_cover
                elif request.form.get("remove_cover") == "1":
                    old_cover, cover_filename = cover_filename, None

                if new_banner:
                    old_banner, banner_filename = banner_filename, new_banner
                elif request.form.get("remove_banner") == "1":
                    old_banner, banner_filename = banner_filename, None

                slug = unique_book_slug(title, exclude_id=book_id)
                status_changed = status != book["publication_status"]
                with connect_db() as db:
                    db.execute(
                        """
                        UPDATE books
                        SET slug = ?, title = ?, summary = ?, description = ?, tags_json = ?,
                            cover_filename = ?, banner_filename = ?, publication_status = ?,
                            published_at = CASE
                                WHEN ? = 'published' AND published_at IS NULL THEN CURRENT_TIMESTAMP
                                ELSE published_at
                            END,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """,
                        (
                            slug, title, summary, description, tags_to_json(tags), cover_filename,
                            banner_filename, status, status, book_id,
                        ),
                    )
                    if status_changed and status == "published":
                        record_activity(
                            db,
                            book_id=book_id,
                            event_type="book_published",
                            title="Книга опубликована",
                            detail="Актуальная версия книги доступна на сайте.",
                        )
                    else:
                        record_activity(
                            db,
                            book_id=book_id,
                            event_type="book_updated",
                            title="Карточка книги обновлена",
                            detail="Изменены описание, оформление или метаданные книги.",
                        )
                    db.commit()

                if old_cover and old_cover != cover_filename:
                    _delete_media(LIBRARY_COVER_DIR, old_cover)
                if old_banner and old_banner != banner_filename:
                    _delete_media(LIBRARY_BANNER_DIR, old_banner)
                flash("Книга сохранена.", "success")
                return redirect(url_for("library_manage.book_edit", book_id=book_id))
            except ValueError as exc:
                _delete_media(LIBRARY_COVER_DIR, new_cover)
                _delete_media(LIBRARY_BANNER_DIR, new_banner)
                flash(str(exc), "error")
            except sqlite3.IntegrityError:
                _delete_media(LIBRARY_COVER_DIR, new_cover)
                _delete_media(LIBRARY_BANNER_DIR, new_banner)
                flash("Не удалось сохранить книгу: проверьте введённые данные.", "error")
        book = get_book(book_id)

    chapter_query = request.args.get("chapter_q", "").strip()
    chapter_status = request.args.get("chapter_status", "").strip()
    if chapter_status not in VALID_STATUSES:
        chapter_status = ""
    try:
        chapter_page = int(request.args.get("chapter_page", "1") or 1)
    except ValueError:
        chapter_page = 1
    chapter_total = count_manage_chapters(book_id, query=chapter_query, status=chapter_status)
    chapter_pagination = page_info(total=chapter_total, requested_page=chapter_page, per_page=100)
    chapters = list_manage_chapter_page(
        book_id, query=chapter_query, status=chapter_status,
        limit=chapter_pagination.per_page, offset=chapter_pagination.offset,
    )
    stats = book_stats(book_id)
    return render_template(
        "library/manage/book_editor.html",
        book=book,
        chapters=chapters,
        stats=stats,
        tags=tags_from_json(book["tags_json"]),
        chapter_query=chapter_query,
        chapter_status=chapter_status,
        chapter_pagination=chapter_pagination,
    )


@bp.post("/books/<int:book_id>/delete")
@management_required
def book_delete(book_id: int):
    book = get_book(book_id)
    if book is None:
        abort(404)
    with connect_db() as db:
        db.execute("DELETE FROM books WHERE id = ?", (book_id,))
        db.commit()
    _delete_media(LIBRARY_COVER_DIR, book["cover_filename"])
    _delete_media(LIBRARY_BANNER_DIR, book["banner_filename"])
    flash("Книга удалена.", "success")
    return redirect(url_for("library_manage.dashboard"))


@bp.post("/books/<int:book_id>/chapters/new")
@management_required
def chapter_new(book_id: int):
    book = get_book(book_id)
    if book is None:
        abort(404)

    with connect_db() as db:
        row = db.execute(
            "SELECT COALESCE(MAX(sort_order), -1) + 1 AS next_order, COUNT(*) AS total FROM book_chapters WHERE book_id = ?",
            (book_id,),
        ).fetchone()
        sort_order = int(row["next_order"])
        ordinal = int(row["total"]) + 1

    title = "Новая глава" if ordinal == 1 else f"Новая глава {ordinal}"
    slug = unique_chapter_slug(book_id, title)
    with connect_db() as db:
        cursor = db.execute(
            """
            INSERT INTO book_chapters
                (book_id, slug, title, summary, content, content_markdown, tags_json, notes,
                 publication_status, sort_order)
            VALUES (?, ?, ?, NULL, '', '', '[]', NULL, 'draft', ?)
            """,
            (book_id, slug, title, sort_order),
        )
        chapter_id = int(cursor.lastrowid)
        record_activity(
            db, book_id=book_id, chapter_id=chapter_id, event_type="chapter_created",
            title="Добавлена глава", detail=title,
        )
        db.execute("UPDATE books SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (book_id,))
        db.commit()

    return redirect(url_for("library_manage.chapter_edit", book_id=book_id, chapter_id=chapter_id))


@bp.route("/books/<int:book_id>/chapters/<int:chapter_id>/edit", methods=["GET", "POST"])
@management_required
def chapter_edit(book_id: int, chapter_id: int):
    book = get_book(book_id)
    chapter = get_chapter(chapter_id)
    if book is None or chapter is None or chapter["book_id"] != book_id:
        abort(404)

    if request.method == "POST":
        try:
            payload = parse_chapter_update(request.form, chapter)
        except ValueError as exc:
            flash(str(exc), "error")
            return _render_chapter_editor(book, chapter)

        content = render_markdown(payload["content_markdown"])
        word_count = markdown_word_count(payload["content_markdown"])
        char_count = markdown_char_count(payload["content_markdown"])
        became_published = payload["publication_status"] == "published" and chapter["publication_status"] != "published"
        slug = chapter["slug"]
        if chapter["published_at"] is None:
            slug = unique_chapter_slug(book_id, payload["title"], exclude_id=chapter_id)
        with connect_db() as db:
            db.execute(
                """
                UPDATE book_chapters
                SET slug = ?, title = ?, summary = ?, content = ?, content_markdown = ?, word_count = ?, char_count = ?, tags_json = ?, notes = ?,
                    publication_status = ?, sort_order = ?,
                    published_at = CASE
                        WHEN ? = 'published' AND published_at IS NULL THEN CURRENT_TIMESTAMP
                        ELSE published_at
                    END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND book_id = ?
                """,
                (
                    slug, payload["title"], payload["summary"], content, payload["content_markdown"], word_count, char_count,
                    tags_to_json(payload["tags"]), payload["notes"], payload["publication_status"],
                    payload["sort_order"], payload["publication_status"], chapter_id, book_id,
                ),
            )
            if became_published:
                record_activity(
                    db, book_id=book_id, chapter_id=chapter_id, event_type="chapter_published",
                    title="Глава опубликована", detail=payload["title"],
                )
            db.execute("UPDATE books SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (book_id,))
            db.commit()
        return redirect(url_for("library_manage.chapter_edit", book_id=book_id, chapter_id=chapter_id))

    return _render_chapter_editor(book, chapter)


def _render_chapter_editor(book, chapter):
    if chapter is None:
        abort(404)
    chapters = manage_chapter_window(book["id"], chapter["id"], radius=5)
    chapter_total = count_manage_chapters(book["id"])
    current_row = next((item for item in chapters if item["id"] == chapter["id"]), None)
    chapter_number = int(current_row["chapter_number"]) if current_row else 0
    stats = chapter_stats(chapter)
    tags = tags_from_json(chapter["tags_json"])
    return render_template(
        "library/writer.html",
        book=book,
        chapter=chapter,
        chapters=chapters,
        chapter_number=chapter_number,
        chapter_total=chapter_total,
        stats=stats,
        chapter_tags=tags,
        chapter_markdown=chapter_markdown(chapter),
    )


@bp.post("/books/<int:book_id>/chapters/preview")
@management_required
def chapter_preview(book_id: int):
    if get_book(book_id) is None:
        abort(404)
    source = request.form.get("content_markdown", "")
    return jsonify({"html": render_markdown(source)})


@bp.post("/books/<int:book_id>/chapters/<int:chapter_id>/autosave")
@management_required
def chapter_autosave(book_id: int, chapter_id: int):
    book = get_book(book_id)
    chapter = get_chapter(chapter_id)
    if book is None or chapter is None or chapter["book_id"] != book_id:
        abort(404)

    try:
        payload = parse_chapter_update(request.form, chapter)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    content = render_markdown(payload["content_markdown"])
    word_count = markdown_word_count(payload["content_markdown"])
    char_count = markdown_char_count(payload["content_markdown"])
    became_published = payload["publication_status"] == "published" and chapter["publication_status"] != "published"
    slug = chapter["slug"]
    if chapter["published_at"] is None:
        slug = unique_chapter_slug(book_id, payload["title"], exclude_id=chapter_id)

    with connect_db() as db:
        db.execute(
            """
            UPDATE book_chapters
            SET slug = ?, title = ?, summary = ?, content = ?, content_markdown = ?, word_count = ?, char_count = ?,
                tags_json = ?, notes = ?, publication_status = ?, sort_order = ?,
                published_at = CASE
                    WHEN ? = 'published' AND published_at IS NULL THEN CURRENT_TIMESTAMP
                    ELSE published_at
                END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND book_id = ?
            """,
            (
                slug, payload["title"], payload["summary"], content, payload["content_markdown"], word_count, char_count,
                tags_to_json(payload["tags"]), payload["notes"], payload["publication_status"],
                payload["sort_order"], payload["publication_status"], chapter_id, book_id,
            ),
        )
        if became_published:
            record_activity(
                db, book_id=book_id, chapter_id=chapter_id, event_type="chapter_published",
                title="Глава опубликована", detail=payload["title"],
            )
        db.execute("UPDATE books SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (book_id,))
        saved_at = db.execute(
            "SELECT updated_at, slug FROM book_chapters WHERE id = ?", (chapter_id,)
        ).fetchone()
        db.commit()

    return jsonify({"ok": True, "saved_at": saved_at["updated_at"], "slug": saved_at["slug"]})


@bp.post("/books/<int:book_id>/chapters/<int:chapter_id>/delete")
@management_required
def chapter_delete(book_id: int, chapter_id: int):
    book = get_book(book_id)
    chapter = get_chapter(chapter_id)
    if book is None or chapter is None or chapter["book_id"] != book_id:
        abort(404)
    with connect_db() as db:
        db.execute("DELETE FROM book_chapters WHERE id = ? AND book_id = ?", (chapter_id, book_id))
        record_activity(
            db,
            book_id=book_id,
            event_type="chapter_deleted",
            title="Глава удалена",
            detail=chapter["title"],
        )
        db.execute("UPDATE books SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (book_id,))
        db.commit()
    flash("Глава удалена.", "success")
    return redirect(url_for("library_manage.book_edit", book_id=book_id))
