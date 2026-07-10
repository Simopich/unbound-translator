from __future__ import annotations

from collections import Counter
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.translation_tokens import (
    layout_token_counts,
    remove_layout_tokens,
    replace_semantic_tokens_with_placeholders,
    restore_semantic_token_placeholders,
    semantic_token_counts,
    visible_width,
)


def test_semantic_token_counts_ignore_layout_tokens():
    text = "[black]Ciao [player]\\n\\l\\p\\btn01{B4}"

    assert semantic_token_counts(text) == Counter(
        {
            "[black]": 1,
            "[player]": 1,
            "\\btn01": 1,
            "{B4}": 1,
        }
    )
    assert layout_token_counts(text) == Counter({"\\n": 1, "\\l": 1, "\\p": 1})


def test_placeholder_roundtrip_preserves_layout_tokens():
    text = "[black]Ciao [player]\\nPremi \\btn01"

    placeholder_text, placeholders = replace_semantic_tokens_with_placeholders(text)
    restored = restore_semantic_token_placeholders(placeholder_text, placeholders)

    assert placeholder_text == "[color-black-1]Ciao [player-name-2]\\nPremi [button-icon-3]"
    assert placeholders == [
        {"placeholder": "[color-black-1]", "token": "[black]"},
        {"placeholder": "[player-name-2]", "token": "[player]"},
        {"placeholder": "[button-icon-3]", "token": "\\btn01"},
    ]
    assert restored == text


def test_remove_layout_tokens_keeps_semantic_tokens_and_collapses_spacing():
    plain, layout = remove_layout_tokens("[red]Prima\\n\\lSeconda\n\n[player]")

    assert plain == "[red]Prima Seconda [player]"
    assert layout == ["\\n", "\\l", "\\p"]


def test_visible_width_treats_colors_as_zero_and_buttons_as_one():
    assert visible_width("[black]OK\\btn01[player]") == 11
