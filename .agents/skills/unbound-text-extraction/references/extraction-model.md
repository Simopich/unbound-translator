# Extraction Model

Read this before changing extractor tables, pointer predicates, categories, IDs, or entry metadata.

## Baseline

- Expected source ROM MD5: `9cad8e771940e7f7094d13911552cef0`.
- Healthy baseline: `23,268` unique-address entries, including `10,828` `scripts`, `3,516` strict aligned
  `pointer_texts`, `82` `mission_descriptions`, `85` `mission_names`, and `14` `plain_scripts`.
- ROM offsets use `0x...`; GBA pointers are little-endian `0x08000000 + ROM offset`.
- Use `lib/pcs_text.py` for every decode/encode operation.

## Source Order

`001_extract_unbound_text.py` merges sources in this order:

1. Fixed slots through `FixedTable`.
2. Sequential terminated strings through `SequentialTable`.
3. Structured pointer arrays through `PointerTable`.
4. Explicit `MANUAL_TEXT_TABLES` addresses.
5. Narrow `MANUAL_TEXT_RANGES` PCS banks.
6. Script and vetted structured pointers in `scan_pointer_texts`.
7. Strict aligned GBA pointers accepted by language/data-noise filters.
8. `POST_POINTER_MANUAL_TEXT_RANGES`.
9. Duplicate-address merge: specific ownership wins and all pointer sources survive.
10. Optional orphan scan, used as audit evidence only.

## Entry Contract

- `id`: address-stable; scripts use `scr_<ROMADDR>`, tables/manual entries use
  `tbl_<category>_<table_index>_<ROMADDR>`.
- `category`: choose the closest existing category; add one only when ownership or downstream behavior differs.
- `address`: uppercase hexadecimal ROM offset.
- `original`: lossless PCS text including engine tokens and layout markers.
- `byte_length`: original span/slot capacity.
- `is_pointer_based`: true only for a usable pointer owner.
- `pointer_sources`: exact GBA-pointer source offsets, possibly empty.
- `table_name` and `table_index`: structured/manual ownership metadata.
- `no_relocation`: only for known fragile pointer-source ranges.

Downstream filtering, resume state, controlfix, maps, and injection depend on this contract.

## Special Cases

- There are 293 ability names but only the first 255 ability-description pointers decode as valid text. Do not extend
  the description table to the name count.
- `plain_scripts` are full-screen text and later require plain line breaks, not dialogue continuation controls.
- High-bank pointer sources in `0x1E00000-0x1F00000` and `0x1FB0000-0x1FC0000` can target the dedicated
  `0x1EE0000-0x1FB0000` text bank.
- Mission titles use the exact `loadpointer 0, title; call mission_handler` signature. Hero/Heroine variants explain
  85 titles for 84 missions; two side missions reuse description records.
- `NO_RELOCATION_POINTER_SOURCE_RANGES` marks fragile routine text. Do not make these entries relocatable merely to fit
  longer translations.
