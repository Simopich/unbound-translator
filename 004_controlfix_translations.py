#!/usr/bin/env python3

import argparse
import json
import re
from pathlib import Path

from lib.pcs_text import Charmap
from lib.translation_tokens import remove_layout_tokens, visible_width


CC_TOKEN_PATTERN = r"\\CC(?:04[0-9A-Fa-f]{6}|(?:10|0B)[0-9A-Fa-f]{4}|[0-9A-Fa-f]{4})"

TOKEN_RE = re.compile(
    CC_TOKEN_PATTERN
    + r"|\\btn[0-9A-Fa-f]{2}"
    r"|\\![0-9A-Fa-f\s]+"
    r"|\\\\[0-9A-Fa-f]{2}"
    r"|\\\?[0-9A-Fa-f]{2}"
    r"|\\9[0-9A-Fa-f]{2}"
    r"|\\F[0-9A-Fa-f]"
    r"|\\(?:pk|mn|Po|Ke|Bl|Lo|Ck|Lv|qo|qc|sm|sf|au|ad|al|ar|pn|n|l|p|e|d|\.|<|>|\+|r)"
    r"|\[[A-Za-z0-9_]+\]"
)

LAYOUT_TOKENS = {"\\n", "\\p", "\\l", "\\pn"}
QUOTE_TOKENS = {"\\qo", "\\qc"}
COLOR_TOKENS = {
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
}

DEFAULT_WRAP_CATEGORIES = (
    "scripts,plain_scripts,move_descriptions,ability_descriptions,item_descriptions,"
    "mission_descriptions,mission_objectives,menu_pokemon_summary,battle_messages,trade_messages"
)
DESCRIPTION_CATEGORIES = {
    "move_descriptions",
    "ability_descriptions",
    "item_descriptions",
    "mission_descriptions",
    "mission_objectives",
}
PLAIN_LINE_WRAP_CATEGORIES = DESCRIPTION_CATEGORIES | {
    "battle_messages",
    "menu_pokemon_summary",
}
MENU_LINE_BREAK_CATEGORIES = {
    "menu_common",
    "menu_battle",
    "menu_cube",
    "menu_cube_system",
    "menu_game_settings",
    "menu_item_storage",
    "menu_link_controls",
    "menu_list_labels",
    "menu_mining",
    "menu_multiplayer",
    "menu_options",
    "menu_pause",
    "menu_pc",
    "menu_pcoptions",
    "menu_pokemon",
    "menu_pokemon_options",
    "menu_save",
    "menu_saving_messages",
    "menu_standalone_labels",
    "menu_trainer_card",
}


def iter_entries(data):
    for table in data.get("tables", []):
        for entry in table.get("entries", []):
            yield entry
    for entry in data.get("free_texts", []):
        yield entry
    for entry in data.get("entries", []):
        yield entry


def strip_hma_quotes(text):
    if isinstance(text, str) and len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        return text[1:-1]
    return text or ""


def source_originals(path):
    if not path:
        return {}
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {entry["id"]: entry.get("original", "") for entry in iter_entries(data)}


def token_spans(text, predicate=None):
    spans = []
    for match in TOKEN_RE.finditer(text):
        token = match.group(0)
        if predicate is None or predicate(token):
            spans.append((match.start(), match.end(), token))
    return spans


def critical_token(token):
    return token not in LAYOUT_TOKENS


def replace_token_family(text, original, predicate):
    original_tokens = [token for _start, _end, token in token_spans(original, predicate)]
    translated_spans = token_spans(text, predicate)
    if not original_tokens or len(original_tokens) != len(translated_spans):
        return text, False

    changed = False
    pieces = []
    last = 0
    for (start, end, current), wanted in zip(translated_spans, original_tokens):
        pieces.append(text[last:start])
        pieces.append(wanted)
        last = end
        changed = changed or current != wanted
    pieces.append(text[last:])
    return "".join(pieces), changed


def leading_critical_tokens(text):
    i = 0
    result = []
    while i < len(text):
        match = TOKEN_RE.match(text, i)
        if match and critical_token(match.group(0)):
            result.append(match.group(0))
            i = match.end()
            continue
        if match and match.group(0) in LAYOUT_TOKENS:
            i = match.end()
            continue
        if text[i].isspace():
            i += 1
            continue
        break
    return result


def remove_leading_color_tokens(text):
    changed = True
    while changed:
        changed = False
        stripped = text.lstrip()
        leading_spaces = text[: len(text) - len(stripped)]
        match = TOKEN_RE.match(stripped)
        if match and match.group(0) in COLOR_TOKENS:
            text = leading_spaces + stripped[match.end() :]
            changed = True
    return text


def ensure_original_prefix(text, original):
    prefix = leading_critical_tokens(original)
    if not prefix:
        return text, False

    prefix_text = "".join(prefix)
    if text.lstrip().startswith(prefix_text):
        return text, False

    # Fullscreen/system text often depends on a leading color token. Replace a
    # translated leading color with the original one instead of stacking colors.
    if prefix and prefix[0] in COLOR_TOKENS:
        text = remove_leading_color_tokens(text)

    return prefix_text + text.lstrip(), True


def normalize_braced_controls(text):
    # Keep raw byte placeholders such as {B4}. Remove braces only around actual
    # PCS/HMA control codes that LLMs often wrap in braces.
    text = re.sub(r"\{(\[[A-Za-z0-9_]+\])\}", r"\1", text)
    text = re.sub(
        r"\{(\\(?:CC[0-9A-Fa-f]+|btn[0-9A-Fa-f]{2}|\?[0-9A-Fa-f]{2}|9[0-9A-Fa-f]{2}|F[0-9A-Fa-f]|[pnlr.]|qo|qc))\}",
        r"\1",
        text,
    )
    return text


def normalize_outer_quotes(text):
    text = strip_hma_quotes(text)
    text = re.sub(r'^"\s*(?=(?:\[[A-Za-z0-9_]+\]|\\))', "", text)
    if text.endswith('"') and (
        len(text) == 1
        or text.endswith('."')
        or text.endswith('!"')
        or text.endswith('?"')
        or text.endswith("\\p\"")
        or text.endswith("\\n\"")
        or text.endswith("\\l\"")
    ):
        text = text[:-1]
    return text


def repair_split_controls(text):
    # LLMs sometimes turn quote/control markers into layout + marker, e.g.
    # \nqo, \pqc, \nCC0818. These are not line breaks; they are broken controls.
    text = re.sub(r"\\[np](qo|qc)", lambda m: "\\" + m.group(1), text)
    text = re.sub(r"\\[np](CC[0-9A-Fa-f]{2,})", lambda m: "\\" + m.group(1), text)
    text = re.sub(r"\\[np](btn[0-9A-Fa-f]{2})", lambda m: "\\" + m.group(1), text)
    text = re.sub(r"\\[np](\?[0-9A-Fa-f]{2})", lambda m: "\\" + m.group(1), text)
    text = re.sub(r"\\[np](![0-9A-Fa-f]{2})", lambda m: "\\" + m.group(1), text)
    text = re.sub(r"\\\\(qo|qc)", lambda m: "\\" + m.group(1), text)
    text = re.sub(r"\\\\(CC[0-9A-Fa-f]{2,})", lambda m: "\\" + m.group(1), text)
    text = re.sub(r"\\\\(btn[0-9A-Fa-f]{2})", lambda m: "\\" + m.group(1), text)
    return text


def repair_control_sequences(text, original):
    changed = False

    text, did_change = replace_token_family(text, original, lambda token: token in QUOTE_TOKENS)
    changed = changed or did_change

    text, did_change = replace_token_family(text, original, lambda token: token in COLOR_TOKENS)
    changed = changed or did_change

    original_critical = [token for _s, _e, token in token_spans(original, critical_token)]
    translated_critical = [token for _s, _e, token in token_spans(text, critical_token)]
    if len(original_critical) == len(translated_critical):
        text, did_change = replace_token_family(text, original, critical_token)
        changed = changed or did_change

    text, did_change = ensure_original_prefix(text, original)
    changed = changed or did_change

    return text, changed


def collapse_duplicate_state_controls(text):
    pieces = []
    last_index = 0
    previous_token = None
    changed = False

    for start, end, token in token_spans(text):
        between = text[last_index:start]
        if between:
            previous_token = None
        pieces.append(between)

        duplicate = token == previous_token and (
            token in COLOR_TOKENS or token.startswith("\\CC")
        )
        if duplicate:
            changed = True
        else:
            pieces.append(token)
            previous_token = token

        last_index = end

    pieces.append(text[last_index:])
    return "".join(pieces), changed


def raw_placeholder(cmap, ch):
    encoded = cmap.encode_char(ch)
    if encoded and len(encoded) == 1:
        return f"{{{encoded[0]:02X}}}"
    return ch


def escape_hex_text_after_cc(text, original, cmap):
    return text, False


def protect_raw_placeholders(text):
    placeholders = []

    def repl(match):
        key = f"\x00RAW{len(placeholders)}\x00"
        placeholders.append((key, match.group(0)))
        return key

    return re.sub(r"\{[0-9A-Fa-f]{2}\}", repl, text), placeholders


def restore_raw_placeholders(text, placeholders):
    for key, value in placeholders:
        text = text.replace(key, value)
    return text


def fix_apostrophes(text):
    protected, placeholders = protect_raw_placeholders(text)
    protected = protected.replace("’", "{B4}")
    protected = protected.replace("‘", "{B3}")
    protected = protected.replace("'", "{B4}")
    return restore_raw_placeholders(protected, placeholders)


def control_sequence(text):
    return [token for _s, _e, token in token_spans(text, critical_token)]


def normalize_actual_layout_breaks(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    def paragraph_repl(match):
        count = len(match.group(0))
        return "\\p" * (count // 2) + ("\\n" if count % 2 else "")

    text = re.sub(r"\n{2,}", paragraph_repl, text)
    return text.replace("\n", "\\n")


def restore_compact_menu_line_breaks(text, original, entry):
    if entry.get("category") not in MENU_LINE_BREAK_CATEGORIES:
        return text, False
    if "\n" in text or any(token in text for token in LAYOUT_TOKENS):
        return text, False

    original_text = strip_hma_quotes(original)
    if "\\n" in original_text:
        original_lines = original_text.split("\\n")
    elif "\n" in original_text:
        original_lines = original_text.split("\n")
    else:
        return text, False

    original_lines = [line.strip() for line in original_lines if line.strip()]
    if len(original_lines) < 2 or len(original_lines) > 4:
        return text, False
    if any(visible_width(remove_layout_tokens(line)[0]) > 16 for line in original_lines):
        return text, False

    translated_parts = text.split()
    if len(translated_parts) != len(original_lines):
        return text, False
    if any(visible_width(part) > 16 for part in translated_parts):
        return text, False

    fixed = "\n".join(translated_parts)
    return fixed, fixed != text


def technical_token_count(text):
    tokens = [
        token
        for _start, _end, token in token_spans(text)
        if token not in LAYOUT_TOKENS and token not in COLOR_TOKENS
    ]
    raw_like = [
        token
        for token in tokens
        if token.startswith("\\!")
        or token.startswith("\\?")
        or token.startswith("\\9")
        or token.startswith("\\CC")
    ]
    return len(tokens), len(raw_like)


def should_skip_wrap(text):
    token_count, raw_like_count = technical_token_count(text)
    return token_count > 32 or raw_like_count > 8


def wrap_width_for_entry(entry, args):
    if entry.get("category") == "item_descriptions":
        return args.item_description_wrap_width
    if entry.get("category") in DESCRIPTION_CATEGORIES:
        return args.description_wrap_width
    return args.wrap_width


def wrap_words(text, width):
    words = text.split()
    lines = []
    current = []
    current_width = 0
    long_words = 0

    for word in words:
        word_width = visible_width(word)
        if word_width > width:
            long_words += 1

        added_width = word_width if not current else current_width + 1 + word_width
        if current and added_width > width:
            lines.append(" ".join(current))
            current = [word]
            current_width = word_width
        else:
            current.append(word)
            current_width = added_width

    if current:
        lines.append(" ".join(current))
    return lines, long_words


def pack_words_into_max_lines(text, max_lines):
    words = text.split()
    if not words or max_lines <= 0:
        return []
    if len(words) <= max_lines:
        return words

    total_width = sum(visible_width(word) for word in words) + len(words) - 1
    target_width = max(1, (total_width + max_lines - 1) // max_lines)
    lines = []
    current = []
    current_width = 0
    remaining_lines = max_lines

    for index, word in enumerate(words):
        word_width = visible_width(word)
        remaining_words = len(words) - index
        must_break_later = remaining_words > remaining_lines
        added_width = word_width if not current else current_width + 1 + word_width
        if (
            current
            and added_width > target_width
            and len(lines) + 1 < max_lines
            and must_break_later
        ):
            lines.append(" ".join(current))
            remaining_lines -= 1
            current = [word]
            current_width = word_width
        else:
            current.append(word)
            current_width = added_width

    if current:
        lines.append(" ".join(current))
    while len(lines) > max_lines:
        tail = lines.pop()
        lines[-1] = lines[-1] + " " + tail
    return lines


def wrap_words_for_entry(text, entry, args):
    width = wrap_width_for_entry(entry, args)
    lines, long_words = wrap_words(text, width)
    if (
        entry.get("category") == "item_descriptions"
        and args.item_description_max_lines > 0
        and len(lines) > args.item_description_max_lines
    ):
        lines = pack_words_into_max_lines(text, args.item_description_max_lines)
        long_words = sum(1 for line in lines if visible_width(line) > width)
    return lines, long_words


def join_script_lines(lines):
    pages = []
    for start in range(0, len(lines), 3):
        page = lines[start : start + 3]
        if not page:
            continue
        text = page[0]
        if len(page) >= 2:
            text += "\n" + page[1]
        if len(page) >= 3:
            text += "\\l" + page[2]
        pages.append(text)
    return "\n\n".join(pages)


def join_plain_script_lines(lines, original):
    original_text = strip_hma_quotes(original)
    original_pages = [page for page in re.split(r"\n{2,}|\\p", original_text) if page.strip()]
    max_lines = max(
        [len([line for line in page.splitlines() if line.strip()]) for page in original_pages] or [2]
    )
    max_lines = max(1, max_lines)

    pages = []
    for start in range(0, len(lines), max_lines):
        page = lines[start : start + max_lines]
        if page:
            pages.append("\n".join(page))
    return "\n\n".join(pages)


def join_wrapped_lines(lines, entry, original):
    if entry.get("category") in PLAIN_LINE_WRAP_CATEGORIES:
        return "\n".join(lines)
    if entry.get("category") == "plain_scripts":
        return join_plain_script_lines(lines, original)
    return join_script_lines(lines)


def wrap_translation(text, entry, original, args, wrap_categories):
    if args.no_wrap or entry.get("category") not in wrap_categories:
        return text, False, 0, False
    if should_skip_wrap(text):
        return text, False, 0, True

    plain_text, _removed_layout = remove_layout_tokens(text)
    if not plain_text:
        return text, False, 0, False

    lines, long_words = wrap_words_for_entry(plain_text, entry, args)
    wrapped = join_wrapped_lines(lines, entry, original)
    return wrapped, wrapped != text, long_words, False


def mission_name_reference_width(entries):
    widths = []
    for entry in entries:
        if entry.get("category") != "mission_names":
            continue
        text = strip_hma_quotes(entry.get("original", ""))
        plain_text, _removed_layout = remove_layout_tokens(text)
        if plain_text:
            widths.append(visible_width(plain_text))
    return max(widths or [0])


def trim_to_width(text, max_width):
    if max_width <= 0 or visible_width(remove_layout_tokens(text)[0]) <= max_width:
        return text, False
    plain_text, _removed_layout = remove_layout_tokens(text)
    words = plain_text.split()
    if not words:
        return text, False
    kept = []
    for word in words:
        candidate = " ".join(kept + [word])
        if visible_width(candidate) > max_width:
            break
        kept.append(word)
    trimmed = " ".join(kept) if kept else plain_text[:max_width]
    return trimmed, trimmed != text


def trim_mission_name(text, max_width):
    return trim_to_width(text, max_width)


def compact_start_menu_label(text, entry, _original, max_width):
    if entry.get("category") != "start_menu_labels":
        return text, False
    return trim_to_width(text, max_width)


def main():
    parser = argparse.ArgumentParser(
        description="Repair translated JSON control codes and apostrophes."
    )
    parser.add_argument(
        "input",
        nargs="?",
        default="unbound-texts-it-untrimmed.json",
        help="Translated JSON to fix.",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="unbound-texts-it-untrimmed-controlfix.json",
        help="Fixed output JSON.",
    )
    parser.add_argument(
        "--source",
        default="unbound-texts.json",
        help="Optional untranslated JSON used as original-control reference.",
    )
    parser.add_argument(
        "--report",
        help="Optional JSON report listing entries whose critical controls still differ.",
    )
    parser.add_argument(
        "--no-wrap",
        action="store_true",
        help="Disable post-translation text wrapping/layout recomputation.",
    )
    parser.add_argument(
        "--wrap-width",
        type=int,
        default=35,
        help="Visible character width for dialogue wrapping. Default: 35.",
    )
    parser.add_argument(
        "--description-wrap-width",
        type=int,
        default=24,
        help="Visible character width for move/ability descriptions. Default: 24.",
    )
    parser.add_argument(
        "--item-description-wrap-width",
        type=int,
        default=34,
        help="Visible character width for item descriptions. Default: 34.",
    )
    parser.add_argument(
        "--item-description-max-lines",
        type=int,
        default=3,
        help="Maximum wrapped lines for item descriptions. Default: 3.",
    )
    parser.add_argument(
        "--wrap-categories",
        default=DEFAULT_WRAP_CATEGORIES,
        help=(
            "Comma-separated categories to wrap. "
            f"Default: {DEFAULT_WRAP_CATEGORIES}."
        ),
    )
    parser.add_argument(
        "--mission-name-max-width",
        type=int,
        default=0,
        help="Maximum visible width for mission names. Use 0 to auto-use the longest English mission name.",
    )
    parser.add_argument(
        "--start-menu-label-max-width",
        type=int,
        default=13,
        help="Maximum visible width for Super Cube/Start menu labels. Default: 13.",
    )
    parser.add_argument(
        "--setting-name-max-width",
        type=int,
        default=15,
        help="Maximum visible width for game setting names. Default: 15.",
    )
    args = parser.parse_args()

    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    entries = list(iter_entries(data))
    originals = source_originals(args.source)
    cmap = Charmap(target_lang="it")
    wrap_categories = {category.strip() for category in args.wrap_categories.split(",") if category.strip()}
    mission_max_width = args.mission_name_max_width or mission_name_reference_width(entries)

    stats = {
        "entries": 0,
        "translated": 0,
        "changed": 0,
        "braced_controls": 0,
        "split_controls": 0,
        "sequence_repairs": 0,
        "deduped_controls": 0,
        "cc_hex_escapes": 0,
        "apostrophe_repairs": 0,
        "menu_line_break_repairs": 0,
        "mission_name_trims": 0,
        "mission_name_max_width": mission_max_width,
        "start_menu_label_trims": 0,
        "start_menu_label_max_width": args.start_menu_label_max_width,
        "setting_name_trims": 0,
        "setting_name_max_width": args.setting_name_max_width,
        "actual_newline_repairs": 0,
        "wrapped": 0,
        "wrap_long_words": 0,
        "wrap_skipped_technical": 0,
        "remaining_control_mismatches": 0,
    }
    remaining = []

    for entry in entries:
        stats["entries"] += 1
        translated = entry.get("translated")
        if not translated:
            continue
        stats["translated"] += 1

        original = strip_hma_quotes(originals.get(entry.get("id"), entry.get("original", "")))
        before = translated

        text = translated

        text = normalize_outer_quotes(text)

        next_text = normalize_actual_layout_breaks(text)
        stats["actual_newline_repairs"] += int(next_text != text)
        text = next_text

        next_text = normalize_braced_controls(text)
        stats["braced_controls"] += int(next_text != text)
        text = next_text

        next_text = repair_split_controls(text)
        stats["split_controls"] += int(next_text != text)
        text = next_text

        next_text, sequence_changed = repair_control_sequences(text, original)
        stats["sequence_repairs"] += int(sequence_changed)
        text = next_text

        next_text, deduped = collapse_duplicate_state_controls(text)
        stats["deduped_controls"] += int(deduped)
        text = next_text

        next_text, cc_escaped = escape_hex_text_after_cc(text, original, cmap)
        stats["cc_hex_escapes"] += int(cc_escaped)
        text = next_text

        next_text = fix_apostrophes(text)
        stats["apostrophe_repairs"] += int(next_text != text)
        text = next_text

        next_text, menu_breaks_restored = restore_compact_menu_line_breaks(text, original, entry)
        stats["menu_line_break_repairs"] += int(menu_breaks_restored)
        text = next_text

        if entry.get("category") == "mission_names":
            next_text, trimmed = trim_mission_name(text, mission_max_width)
            stats["mission_name_trims"] += int(trimmed)
            text = next_text

        next_text, start_menu_trimmed = compact_start_menu_label(
            text, entry, original, args.start_menu_label_max_width
        )
        stats["start_menu_label_trims"] += int(start_menu_trimmed)
        text = next_text

        if entry.get("category") == "setting_names":
            next_text, setting_trimmed = trim_to_width(text, args.setting_name_max_width)
            stats["setting_name_trims"] += int(setting_trimmed)
            text = next_text

        next_text, wrapped, long_words, skipped_wrap = wrap_translation(
            text, entry, original, args, wrap_categories
        )
        stats["wrapped"] += int(wrapped)
        stats["wrap_long_words"] += long_words
        stats["wrap_skipped_technical"] += int(skipped_wrap)
        text = next_text

        if text != before:
            entry["translated"] = text
            stats["changed"] += 1

        if control_sequence(text) != control_sequence(original):
            stats["remaining_control_mismatches"] += 1
            if len(remaining) < 200:
                remaining.append(
                    {
                        "id": entry.get("id"),
                        "category": entry.get("category"),
                        "original_controls": control_sequence(original),
                        "translated_controls": control_sequence(text),
                    }
                )

    Path(args.output).write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    if args.report:
        Path(args.report).write_text(
            json.dumps({"stats": stats, "remaining": remaining}, indent=2, ensure_ascii=False)
            + "\n",
            encoding="utf-8",
        )

    for key, value in stats.items():
        print(f"{key}: {value}")
    print(f"output: {args.output}")


if __name__ == "__main__":
    main()
