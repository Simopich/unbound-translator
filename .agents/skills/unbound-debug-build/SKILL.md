---
name: unbound-debug-build
description: Build a focused Pokemon Unbound test ROM from selected IDs or categories. Use for translation whitelists, rapid menu/UI checks, or limited extraction-to-injection verification; do not use for release artifacts, capacity failures, or bugs that require the complete translation.
---

# Unbound Debug Build

Use this for quick feedback without translating the whole ROM. Use OS-provided temporary storage or `out/debug-*`
artifacts; never assume a POSIX `/tmp` directory exists.

## Inputs And Output

- Input ROM: `rom/unbound.gba`, MD5 `9cad8e771940e7f7094d13911552cef0`.
- Selection: user-provided IDs/ranges/categories. Do not invent a narrow selection when the bug may depend on unrelated
  runtime text.
- Output: focused translated ROM plus injector map. Never modify or overwrite the source ROM.

## Workflow

1. Extract and prepare:

```bash
python 001_extract_unbound_text.py rom/unbound.gba -o out/debug-unbound-texts.json
python 002_prepare_translation_text.py out/debug-unbound-texts.json -o out/debug-unbound-texts-prepared.json
```

2. Translate a whitelist. Default to user-provided IDs/ranges; for menu checks include
   `--include-category-prefixes menu_`.

```bash
python 003_llm_translate.py out/debug-unbound-texts-prepared.json --target it --api-base https://opencode.ai/zen/go/v1 --api-key YOUR_API_KEY --model your-model-name --workers 4 --batch-size 20 --include-category-prefixes menu_ -o out/debug-unbound-texts-it.json --overwrite
```

3. Controlfix and inject:

```bash
python 004_controlfix_translations.py out/debug-unbound-texts-it.json -o out/debug-unbound-texts-it-controlfix.json --source out/debug-unbound-texts-prepared.json --report out/debug-controlfix-report.json
python 005_hybrid_injector.py rom/unbound.gba out/debug-unbound-texts-it-controlfix.json -o out/debug-unbound-translated.gba --map-output out/debug-hybrid-map.json
```

## Rules

Always run `004_controlfix_translations.py` before injection. Preserve user output files unless explicitly asked to
overwrite them. Keep protected tokens and control layout intact.

## Verification

- Injector must report zero pointer mismatches, encode errors, and truncations.
- Inspect the map for selected entries and confirm they were patched or relocated as expected.
- Report ROM and map paths. State clearly which IDs/categories the focused build does not cover.
