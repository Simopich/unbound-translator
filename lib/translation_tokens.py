"""Helpers for Pokemon Unbound translation text and protected tokens."""

from __future__ import annotations

from collections import Counter
import re
from lib.pcs_text import CC_TOKEN_PATTERN


TOKEN_RE = re.compile(
    CC_TOKEN_PATTERN
    + r"|\\btn[0-9A-Fa-f]{2}"
    r"|\\![0-9A-Fa-f]{2}"
    r"|\\\\[0-9A-Fa-f]{2}"
    r"|\\\?[0-9A-Fa-f]{2}"
    r"|\\9[0-9A-Fa-f]{2}"
    r"|\\F[0-9A-Fa-f]"
    r"|\\(?:pk|mn|Po|Ke|Bl|Lo|Ck|Lv|qo|qc|sm|sf|au|ad|al|ar|pn|n|l|p|e|d|\.|<|>|\+|r)"
    r"|\[[A-Za-z0-9_]+\]"
    r"|\{[0-9A-Fa-f]{2}\}"
)

LAYOUT_TOKENS = {"\\n", "\\l", "\\p", "\\pn"}


def strip_hma_quotes(text: str | None) -> str:
    if isinstance(text, str) and len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        return text[1:-1]
    return text or ""


def token_spans(text: str, predicate=None) -> list[tuple[int, int, str]]:
    spans = []
    for match in TOKEN_RE.finditer(text):
        token = match.group(0)
        if predicate is None or predicate(token):
            spans.append((match.start(), match.end(), token))
    return spans


def semantic_tokens(text: str) -> list[str]:
    return [
        token
        for _start, _end, token in token_spans(text)
        if token not in LAYOUT_TOKENS
    ]


def semantic_token_counts(text: str) -> Counter[str]:
    return Counter(semantic_tokens(text))


def _newline_layout_tokens(count: int) -> list[str]:
    tokens = ["\\p"] * (count // 2)
    if count % 2:
        tokens.append("\\n")
    return tokens


def layout_tokens(text: str) -> list[str]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    result = []
    index = 0
    while index < len(text):
        if text[index] == "\r":
            if index + 1 < len(text) and text[index + 1] == "\n":
                index += 2
            else:
                index += 1
            result.append("\\n")
            continue
        if text[index] == "\n":
            end = index
            while end < len(text) and text[end] == "\n":
                end += 1
            result.extend(_newline_layout_tokens(end - index))
            index = end
            continue

        match = TOKEN_RE.match(text, index)
        if match:
            token = match.group(0)
            if token in LAYOUT_TOKENS:
                result.append(token)
            index = match.end()
            continue

        index += 1
    return result


def layout_token_counts(text: str) -> Counter[str]:
    return Counter(layout_tokens(text))


def collapse_layout_spacing(text: str) -> str:
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r"([(\[{]) +", r"\1", text)
    return text.strip()


def remove_layout_tokens(text: str) -> tuple[str, list[str]]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    layout = []
    pieces = []
    index = 0

    while index < len(text):
        if text[index] == "\r":
            if index + 1 < len(text) and text[index + 1] == "\n":
                index += 2
            else:
                index += 1
            layout.append("\\n")
            pieces.append(" ")
            continue
        if text[index] == "\n":
            end = index
            while end < len(text) and text[end] == "\n":
                end += 1
            layout.extend(_newline_layout_tokens(end - index))
            pieces.append(" ")
            index = end
            continue

        match = TOKEN_RE.match(text, index)
        if match:
            token = match.group(0)
            if token in LAYOUT_TOKENS:
                layout.append(token)
                pieces.append(" ")
            else:
                pieces.append(token)
            index = match.end()
            continue

        pieces.append(text[index])
        index += 1

    return collapse_layout_spacing("".join(pieces)), layout


def token_visible_width(token: str) -> int:
    if token in LAYOUT_TOKENS:
        return 0
    if token.startswith("[") and token.endswith("]"):
        if token in {
            "[white]",
            "[white2]",
            "[black]",
            "[grey]",
            "[gray]",
            "[red]",
            "[orange]",
            "[green]",
            "[lightgreen]",
            "[blue]",
            "[lightblue]",
            "[white3]",
            "[lightblue2]",
            "[cyan]",
            "[lightblue3]",
            "[navyblue]",
            "[darknavyblue]",
            "[resetfont]",
            "[pause]",
            "[wait_sound]",
            "[escape]",
            "[shift_right]",
            "[shift_down]",
            "[fill_window]",
            "[skip]",
            "[japanese]",
            "[latin]",
            "[pause_music]",
            "[resume_music]",
        }:
            return 0
        return 8
    if token.startswith("\\CC") or token.startswith("\\!") or token.startswith("\\?"):
        return 0
    if token.startswith("\\9") or token.startswith("\\btn"):
        return 1
    if token in {"\\.", "\\e", "\\d", "\\r"}:
        return 0
    if token in {"\\qo", "\\qc"}:
        return 1
    if token.startswith("{") and token.endswith("}"):
        return 1
    return 1


def visible_width(text: str) -> int:
    width = 0
    index = 0
    while index < len(text):
        match = TOKEN_RE.match(text, index)
        if match:
            width += token_visible_width(match.group(0))
            index = match.end()
            continue
        if text[index] not in "\r\n":
            width += 1
        index += 1
    return width
