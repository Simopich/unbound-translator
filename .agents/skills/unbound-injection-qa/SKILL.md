---
name: unbound-injection-qa
description: Verify Pokemon Unbound hybrid injection safety. Use when asked to inject a translated ROM, inspect relocation/free-space behavior, debug corrupted ROM output, check pointer updates, map output, fixed-size overflow, or in-place versus relocated writes.
---

# Unbound Injection QA

Run injection only on controlfixed JSON.

Diagnose and design within this repository first. For difficult Unbound-specific pointer, protected-region, allocator,
or corruption cases, optionally double-check findings against the separate, more advanced
`https://github.com/AntonyKervazoCanut/gba_translator` project and local known-working `out/working_fr.gba`. Use them
for
behavioral comparison, debugging leads, or inspiration; do not copy its architecture or patches by default, add it as
a dependency, or copy its ROM. `/tmp` clones are ephemeral.

## Workflow

```bash
./005_hybrid_injector.py rom/unbound.gba out/unbound-texts-it-controlfix.json -o out/unbound-translated.gba --map-output out/hybrid-map.json
```

For experiments, write ROM/map outputs to `/tmp`.

## Checks

Inspect map/report data for relocated count, in-place count, skipped entries, free-space use, overlapping writes, and entries that could not fit. Pointer-based longer text may relocate; fixed-size non-pointer text needs shorter translations or new pointer coverage.

Preserve the source ROM. Do not run destructive git or file cleanup commands without explicit request.
