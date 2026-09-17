from __future__ import annotations

import html
import re

import mistune
from markdownify import markdownify as _html_to_markdown

_WORD_RE = re.compile(r"[\wА-Яа-яЁё]+(?:[-’'][\wА-Яа-яЁё]+)*", re.UNICODE)
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")

_MARKDOWN = mistune.create_markdown(
    escape=True,
    plugins=["strikethrough", "table", "footnotes", "task_lists"],
)
_AST_MARKDOWN = mistune.create_markdown(
    renderer="ast",
    plugins=["strikethrough", "table", "footnotes", "task_lists"],
)


def render_markdown(source: str | None) -> str:
    return _MARKDOWN(source or "").strip()


def html_to_markdown(source: str | None) -> str:
    if not source:
        return ""
    converted = _html_to_markdown(
        source,
        heading_style="ATX",
        bullets="-",
        strip=["script", "style"],
    )
    converted = re.sub(r"\n{3,}", "\n\n", converted)
    return converted.strip()


def _collect_ast_text(node, output: list[str]) -> None:
    if isinstance(node, list):
        for child in node:
            _collect_ast_text(child, output)
        return
    if not isinstance(node, dict):
        return

    node_type = node.get("type")
    if node_type in {"text", "codespan", "inline_html"}:
        raw = node.get("raw")
        if raw:
            output.append(str(raw))
    elif node_type == "block_code":
        raw = node.get("raw")
        if raw:
            output.append(str(raw).strip("\n"))

    children = node.get("children")
    if children:
        _collect_ast_text(children, output)

    if node_type in {
        "paragraph", "heading", "block_quote", "list_item", "block_code",
        "table_cell", "footnote_item",
    }:
        output.append("\n")


def markdown_plain_text(source: str | None) -> str:
    if not source:
        return ""
    ast = _AST_MARKDOWN(source)
    parts: list[str] = []
    _collect_ast_text(ast, parts)
    text = "".join(parts)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def markdown_word_count(source: str | None) -> int:
    return len(_WORD_RE.findall(markdown_plain_text(source)))


def markdown_char_count(source: str | None) -> int:
    return len(markdown_plain_text(source))


def markdown_outline(source: str | None) -> list[dict[str, int | str]]:
    outline: list[dict[str, int | str]] = []
    if not source:
        return outline
    fenced = False
    fence_marker = ""
    for line_number, line in enumerate(source.splitlines(), start=1):
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            marker = stripped[:3]
            if not fenced:
                fenced = True
                fence_marker = marker
            elif marker == fence_marker:
                fenced = False
                fence_marker = ""
            continue
        if fenced:
            continue
        match = _HEADING_RE.match(line)
        if not match:
            continue
        title = re.sub(r"\s+#+\s*$", "", match.group(2)).strip()
        if title:
            outline.append({"level": len(match.group(1)), "title": title, "line": line_number})
    return outline
