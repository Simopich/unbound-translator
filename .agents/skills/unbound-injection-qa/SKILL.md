---
name: unbound-injection-qa
description: Build or audit Pokemon Unbound translated ROMs and diagnose relocation safety. Use for injection, free-space/map analysis, pointer mismatches, corruption, freezes linked to relocated text, or in-place-versus-relocated behavior; use unbound-relocation-compaction for bulk ordinary relocation fitting and unbound-capacity-curation for total-capacity or rigid-slot failures.
---

# Unbound Injection QA

## Inputs And Output

- Input ROM must match MD5 `9cad8e771940e7f7094d13911552cef0`.
- Input JSON must already be controlfixed. Release input is `ready-translations/<language>.json`.
- Output is a translated ROM plus map report. Preserve the source ROM; never commit or release ROM files.

## Build

```bash
python 005_hybrid_injector.py rom/unbound.gba ready-translations/it.json -o out/unbound-translated-it.gba --target-lang it --map-output out/hybrid-map-it.json
```

Use `--dry-run` for capacity/pointer preflight. Use OS-provided temporary storage or `out/debug-*` artifacts; never
assume `/tmp` exists. Unfitted translations remain original by default and appear in the map; add
`--fail-on-no-space` for strict capacity audits. Never use `--allow-lossy-fit` for a release.

## Safety Model

- Generic writes begin only after every applied relocation candidate has a validated source and allocated destination.
  Candidates without space and oversized fixed slots stay unchanged and are reported, never truncated.
- PCS text is byte-addressable; alignment 1 is valid.
- `vetted_ff` destinations must remain inside `VETTED_FREE_SPACE_RANGES` and outside
  `FREE_SPACE_EXCLUDE_RANGES`.
- `reclaimed_script_text` may contain only `scripts` literals fully inside `0x1EE0000-0x1FB0000` whose references are
  all direct script `0x0F`/`0x67` operands. Whole-ROM scanning must find no hidden exact/interior pointers; subtract
  pointer operands, overlapping entries, and non-owned ranges.
- Never reclaim structured tables, Pokédex text, menus, abilities, battle data, generic `pointer_texts`, or arbitrary
  old slots.
- `no_relocation` text must fit in place through complete token-safe wording, normally `translated_fixed`.

## Diagnosis

Inspect map/report data for input count, free/used/remaining bytes, relocated and deduplicated entries, pointer writes,
runtime patches, fixed overrides, `missing_relocations`, `missing_fixed_slots`, skips, and per-category
no-space/truncation data. Trace suspicious entry IDs through their original address, pointer sources, destination,
storage kind, and encoded size.

For difficult Unbound-specific behavior, investigate locally first. Optionally compare against
`out/working_fr.gba` or `https://github.com/AntonyKervazoCanut/gba_translator` as behavioral evidence only; do not copy
its architecture or ROM.

## Success Criteria

A release-capable build has zero missing relocation candidates, pointer mismatches, implausible pointers, encode
errors, lossy fixed/no-relocation truncations, and ability compactions. Report ROM and map paths plus decisive counts.

For relocation-compaction QA, compare before/after maps and record relocation count, relocated bytes, and remaining free
bytes. Require every remaining relocation ID to have documented complete blocked wording, except exact official fixture
text deliberately restored after tests. Count-only comparison is insufficient: compare actual ID sets and report
remaining categories. Build the full ROM after dry-run; keep ROM artifacts private under `out/`.
