---
name: unbound-runtime-patch
description: Create, repair, review, or remove a target-language Pokemon Unbound runtime ROM patch when translation JSON and controlfix cannot express the required behavior. Use for renderer operand order, shared suffixes, language-specific assembly/data writes, handled entry ownership, or patch-loader failures; do not use for wording-only edits.
---

# Unbound Runtime Patch

Runtime patches are the last resort for target-language behavior that cannot be represented safely in translation JSON
or generic controlfix logic. One behavior equals one file under `patches/<language>/`.

## Inputs And Output

- Input: target language, observed behavior, source-ROM bytes/pointers, affected entry IDs, and comparison evidence.
- Output: one focused `patches/<language>/<behavior>.py` file, regression coverage, and injector map evidence.
- Patch module exports `apply(context)` and returns a JSON-serializable report.

## Workflow

1. Prove the issue is runtime behavior, not extraction ownership, wording, token repair, or ordinary relocation.
2. Identify exact source-ROM offsets and accepted original byte/text forms. Prefer local disassembly/runtime evidence;
   comparison ROMs are corroboration only.
3. Implement idempotent writes: accept known original forms and the already-patched form; reject every unexpected value.
4. Honor `context.dry_run`; validate everything in dry-run but write nothing.
5. Add every patch-owned translation entry to `context.handled_entry_ids` so generic injection cannot overwrite it.
6. Return stable report fields including `kind`, write count, and touched offsets/pointers. Avoid environment-specific paths.
7. Add/update a focused fixture in `tests/fixtures/runtime_patches/` and assertions in
   `tests/test_injector_runtime_patch.py`.
8. Run dry-run and full injection for the selected language; inspect `runtime_patches` and skipped-owned counts in map.

## Boundaries

- Never add a patch when editing translation JSON or generic language-agnostic layout logic is sufficient.
- Never scan/write broad ROM ranges, rely on unchecked current bytes, silently accept mismatch, or alter another
  language's output.
- Do not copy another translator's patch implementation wholesale. Derive and validate this project's solution.
- Remove obsolete patches and tests when the behavior no longer requires runtime modification.

## Verification

```bash
python -m py_compile patches/<language>/<behavior>.py
python -m pytest tests/test_injector_runtime_patch.py
```

A valid build reports the patch once, owns the intended IDs, changes only expected offsets, and retains all normal
injector zero-loss safety counters.
