# Extraction Audit Playbook

Read this when locating a visible missing string, triaging PCS hits, or choosing an extraction rule.

## Commands

Baseline:

```bash
python 001_extract_unbound_text.py rom/unbound.gba -o out/audit-unbound-texts.json
```

Focused audit:

```bash
python 001_extract_unbound_text.py rom/unbound.gba -o out/audit-unbound-texts.json --audit-menu-text --audit-string "Missing text" --audit-output out/unbound-text-audit.json
```

For many queries, use `--audit-strings-file`; blank and `#` lines are ignored. Use `--audit-no-case-variants` when case
matters. Use `--include-orphans` and `--all-pointers` only as noisy discovery aids.

## Triage

- `found_and_extracted`: inspect the existing entry and route to translation/layout/injection; do not duplicate it.
- `found_but_not_extracted`: identify its table, pointer source, script operand, record, or bounded bank.
- `not_found_as_pcs_text`: verify spelling/case/tokens, then investigate graphical, compressed, custom-encoded, or
  dynamically assembled text.

An audit hit inside an existing entry's span is already covered even when it is not at the entry start.

## Choose The Narrowest Owner

- Fixed-width inline record: `FIXED_TABLES`; set slot/stride accurately.
- Consecutive terminated strings: `SEQUENTIAL_TABLES`; require verified start/count and clean advancement.
- Stable 32-bit pointer array: `POINTER_TABLES`; preserve invalid rows instead of guessing.
- Few isolated addresses: `MANUAL_TEXT_TABLES`.
- Contiguous vetted PCS bank: `MANUAL_TEXT_RANGES` or `POST_POINTER_MANUAL_TEXT_RANGES` with precise half-open bounds.
- Script/dynamic pointer pattern: a constrained source predicate requiring opcode, structure, source bank, and target.
- Orphan-only hit: keep as evidence until a real owner is proven.

## Evidence Checklist

- Visible English text, screen/event, and whether static, dynamic, or assembled.
- PCS hit offsets and decoded context.
- Nearby existing entry ID/category/address.
- Pointer sources, table shape, record stride, or bounded bank evidence.
- Required category/layout behavior.
- Relocation needs and exact pointer-source evidence.

Useful inspection:

```bash
jq -r '.entries[] | select(.original | contains("Missing text")) | [.id, .category, .address, (.pointer_sources | join(","))] | @tsv' out/audit-unbound-texts.json
rg -n "FIXED_TABLES|SEQUENTIAL_TABLES|POINTER_TABLES|MANUAL_TEXT|scan_pointer_texts|is_.*pointer|NO_RELOCATION" 001_extract_unbound_text.py
```
