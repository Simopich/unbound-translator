# AGENTS.md

## Session Mode

Start every new session in `/caveman ultra` mode.

## Project

`unbound-translator` is a Python toolchain for extracting, translating, formatting, and injecting Pokemon Unbound text
into a 32 MB GBA ROM. The source ROM is `rom/unbound.gba`; its required MD5 is
`9cad8e771940e7f7094d13911552cef0`.

The supported development platforms are Windows, macOS, and Linux with Python 3.10 or newer. Use `python script.py`
examples so commands remain portable across all three systems.

ROMs and generated ROM artifacts are private local inputs. Never commit, upload, or release them. Use the project PCS
codec in `lib/pcs_text.py`; do not add Meowth/HMA runtime dependencies.

## Setup And Commands

Install development dependencies:

```bash
python -m pip install -r requirements-dev.txt
```

Run the complete pipeline from the repository root:

```bash
python 001_extract_unbound_text.py rom/unbound.gba -o out/unbound-texts.json
python 002_prepare_translation_text.py out/unbound-texts.json -o out/unbound-texts-prepared.json
python 003_llm_translate.py out/unbound-texts-prepared.json --target it --api-base https://opencode.ai/zen/go/v1 --api-key YOUR_API_KEY --model your-model-name --workers 4 --batch-size 20 -o out/unbound-texts-it.json
python 004_controlfix_translations.py out/unbound-texts-it.json -o out/unbound-texts-it-controlfix.json --source out/unbound-texts-prepared.json --report out/controlfix-report.json
python 005_hybrid_injector.py rom/unbound.gba out/unbound-texts-it-controlfix.json -o out/unbound-translated.gba --target-lang it --map-output out/hybrid-map.json
```

Use `006_decontrolfix_translations.py` before editing an already-controlfixed file, then rerun controlfix. The canonical
release input is `ready-translations/it.json`.

## Architecture

- `001_extract_unbound_text.py`: lossless extraction and coverage audit.
- `002_prepare_translation_text.py`: layout cleanup and readable protected-token placeholders.
- `003_llm_translate.py`: PokeAPI localization, LLM fallback, resume, and filters.
- `004_controlfix_translations.py`: token repair and category-specific layout.
- `005_hybrid_injector.py`: transactional in-place writes, relocation, runtime patches, and map output.
- `006_decontrolfix_translations.py`: editable cleanup of controlfixed JSON.
- `lib/pcs_text.py`: authoritative PCS codec.
- `lib/translation_tokens.py`: protected-token and layout helpers.
- `patches/<language>/*.py`: one language-specific runtime behavior per file.
- `ready-translations/`: complete controlfixed release inputs.
- `.agents/skills/unbound-*`: detailed task workflows. Use the matching skill instead of adding procedure here.

## Invariants

### Extraction

- Keep extraction lossless. Never translate, normalize, wrap, or repair `original` text.
- Preserve stable IDs, categories, exact pointer sources, byte lengths, and `no_relocation` ownership.
- Prove the owning table, record, script operand, or bounded text bank before accepting broad pointer/orphan findings.
- Decode and encode with `lib/pcs_text.py`, never ad hoc ASCII byte handling.

### Translation And Layout

- Prepare before translation; controlfix after translation and before injection.
- Preserve semantic/control tokens exactly unless a tested grammar rule explicitly permits reordering.
- For manual wording, use PokeAPI localization first, then Bulbapedia/Pokemon Database, then the official target-
  language FireRed ROM. Italian FireRed is `out/red_ita.gba`.
- Keep wording in translation JSON. Put target-language runtime behavior in `patches/<language>/`, not shared scripts.
- Use `translated_fixed` only for complete, token-safe wording required by a fixed/no-relocation limit. Never silently
  truncate or conceal lost meaning.

### Injection

- Inject only controlfixed JSON. Default pointer policy is `oversized`; `changed` is experimental.
- Relocation is transactional: validate and allocate every applied source/destination before generic writes. Entries
  without space remain original and appear in the map; use `--fail-on-no-space` for strict capacity audits.
- Reclaim only injector-proven, fully owned high-bank `scripts` literals. Never reclaim structured tables, menus,
  Pokedex text, abilities, battle data, generic `pointer_texts`, or arbitrary old slots.
- `--allow-lossy-fit` is diagnostic only and forbidden for release builds.

## External Evidence

- Investigate and solve within this repository first; preserve its independent architecture.
- `https://github.com/AntonyKervazoCanut/gba_translator` and `out/working_fr.gba` are optional behavioral second opinions
  for difficult Unbound bugs. Use them as evidence or inspiration, never as architecture/code to copy wholesale.
- `out/red_ita.gba` is the official Italian FireRed wording and layout reference.
- Comparison ROMs are ignored local assets and must never be committed or released.

## Verification

- Documentation-only changes: `git diff --check`.
- Changed Python: `python -m py_compile <changed-files>`.
- Behavioral changes: `python -m pytest`.
- Layout/token fixes: add a focused fixture and regression test under `tests/fixtures/` and `tests/`.
- Extraction changes: rerun focused audit and baseline extraction; explain every category-count delta.
- Translation/layout/injection changes: build the applicable ROM when inputs exist; report ROM and map paths.
- Release-capable injection: require zero pointer mismatches, implausible pointers, encode errors, fixed/no-relocation
  truncations, ability compactions, and missing relocation candidates.
- Preserve unrelated worktree changes. Do not perform destructive Git/file cleanup without explicit permission.

## Task Skills

- `unbound-text-extraction`: find and add missing ROM text coverage.
- `unbound-translation-run`: prepare, translate, resume, and curate official wording.
- `unbound-layout-controlfix`: repair tokens, wrapping, controls, and overflow.
- `unbound-relocation-compaction`: fit ordinary relocated translations back into original PCS byte slots.
- `unbound-capacity-curation`: curate total-capacity, fixed-slot, and `no_relocation` failures safely.
- `unbound-injection-qa`: build ROMs and audit relocation/map safety.
- `unbound-runtime-patch`: implement target-language runtime behavior that JSON cannot express.
- `unbound-debug-build`: build focused whitelist/category test ROMs.
- `unbound-release-pipeline`: maintain BPS-only GitHub releases and Discord announcements.
- `unbound-docs-sync`: keep durable documentation and skill metadata aligned.

## Release Contract

`.github/workflows/release-ready-translations.yml` downloads the secret English ROM URL, verifies MD5, injects every
`ready-translations/*.json`, and publishes only `unbound-translated-<language>.bps`. Releases are prereleases. Failed or
cancelled builds do not announce to Discord. Notification failure must not fail a successful release. Never upload a ROM.

Keep roadmap and future proposals in `README.md` or dedicated documentation, not this file.
