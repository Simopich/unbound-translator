#!/usr/bin/env python3

import argparse
import json
import re
from pathlib import Path

from lib.gen3_font import text_pixel_width
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
BATTLE_PROMPT_NAME_SECOND_LINE_IDS = {
    "tbl_battle_messages_00412_3FE6D5",
}
INVERTED_STAT_MODIFIER_IDS = {
    "tbl_battle_messages_00224_3FCB41",
    "tbl_battle_messages_00226_3FCB50",
}
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
    "scripts,plain_scripts,pokedex_descriptions,move_descriptions,ability_descriptions,item_descriptions,"
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
    "pokedex_descriptions",
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


def starts_with_tokens(text, tokens):
    index = 0
    for token in tokens:
        while index < len(text) and text[index].isspace():
            index += 1
        if not text.startswith(token, index):
            return False
        index += len(token)
    return True


def ensure_original_prefix(text, original):
    prefix = leading_critical_tokens(original)
    if not prefix:
        return text, False

    prefix_text = "".join(prefix)
    stripped = text.lstrip()
    if stripped.startswith(prefix_text) or starts_with_tokens(stripped, prefix):
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


def allows_critical_token_reorder(original):
    original = strip_hma_quotes(original)
    return bool(
        re.match(r"^\\\\(?:0F|10)’s \\\\00(?:\n|\\n)\[player\]$", original)
        or re.match(r"^Using \\\\16, the \\\\00 of(?:\n|\\n)\\\\13 \[player\]$", original)
        or re.fullmatch(
            r"\\\\1C \\\\1D is(?:\n|\\n)about to use \[player\]\."
            r"(?:\n|\\n){2}Will \\\\23 change(?:\n|\\n)Pokémon\?",
            original,
        )
    )


def repair_control_sequences(text, original):
    changed = False

    text, did_change = replace_token_family(text, original, lambda token: token in QUOTE_TOKENS)
    changed = changed or did_change

    text, did_change = replace_token_family(text, original, lambda token: token in COLOR_TOKENS)
    changed = changed or did_change

    if allows_critical_token_reorder(original):
        return text, changed

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


def controls_match(text, original):
    translated_controls = control_sequence(text)
    original_controls = control_sequence(original)
    if translated_controls == original_controls:
        return True
    if allows_critical_token_reorder(original):
        return sorted(translated_controls) == sorted(original_controls)
    return False


def remove_excess_name_tokens(text, original):
    """Remove model-invented duplicate dynamic names, keeping possessive placement."""
    changed = False
    for token in ("[player]", "[rival]"):
        excess = text.count(token) - original.count(token)
        for _ in range(max(0, excess)):
            text = text.replace(token, "", 1)
            changed = True
    return text, changed


def normalize_pokedex_category(text):
    fixed = re.sub(r"^Pokémon\s+", "", text, flags=re.IGNORECASE)
    fixed = re.sub(r"\s+Pokémon$", "", fixed, flags=re.IGNORECASE)
    return fixed, fixed != text


def restore_short_battle_fragment_spacing(text, original, entry):
    if entry.get("category") != "battle_messages":
        return text, False
    source = strip_hma_quotes(original)
    if entry.get("id") in INVERTED_STAT_MODIFIER_IDS:
        fixed = " " + text.strip()
        return fixed, fixed != text
    if visible_width(source.strip()) > 20:
        return text, False

    fixed = text
    if source.startswith(" ") and not fixed.startswith(" "):
        fixed = " " + fixed
    if source.endswith(" ") and not fixed.endswith(" "):
        fixed += " "
    return fixed, fixed != text


def normalize_actual_layout_breaks(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    def paragraph_repl(match):
        count = len(match.group(0))
        # The explicit alias prevents paragraph + "k..." from becoming the
        # longer Pokemon glyph token ``\\pk`` during PCS encoding.
        return "\\pn" * (count // 2) + ("\\n" if count % 2 else "")

    text = re.sub(r"\n{2,}", paragraph_repl, text)
    return text.replace("\n", "\\n")


def original_layout_lines(original):
    original_text = strip_hma_quotes(original)
    if "\\n" in original_text:
        lines = original_text.split("\\n")
    elif "\n" in original_text:
        lines = original_text.split("\n")
    else:
        return []
    return [line.strip() for line in lines if line.strip()]


def restore_compact_menu_line_breaks(text, original, entry):
    if entry.get("category") not in MENU_LINE_BREAK_CATEGORIES:
        return text, False
    if "\n" in text or any(token in text for token in LAYOUT_TOKENS):
        return text, False

    original_lines = original_layout_lines(original)
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


def restore_menu_description_line_breaks(text, original, entry):
    if entry.get("category") not in MENU_LINE_BREAK_CATEGORIES:
        return text, False
    if "\n" in text or any(token in text for token in LAYOUT_TOKENS):
        return text, False

    original_lines = original_layout_lines(original)
    if len(original_lines) < 2:
        return text, False

    width = max(visible_width(remove_layout_tokens(line)[0]) for line in original_lines)
    if width <= 16:
        return text, False

    lines, _long_words = wrap_words(text, width)
    fixed = "\n".join(lines)
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
    if entry.get("category") == "pokedex_descriptions":
        return args.pokedex_description_wrap_width
    if entry.get("category") == "mission_objectives":
        return args.mission_objective_wrap_width
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


def wrap_words_by_pixels(text, max_pixels):
    words = text.split()
    lines = []
    current = []
    for word in words:
        candidate = " ".join(current + [word])
        if current and text_pixel_width(candidate) > max_pixels:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return lines


def non_layout_tokens(text):
    return [
        token
        for token in TOKEN_RE.findall(text)
        if token not in LAYOUT_TOKENS
    ]


def fit_mission_description_lines(text, max_pixels, max_lines):
    """Fit a non-scrolling mission description without losing runtime tokens."""
    original = " ".join(text.split())
    lines = wrap_words_by_pixels(original, max_pixels)
    if len(lines) <= max_lines:
        return lines, 0

    words = original.split()
    required_tokens = non_layout_tokens(original)
    candidates = []
    for prefix_count in range(1, len(words)):
        for suffix_count in range(1, len(words) - prefix_count):
            candidate = " ".join(
                words[:prefix_count] + ["..."] + words[len(words) - suffix_count:]
            )
            if non_layout_tokens(candidate) != required_tokens:
                continue
            candidate_lines = wrap_words_by_pixels(candidate, max_pixels)
            if len(candidate_lines) <= max_lines:
                kept = prefix_count + suffix_count
                candidates.append((-kept, -len(candidate), candidate_lines))
    if not candidates:
        return ["..."], 0
    return min(candidates)[-1], 0


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


def compact_words_in_middle(text, max_total):
    words = text.split()
    if not words or visible_width(" ".join(words)) <= max_total:
        return " ".join(words)

    marker = "..."
    required_tokens = non_layout_tokens(text)
    candidates = []
    for prefix_count in range(1, len(words)):
        for suffix_count in range(1, len(words) - prefix_count):
            candidate = " ".join(
                words[:prefix_count] + [marker] + words[len(words) - suffix_count:]
            )
            if non_layout_tokens(candidate) != required_tokens:
                continue
            width = visible_width(candidate)
            if width <= max_total:
                kept = prefix_count + suffix_count
                balance = abs(prefix_count - suffix_count)
                candidates.append((-kept, balance, -width, candidate))
    if not candidates:
        return " ".join(words)
    return min(candidates)[-1]


def fit_pokedex_description_lines(text, width, max_lines, max_total):
    original = " ".join(text.split())
    for total_budget in range(max_total, 0, -1):
        compacted = compact_words_in_middle(original, total_budget)
        lines, long_words = wrap_words(compacted, width)
        if max_lines > 0 and len(lines) > max_lines:
            lines = pack_words_into_max_lines(compacted, max_lines)
            long_words = sum(1 for line in lines if visible_width(line) > width)
        if (
                (max_lines <= 0 or len(lines) <= max_lines)
                and max((visible_width(line) for line in lines), default=0) <= width
        ):
            return lines, long_words
    return ["..."], 0


def wrap_words_for_entry(text, entry, args):
    if entry.get("category") == "pokedex_descriptions":
        return fit_pokedex_description_lines(
            text,
            args.pokedex_description_wrap_width,
            args.pokedex_description_max_lines,
            args.pokedex_description_max_total,
        )
    if entry.get("category") == "mission_descriptions":
        return fit_mission_description_lines(
            text,
            args.mission_description_max_pixels,
            args.mission_description_max_lines,
        )
    if entry.get("category") == "mission_objectives":
        return fit_pokedex_description_lines(
            text,
            args.mission_objective_wrap_width,
            args.mission_objective_max_lines,
            args.mission_objective_max_total,
        )
    if entry.get("category") == "move_descriptions":
        lines = wrap_words_by_pixels(text, args.move_description_max_pixels)
        long_words = sum(
            text_pixel_width(word) > args.move_description_max_pixels
            for word in text.split()
        )
        return lines, long_words
    if entry.get("category") == "ability_descriptions":
        lines = wrap_words_by_pixels(text, args.ability_description_max_pixels)
        if (
            args.ability_description_max_lines > 0
            and len(lines) > args.ability_description_max_lines
        ):
            raise ValueError(
                f"Ability description {entry.get('id', '<unknown>')} needs "
                f"{len(lines)} rows; compact it to at most "
                f"{args.ability_description_max_lines} rows of "
                f"{args.ability_description_max_pixels} pixels"
            )
        if max((visible_width(line) for line in lines), default=0) > args.ability_description_max_chars:
            raise ValueError(
                f"Ability description {entry.get('id', '<unknown>')} exceeds "
                f"the original-ROM limit of {args.ability_description_max_chars} "
                "visible characters"
            )
        long_words = sum(
            text_pixel_width(word) > args.ability_description_max_pixels
            for word in text.split()
        )
        return lines, long_words
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



def restore_battle_prompt_layout(text, _original, entry):
    if entry.get("id") not in BATTLE_PROMPT_NAME_SECOND_LINE_IDS:
        return text, False

    match = re.search(r"\\\\12\??", text)
    if not match:
        return text, False

    prompt = text[: match.start()].strip()
    while prompt.endswith(("\\n", "\\l", "\n")):
        if prompt.endswith(("\\n", "\\l")):
            prompt = prompt[:-2].rstrip()
        else:
            prompt = prompt[:-1].rstrip()
    pokemon = match.group(0)
    trailing = text[match.end() :].strip()
    if trailing and set(trailing) <= set("?!."):
        pokemon += trailing
    if not prompt:
        return text, False

    fixed = f"{prompt}\n{pokemon}"
    return fixed, fixed != text


def wrap_translation(text, entry, original, args, wrap_categories, preserve_text=False):
    if args.no_wrap or entry.get("category") not in wrap_categories:
        return text, False, 0, False
    if (
        entry.get("category") == "ability_descriptions"
        and entry.get("translated_fixed")
    ):
        return text, False, 0, False
    if should_skip_wrap(text):
        return text, False, 0, True
    if entry.get("category") == "battle_messages" and (
        "\n" in text or any(token in text for token in LAYOUT_TOKENS)
    ):
        return text, False, 0, False

    plain_text, _removed_layout = remove_layout_tokens(text)
    if not plain_text:
        return text, False, 0, False

    if preserve_text:
        if entry.get("category") == "move_descriptions":
            width = args.move_description_max_pixels
            lines = wrap_words_by_pixels(plain_text, width)
            long_words = sum(text_pixel_width(word) > width for word in plain_text.split())
        elif entry.get("category") in {"mission_descriptions", "ability_descriptions"}:
            width = (
                args.mission_description_max_pixels
                if entry.get("category") == "mission_descriptions"
                else args.ability_description_max_pixels
            )
            lines = wrap_words_by_pixels(plain_text, width)
            long_words = sum(text_pixel_width(word) > width for word in plain_text.split())
        else:
            lines, long_words = wrap_words(plain_text, wrap_width_for_entry(entry, args))
    else:
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


def trim_to_pixel_width(text, max_pixels):
    plain_text, _removed_layout = remove_layout_tokens(text)
    if max_pixels <= 0 or text_pixel_width(plain_text) <= max_pixels:
        return text, False
    words = plain_text.split()
    if not words:
        return text, False
    kept = []
    for word in words:
        candidate = " ".join(kept + [word])
        if text_pixel_width(candidate) > max_pixels:
            break
        kept.append(word)
    if kept:
        trimmed = " ".join(kept)
    else:
        trimmed = ""
        for char in plain_text:
            if text_pixel_width(trimmed + char) > max_pixels:
                break
            trimmed += char
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
        "--wrap-only",
        action="store_true",
        help="Apply only safe layout normalization/wrapping; preserve all other controls.",
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
        help="Visible character width for ability descriptions. Default: 24.",
    )
    parser.add_argument(
        "--move-description-max-pixels",
        type=int,
        default=122,
        help=(
            "Maximum pixel width for move-description lines, measured from the "
            "ordinary entries in the working French ROM. Default: 122."
        ),
    )
    parser.add_argument(
        "--ability-description-max-pixels",
        type=int,
        default=191,
        help=(
            "Maximum pixel width for ability-description lines, measured from "
            "the original English ROM. Default: 191."
        ),
    )
    parser.add_argument(
        "--ability-description-max-lines",
        type=int,
        default=1,
        help=(
            "Maximum ability-description rows observed in the original English "
            "ROM. Default: 1."
        ),
    )
    parser.add_argument(
        "--ability-description-max-chars",
        type=int,
        default=34,
        help=(
            "Maximum visible characters in an ability description, observed "
            "in the original English ROM. Default: 34."
        ),
    )
    parser.add_argument(
        "--mission-description-max-pixels",
        type=int,
        default=172,
        help="Pixel width for non-scrolling Mission Log descriptions. Default: 172.",
    )
    parser.add_argument(
        "--mission-description-max-lines",
        type=int,
        default=3,
        help="Maximum lines for Mission Log descriptions. Default: 3.",
    )
    parser.add_argument(
        "--mission-objective-wrap-width",
        type=int,
        default=35,
        help="Visible character width for pause-menu mission objectives. Default: 35.",
    )
    parser.add_argument(
        "--mission-objective-max-lines",
        type=int,
        default=2,
        help="Maximum explicit lines for pause-menu mission objectives. Default: 2.",
    )
    parser.add_argument(
        "--mission-objective-max-total",
        type=int,
        default=65,
        help="Maximum total visible mission-objective length. Default: 65.",
    )
    parser.add_argument(
        "--pokedex-description-wrap-width",
        type=int,
        default=43,
        help="Visible character width for Pokédex descriptions. Default: 43.",
    )
    parser.add_argument(
        "--pokedex-description-max-lines",
        type=int,
        default=3,
        help="Maximum wrapped lines for Pokédex descriptions. Default: 3.",
    )
    parser.add_argument(
        "--pokedex-description-max-total",
        type=int,
        default=124,
        help="Maximum total visible Pokédex description length. Default: 124.",
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
        default=93,
        help="Maximum pixel width for game setting names. Default: 93.",
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
        "excess_name_token_repairs": 0,
        "pokedex_category_repairs": 0,
        "battle_fragment_spacing_repairs": 0,
        "deduped_controls": 0,
        "cc_hex_escapes": 0,
        "apostrophe_repairs": 0,
        "menu_line_break_repairs": 0,
        "menu_description_line_break_repairs": 0,
        "battle_prompt_layout_repairs": 0,
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

        if args.wrap_only:
            text = normalize_actual_layout_breaks(text)
            text, wrapped, long_words, skipped_wrap = wrap_translation(
                text,
                entry,
                original,
                args,
                wrap_categories,
                preserve_text=entry.get("category") != "mission_objectives",
            )
            stats["wrapped"] += int(wrapped)
            stats["wrap_long_words"] += long_words
            stats["wrap_skipped_technical"] += int(skipped_wrap)
            if text != before:
                entry["translated"] = text
                stats["changed"] += 1

            fixed = entry.get("translated_fixed")
            if isinstance(fixed, str) and fixed:
                fixed_before = fixed
                fixed = normalize_actual_layout_breaks(fixed)
                fixed, fixed_wrapped, fixed_long_words, fixed_skipped = wrap_translation(
                    fixed,
                    entry,
                    original,
                    args,
                    wrap_categories,
                    preserve_text=entry.get("category") != "mission_objectives",
                )
                stats["wrapped"] += int(fixed_wrapped)
                stats["wrap_long_words"] += fixed_long_words
                stats["wrap_skipped_technical"] += int(fixed_skipped)
                if fixed != fixed_before:
                    entry["translated_fixed"] = fixed
            continue

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

        next_text, excess_names_repaired = remove_excess_name_tokens(text, original)
        stats["excess_name_token_repairs"] += int(excess_names_repaired)
        text = next_text

        if entry.get("category") == "pokedex_species":
            next_text, category_repaired = normalize_pokedex_category(text)
            stats["pokedex_category_repairs"] += int(category_repaired)
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

        next_text, menu_description_breaks_restored = restore_menu_description_line_breaks(
            text, original, entry
        )
        stats["menu_description_line_break_repairs"] += int(menu_description_breaks_restored)
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
            next_text, setting_trimmed = trim_to_pixel_width(
                text, args.setting_name_max_width
            )
            stats["setting_name_trims"] += int(setting_trimmed)
            text = next_text

        next_text, wrapped, long_words, skipped_wrap = wrap_translation(
            text, entry, original, args, wrap_categories
        )
        stats["wrapped"] += int(wrapped)
        stats["wrap_long_words"] += long_words
        stats["wrap_skipped_technical"] += int(skipped_wrap)
        text = next_text

        next_text, battle_prompt_layout_restored = restore_battle_prompt_layout(
            text, original, entry
        )
        stats["battle_prompt_layout_repairs"] += int(battle_prompt_layout_restored)
        text = next_text

        next_text, fragment_spacing_repaired = restore_short_battle_fragment_spacing(
            text, original, entry
        )
        stats["battle_fragment_spacing_repairs"] += int(fragment_spacing_repaired)
        text = next_text

        if text != before:
            entry["translated"] = text
            stats["changed"] += 1

        if not controls_match(text, original):
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
