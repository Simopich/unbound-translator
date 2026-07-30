# AGENTS.md

This repository is `unbound-translator`, a Python toolchain for translating Pokemon Unbound into other languages.

## Project Context

- Pokemon Unbound is already a 32 MB GBA ROM, so the old Meowth-GBA-Translator approach of expanding the ROM to 32 MB and writing all text into one dedicated area is not suitable here.
- The project now uses custom scripts and a local PCS text codec in `lib/pcs_text.py`.
- Text relocation uses vetted writable spans inside the ROM's contiguous `0xFF` blocks. The spans were validated against
  a known-working build so engine-owned bytes at apparent free-run edges are not overwritten.
- The injection strategy is hybrid: short translated text is written in place, and longer pointer-based text is
  relocated first into vetted `0xFF` spans, then into safely reclaimed old text slots, with every pointer updated.
- `005_hybrid_injector.py` defaults to `--pointer-policy oversized`; use `--pointer-policy changed` only for experiments that intentionally relocate every changed pointer string.
- Relocation is transactional. Before generic writes, the injector validates every pointer source, proves reclaimable
  source slots with a whole-ROM raw-pointer scan, and allocates every destination. It aborts if any entry cannot
  fit; successful map output records vetted/reclaimed capacity, usage, storage kind, and loss counters.
- Some extracted entries have `no_relocation: true` for fragile engine/common routine text, including receive-item,
  Cube, PC, and field routine pointers. Use a token-safe `translated_fixed` value when the complete `translated` text
  does not fit. Fixed truncation and ability compaction abort by default; `--allow-lossy-fit` explicitly restores legacy
  lossy behavior for diagnostics only.
- The source ROM used by this project has MD5 `9cad8e771940e7f7094d13911552cef0`.

## External Double-Checks

- This is an independent project with its own architecture and ideas. Investigate problems locally and design fixes
  around this repository's code first. Do not copy another translator's approaches, architecture, patches, or workflow
  by default.
- [AntonyKervazoCanut/gba_translator](https://github.com/AntonyKervazoCanut/gba_translator) is a more advanced separate
  project that can be consulted as an optional second opinion. Use it to double-check assumptions, compare proven game
  behavior, find debugging leads, or inspire a solution when useful. Evaluate every idea against this project's needs
  and implement it independently.
- Known local comparison ROMs are `out/working_fr.gba` (working French Unbound build from that translator) and
  `out/red_ita.gba` (official Italian FireRed). ROM files are local/ignored assets and must never be committed or
  released. A clone under `/tmp` is ephemeral; use the GitHub URL in a new task.
- For translation wording, retain the separate priority in Translation Notes: official PokeAPI/localized references,
  then Bulbapedia/Pokémon Database, then target-language FireRed. The French translator/build is only an optional
  behavioral comparison, not a translation authority.

## Main Scripts

- `001_extract_unbound_text.py`: extracts text from the ROM into JSON. The expected output shape is a JSON object containing an `entries` array, though some utilities also tolerate older `tables` and `free_texts` shapes.
- `002_prepare_translation_text.py`: adds layout-free `translation_source` fields to extracted JSON while preserving each entry's original ROM text. It removes layout markers and replaces semantic/control tokens in `translation_source` with readable placeholders recorded in `semantic_token_placeholders`.
- `003_llm_translate.py`: prefills official localized names/flavor text from cached PokeAPI v2 responses, then
  translates unmatched prepared JSON through an OpenAI-compatible chat completions API or a Codex CLI ChatGPT login. It
  preserves the JSON shape, fills `translated` fields, supports `--resume`, restores semantic/control placeholders to
  real tokens, validates returned batches, and retries model output that drops/adds protected placeholders or tokens.
- `004_controlfix_translations.py`: repairs translated control codes, quote tokens, apostrophes, and other formatting damage caused by translation. It also recomputes post-translation text wrapping/layout for dialogue and description-like text.
- `005_hybrid_injector.py`: injects translated text with transactional in-place writes and pointer relocation. It uses
  vetted `0xFF` spans first, then reclaims an old text slot only when a whole-ROM raw-pointer scan exactly matches
  its extracted pointer sources. It excludes engine-owned FF storage (`0x16586A-0x166C9A` and
  `0x19A837-0x19B86A`), battle graphics (`0x230000-0x500000`), and CFRU/Unbound reserved upper-ROM data
  (`0x1000000-0x1FE0000`), keeps eight-byte margins, intersects detected runs with `lib/unbound_free_space.py`, and
  only repoints aligned or verified script operands. All relocation destinations are allocated before generic writes;
  no-space aborts the build. It discovers and applies every `patches/<target-lang>/*.py` runtime patch in filename order.
  Runtime-patch paths in map output always use POSIX `/` separators so reports are stable on Windows and Unix.
- `006_decontrolfix_translations.py`: removes controlfix layout from translated JSON for manual re-editing, preserving the controlfixed value in `translated_controlfixed` by default.
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

When resuming LLM translation, use the same input and output paths with `--resume`. To manually edit already-controlfixed translations, run `./006_decontrolfix_translations.py out/unbound-texts-it-controlfix.json -o out/unbound-texts-it-editable.json`, edit `translated`, then rerun `004_controlfix_translations.py` before injecting.

## Extraction Notes

- A healthy expanded baseline currently reports `23,268` unique-address entries, including `10,828` `scripts`, `3,516`
  strict aligned `pointer_texts`, `82` `mission_descriptions`, `85` `mission_names`, and `14` `plain_scripts`. The
  extractor merges duplicate
  addresses, preferring specific table/category ownership and preserving all pointer sources.
- Ability names have 293 entries, but `data.abilities.descriptions` only has 255 valid text pointers resolving to 252
  unique strings. Do not expand `ability_descriptions` to match the ability-name count; entries after index 254 decode
  non-text data as garbage.
- Opening narration and other full-screen script text is categorized as `plain_scripts` by the extractor. These entries still use `scr_` ids, but controlfix must wrap them with plain line breaks instead of dialogue `\l` controls.
- `Pointer text rejected` in extractor output means candidate pointers were checked and discarded because they did not decode as plausible text. It does not mean translations failed.
- Do not blindly accept all rejected pointer candidates. If text is missing, add or refine the pointer-source pattern for the specific game system that owns that text.
- Known strings such as `Choose a character.` and `Choose a skin tone.` are extracted through the script/menu `0x67` pointer pattern.
- Manual extraction uses explicit addresses plus narrow vetted PCS ranges for contiguous menu/UI blocks and fixed text
  banks. Structured pointer tables now include legacy move descriptions, all item-record description pointers,
  extra-form Pokédex descriptions, and Pokédex form names. Extracted ids are address-stable: script ids use
  `scr_<ROMADDR>`, and table/manual ids use `tbl_<category>_<table_index>_<ROMADDR>`. The extractor also accepts
  structured high-bank sources in `0x1E00000-0x1F00000` and `0x1FB0000-0x1FC0000` targeting `0x1EE0000-0x1FB0000`, plus
  unaligned trainer/link-record pointer fields. By default it additionally checks every aligned GBA pointer with a
  strict language/data-noise filter, excludes trainer structs and adjacent binary data at `0x23EAC8-0x246E00`, and
  categorizes newly discovered strings as `pointer_texts`; use
  `--no-aligned-pointer-text` only to reproduce the narrower legacy scan. Mission title pointers remain `mission_names`;
  controlfix caps their visible width. Exact pointer sources allow relocation where safe.
- Use `001_extract_unbound_text.py rom/unbound.gba -o out/unbound-texts.json --audit-menu-text` when auditing menu coverage during extraction. `found_but_not_extracted` means extractor coverage needs a new table/address; `not_found_as_pcs_text` likely means graphical/tile text, compressed data, or custom UI encoding.
- Extraction should remain as-is/lossless. Use `002_prepare_translation_text.py` for translation cleanup instead of changing extracted `original` strings.

## Translation Notes

- `003_llm_translate.py` currently supports Latin-script target languages only: `de`, `en`, `es`, `fr`, `it`, `pt`, and `pt-br`.
- Before LLM batching, `003_llm_translate.py` uses PokeAPI v2 for `pokemon_names`, `pokedex_species`,
  `pokedex_descriptions`, `move_names`, `move_descriptions`, `item_names`, `item_descriptions`, `ability_names`,
  `ability_descriptions`, `type_names`, `nature_names`, and `habitat_names`. Existing translations take precedence.
  Category-specific numeric IDs/slugs handle ROM placeholder rows and reordered tables; failed numeric name lookups fall
  back through cached PokeAPI resource lists, names require a normalized English-source match, genera accept the omitted
  `Pokémon` suffix, and flavor text requires matching English text plus version/version-group. Protected-token entries,
  ROM-exclusive records, missing localizations, and API/network failures fall back to the LLM. It uses 8 parallel
  workers by default, deduplicates concurrent lookups, and shows a live progress bar before LLM batching. Responses
  persist in `.cache/pokeapi`, which Git ignores; tune with `--pokeapi-workers`, `--pokeapi-cache`, `--pokeapi-timeout`,
  and `--pokeapi-base`, or disable with `--no-pokeapi`.
- Non-Latin target languages are out of scope for now because they likely require a font patch.
- `002_prepare_translation_text.py` adds `translation_source`; it removes layout markers such as actual line breaks, `\n`, `\l`, `\p`, and `\pn`. It keeps real semantic/control tokens in `original`, but replaces them in `translation_source` with readable placeholders such as `[player-name-1]`, `[buffer1-2]`, `[color-red-3]`, `[button-icon-4]`, and `[control-code-5]`.
- Semantic/control tokens are protected game-engine tokens that must survive translation exactly and in the same count. Examples include `[player]`, `[buffer1]`, `[red]`, `\CC12`, `\btn01`, `\pk`, `\mn`, `\qo`, `\qc`, and `{B4}`.
- `003_llm_translate.py` uses `translation_source` when present. After each model response it checks placeholder counts, restores placeholders through `semantic_token_placeholders`, then checks semantic/control token counts and retries if a placeholder or token is missing, duplicated, or invented, or if the model adds layout markers.
- `003_llm_translate.py` prints a warning when it falls back to a single-entry prompt because that path has less context and can reduce translation accuracy.
- `003_llm_translate.py --exclude-categories` removes matching entries from the output JSON entirely. It does not copy them as English translations.
- `003_llm_translate.py --include-ids`, `--include-id-ranges`, `--include-categories`, and `--include-category-prefixes` keep only matching entries in the output JSON. This is preferred for small debug ROMs.
- `003_llm_translate.py --priority-order --limit N` is intended for debug builds: it translates only the first `N` missing entries after priority sorting, favoring menu/UI/common/short text.
- For every target-language translation addition, edit, or fix, research wording in this order: PokeAPI localized data,
  then Bulbapedia/Pokémon Database, then the official FireRed ROM in the target language for exact in-game phrasing and
  control layout. Use a known local ROM path (Italian: `out/red_ita.gba`); otherwise ask the user for that ROM path
  before relying on it. Plain OpenAI-compatible chat APIs usually do not browse the web by themselves.
- When manually translating entries, use established official terminology where available. For Italian battle text,
  prefer
  official-style terms such as `Brutto colpo!`, `è esausto!`, `Punti Esperienza`, ability names like `Pressione`, and
  natural stat-change phrasing such as `La precisione di [name] cala!`.
- Keep scripts language-agnostic unless explicitly asked otherwise. Do not add single-language translation hacks to scripts, such as `if` branches that replace text with an Italian phrase. Put language-specific wording in translation JSON; scripts should only contain reusable layout, token, extraction, validation, and injection logic.
- To use a ChatGPT subscription login instead of an API key, run `codex login` first or provide `CODEX_ACCESS_TOKEN`, then run `003_llm_translate.py` with `--auth chatgpt`. This delegates batches to `codex exec`; `--model` is optional in this mode and overrides the Codex default model when provided.
- For OpenCode, use `--api-base https://opencode.ai/zen/go/v1`; `003_llm_translate.py` appends `/chat/completions` automatically. `API HTTP 403: error code: 1010` means the upstream gateway rejected the HTTP request before the model handled it. The script sends a browser-like `User-Agent` by default and exposes `--user-agent` for overrides.
- Translation progress is shown as a fixed `0` to `100%` bar based on total translatable entries in the full file, not only the entries translated in the current run. During `--rate-limit` sleeps, the bar temporarily shows a shared `waiting for rate limit reset` countdown and clears it after waiting.
- `003_llm_translate.py` retries transient API failures up to 3 total attempts. It does not retry unauthorized, forbidden, rate-limit, other 4xx client errors, or partial/mismatched translation batches.
- If a batch reaches the API output token limit, `003_llm_translate.py` falls back to translating entries individually. If a single-entry request still reaches the limit, it uses a compact single-item JSON prompt and then a plain-text prompt with the same model. If the entry still cannot be translated because of the output token limit, it prints a warning with the entry id, leaves the entry untranslated, and continues.
- Use `--rate-limit N` to cap total API calls per minute across all workers and retry attempts. Use `0` to disable the limiter.
- `004_controlfix_translations.py` wraps translated text by default for `scripts`, `plain_scripts`,
  move/ability/item/mission descriptions, mission objectives, Pokémon summary text, battle messages, and
  `trade_messages`. It allows known battle stat-change and trainer-switch prompts to reorder protected tokens for
  natural
  or official target-language grammar, and keeps the `What will [pokemon] do?` battle prompt to two
  lines with the Pokémon name alone on line 2.
  Normal `scripts` entries are wrapped into dialogue pages with `\n`, `\l`, and paragraph breaks. `plain_scripts`,
  descriptions, summary text, and battle messages use plain line breaks. Mission Log descriptions use a narrower
  three-line budget, while pause-menu mission objectives retain their wider two-line budget.
  Mission names are not wrapped; they are capped to the longest extracted English mission-name visible width by default,
  tunable with `--mission-name-max-width`. `start_menu_labels` are capped to `--start-menu-label-max-width` (default
  13), and `setting_names` are capped to `--setting-name-max-width` (default 15), so narrow menu/list labels do not
  clip. Item descriptions default to a wider 34-character, 3-line layout; tune with `--item-description-wrap-width` and
  `--item-description-max-lines`. Compact multi-row menu labels keep their original row breaks so choices such as
  `Yes\nNo` remain selectable on separate rows. Tune with `--wrap-width`, `--description-wrap-width`, and
  `--wrap-categories`, or disable with `--no-wrap`.
- The injector caps every encoded ability description to a conservative 46-byte ceiling observed in the working French
  ROM because longer payloads corrupt Summary. Preserve complete wording in `translated` and provide a token-safe,
  fitting `translated_fixed` display value. Over-budget values abort unless `--allow-lossy-fit` is explicitly used.
- Controlfix removes excess `[player]`/`[rival]` tokens invented by translation while preserving source counts, avoiding
  duplicate names in PC labels, residence signs, and possessive messages.
- Controlfix restores source boundary spaces on short `battle_messages` fragments. Italian stat templates carry
  `aumenta`/`diminuisce` before a leading-space intensity buffer, producing `aumenta di molto!` / `diminuisce di molto!`
  without a space before `!`. The move-use template must not duplicate buffer punctuation, and the battle action prompt
  keeps the Pokémon token alone on line 2.
- Pokédex descriptions use working-French-ROM limits of 3 lines, 43 visible characters per line, and 124 visible
  characters total. Over-budget text keeps its beginning and ending with a middle ellipsis; tune with the dedicated
  `--pokedex-description-wrap-width`, `--pokedex-description-max-lines`, and `--pokedex-description-max-total` options.
- The extractor follows the exact shared mission-handler call signature and covers all 84 missions as `85`
  `mission_names` (separate Hero/Heroine main-story variants) and `82` unique `mission_descriptions` (two side-mission
  registrations reuse text records). Descriptions use FireRed font
  metrics and the working French pipeline's non-scrolling limit of 3 plain lines at 172 pixels per line; `0xFA` scroll
  and `0xFB` page controls are invalid there. `mission_objectives` retain the wide pause box's 2-line, 35-character,
  65-total budget. Tune them independently with the dedicated mission description/objective options.
- Keep language-specific ROM behavior in one file per patch under `patches/<language>/`, not in shared scripts or
  translation JSON. The injector applies every patch file for the selected `--target-lang` in filename order and records
  them in map output.
- Italian `pokedex_category_order.py` swaps the category/suffix render operands and writes trailing-space `Pokémon `,
  producing `Pokémon Ratto`; it owns `scr_415F8F` so generic injection cannot overwrite the suffix slot. Controlfix
  strips
  redundant leading/trailing `Pokémon` from `pokedex_species` values because the renderer supplies the prefix.
- Italian `mission_log_tab_titles.py` blanks the shared runtime ` Missions` suffix through its live pointer at
  `0x1EBE988` and owns `tbl_mission_log_00000_1F56040`. Italian filter entries therefore contain complete labels such
  as `Tutte le Missioni` and `Missioni Completate` without producing concatenated text.
- Always run `004_controlfix_translations.py` after LLM translation before injecting.
- `006_decontrolfix_translations.py` is an editable cleanup pass for already-controlfixed JSON, not a perfect inverse: wrapping/layout tokens can be removed, but prior trims and repairs cannot be reconstructed.
- During injection, `plain_scripts` blank lines are encoded as repeated newline bytes (`0xFE 0xFE`) instead of the paragraph/prompt byte (`0xFB`), because the full-screen renderer shows the bottom arrow and can overflow when it receives `0xFB`.

## Debug Workflow

Use this to test a small manually whitelisted ROM build:

```bash
./001_extract_unbound_text.py rom/unbound.gba -o out/debug-unbound-texts.json
./002_prepare_translation_text.py out/debug-unbound-texts.json -o out/debug-unbound-texts-prepared.json
./003_llm_translate.py out/debug-unbound-texts-prepared.json --target it --api-base https://opencode.ai/zen/go/v1 --api-key YOUR_API_KEY --model your-model-name --workers 4 --batch-size 20 --include-ids tbl_menu_pause_00003_415A6E,tbl_menu_pause_00004_415A77,tbl_battle_messages_00412_3FE6D5 --include-category-prefixes menu_ -o out/debug-unbound-texts-it.json --overwrite
./004_controlfix_translations.py out/debug-unbound-texts-it.json -o out/debug-unbound-texts-it-controlfix.json --source out/debug-unbound-texts-prepared.json --report out/debug-controlfix-report.json
./005_hybrid_injector.py rom/unbound.gba out/debug-unbound-texts-it-controlfix.json -o out/debug-unbound-translated.gba --map-output out/debug-hybrid-map.json
```

## Codex Project Config

- Project Codex config lives in `.codex/config.toml`. It uses low verbosity, medium reasoning, workspace-write sandboxing, on-request approvals, disabled default web search, and subagent limits of 6 threads, depth 1, and 1800 seconds per job.
- Custom project subagents live in `.codex/agents/`. They are intentionally narrow and terse; use them when explicitly asked to delegate or run parallel agent work.
- Repo skills live in `.agents/skills/`. Use them for repeated workflows: `unbound-text-extraction`,
  `unbound-debug-build`, `unbound-translation-run`, `unbound-layout-controlfix`, `unbound-injection-qa`, and
  `unbound-docs-sync`.
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

- `ready-translations/` contains one complete controlfixed translation JSON per language. GitHub Actions workflow
  `Release Ready Translation Patches` downloads the English ROM from the `UNBOUND_ENGLISH_ROM_URL` secret, validates
  its known MD5, injects every `ready-translations/*.json` directly, and releases only
  `unbound-translated-<language>.bps` assets. It runs on every push to `main`, cancels obsolete builds, and uses
  `ready-<UTC-build-time>-<commit-sha>` as its release tag, with an optional manual tag override. Release descriptions
  list the flag-marked assets, latest version tag, and linked commit hashes/messages. All generated releases are
  pre-releases and it must never upload a ROM. Optional `DISCORD_WEBHOOK_URL` notifications announce successful
  prereleases with their BPS assets; failed or cancelled builds stay silent, and notification failures do not fail the
  release.
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
- After every bugfix or translation/layout/control/injection fix, automatically build a test ROM before handoff when the
  required source ROM and translation input are available. Use a focused debug ROM only when it covers the reported
  issue; otherwise build the applicable full translation ROM. Report the ROM and map-output paths for testing.
- When fixing a layout, wrapping, or protected-token bug, add a small regression fixture/test under `tests/fixtures/`
  and `tests/` so the case stays covered without requiring a ROM.
