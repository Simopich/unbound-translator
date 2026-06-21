# unbound-translator

`unbound-translator` is a project aimed at translating the game Pokémon Unbound into other languages.

## Preview

![Pokémon Unbound Italian Screenshot](resources/showcase.png)

The project was previously based on [Olcmyk/Meowth-GBA-Translator](https://github.com/Olcmyk/Meowth-GBA-Translator), but it quickly transitioned to custom scripts because of how that translator works. Meowth expands the ROM to 32 MB and writes all translated text into a dedicated area. That approach cannot work cleanly with Pokémon Unbound, because Unbound is already a 32 MB GBA ROM.

## How It Works

The current injector uses a hybrid strategy:

- Short translated strings that still fit their original slots are written in place.
- Longer pointer-based strings are relocated into free space inside the existing ROM.
- Free space is found by scanning for contiguous `0xFF` blocks.
- Script pointers are then updated to point at the relocated translated text.

This avoids expanding the ROM while still allowing longer translations where the original text was pointer-based.

## Free Space

This relocation approach was possible because Pokémon Unbound still has `1,102,003` bytes of free space available in the ROM. Those regions are detected by scanning for contiguous `0xFF` blocks and are used as targets for translated strings that no longer fit in their original locations.

## Workflow

Put the source ROM somewhere in the repo, for example:

```bash
rom/unbound.gba
```

The ROM used for this project has MD5:

```text
9cad8e771940e7f7094d13911552cef0
```

### 1. Extract Text

```bash
./extract_unbound_text.py rom/unbound.gba -o out/unbound-texts.json
```

Translate the generated JSON while preserving its structure. Each entry should keep its `original` field and receive a `translated` field.

### 2. Translate Text

```bash
./llm_translate.py out/unbound-texts.json \
  --target it \
  --api-base https://opencode.ai/zen/go/v1 \
  --api-key YOUR_API_KEY \
  --model your-model-name \
  --workers 4 \
  --batch-size 20 \
  -o out/unbound-texts-it.json
```

If the translation is interrupted, resume from the existing output JSON:

```bash
./llm_translate.py out/unbound-texts.json \
  --target it \
  --api-base https://opencode.ai/zen/go/v1 \
  --api-key YOUR_API_KEY \
  --model your-model-name \
  --workers 4 \
  --batch-size 20 \
  -o out/unbound-texts-it.json \
  --resume
```

The script uses an OpenAI-compatible chat completions API. It validates every returned batch. If a batch reaches the API output token limit, the script falls back to translating each entry individually; if a single-entry request still reaches the limit, it retries that entry with a compact single-item prompt and then a plain-text prompt using the same model. If the entry still cannot be translated because of the output token limit, the script prints a warning with the entry id, leaves that entry untranslated, and continues.

Translation progress is shown as a fixed `0` to `100%` progress bar based on the total translatable entries in the file, so resumed runs continue from the already completed percentage.

Transient API failures such as empty responses, non-JSON HTTP responses, invalid model JSON, missing choices, and server/network errors are retried up to 3 total attempts. Unauthorized requests, forbidden requests, rate-limit responses, other 4xx client errors, and partial or mismatched batch responses stop immediately.

For slow or free-tier APIs, use `--rate-limit` to cap total API calls per minute across all workers:

```bash
./llm_translate.py out/unbound-texts.json \
  --target it \
  --api-base https://opencode.ai/zen/go/v1 \
  --api-key YOUR_API_KEY \
  --model your-model-name \
  --workers 4 \
  --batch-size 20 \
  --rate-limit 30 \
  -o out/unbound-texts-it.json \
  --resume
```

For OpenCode, use `--api-base https://opencode.ai/zen/go/v1`; the script appends `/chat/completions` automatically. If the provider returns `API HTTP 403: error code: 1010`, the request is being rejected by the upstream gateway before reaching the model. The script sends a browser-like `User-Agent` by default, and it can be overridden with `--user-agent`.

For now, only Latin-script target languages are supported by the translation script because non-Latin languages will likely require a font patch. The prompt asks the model to use established official Pokémon terminology for moves, items, abilities, descriptions, and common franchise text. If the selected API/model has web or retrieval access, it is instructed to consult reputable Pokémon references such as Bulbapedia or Pokémon Database; plain OpenAI-compatible chat APIs usually do not browse the web by themselves.

### 3. Repair Control Codes

Run the control-fix script after translation:

```bash
./controlfix_translations.py out/unbound-texts-it.json \
  -o out/unbound-texts-it-controlfix.json \
  --source out/unbound-texts.json \
  --report out/controlfix-report.json
```

This step is still needed. It repairs common translation damage such as broken control codes, misplaced braces, outer quotes, and apostrophes.

### 4. Inject Translation

```bash
./hybrid_injector.py rom/unbound.gba out/unbound-texts-it-controlfix.json \
  -o out/unbound-translated.gba \
  --map-output out/hybrid-map.json
```

The output ROM will be written to:

```bash
out/unbound-translated.gba
```

## Ready Translations

In the `ready-translations` folder you can find pre-translated text in both JSON and BPS patch format. For now, only Italian is included.

The ready translations currently included in the repo were made using DeepSeek V4 Flash.

## Known Issues

This repo is in a very early stage, so bugs can occur. Some text may glitch out of the screen, or the screen may flash red or other colors in some places.

The scripts have been tested with the Italian language. Support for other languages can be added, for example German.

## TODO

- Add pre-made translations for other languages
- Polishing

## Notes

- The injector does not expand the ROM.
- Pointer-based text may be relocated into existing `0xFF` free space.
- Fixed-size text that cannot be relocated may still need shorter translations.
- `hybrid-map.json` records relocation decisions and injection stats.
- Issues and pull requests are welcome.
- Yes, this repo is vibecoded, I'm sorry but I don't have time to manually work on this...
