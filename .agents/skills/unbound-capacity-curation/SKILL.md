---
name: unbound-capacity-curation
description: Resolve Pokemon Unbound total free-space deficits and rigid fixed-slot fit failures through safe translation curation. Use when injector capacity is insufficient, no_relocation text exceeds its slot, translated_fixed is required, or ability/display limits fail; use unbound-relocation-compaction for bulk map-driven fitting of ordinary pointer-based relocations.
---

# Unbound Capacity Curation

Preserve a complete, natural translation while reducing encoded PCS size. This is editorial curation guided by injector
evidence, not lossy controlfix or automatic truncation.

## Inputs And Output

- Input: source ROM, target-language JSON, prepared/source JSON, failing injector output, and category scope.
- Output: edited canonical translation JSON, controlfixed release JSON, successful dry-run/full injector map, and a
  concise review list for the category batch.
- Work one category at a time. For small categories, combine adjacent categories up to roughly 1,000 entries; for a
  large category, complete that category before requesting review.

## Workflow

1. Preserve the current JSON and establish whether it is editable or controlfixed. If controlfixed, run
   `006_decontrolfix_translations.py` to an editable working file.
2. Reproduce with `005_hybrid_injector.py --dry-run`. Record missing entries/bytes, remaining free space, and every
   fixed/no-relocation error. Use `unbound-relocation-compaction` when ordinary relocation fitting is the actual task.
3. Select one failing category or rigid contract. Retain entry IDs, source wording, display/slot budget, and renderer
   context for review.
4. Rewrite each value with shorter natural syntax while preserving full meaning, official terminology, semantic/control
   tokens, required punctuation, and renderer context.
5. Use abbreviations only after natural shorter phrasing fails, and only for immediately recognizable terms. Never
   remove clauses, placeholders, gameplay facts, or required controls merely to fit.
6. For `no_relocation`, fixed-size, or ability-display limits, keep full wording in `translated` and add a complete,
   token-safe `translated_fixed` only when the entry contract requires it.
7. Rerun controlfix, token/layout tests, and injector dry-run. Iterate until the rigid contract passes or the remaining
   capacity deficit is quantified. Build the full ROM and inspect the map.
8. Apply approved edits to the canonical JSON only after checks pass. Do not mix unrelated translation cleanup.

## Stop Conditions

Stop and report rather than degrade translation when meaning cannot fit naturally, protected tokens would change, the
failure is actually pointer ownership/free-space logic, or a runtime renderer needs a language patch. Never use
`--allow-lossy-fit` as a solution.

## Verification And Report

- Compare semantic tokens against source `semantic_token_placeholders`, not existing target text: existing translations
  may already contain duplicated controls or raw glyph bytes. Compare mismatch ID sets before/after, not only counts;
  require no new IDs and report resolved IDs.
- Injector reports zero missing candidates, truncations, ability compactions, pointer mismatches, implausible pointers,
  and encode errors.
- Report unresolved fixed/rigid entries or remaining free-space deficit rather than weakening complete wording.
- Run the full test suite. Exact official wording fixtures override capacity reduction.
- Report category, entries reviewed/changed, bytes recovered when measurable, representative before/after wording, and
  ROM/map paths.
