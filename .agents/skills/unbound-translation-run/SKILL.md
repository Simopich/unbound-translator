---
name: unbound-translation-run
description: Prepare, run, resume, and inspect Pokemon Unbound translation JSON. Use when asked to translate or resume translation, tune batch/workers/rate limits, use ChatGPT auth or an OpenAI-compatible API, filter ids/categories, or diagnose untranslated entries before controlfix.
---

# Unbound Translation Run

Translation starts from prepared JSON. Do not translate raw extraction output unless preparation has run.

## Workflow

1. Prepare:

```bash
./002_prepare_translation_text.py out/unbound-texts.json -o out/unbound-texts-prepared.json
```

2. Translate or resume:

```bash
./003_llm_translate.py out/unbound-texts-prepared.json --target it --api-base https://opencode.ai/zen/go/v1 --api-key YOUR_API_KEY --model your-model-name --workers 4 --batch-size 20 -o out/unbound-texts-it.json
```

Use `--resume` with the same input/output paths. Use `--rate-limit N` for strict API quotas. Use `--auth chatgpt` only after `codex login` or `CODEX_ACCESS_TOKEN`.

## Reference Priority

For every target-language translation addition, edit, or fix, research wording in this order:

1. PokeAPI localized data, then Bulbapedia and Pokémon Database.
2. The official FireRed ROM in the target language for exact in-game wording and control/layout conventions.

Use an already-known local ROM path when available (Italian: `out/red_ita.gba`). If no target-language FireRed ROM path
is known, ask the user for it before relying on FireRed as a reference. Preserve all semantic and control tokens from
the source entry.

## Checks

Confirm output JSON shape is preserved and `translated` fields are filled. If semantic/control tokens drift, inspect `lib/translation_tokens.py` behavior and retry with smaller batches or targeted includes.

Never use `--exclude-categories` expecting English copies; excluded entries are removed.
