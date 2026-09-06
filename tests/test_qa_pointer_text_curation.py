"""Byte, layout and buffer-role contracts for the QA Italian curation."""

import json
import re
import sys
from pathlib import Path

from lib.gen3_font import text_pixel_width
from lib.translation_tokens import semantic_token_counts
from tests.helpers import load_script_module

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads(
    (ROOT / 'tests/fixtures/qa_pointer_text_fits_it.json').read_text(encoding='utf-8')
)
INJECTOR = load_script_module('005_hybrid_injector.py', 'qa_curation_injector')
CONTROLFIX = load_script_module('004_controlfix_translations.py', 'qa_curation_controlfix')


def curated_entries():
    entries = json.loads((ROOT / 'ready-translations/it.json').read_text(encoding='utf-8'))['entries']
    by_id = {entry['id']: entry for entry in entries}
    ids = FIXTURE['fitted_ids']
    assert len(ids) == len(set(ids))
    return [by_id[entry_id] for entry_id in ids]


def semantic_counts(text):
    counts = semantic_token_counts(text)
    # B3/B4 are printable quote glyphs, not renderer state or runtime buffers.
    counts.pop('{B3}', None)
    counts.pop('{B4}', None)
    return counts


def pixel_width(text):
    return text_pixel_width(INJECTOR.normalize_text_escapes(text))


def test_curated_pointer_texts_fit_without_relocation_or_token_loss():
    cmap = INJECTOR.Charmap(target_lang='it')
    for entry in curated_entries():
        value = INJECTOR.translation_for_injection(entry)
        encoded = INJECTOR.encode_text(cmap, value)
        assert entry['category'] == 'pointer_texts', entry['id']
        assert len(encoded) <= entry['byte_length'], entry['id']
        assert encoded[-1] == 0xFF, entry['id']
        assert not INJECTOR.should_relocate_pointer_entry(entry, encoded, 'oversized')
        assert semantic_counts(value) == semantic_counts(entry['original']), entry['id']
        assert CONTROLFIX.control_sequence(value) == CONTROLFIX.control_sequence(
            INJECTOR.strip_hma_quotes(entry['original'])
        ), entry['id']


def test_curated_layout_stays_inside_source_line_width_and_row_limits():
    boundary = r'(?:(?:\\[nlp])|\s)*'
    for entry in curated_entries():
        source = CONTROLFIX.normalize_actual_layout_breaks(
            INJECTOR.strip_hma_quotes(entry['original'])
        )
        value = entry['translated']
        source_lines = re.split(r'\\[nlp]', source)
        source_width = max(map(pixel_width, source_lines))
        for line in re.split(r'\\[nlp]', value):
            assert pixel_width(line) <= source_width, entry['id']
        prefix = re.match(boundary, source)[0]
        suffix = re.search(boundary + '$', source)[0]
        assert value.startswith(prefix) and value.endswith(suffix), entry['id']
        source_body = source[len(prefix):len(source)-len(suffix) if suffix else None]
        value_body = value[len(prefix):len(value)-len(suffix) if suffix else None]
        if not any(token in source_body for token in ('\\p', '\\l')):
            assert len(re.split(r'\\[nlp]', value_body)) <= len(
                re.split(r'\\[nlp]', source_body)
            ), entry['id']


def test_curated_official_names_and_buffer_roles_match_reviewed_examples():
    by_id = {entry['id']: entry for entry in curated_entries()}
    for expected in FIXTURE['examples']:
        actual = by_id[expected['id']]
        for key, value in expected.items():
            assert actual[key] == value, (expected['id'], key)


def test_controlfix_does_not_change_reviewed_buffer_roles(tmp_path, monkeypatch):
    source = tmp_path / 'curated.json'
    output = tmp_path / 'fixed.json'
    source.write_text(json.dumps({'entries': FIXTURE['examples']}), encoding='utf-8')
    monkeypatch.setattr(sys, 'argv', ['004_controlfix_translations.py', str(source),
                                    '-o', str(output), '--source', str(source)])
    CONTROLFIX.main()
    actual = json.loads(output.read_text(encoding='utf-8'))['entries']
    assert actual == FIXTURE['examples']
