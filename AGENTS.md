# AGENTS.md

This repository is `unbound-translator`, a Python toolchain for translating Pokemon Unbound into other languages.

## Project Context

- Pokemon Unbound is already a 32 MB GBA ROM, so the old Meowth-GBA-Translator approach of expanding the ROM to 32 MB and writing all text into one dedicated area is not suitable here.
- The project now uses custom scripts and a local PCS text codec in `lib/pcs_text.py`.
- Text relocation works because the ROM has `1,102,003` bytes of detected free space. The injector finds this space by scanning contiguous `0xFF` blocks.
- The injection strategy is hybrid: short translated text is written in place, and longer pointer-based text is relocated into detected free space with script pointers updated to the new addresses.
- `005_hybrid_injector.py` defaults to `--pointer-policy oversized`; use `--pointer-policy changed` only for experiments that intentionally relocate every changed pointer string.
- Some extracted entries have `no_relocation: true` for fragile engine/common routine text, including receive-item, Cube, PC, and field routine pointers. Keep these translations short enough for their original `byte_length`; the injector forces them in place and reports `No-reloc truncated` if they do not fit.
- The source ROM used by this project has MD5 `9cad8e771940e7f7094d13911552cef0`.

## Main Scripts

- `001_extract_unbound_text.py`: extracts text from the ROM into JSON. The expected output shape is a JSON object containing an `entries` array, though some utilities also tolerate older `tables` and `free_texts` shapes.
- `002_prepare_translation_text.py`: adds layout-free `translation_source` fields to extracted JSON while preserving each entry's original ROM text. It removes layout markers and replaces semantic/control tokens in `translation_source` with readable placeholders recorded in `semantic_token_placeholders`.
- `003_llm_translate.py`: translates prepared JSON through an OpenAI-compatible chat completions API or a Codex CLI ChatGPT login. It preserves the JSON shape, fills `translated` fields, supports `--resume`, restores semantic/control placeholders to real tokens, validates returned batches, and retries model output that drops/adds protected placeholders or tokens.
- `004_controlfix_translations.py`: repairs translated control codes, quote tokens, apostrophes, and other formatting damage caused by translation. It also recomputes post-translation text wrapping/layout for dialogue and description-like text.
- `005_hybrid_injector.py`: injects translated text into the ROM using in-place writes and pointer relocation into free `0xFF` space.
- `lib/pcs_text.py`: local PCS charmap and codec. Do not reintroduce Meowth charmap dependencies.
- `lib/translation_tokens.py`: shared layout and semantic/control token helpers used by prepare, translation, and layout repair code.

## Workflow

Use this baseline flow:

```bash
./001_extract_unbound_text.py rom/unbound.gba -o out/unbound-texts.json
./002_prepare_translation_text.py out/unbound-texts.json -o out/unbound-texts-prepared.json
./003_llm_translate.py out/unbound-texts-prepared.json --target it --api-base https://opencode.ai/zen/go/v1 --api-key YOUR_API_KEY --model your-model-name --workers 4 --batch-size 20 -o out/unbound-texts-it.json
./004_controlfix_translations.py out/unbound-texts-it.json -o out/unbound-texts-it-controlfix.json --source out/unbound-texts-prepared.json --report out/controlfix-report.json
./005_hybrid_injector.py rom/unbound.gba out/unbound-texts-it-controlfix.json -o out/unbound-translated.gba --map-output out/hybrid-map.json
```

When resuming LLM translation, use the same input and output paths with `--resume`.

## Extraction Notes

- A healthy baseline extraction currently reports about `15,040` entries, with about `8,881` `scripts` entries and `14` `plain_scripts` entries.
- Ability names have 293 entries, but `data.abilities.descriptions` only has 255 valid text pointers. Do not expand `ability_descriptions` to match the ability-name count; entries after index 254 decode non-text data as garbage.
- Opening narration and other full-screen script text is categorized as `plain_scripts` by the extractor. These entries still use `scr_` ids, but controlfix must wrap them with plain line breaks instead of dialogue `\l` controls.
- `Pointer text rejected` in extractor output means candidate pointers were checked and discarded because they did not decode as plausible text. It does not mean translations failed.
- Do not blindly accept all rejected pointer candidates. If text is missing, add or refine the pointer-source pattern for the specific game system that owns that text.
- Known strings such as `Choose a character.` and `Choose a skin tone.` are extracted through the script/menu `0x67` pointer pattern.
- Manual extraction uses explicit addresses plus narrow vetted PCS ranges for contiguous menu/UI blocks and fixed text banks. This includes item descriptions, battle messages, Pokemon summary text, mission log notifications/descriptions, and the newer Trainer Card profile labels and month names at `0x1F81E44-0x1F81EE5`. Entries can include pointer sources when exact GBA pointers to those strings are present, which lets important menus such as Cube V3, save, Trainer Card, and game settings relocate instead of being fixed-size only.
- Use `001_extract_unbound_text.py rom/unbound.gba -o out/unbound-texts.json --audit-menu-text` when auditing menu coverage during extraction. `found_but_not_extracted` means extractor coverage needs a new table/address; `not_found_as_pcs_text` likely means graphical/tile text, compressed data, or custom UI encoding.
- Extraction should remain as-is/lossless. Use `002_prepare_translation_text.py` for translation cleanup instead of changing extracted `original` strings.

## Translation Notes

- `003_llm_translate.py` currently supports Latin-script target languages only: `de`, `en`, `es`, `fr`, `it`, `pt`, and `pt-br`.
- Non-Latin target languages are out of scope for now because they likely require a font patch.
- `002_prepare_translation_text.py` adds `translation_source`; it removes layout markers such as actual line breaks, `\n`, `\l`, `\p`, and `\pn`. It keeps real semantic/control tokens in `original`, but replaces them in `translation_source` with readable placeholders such as `[player-name-1]`, `[buffer1-2]`, `[color-red-3]`, `[button-icon-4]`, and `[control-code-5]`.
- Semantic/control tokens are protected game-engine tokens that must survive translation exactly and in the same count. Examples include `[player]`, `[buffer1]`, `[red]`, `\CC12`, `\btn01`, `\pk`, `\mn`, `\qo`, `\qc`, and `{B4}`.
- `003_llm_translate.py` uses `translation_source` when present. After each model response it checks placeholder counts, restores placeholders through `semantic_token_placeholders`, then checks semantic/control token counts and retries if a placeholder or token is missing, duplicated, or invented, or if the model adds layout markers.
- `003_llm_translate.py` prints a warning when it falls back to a single-entry prompt because that path has less context and can reduce translation accuracy.
- `003_llm_translate.py --exclude-categories` removes matching entries from the output JSON entirely. It does not copy them as English translations.
- `003_llm_translate.py --include-ids`, `--include-id-ranges`, `--include-categories`, and `--include-category-prefixes` keep only matching entries in the output JSON. This is preferred for small debug ROMs.
- `003_llm_translate.py --priority-order --limit N` is intended for debug builds: it translates only the first `N` missing entries after priority sorting, favoring menu/UI/common/short text.
- The LLM prompt asks for established official Pokemon terminology and may ask models with web/retrieval access to consult reputable references such as Bulbapedia or Pokemon Database. Plain OpenAI-compatible chat APIs usually do not browse by themselves.
- To use a ChatGPT subscription login instead of an API key, run `codex login` first or provide `CODEX_ACCESS_TOKEN`, then run `003_llm_translate.py` with `--auth chatgpt`. This delegates batches to `codex exec`; `--model` is optional in this mode and overrides the Codex default model when provided.
- For OpenCode, use `--api-base https://opencode.ai/zen/go/v1`; `003_llm_translate.py` appends `/chat/completions` automatically. `API HTTP 403: error code: 1010` means the upstream gateway rejected the HTTP request before the model handled it. The script sends a browser-like `User-Agent` by default and exposes `--user-agent` for overrides.
- Translation progress is shown as a fixed `0` to `100%` bar based on total translatable entries in the full file, not only the entries translated in the current run. During `--rate-limit` sleeps, the bar temporarily shows a shared `waiting for rate limit reset` countdown and clears it after waiting.
- `003_llm_translate.py` retries transient API failures up to 3 total attempts. It does not retry unauthorized, forbidden, rate-limit, other 4xx client errors, or partial/mismatched translation batches.
- If a batch reaches the API output token limit, `003_llm_translate.py` falls back to translating entries individually. If a single-entry request still reaches the limit, it uses a compact single-item JSON prompt and then a plain-text prompt with the same model. If the entry still cannot be translated because of the output token limit, it prints a warning with the entry id, leaves the entry untranslated, and continues.
- Use `--rate-limit N` to cap total API calls per minute across all workers and retry attempts. Use `0` to disable the limiter.
- `004_controlfix_translations.py` wraps translated text by default for `scripts`, `plain_scripts`, `move_descriptions`, `ability_descriptions`, and `trade_messages`. Normal `scripts` entries are wrapped into dialogue pages with `\n`, `\l`, and paragraph breaks. `plain_scripts` entries are full-screen script text and must use plain line breaks. Descriptions are wrapped with regular line breaks. Compact multi-row menu labels keep their original row breaks so choices such as `Yes\nNo` remain selectable on separate rows. Tune with `--wrap-width`, `--description-wrap-width`, and `--wrap-categories`, or disable with `--no-wrap`.
- Always run `004_controlfix_translations.py` after LLM translation before injecting.
- During injection, `plain_scripts` blank lines are encoded as repeated newline bytes (`0xFE 0xFE`) instead of the paragraph/prompt byte (`0xFB`), because the full-screen renderer shows the bottom arrow and can overflow when it receives `0xFB`.

## Debug Workflow

Use this to test a small manually whitelisted ROM build:

```bash
./001_extract_unbound_text.py rom/unbound.gba -o out/debug-unbound-texts.json
./002_prepare_translation_text.py out/debug-unbound-texts.json -o out/debug-unbound-texts-prepared.json
./003_llm_translate.py out/debug-unbound-texts-prepared.json --target it --api-base https://opencode.ai/zen/go/v1 --api-key YOUR_API_KEY --model your-model-name --workers 4 --batch-size 20 --include-ids scr_07448,scr_05226,scr_05227,scr_07449 --include-id-ranges scr_09019-scr_09114 --include-category-prefixes menu_ -o out/debug-unbound-texts-it.json --overwrite
./004_controlfix_translations.py out/debug-unbound-texts-it.json -o out/debug-unbound-texts-it-controlfix.json --source out/debug-unbound-texts-prepared.json --report out/debug-controlfix-report.json
./005_hybrid_injector.py rom/unbound.gba out/debug-unbound-texts-it-controlfix.json -o out/debug-unbound-translated.gba --map-output out/debug-hybrid-map.json
```

## Codex Project Config

- Project Codex config lives in `.codex/config.toml`. It uses low verbosity, medium reasoning, workspace-write sandboxing, on-request approvals, disabled default web search, and subagent limits of 6 threads, depth 1, and 1800 seconds per job.
- Custom project subagents live in `.codex/agents/`. They are intentionally narrow and terse; use them when explicitly asked to delegate or run parallel agent work.
- Repo skills live in `.agents/skills/`. Use them for repeated workflows: `unbound-menu-extraction`, `unbound-debug-build`, `unbound-translation-run`, `unbound-layout-controlfix`, `unbound-injection-qa`, and `unbound-docs-sync`.
- Available subagents:
  - `extractor-scout`: missing ROM text/menu extraction coverage, PCS hits, pointer sources, and vetted range proposals.
  - `pcs-codec-guardian`: PCS charmap, terminators, control bytes, raw escapes, and encode/decode round trips.
  - `translation-token-auditor`: semantic/control token preservation across prepare, translation, and controlfix.
  - `layout-reviewer`: wrapping and overflow risks for dialogue, plain scripts, descriptions, and menus.
  - `injector-safety`: hybrid injection risks, relocation, free-space allocation, pointer updates, and map output.
  - `localization-glossary`: Pokemon terminology, UI wording, casing, placeholders, and repeated-string consistency.
  - `pipeline-qa`: compact verification runs and metrics for extraction, controlfix, injection, and debug builds.
  - `docs-sync`: README/AGENTS drift; this agent must also compact `AGENTS.md` by merging duplicates and removing stale detail when docs grow.

## Ready Translations

- `ready-translations/` contains pretranslated assets in JSON and BPS patch format.
- Only Italian is included for now.
- The included ready translations were made using DeepSeek V4 Flash.

## Known Issues

- The repo is in a very early stage.
- Some text may overflow or glitch out of screen.
- Some screens may flash red or other colors.
- The scripts have mainly been tested with Italian. Other Latin-script languages can be added and tested.

## Maintenance Rules

- When an important change is made to scripts, workflow, output JSON structure, supported languages, ROM assumptions, or repository layout, update both `AGENTS.md` and `README.md` in the same change.
- Keep command examples in `README.md` and `AGENTS.md` aligned.
- Do not add new Meowth runtime dependencies.
- Preserve existing user changes in the working tree. Do not revert unrelated edits.
- Prefer small, focused changes and verify Python scripts with `python3 -m py_compile` when editing them.
