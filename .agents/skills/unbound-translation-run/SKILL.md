---
name: unbound-translation-run
description: Prepare, run, resume, or diagnose Pokemon Unbound translation JSON. Use for PokeAPI localization, LLM translation, authentication, workers/batches/rate limits, filters, untranslated entries, official terminology, or manual wording fixes before controlfix; do not use for layout-only repair, injection safety, or ROM runtime patches.
---

# Unbound Translation Run

## Inputs And Output

- Input must be prepared JSON with `translation_source` and protected placeholder metadata. Never translate raw
  extraction output directly.
- Output preserves the input JSON shape and fills `translated`; it is not injection-ready until controlfix runs.
- Supported targets are Latin-script `de`, `en`, `es`, `fr`, `id`, `it`, `pt`, and `pt-br`.

## Workflow

```bash
python 002_prepare_translation_text.py out/unbound-texts.json -o out/unbound-texts-prepared.json

python 003_llm_translate.py out/unbound-texts-prepared.json --target it --api-base https://opencode.ai/zen/go/v1 --api-key YOUR_API_KEY --model your-model-name --workers 4 --batch-size 20 -o out/unbound-texts-it.json
```

Use `--resume` with the same input/output. Use `--rate-limit N` for a global request cap. Use `--auth chatgpt` only
after `codex login` or with `CODEX_ACCESS_TOKEN`.

## PokeAPI First

PokeAPI localization precedes LLM fallback for Pokemon names/species/descriptions, moves, items, abilities, types,
natures, and habitats. Existing translations take precedence. Numeric IDs/slugs plus normalized English matching guard
against placeholder/reordered ROM rows; unmatched, ROM-exclusive, tokenized, or unavailable records fall back to LLM.

Cache responses under `.cache/pokeapi` and keep that directory uncommitted. Tune with `--pokeapi-workers`,
`--pokeapi-cache`, `--pokeapi-timeout`, and `--pokeapi-base`; use `--no-pokeapi` only for explicit diagnosis.

## Filtering

- `--include-ids`, `--include-id-ranges`, `--include-categories`, and `--include-category-prefixes` keep only matching
  entries in output and are suitable for debug builds.
- `--priority-order --limit N` translates the first missing entries after UI/common priority sorting.
- `--exclude-categories` removes matching entries; it does not copy English text into output.

## Localization Rules

For every manual addition/fix, research wording in this order:

1. PokeAPI localized data.
2. Bulbapedia and Pokemon Database.
3. Official target-language FireRed ROM for exact in-game wording/layout (`out/red_ita.gba` for Italian).

Preserve all semantic/control placeholders and restored engine tokens exactly. Prefer established official terminology;
do not add language-specific replacement branches to shared Python scripts.

## Verification And Failure Handling

- Confirm output shape/count and filled `translated` values.
- Validate placeholder counts, semantic/control tokens, and absence of model-invented layout controls.
- Retry malformed batches with smaller batches or targeted IDs; do not accept partial/mismatched model output.
- API output-limit fallbacks may reach single-entry/plain-text prompts. If a final single entry still fails, leave it
  untranslated and report its ID rather than inventing/truncating text.
- Run `004_controlfix_translations.py` before injection.
