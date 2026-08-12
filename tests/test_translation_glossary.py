import importlib.util
import json
from pathlib import Path

import pytest

from lib.gen3_font import text_pixel_width
from lib.pcs_text import Charmap
from lib.translation_tokens import visible_width
from lib.translation_glossary import (
    GlossaryError,
    GlossaryLimit,
    GlossaryTerm,
    TranslationGlossary,
    load_glossary,
    restore_glossary_placeholders,
)


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "llm_translate",
    ROOT / "003_llm_translate.py",
)
LLM_TRANSLATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LLM_TRANSLATE)


def test_italian_glossary_is_valid_and_has_unique_sources():
    glossary = load_glossary(ROOT / "glossaries" / "it.json", expected_language="it")
    sources = [term.source for term in glossary.terms]

    assert len(sources) >= 180
    assert len(sources) == len(set(sources))
    assert "Frozen Heights" in sources
    assert "Jax" in sources
    assert "The Shadows" in sources
    assert "A Hero’s Journey" in sources


def test_italian_glossary_covers_every_extracted_mission_name():
    glossary = load_glossary(ROOT / "glossaries" / "it.json", expected_language="it")
    prepared = json.loads(
        (ROOT / "ready-translations" / "it.json").read_text(encoding="utf-8")
    )
    entries = list(prepared.get("entries", []))
    for table in prepared.get("tables", []):
        entries.extend(table.get("entries", []))
    entries.extend(prepared.get("free_texts", []))
    mission_names = [
        entry["translation_source"]
        for entry in entries
        if entry.get("category") == "mission_names"
    ]

    assert len(mission_names) == 85
    for name in mission_names:
        matches = glossary.matches(name, "mission_names")
        assert len(matches) == 1, name
        assert matches[0][:2] == (0, len(name)), name


def test_longest_glossary_match_wins_and_each_occurrence_is_protected():
    glossary = TranslationGlossary(
        "it",
        [
            GlossaryTerm("Borrius", "Borrius", "region"),
            GlossaryTerm("Tomb of Borrius", "Tomba di Borrius", "place"),
        ],
    )

    protected, replacements = glossary.protect(
        "Return to the Tomb of Borrius in Borrius."
    )

    assert protected == "Return to the ⟦glossary-1⟧ in ⟦glossary-2⟧."
    assert [row["target"] for row in replacements] == ["Tomba di Borrius", "Borrius"]
    assert restore_glossary_placeholders(protected, replacements) == (
        "Return to the Tomba di Borrius in Borrius."
    )


def test_glossary_placeholder_loss_is_rejected():
    replacements = [
        {
            "placeholder": "⟦glossary-1⟧",
            "source": "Jax",
            "target": "Jax",
            "kind": "character",
        }
    ]

    with pytest.raises(GlossaryError, match="expected 1, got 0"):
        restore_glossary_placeholders("Giacomo", replacements)


def test_missing_targets_ignores_adjacent_rom_control_tokens(tmp_path):
    path = tmp_path / "it.json"
    path.write_text(
        json.dumps(
            {
                "language": "it",
                "terms": [
                    {"source": "Aklove", "target": "Aklove", "kind": "character"}
                ],
            }
        ),
        encoding="utf-8",
    )
    glossary = load_glossary(path, expected_language="it")

    assert glossary.missing_targets("Aklove", r"\qoAklove\qc") == []


def test_missing_targets_ignores_controlfixed_line_wrapping(tmp_path):
    path = tmp_path / "it.json"
    path.write_text(
        json.dumps(
            {
                "language": "it",
                "terms": [
                    {
                        "source": "Fall Badge",
                        "target": "Medaglia Autunno",
                        "kind": "feature",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    glossary = load_glossary(path, expected_language="it")

    assert glossary.missing_targets(
        "Fall Badge", "Medaglia\nAutunno"
    ) == []


def test_category_scoped_term_does_not_replace_same_named_ability():
    glossary = TranslationGlossary(
        "it",
        [
            GlossaryTerm(
                "Honey Gather",
                "Raccolta di miele",
                "mission",
                categories=("mission_names",),
            )
        ],
    )

    assert glossary.matches("Honey Gather", "ability_names") == []
    assert glossary.protect("Honey Gather", "mission_names")[0] == "⟦glossary-1⟧"


def test_limited_term_uses_compact_target_only_in_limited_category():
    term = GlossaryTerm(
        "Mission Log",
        "Missioni",
        "feature",
        full_target="Registro Missioni",
        limits=(
            GlossaryLimit(
                ("start_menu_labels",), 13, "visible_characters", True
            ),
        ),
    )
    glossary = TranslationGlossary("it", [term])

    _protected, menu_replacements = glossary.protect(
        "Mission Log", "start_menu_labels"
    )
    _protected, script_replacements = glossary.protect("Open Mission Log", "scripts")

    assert menu_replacements[0]["target"] == "Missioni"
    assert menu_replacements[0]["full_target"] == "Registro Missioni"
    assert script_replacements[0]["target"] == "Registro Missioni"


def test_italian_compact_targets_record_limits_and_full_wording():
    glossary = load_glossary(ROOT / "glossaries" / "it.json", expected_language="it")
    by_source = {term.source: term for term in glossary.terms}

    expected = {
        "If We Were Meant to Fly": ("Nati per volare", "Se fossimo fatti per volare"),
        "Exp. Millionaire": ("Milionario di PE", "Milionario di Punti Esperienza"),
        "The West Borrius Pokédex": (
            "Pokédex Borrius Ovest",
            "Il Pokédex di Borrius Occidentale",
        ),
        "Mission Log": ("Missioni", "Registro Missioni"),
        "Mining Scan": ("Scansione min.", "Scansione Mineraria"),
        "Stat Scanner": ("Scannerstat.", "Scanner Statistiche"),
    }
    for source, (target, full_target) in expected.items():
        term = by_source[source]
        assert term.target == target
        assert term.full_target == full_target
        assert term.limits

    mission_terms = [term for term in glossary.terms if term.kind == "mission"]
    assert len(mission_terms) == 85
    assert all(
        len(term.limits) == 1
        and term.limits[0].categories == ("mission_names",)
        and term.limits[0].max_length == 26
        and term.limits[0].length_unit == "visible_characters"
        for term in mission_terms
    )
    assert sum(term.limits[0].use_compact_target for term in mission_terms) == 3


def test_every_italian_limited_target_fits_its_recorded_limit():
    glossary = load_glossary(ROOT / "glossaries" / "it.json", expected_language="it")
    cmap = Charmap("it")

    for term in glossary.terms:
        for limit in term.limits:
            categories = limit.categories or (None,)
            for category in categories:
                target = term.target_for(category)
                if limit.length_unit == "visible_characters":
                    actual = visible_width(target)
                elif limit.length_unit == "pixels":
                    actual = text_pixel_width(target)
                else:
                    actual = len(cmap.encode(target))
                assert actual <= limit.max_length, (
                    term.source,
                    category,
                    target,
                    actual,
                    limit,
                )


def test_every_exact_nonrelocatable_glossary_name_records_its_pcs_limit():
    glossary = load_glossary(ROOT / "glossaries" / "it.json", expected_language="it")
    ready = json.loads(
        (ROOT / "ready-translations" / "it.json").read_text(encoding="utf-8")
    )
    entries = list(ready.get("entries", []))
    for table in ready.get("tables", []):
        entries.extend(table.get("entries", []))
    entries.extend(ready.get("free_texts", []))

    checked = []
    for entry in entries:
        source = entry.get("translation_source", "")
        category = entry.get("category", "")
        matches = glossary.matches(source, category)
        if len(matches) != 1 or matches[0][:2] != (0, len(source)):
            continue
        pointer_based = entry.get(
            "is_pointer_based", bool(entry.get("pointer_sources"))
        )
        if pointer_based and not entry.get("no_relocation"):
            continue
        term = matches[0][2]
        assert any(
            limit.length_unit == "pcs_bytes"
            and category in limit.categories
            and limit.max_length == entry["byte_length"]
            for limit in term.limits
        ), entry["id"]
        checked.append(entry["id"])

    assert checked == [
        "tbl_item_names_00278_8791C8",
        "tbl_item_names_00366_87A0E8",
        "tbl_trainer_classes_00045_23E7A1",
        "tbl_trainer_classes_00048_23E7C8",
    ]


def test_llm_work_item_uses_glossary_and_restores_approved_italian():
    glossary = TranslationGlossary(
        "it",
        [GlossaryTerm("Frozen Heights", "Alture Ghiacciate", "place")],
    )
    data = {
        "entries": [
            {
                "id": "scr_test",
                "category": "scripts",
                "translation_source": "Welcome to Frozen Heights, [player-name-1]!",
                "semantic_token_placeholders": [
                    {"placeholder": "[player-name-1]", "token": "[player]"}
                ],
            }
        ]
    }

    work, already_translated, skipped_empty = LLM_TRANSLATE.build_work_items(data, glossary)
    item = work[0]

    assert already_translated == 0
    assert skipped_empty == 0
    assert item["text"] == "Welcome to ⟦glossary-1⟧, [player-name-1]!"
    assert LLM_TRANSLATE.validate_and_restore_semantic_tokens(
        work,
        ["Benvenuto ad ⟦glossary-1⟧, [player-name-1]!"],
    ) == ["Benvenuto ad Alture Ghiacciate, [player]!"]


def test_existing_translation_without_required_target_is_queued_for_refresh():
    glossary = TranslationGlossary(
        "it",
        [GlossaryTerm("Frozen Heights", "Alture Ghiacciate", "place")],
    )
    data = {
        "entries": [
            {
                "translation_source": "Welcome to Frozen Heights!",
                "translated": "Benvenuto a Frozen Heights!",
            },
            {
                "translation_source": "Return to Frozen Heights!",
                "translated": "Torna alle Alture Ghiacciate!",
            },
        ]
    }

    invalidated = LLM_TRANSLATE.invalidate_nonconforming_glossary_translations(
        data, glossary
    )

    assert invalidated == 1
    assert "translated" not in data["entries"][0]
    assert data["entries"][1]["translated"] == "Torna alle Alture Ghiacciate!"


def test_glossary_language_must_match_target(tmp_path):
    path = tmp_path / "fr.json"
    path.write_text(json.dumps({"language": "fr", "terms": []}), encoding="utf-8")

    with pytest.raises(GlossaryError, match="does not match target"):
        load_glossary(path, expected_language="it")
