---
name: unbound-layout-controlfix
description: Repair Pokemon Unbound translated control codes and layout. Use when asked about broken tokens, quote/apostrophe damage, dialogue wrapping, plain_scripts line breaks, description widths, overflowing text, or preparing translated JSON for injection.
---

# Unbound Layout Controlfix

Use `004_controlfix_translations.py` after every translation run and before injection.

Develop layout fixes from this repository's renderer evidence and requirements first. When useful, optionally
double-check Unbound behavior or gather inspiration from the separate, more advanced
`https://github.com/AntonyKervazoCanut/gba_translator` project and local `out/working_fr.gba`; do not copy its approach
by default. Use `out/red_ita.gba` for official Italian FireRed wording/control conventions. Reference ROMs are
local/ignored and must not be committed or released.

## Workflow

```bash
./004_controlfix_translations.py out/unbound-texts-it.json -o out/unbound-texts-it-controlfix.json --source out/unbound-texts-prepared.json --report out/controlfix-report.json
```

Tune with `--wrap-width`, `--description-wrap-width`, `--wrap-categories`, or `--no-wrap` only for targeted diagnosis.

## Rules

Preserve semantic/control tokens exactly: `[player]`, `[buffer1]`, colors, `\CC12`, `\btn01`, `\pk`, `\mn`, `\qo`, `\qc`, and raw `{B4}`-style bytes.

Normal `scripts` use dialogue page controls. `plain_scripts` are full-screen text and must use plain line breaks, not dialogue `\l` wrapping.

Report entry id, category, source text, translated text, token difference, and wrapping issue.
