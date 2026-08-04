---
name: unbound-layout-controlfix
description: Repair Pokemon Unbound translated controls and screen layout. Use for broken placeholders/tokens, quote bytes, wrapping, description limits, menu overflow, plain-script controls, battle grammar, or preparing JSON for injection; do not use for extraction coverage, runtime ROM behavior, or relocation-capacity curation.
---

# Unbound Layout Controlfix

## Inputs And Output

- Input: translated JSON plus the prepared/source JSON used as control reference.
- Output: controlfixed JSON and optional mismatch report.
- Never repair wording/layout in raw extraction output. Run this after translation and before injection.

```bash
python 004_controlfix_translations.py out/unbound-texts-it.json -o out/unbound-texts-it-controlfix.json --source out/unbound-texts-prepared.json --report out/controlfix-report.json
```

Use `006_decontrolfix_translations.py` before manually editing already-controlfixed text, then rerun controlfix.

## Rules

- Preserve semantic/control tokens exactly: player/buffer placeholders, colors, `\CC*`, `\btn*`, `\pk`, `\mn`,
  `\qo`, `\qc`, raw `{B4}` bytes, and category-specific controls. Reordering is allowed only for established grammar
  templates that validate source/target token counts.
- Normal `scripts` use dialogue `\n`, `\l`, and page controls. `plain_scripts` use plain line breaks; blank lines must
  not become dialogue prompt/scroll controls.
- Keep compact multi-row choices on separate rows. Do not flatten selectable labels.
- Use FireRed font metrics or measured renderer evidence, not character count alone when the screen is pixel-bounded.
- Keep language-specific wording in JSON and runtime behavior in `patches/<language>/`, never hard-coded in shared
  controlfix logic.
- Compare mismatch ID sets before and after changes. Equal counts can hide one resolved ID and one new regression;
  require the post-change set to introduce no new IDs.
- Validate target tokens against prepared/source `semantic_token_placeholders`, not existing target text. Existing text
  may contain duplicated `[buffer*]`/color controls or a raw byte that merely spells a normal glyph.
- Distinguish literal layout tokens from actual JSON newlines. `\n` and an actual newline can encode similarly but are
  not interchangeable when fixtures or renderer contracts require the literal token.

## Known Budgets

- Pokédex descriptions: at most 3 lines, 43 visible characters per line, 124 total.
- Mission Log descriptions: at most 3 plain lines, 172 pixels each; no scroll/page controls.
- Pause-menu mission objectives: 2 lines, 35 visible characters per line, 65 total.
- Move/ability descriptions use `--description-wrap-width` (default 24).
- Item descriptions use `--item-description-wrap-width` (default 34) and 3 lines.
- Ability descriptions require a complete token-safe `translated_fixed` value within the injector's 46-byte display
  ceiling when full wording cannot fit.

## References And Diagnosis

Use `out/red_ita.gba` for official Italian FireRed wording/control conventions. For difficult Unbound renderer behavior,
optionally compare `out/working_fr.gba` or the separate French translator as behavioral evidence, not architecture to
copy.

For each failure, record entry ID/category, original, translated value, protected-token delta, encoded size, line/pixel
width, and renderer context.

## Verification

Add a focused fixture/test for every layout or token bug. Run controlfix, the relevant tests, and an applicable ROM
build. Report controlfix report, ROM, and injector map paths.

Run exact ready-translation fixtures before accepting capacity edits. Restore fixture wording instead of changing a test
to bless a shorter unofficial form.
