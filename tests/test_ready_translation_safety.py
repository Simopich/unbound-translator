import json
from pathlib import Path

import pytest

from lib.pcs_text import hma_quote
from lib.translation_tokens import semantic_token_counts
from tests.helpers import load_script_module

READY_ITALIAN = Path(__file__).resolve().parents[1] / "ready-translations" / "it.json"
READY_INDONESIAN = Path(__file__).resolve().parents[1] / "ready-translations" / "id.json"
FIXTURE = (
    Path(__file__).resolve().parent / "fixtures" / "fixed_translation_overrides.json"
)
INJECTOR = load_script_module("005_hybrid_injector.py", "ready_translation_injector")
TRANSLATOR = load_script_module("003_llm_translate.py", "ready_translation_translator")
KNOWN_BINARY_FALSE_POSITIVES = {
    "scr_24019A",
    "scr_245EE0",
    "scr_246AE0",
}


def test_indonesian_is_supported_and_uses_current_ready_schema():
    assert TRANSLATOR.LANGUAGE_NAMES["id"] == "Indonesian"

    italian = json.loads(READY_ITALIAN.read_text(encoding="utf-8"))["entries"]
    indonesian = json.loads(READY_INDONESIAN.read_text(encoding="utf-8"))["entries"]
    assert len(indonesian) == len(italian)

    translated_fields = {"translated", "translated_fixed", "translated_controlfixed"}
    for expected, actual in zip(italian, indonesian, strict=True):
        expected_schema = {
            key: value for key, value in expected.items() if key not in translated_fields
        }
        actual_schema = {
            key: value for key, value in actual.items() if key not in translated_fields
        }
        assert actual_schema == expected_schema, actual["id"]

    translated = [entry for entry in indonesian if entry.get("translated")]
    assert len(translated) > 16_000

    charmap = INJECTOR.Charmap(target_lang="id")
    for entry in translated:
        source_tokens = semantic_token_counts(entry["original"])
        translated_tokens = semantic_token_counts(entry["translated"])
        for apostrophe_byte in ("{B3}", "{B4}"):
            source_tokens.pop(apostrophe_byte, None)
            translated_tokens.pop(apostrophe_byte, None)
        assert translated_tokens == source_tokens, entry["id"]

        encoded = INJECTOR.encode_text(
            charmap,
            entry["translated"],
            plain_script=entry.get("category") == "plain_scripts",
        )
        if entry.get("category") == "ability_descriptions":
            assert len(encoded) <= INJECTOR.ABILITY_DESCRIPTION_MAX_BYTES, entry["id"]
        if entry.get("no_relocation") or not INJECTOR.pointer_sources(entry):
            assert len(encoded) <= int(entry["byte_length"]), entry["id"]


def test_ready_italian_preserves_known_binary_pointer_false_positives():
    entries = json.loads(READY_ITALIAN.read_text(encoding="utf-8"))["entries"]
    entries_by_id = {entry["id"]: entry for entry in entries}

    for entry_id in KNOWN_BINARY_FALSE_POSITIVES:
        entry = entries_by_id.get(entry_id)
        if entry is not None:
            assert hma_quote(entry["translated"]) == entry["original"]


def test_compact_translation_fixture_prefers_display_text_and_preserves_tokens():
    entries = json.loads(FIXTURE.read_text(encoding="utf-8"))["entries"]

    for entry in entries:
        assert INJECTOR.translation_for_injection(entry) == entry["translated_fixed"]
        assert semantic_token_counts(entry["translated_fixed"]) == semantic_token_counts(
            entry["translated"]
        )

    broken = dict(entries[0], translated_fixed="Attacca!")
    with pytest.raises(ValueError, match="changes protected tokens"):
        INJECTOR.translation_for_injection(broken)


def test_ready_italian_compact_overrides_are_lossless_and_fit():
    entries = json.loads(READY_ITALIAN.read_text(encoding="utf-8"))["entries"]
    cmap = INJECTOR.Charmap(target_lang="it")
    checked = 0

    for entry in entries:
        fixed = entry.get("translated_fixed")
        if not fixed:
            continue

        checked += 1
        assert "\ufffd" not in fixed, entry["id"]
        assert semantic_token_counts(fixed) == semantic_token_counts(
            entry.get("translated", "")
        ), entry["id"]

        encoded = INJECTOR.encode_text(
            cmap,
            fixed,
            plain_script=entry.get("category") == "plain_scripts",
        )
        if entry.get("category") == "ability_descriptions":
            assert len(encoded) <= INJECTOR.ABILITY_DESCRIPTION_MAX_BYTES, entry["id"]
        if not INJECTOR.pointer_sources(entry):
            assert len(encoded) <= int(entry["byte_length"]), entry["id"]

    assert checked > 0
