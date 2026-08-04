---
name: unbound-relocation-compaction
description: Compact ordinary pointer-based Pokemon Unbound translations that the injector relocates because they exceed their original PCS slots. Use for fresh-map relocation batches, byte-budget shortening, parallel LLM curation, semantic review, selected-ID canonical merges, and proving that only documented complete blocked strings remain relocated; use unbound-capacity-curation for exhausted ROM free space, no_relocation, translated_fixed, or rigid display limits.
---

# Unbound Relocation Compaction

Fit relocated translations back into their original slots without losing meaning, official terminology, or engine
tokens. This is map-driven editorial curation, not truncation.

## Inputs And Output

- Input: verified source ROM, controlfixed target JSON, prepared/source JSON, and a fresh injector map.
- Output: selected-ID edits in the canonical JSON, controlfix report, full ROM/map build, and documented blocked IDs.
- Process ordinary pointer-based relocations only. Route total free-space failures and rigid/fixed slots to
  `unbound-capacity-curation`.

## Byte Contract

- Treat `entry.byte_length` as total slot capacity including the `0xFF` terminator.
- Require `len(Charmap(target_lang).encode(text)) <= entry.byte_length`.
- Do not use `Charmap.byte_length()` as total size; it excludes the terminator.
- Use a fresh injector map as candidate authority. A post-curation map already excludes entries that now fit.

## Workflow

1. If work is conditional on a requested model, verify its explicit worker override before reading project state or
   writing files. Stop untouched when unavailable.
2. Run injector `--dry-run`; use the exact `relocations` IDs as candidates. Record relocation count/bytes and free space.
3. Preserve the canonical JSON. If it is controlfixed, decontrolfix to an editable working copy.
4. Build disjoint category-aware batches. Keep ID, category, source, prior target text, `max_bytes`, encoded bytes, and
   `semantic_token_placeholders` in every record. Split large categories evenly; combine small categories up to roughly
   1,000 entries.
5. Run workers at the actual concurrency limit in waves. Give each worker one file and permit edits only to `shortened`.
   Require natural concise syntax first, official abbreviations only when necessary, and explicit `blocked_ids` for text
   that cannot fit completely.
6. Run a disjoint second semantic pass over every batch. Compare source, prior target, and shortened text; repair dropped
   clauses, gameplay conditions, tone, and plausible but unofficial terminology.
7. Validate complete candidate coverage, unique IDs, JSON parsing, PCS bytes, and tokens. Require zero over-limit
   non-blocked entries and zero new source-token mismatch IDs.
8. Run controlfix on the editable result. Since a full decontrolfix/controlfix round trip may rewrite unrelated manual
   layout, merge only selected controlfixed `translated` values into a copy of the canonical JSON. Assert stable IDs and
   no changed field other than `translated`.
9. Compare controlfix mismatch ID sets, run full tests, injector dry-run, and full ROM build. Replace the canonical JSON
   only after all checks pass.

## Translation And Token Rules

- Preserve complete meaning, facts, tone, names, punctuation required by the renderer, and all source semantic tokens.
- Research terminology through PokeAPI localization, trusted Pokemon references, then the official target FireRed ROM.
- Treat prepared/source `semantic_token_placeholders` as authority. Existing target text may already duplicate controls
  or use raw bytes for ordinary glyphs.
- Compare mismatch ID sets before/after, not only counts. Equal counts can hide one resolved and one new mismatch.
- Preserve exact official wording protected by fixtures, even when it must remain relocated. Distinguish literal `\n`
  tokens from actual JSON newlines.

## Stop Conditions

Block and report rather than remove meaning, gameplay clauses, or tokens. Do not use `--allow-lossy-fit`. Stop when the
failure is actually ownership/allocation logic, a rigid slot needing `translated_fixed`, or renderer behavior needing a
runtime patch.

## Verification And Report

- Remaining relocation IDs equal documented complete blocked IDs plus exact official fixture text deliberately kept.
- Injector reports zero missing candidates, pointer mismatches, implausible pointers, encode errors, fixed/no-relocation
  truncations, and ability compactions.
- Report entries selected/changed/blocked, before/after relocation count and bytes, remaining categories, free bytes,
  representative wording fixes, controlfix delta, test result, ROM path, and map path.
