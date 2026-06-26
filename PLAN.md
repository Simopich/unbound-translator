# PLAN.md

This file tracks concrete improvements needed to make `unbound-translator` more complete and more space-efficient.

## 1. Pointer String Interning

Many recurring standalone strings can share one relocated memory location.

Implement interning for pointer-based entries whose final encoded translated bytes are identical.

Example:

```text
Alture Ghiacciate
```

If several pointer-based entries translate to exactly the same encoded bytes, write the bytes once into free space and patch all pointer sources to that same address.

Requirements:

- Only intern pointer-based entries.
- Only intern after encoding and control-fix.
- Key by exact encoded bytes, not by Unicode string, because the ROM stores bytes.
- Preserve all pointer sources for all interned entries.
- Add `--intern-pointer-strings`, default enabled.
- Add `--no-intern-pointer-strings` for debugging.
- Add intern stats:
  - intern groups
  - pointer entries deduplicated
  - bytes saved
- Record intern groups in `hybrid-map.json`.

Limitations:

- This only helps standalone strings.
- It cannot deduplicate substrings inside longer text. For example, `Welcome to Frozen Heights!` cannot share only the `Frozen Heights` substring unless the game script supports string concatenation.

## 2. Glossary And Consistency Pass

The same game term can appear in different categories and scripts. The LLM may translate one occurrence and leave another in English.

Implement a glossary consistency script or pass before controlfix.

Inputs:

- translated JSON
- source JSON
- glossary file, probably `glossary/it.json`

Glossary format example:

```json
{
  "Frozen Heights": "Alture Ghiacciate",
  "Bellin Town": "Borgo Bellin",
  "Pokémon Center": "Centro Pokémon"
}
```

Requirements:

- Replace known terms in `translated` text.
- Prefer longest match first.
- Preserve semantic/control tokens.
- Do not replace inside protected tokens such as `[player]`, `[buffer1]`, `\CC...`, `{B4}`.
- Report every replacement:
  - entry id
  - category
  - source term
  - replacement
- Add a dry-run mode.

This should help with cases where `Frozen Heights` is correctly translated as a map name but remains English in script text.

## 3. Menu Extraction Audit

Some menu text may still be untranslated because it is not extracted, not because it is skipped during injection.

Run a targeted audit for common always-visible UI strings:

- `SAVING.`
- `DON'T TURN OFF THE POWER`
- `YES`
- `NO`
- `BAG`
- `POKéMON`
- `SAVE`
- `OPTION`
- `PLAYER`
- `TIME`
- `MONEY`
- `BADGES`
- `A Button`
- `B Button`
- PC menu labels
- Pokémon party menu labels
- item storage labels
- battle menu labels
- options menu labels

Implementation ideas:

- Add an audit script that searches the ROM for encoded PCS forms of known English strings.
- Compare found offsets against extracted entries.
- Output:
  - found and extracted
  - found but not extracted
  - not found as PCS text
  - likely graphical/tile text

Important distinction:

- Extracted and translated but skipped means injector/space issue.
- Not extracted means extractor coverage issue.
- Not found as PCS text may mean graphical text, compressed data, or custom UI encoding.

## 4. Menu Priority And Fixed-Size Handling

Menu text should be treated as high-value because it appears throughout the whole game.

For menu categories:

- Try in-place first if it fits.
- If pointer-based and too long, relocate with very high priority.
- If fixed-size and too long, report clearly as `fixed_truncated` or `fixed_unfit`.

Future compression may target these first:

- abbreviate menu labels
- use shorter official terminology
- reduce punctuation/spacing
- prefer compact UI phrases over literal translations

## 5. Translation Memory For Repeated English Text

Before calling the LLM, detect duplicate English `translation_source` values.

Requirements:

- Translate each unique source text once.
- Copy the translated result to all duplicate entries.
- Preserve each entry id and JSON structure.
- Validate semantic/control token counts for every copied translation.
- Report duplicate groups and API calls saved.

Benefits:

- Lower API cost.
- More consistent translations.
- More identical translated strings, which improves pointer-string interning.

## 6. Space Optimization Roadmap

After priority injection and reports are implemented, use reports to guide compression.

Recommended order:

1. Prioritize and intern pointer strings.
2. Generate skipped report.
3. Fix glossary consistency.
4. Compress skipped high-priority menu/UI strings manually or with a dedicated shortening pass.
5. Re-run injection and compare skipped counts.
6. Only then consider more advanced compression or font/text engine patches.

Useful metrics to track over time:

- total translated entries
- injected translated entries
- skipped translated entries
- skipped high-priority entries
- free bytes used
- free bytes remaining
- bytes saved by interning
- bytes saved by manual compression
- fixed-size truncations
- encode errors

## 7. Suggested Workflow After These Changes

```bash
./001_extract_unbound_text.py rom/unbound.gba -o out/unbound-texts.json
./002_prepare_translation_text.py out/unbound-texts.json -o out/unbound-texts-prepared.json
./003_llm_translate.py out/unbound-texts-prepared.json --target it ... -o out/unbound-texts-it.json
./glossary_consistency.py out/unbound-texts-it.json --glossary glossary/it.json -o out/unbound-texts-it-glossary.json
./004_controlfix_translations.py out/unbound-texts-it-glossary.json -o out/unbound-texts-it-controlfix.json --source out/unbound-texts-prepared.json --report out/controlfix-report.json
./005_hybrid_injector.py rom/unbound.gba out/unbound-texts-it-controlfix.json -o out/unbound-translated.gba --map-output out/hybrid-map.json
```

`glossary_consistency.py` does not exist yet. It is listed here as a planned script.
