---
name: unbound-text-extraction
description: Extract, audit, and extend all Pokemon Unbound ROM text coverage. Use when asked to find untranslated text; audit PCS strings; add or repair fixed, sequential, pointer, script, manual-table, or contiguous-range extraction; investigate dialogue, narration, missions, battle text, item descriptions, menus, UI, credits, or orphan text; or classify text as PCS, graphical, compressed, or custom encoded.
---

# Unbound Text Extraction

Use this skill for *all* text coverage work, not only menus. Read the relevant
extractor code before changing it: `001_extract_unbound_text.py`,
`lib/pcs_text.py`, and any existing JSON/audit output. Extraction is a
lossless ROM-discovery step. Do not translate, normalize wording, remove
layout, repair controls, or alter text for a target language here. Those jobs
belong to `002_prepare_translation_text.py` and `004_controlfix_translations.py`.

## ROM And Baseline

- Default ROM: `rom/unbound.gba`.
- Expected source MD5: `9cad8e771940e7f7094d13911552cef0`.
- A healthy expanded baseline has `23,274` unique-address entries: `10,828`
  `scripts`, `3,522` strict aligned `pointer_texts`, `82` `mission_descriptions`,
  `85` `mission_names`, and `14` `plain_scripts`. This covers all 84 missions:
  Hero/Heroine use separate main-story title strings, while two side-mission
  registrations reuse text records. Treat these as regression
  signals when coverage grows.
- The ROM is 32 MB. ROM offsets are written as `0x...`; a GBA pointer is
  little-endian `0x08000000 + ROM offset`.
- Decode and encode only through `lib/pcs_text.py`. Do not add Meowth/HMA
  dependencies or use ASCII byte searches for text that must be PCS encoded.

## Extractor Model

`001_extract_unbound_text.py` merges these sources, in this order:

1. Fixed slots: names and other constant-size records. `FixedTable` supports
   direct slots, pointer names inside larger records, and substring names.
2. Sequential terminated strings: `SequentialTable` advances by decoded byte
   length.
3. Pointer tables: `PointerTable` reads 32-bit GBA pointers from known tables.
4. Explicit manual addresses: `MANUAL_TEXT_TABLES` covers isolated strings.
5. Narrow manual PCS ranges: `MANUAL_TEXT_RANGES` covers contiguous banks
   before generic pointer scanning.
6. Script and vetted structured pointers: `scan_pointer_texts` accepts normal
   script loadpointer sources, selected `0x67` pointers, high-bank tables, and
   unaligned trainer/link record fields.
7. Strict aligned pointers: every aligned GBA pointer is checked with a
   language/data-noise filter; accepted discoveries use `pointer_texts`.
8. Post-pointer manual ranges: `POST_POINTER_MANUAL_TEXT_RANGES` fills text
   banks that generic scanning would not cover safely.
9. Duplicate-address merge: one translation owner survives per ROM string;
   specific table/category entries win and all pointer sources are retained.
10. Optional orphan scan: unreferenced terminated PCS runs. It is audit-only
    evidence until a real owner/source is found.

Known special cases:

- The 293 ability names do **not** imply 293 descriptions. Only the first 255
  ability-description pointers decode as valid text.
- `plain_scripts` are full-screen text and need plain line breaks later, not
  dialogue continuation controls. Their addresses/ranges are explicit.
- Direct high-bank sources in `0x1E00000-0x1F00000` and
  `0x1FB0000-0x1FC0000` targeting `0x1EE0000-0x1FB0000` cover credits,
  missions, menus, descriptions, and late NPC text without normal opcodes.
- Mission titles are detected from the exact `loadpointer 0, title; call
  mission_handler` signature plus explicit Hero/Heroine main-story pointers.
  Keep this classifier exact because their layout limit differs later.
- `NO_RELOCATION_POINTER_SOURCE_RANGES` marks fragile routine text. Such
  entries get `no_relocation: true`, must remain inside `byte_length`, and may
  not be made relocatable merely to fit a longer translation.

## Fast Paths

Baseline extraction:

```bash
./001_extract_unbound_text.py rom/unbound.gba -o /tmp/unbound-texts.json
```

The strict aligned-pointer pass is enabled by default. Use
`--no-aligned-pointer-text` only for a narrow legacy comparison; it is not the
recommended translation baseline.

Audit built-in UI strings plus supplied strings, retaining machine-readable
evidence:

```bash
./001_extract_unbound_text.py rom/unbound.gba -o /tmp/unbound-texts.json \
  --audit-menu-text \
  --audit-string "Missing text" \
  --audit-output /tmp/unbound-text-audit.json
```

For many exact strings, make a UTF-8 file with one query per line. Empty lines
and lines starting `#` are ignored:

```bash
./001_extract_unbound_text.py rom/unbound.gba -o /tmp/unbound-texts.json \
  --audit-menu-text --audit-strings-file /tmp/text-queries.txt \
  --audit-output /tmp/unbound-text-audit.json
```

Use `--audit-no-case-variants` when casing itself matters. Default audit also
checks upper/title case forms. Use `--audit-max-hits-per-string -1` only for a
small query set; otherwise repeated fragments produce noisy reports. Increase
`--audit-preview-bytes` only when the decoded preview is too short.

Use these discovery flags sparingly:

```bash
./001_extract_unbound_text.py rom/unbound.gba -o /tmp/unbound-orphans.json \
  --include-orphans --max-text-length 0x800

./001_extract_unbound_text.py rom/unbound.gba -o /tmp/unbound-all-pointers.json \
  --all-pointers
```

`--include-orphans` can find valid unreferenced PCS strings but also produces
noise. `--all-pointers` accepts every plausible GBA pointer and is noisier
still. Never merge either result into normal extraction without proving the
actual data owner and adding a narrow durable source rule.

## Audit Triage

Each PCS audit hit has one of three meanings:

| Result                    | Meaning                                 | Next action                                                                                                                                                            |
|---------------------------|-----------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `found_and_extracted`     | Covered entry already spans the hit.    | Inspect its id/category, translation, layout, or injection path. Do not add a duplicate extractor rule.                                                                |
| `found_but_not_extracted` | PCS bytes exist but no entry owns them. | Identify the owning table, pointer source, or bounded text bank; then add the narrowest matching extraction rule.                                                      |
| `not_found_as_pcs_text`   | Exact PCS encoding absent.              | Check spelling/case/tokens first. Then investigate graphical tile text, compressed data, a custom encoding, or dynamically assembled UI. Do not add a blind PCS range. |

The audit compares a hit against every extracted entry range, not only an entry
start. A hit inside a longer extracted message is already covered.

For a missing screen or dialogue, record before editing:

- Visible English string, surrounding screen/event, and whether it is static,
  dynamic, or assembled from fragments.
- ROM offset for every PCS hit and a decoded preview around it.
- Existing entry id/category/address if nearby text is already covered.
- Pointer source offsets, pointer-table shape, record stride, or a clean
  bounded contiguous bank.
- Whether the runtime needs the string to relocate. Exact pointer sources are
  essential evidence for relocation; a text hit alone is not.
- Expected category/layout: `scripts`, `plain_scripts`, `mission_names`,
  descriptions, battle messages, menu label, etc.

## Choosing An Extraction Rule

Use the smallest rule that explains the data owner:

| Owner shape                          | Add/change                                                     | Notes                                                                                                                                  |
|--------------------------------------|----------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------|
| Fixed-width inline record            | `FIXED_TABLES`                                                 | Set `slot_size`; use `stride` when record size differs; set `substring_name` only when text begins at a variable offset inside a slot. |
| Consecutive terminated strings       | `SEQUENTIAL_TABLES`                                            | Use only a verified count and start; decode must advance cleanly.                                                                      |
| Stable 32-bit pointer array          | `POINTER_TABLES`                                               | Set correct start, count, and stride; invalid pointers must remain visible as invalid entries rather than guessed text.                |
| Few isolated known addresses         | `MANUAL_TEXT_TABLES`                                           | Best for standalone labels/messages. Keep table name and address order stable.                                                         |
| Contiguous, vetted PCS bank          | `MANUAL_TEXT_RANGES` or `POST_POINTER_MANUAL_TEXT_RANGES`      | Use precise half-open `[start, end)` limits. Include only strings that pass the existing manual-range plausibility check.              |
| Script opcode/dynamic source pattern | `is_script_text_pointer_source` or a new constrained predicate | Restrict by opcode, bank, structure, and target range. Random 4-byte values are not evidence.                                          |
| Direct structured high-bank pointer  | `is_additional_text_pointer_source` or a sibling predicate     | Require aligned source plus both vetted source and target ranges.                                                                      |
| String found only by orphan scan     | Do not add it yet                                              | Find its real table/reference first; otherwise leave as audit evidence.                                                                |

Prefer an explicit address list over a wide range when only a few strings are
known. Prefer a narrow range over a broad pointer scan when a system owns a
small contiguous text bank. Do not duplicate a string already covered by an
earlier source; `known_targets` and occupied ranges exist to avoid that.

## Entry Contract

Normal output is `{"entries": [...]}`. Every extracted entry contains:

- `id`: address-stable. Scripts are `scr_<ROMADDR>`; table/manual entries are
  `tbl_<category>_<table_index>_<ROMADDR>`.
- `category`: controls later translation/layout policy. Choose the existing
  closest category; add a new one only when it has a clear owner and later
  behavior needs to distinguish it.
- `address`: uppercase hexadecimal ROM offset.
- `original`: lossless PCS decode, including engine tokens/layout markers.
- `byte_length`: original encoded span/slot capacity used for in-place writes.
- `is_pointer_based`: true only when the text has a usable pointer owner.
- `pointer_sources`: exact hexadecimal GBA-pointer locations, possibly empty.
- `table_name` and `table_index`: present for structured/manual table entries.
- `no_relocation`: only for known fragile pointer-source ranges.

Do not change id formatting, omit `pointer_sources`, fake pointer-based status,
or silently alter `original`. Downstream debug filters, maps, resume data,
layout repair, and hybrid injection depend on these fields.

## Safe Implementation Sequence

1. Run the baseline/audit into `/tmp`; preserve existing `out/` artifacts
   unless the task names them.
2. Prove ownership using existing nearby tables, pointer references, record
   layout, or a bounded PCS bank.
3. Add the narrowest data declaration/predicate in
   `001_extract_unbound_text.py`. Keep categories, table names, and addresses
   stable. Do not modify `lib/pcs_text.py` unless the byte codec itself is
   demonstrably wrong.
4. Re-run baseline extraction and the focused audit. Confirm the prior
   `found_but_not_extracted` hits become `found_and_extracted`, with correct
   entry address/category and no duplicate text owner.
5. Compare counts/category deltas. Explain intentional deltas; investigate
   unrelated drops.
6. Check relocation safety: a pointer-based entry needs real
   `pointer_sources`; routine text in protected source ranges needs
   `no_relocation`.
7. Run `python3 -m py_compile 001_extract_unbound_text.py lib/pcs_text.py`
   when either file changes.
8. Update `README.md` and `AGENTS.md` for durable extractor behavior, known
   ranges, output-contract changes, or workflow flags. Do not document every
   one-off investigation.

## Useful Inspection Commands

Inspect entry/category coverage without changing files:

```bash
jq -r '.entries[] | select(.original | contains("Missing text")) | [.id, .category, .address, (.pointer_sources | join(","))] | @tsv' /tmp/unbound-texts.json
jq '[.entries[] | select(.category == "mission_names")] | length' /tmp/unbound-texts.json
jq '[.entries[] | select(.no_relocation == true)] | {count:length, entries: map({id, address, pointer_sources})}' /tmp/unbound-texts.json
```

Inspect code by concept:

```bash
rg -n "FIXED_TABLES|SEQUENTIAL_TABLES|POINTER_TABLES|MANUAL_TEXT|scan_pointer_texts|is_.*pointer|NO_RELOCATION|plain_scripts|mission_names" 001_extract_unbound_text.py
rg -n "decode_pcs|encode|terminator|control" lib/pcs_text.py
```

## Report Back

Return high-signal facts: queried text/screen, PCS offsets, audit status,
entry id/category/address, pointer-source evidence, extraction rule added or
rejected, category-count delta, verification commands, and remaining limits.
For non-PCS text, say clearly that it is likely graphical/compressed/custom
encoded and avoid implying normal extraction can translate it.
