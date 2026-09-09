"""Regression coverage for complete oversized heuristic-pointer translations."""

import json
from pathlib import Path

from lib.translation_tokens import semantic_token_counts
from tests.helpers import load_script_module


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/oversized_pointer_text_it.json"
INJECTOR = load_script_module("005_hybrid_injector.py", "pointer_text_relocation_injector")


def test_oversized_pointer_text_relocates_to_vetted_space_without_text_loss():
    entry = json.loads(FIXTURE.read_text(encoding="utf-8"))["entries"][0]
    cmap = INJECTOR.Charmap(target_lang="it")
    translated = INJECTOR.translation_for_injection(entry)
    encoded = INJECTOR.encode_text(cmap, translated)
    address = INJECTOR.parse_address(entry["address"])
    pointer_source = INJECTOR.parse_address(entry["pointer_sources"][0])
    rom = bytearray(b"\x00" * 0x300)
    rom[pointer_source:pointer_source + 4] = (
        INJECTOR.GBA_POINTER_BASE + address
    ).to_bytes(4, "little")

    assert len(encoded) > entry["byte_length"]
    assert semantic_token_counts(translated) == semantic_token_counts(entry["original"])
    assert INJECTOR.should_relocate_pointer_entry(entry, encoded, "oversized")

    candidates, skipped = INJECTOR.collect_relocation_candidates(
        rom,
        [entry],
        cmap,
        "oversized",
        set(),
        0x100,
    )
    assert skipped == {}
    assert len(candidates) == 1
    assert candidates[0].encoded == encoded

    plan, missing = INJECTOR.plan_relocations(
        [INJECTOR.FreeBlock(0x200, 0x280, 0x200)],
        candidates,
        INJECTOR.DEFAULT_TEXT_ALIGNMENT,
    )
    assert plan == {entry["id"]: (0x200, "vetted_ff", False)}
    assert missing == []


def test_pointer_text_that_fits_remains_in_place():
    entry = json.loads(FIXTURE.read_text(encoding="utf-8"))["entries"][0]
    entry["byte_length"] = 64
    encoded = INJECTOR.encode_text(
        INJECTOR.Charmap(target_lang="it"),
        INJECTOR.translation_for_injection(entry),
    )

    assert not INJECTOR.should_relocate_pointer_entry(entry, encoded, "oversized")


def test_every_ready_italian_translation_fits_or_is_relocation_eligible():
    entries = json.loads(
        (ROOT / "ready-translations/it.json").read_text(encoding="utf-8")
    )["entries"]
    cmap = INJECTOR.Charmap(target_lang="it")
    unresolved = []

    for entry in entries:
        if not entry.get("translated"):
            continue
        encoded = INJECTOR.encode_text(
            cmap,
            INJECTOR.translation_for_injection(entry),
            plain_script=entry.get("category") == "plain_scripts",
        )
        if len(encoded) <= int(entry["byte_length"]):
            continue
        if not INJECTOR.should_relocate_pointer_entry(entry, encoded, "oversized"):
            unresolved.append(
                (entry["id"], entry["category"], len(encoded), entry["byte_length"])
            )

    assert unresolved == []
