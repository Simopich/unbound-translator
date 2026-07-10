# PLAN.md

This file tracks the staged plan for improving translation quality, automated validation, and future community-backed
translation workflows.

## 1. Translation QA Report

Add a QA report script, for example:

```text
007_translation_qa.py
```

Inputs:

- translated JSON
- source/prepared JSON

Checks:

- missing translations
- likely English leftovers
- repeated source strings translated inconsistently
- required semantic/control token mismatches
- malformed control codes
- translated strings too long for fixed-size or `no_relocation` entries
- menu label overflow risks
- suspicious untranslated Pokémon/game terms

Output:

- machine-readable JSON report
- concise terminal summary
- non-zero exit option for CI failures

Prioritize warnings by category:

1. menus/UI
2. battle messages
3. item/move/ability descriptions
4. mission names/objectives
5. common NPC dialogue
6. long story dialogue

## 2. GitHub Actions CI

Add GitHub Actions for normal PR validation without requiring or uploading a ROM.

Create workflow:

```text
.github/workflows/ci.yml
```

CI should run on:

- pull requests
- pushes to `main`

Baseline jobs:

```bash
python3 -m py_compile \
  001_extract_unbound_text.py \
  002_prepare_translation_text.py \
  003_llm_translate.py \
  004_controlfix_translations.py \
  005_hybrid_injector.py \
  006_decontrolfix_translations.py

python3 -m pytest
```

Use `requirements-dev.txt` for test dependencies.

CI must not:

- commit or download ROMs
- upload generated `.gba` files
- require private ROM data for normal PRs

Later CI additions:

- run `007_translation_qa.py` against committed ready translations if fixtures/source files are available
- validate JSON shape for `ready-translations/*.json`
- reject malformed translation entries
- verify generated reports are deterministic

## 3. Optional Self-Hosted Release Workflow For BPS

GitHub-hosted runners cannot build BPS patches without access to the base ROM. Do not upload or commit ROM files.

For automated BPS builds, add an optional self-hosted runner workflow only.

Create later:

```text
.github/workflows/release-bps.yml
```

Constraints:

- `runs-on: self-hosted`
- base ROM exists only on maintainer machine
- workflow verifies ROM MD5 before use
- generated translated ROM is deleted after patch creation
- only `.bps` and non-ROM reports are uploaded

Required checks:

```bash
md5 -q rom/unbound.gba
# expected: 9cad8e771940e7f7094d13911552cef0
```

Example release steps:

1. checkout repo
2. verify base ROM hash
3. run controlfix if needed
4. inject translated JSON into local ROM
5. create `.bps`
6. remove generated `.gba`
7. upload `.bps` release artifact

Do not add GitHub-hosted ROM decryption or base64-ROM secrets unless explicitly re-evaluated; self-hosted runner is the
preferred non-upload path.

## 4. Category-Specific Review Passes

Use QA reports to review high-impact categories first.

Review order:

1. menus/UI
2. battle messages
3. item descriptions
4. move descriptions
5. ability descriptions
6. mission names
7. mission objectives/descriptions
8. common NPC dialogue
9. long story dialogue

Goals:

- improve user-visible text before rare dialogue
- keep narrow UI labels compact
- align battle text with official Italian style
- reduce overflow/controlfix problems before injection
- identify categories that need custom wrapping or shorter phrasing

## 5. Curated Contribution Path Before Weblate

Before adding Weblate, support lightweight community proofreading through GitHub issues.

Suggested issue template:

```text
Original:
Current translation:
Suggested translation:
Language:
Where seen / screenshot:
Notes:
```

Maintainer manually applies accepted corrections to translation JSON or future PO files.

Use this phase to learn common contributor mistakes before building automated community tooling.

## 6. Future Weblate/PO Proofreading Layer

Add Weblate only after translation QA and pipeline checks are reliable.

Weblate should be positioned as:

> Suggest translation improvements.

Not as:

> Translate the ROM collaboratively from zero.

Prerequisites:

- extraction coverage mostly stable
- token validator solid
- controlfix reliable
- ready JSON generation deterministic
- CI can block bad PRs
- maintainer has review time

Proposed future architecture:

```text
source/prepared JSON = canonical source catalog
weblate/*.po = community-editable translations
ready-translations/<lang>.json = generated release artifact
```

Community PR rules:

- allow edits only to PO translation strings
- validate protected token counts
- validate PO syntax
- run generated JSON check if release JSON is committed
- never accept community edits directly into ROM-ready JSON without CI/controlfix/injection checks

Expose categories gradually if possible:

1. menus
2. battle messages
3. mission names/objectives
4. item descriptions
5. dialogue/scripts

## 7. Release Workflow With QA

Target workflow once QA script exists:

```bash
./001_extract_unbound_text.py rom/unbound.gba -o out/unbound-texts.json
./002_prepare_translation_text.py out/unbound-texts.json -o out/unbound-texts-prepared.json
./003_llm_translate.py out/unbound-texts-prepared.json --target it ... -o out/unbound-texts-it.json
./007_translation_qa.py out/unbound-texts-it.json --source out/unbound-texts-prepared.json --report out/translation-qa.json
./004_controlfix_translations.py out/unbound-texts-it.json -o out/unbound-texts-it-controlfix.json --source out/unbound-texts-prepared.json --report out/controlfix-report.json
./005_hybrid_injector.py rom/unbound.gba out/unbound-texts-it-controlfix.json -o out/unbound-translated.gba --map-output out/hybrid-map.json
```

Community-backed translation remains a later phase, after these checks can reliably reject unsafe edits.
