---
name: unbound-text-extraction
description: Find, classify, audit, or add missing Pokemon Unbound ROM text extraction coverage. Use for absent dialogue, missions, battle text, descriptions, menus, UI, credits, PCS hits, orphan text, tables, pointers, scripts, or bounded ranges; do not use for translation wording, layout repair, or injection-only failures.
---

# Unbound Text Extraction

Use this workflow only for lossless ROM discovery. Read `001_extract_unbound_text.py` and `lib/pcs_text.py` before
editing. Translation cleanup belongs to `002_prepare_translation_text.py`; wrapping/control repair belongs to
`004_controlfix_translations.py`.

## Inputs And Output

- Input ROM: `rom/unbound.gba`, MD5 `9cad8e771940e7f7094d13911552cef0`.
- Evidence: visible text/screen, event context, an address/pointer/table clue, or an audit query.
- Output: lossless `{"entries": [...]}` JSON plus focused audit evidence.
- Success: a proven owner/source, stable category/ID, exact pointer sources where relocatable, and no unexplained count
  regression. A raw PCS hit alone does not prove ownership.

## Choose The Path

- For an exact visible string or screen audit, read [references/audit-playbook.md](references/audit-playbook.md).
- Before adding/changing extraction structures, read [references/extraction-model.md](references/extraction-model.md).
- If the string is already extracted, stop extraction work and route the issue to translation, controlfix, or injection.
- If exact PCS encoding is absent, investigate graphical tiles, compression, custom encoding, or runtime assembly; do
  not add a blind PCS range.

## Workflow

1. Run baseline extraction or a focused audit in OS-provided temporary storage or an `out/audit-*` artifact; never
   assume `/tmp` exists.
2. Record visible text, screen/event, PCS offsets, nearby decoded text, existing entry ownership, and pointer evidence.
3. Prove ownership from a fixed record, sequential bank, pointer table, script operand, explicit address, or tightly
   bounded text range.
4. Add the narrowest rule in `001_extract_unbound_text.py`. Change `lib/pcs_text.py` only when the codec itself is
   demonstrably wrong.
5. Rerun baseline and focused audit. Confirm the hit is covered once, with the correct category and pointer sources.
6. Compare entry/category counts and investigate unrelated drops.
7. Compile changed Python and run extraction tests.

## Boundaries

- Never alter `original`, ID formatting, pointer ownership, byte lengths, or `no_relocation` to make translation easier.
- Never promote noisy `--include-orphans` or `--all-pointers` output without proving a durable owner.
- Prefer explicit addresses to a broad range for isolated strings; prefer a narrow range to a generic pointer scan for
  a small owned bank.
- A pointer-based entry needs real `pointer_sources`. Fragile routine pointers remain `no_relocation`.

## Verification And Report

Run:

```bash
python -m py_compile 001_extract_unbound_text.py lib/pcs_text.py
python -m pytest tests/test_extraction.py tests/test_pcs_text.py
```

Report queried text/screen, PCS offsets, audit status, entry ID/category/address, ownership evidence, rule added or
rejected, count deltas, and remaining non-PCS uncertainty.
