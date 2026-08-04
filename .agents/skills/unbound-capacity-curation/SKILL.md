---
name: unbound-capacity-curation
description: Resolve Pokemon Unbound relocation-capacity or fixed-slot fit failures by safely shortening translated JSON category by category. Use when transactional preflight reports entries or bytes that do not fit, translations require translated_fixed, or a release JSON exceeds safe ROM capacity; do not use automated truncation or abbreviate before natural shorter wording is exhausted.
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
2. Reproduce with `005_hybrid_injector.py --dry-run`. Record missing entry/byte totals and any fixed/no-relocation error.
3. Select one category batch. Prioritize strings whose encoded translation exceeds the original slot or consumes
   relocation space; retain entry IDs and source wording for review.
4. Rewrite each value with shorter natural syntax while preserving full meaning, official terminology, semantic/control
   tokens, required punctuation, and renderer context.
5. Use abbreviations only after natural shorter phrasing fails, and only for immediately recognizable terms. Never
   remove clauses, placeholders, gameplay facts, or required controls merely to fit.
6. For `no_relocation`, fixed-size, or ability-display limits, keep full wording in `translated` and add a complete,
   token-safe `translated_fixed` only when the entry contract requires it.
7. Rerun controlfix, token/layout tests, and injector dry-run. Iterate until the batch passes or the remaining deficit is
   quantified. Then build the full ROM and inspect the map.
8. Apply approved edits to the canonical JSON before moving to the next batch. Do not mix unrelated translation cleanup.

## Stop Conditions

Stop and report rather than degrade translation when meaning cannot fit naturally, protected tokens would change, the
failure is actually pointer ownership/free-space logic, or a runtime renderer needs a language patch. Never use
`--allow-lossy-fit` as a solution.

## Verification And Report

- Protected-token counts match source; controlfix reports no new mismatch.
- Injector reports zero missing candidates, truncations, ability compactions, pointer mismatches, implausible pointers,
  and encode errors.
- Report category, entries reviewed/changed, bytes recovered when measurable, representative before/after wording, and
  ROM/map paths.
