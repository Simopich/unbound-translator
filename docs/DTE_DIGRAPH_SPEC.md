# Strategy 5: Target-Language Digraph Compression (DTE) Specification

## Overview

Dual Tile Encoding (DTE), also known as digraph compression, is an architectural technique for game localization where single unassigned byte values represent frequent two-character combinations (bigrams).

In Pokemon Unbound, Italian dialogue text is ~20–28% longer than the original English dialogue. By tokenizing the 32–48 most frequent Italian bigrams into single byte codes, text length is compressed by **10–15% losslessly** without losing words, punctuation, or formatting.

---

## Technical Architecture

### 1. Font & Character Code Space (PCS)
The Pokemon Character Set (PCS) used in Gen 3 FireRed/Emerald has several unassigned / unused byte ranges:
- `0x01 - 0x05`: Unused control range.
- `0x20 - 0x33`: Unassigned glyph codes in the primary font table.
- `0x70 - 0x7E`: Unassigned / empty punctuation slots.
- `0xCE - 0xCF`, `0xDF`: Reserved gaps.

By designating a 32-byte block (e.g. `0x20 - 0x3F` or `0x70 - 0x7F`) as DTE tokens, these bytes can represent the top 32 Italian character pairs:
- `" d"`, `" l"`, `"di"`, `" c"`, `" p"`, `"in"`, `"he"`, `"on"`
- `"re"`, `"er"`, `"un"`, `"ne"`, `"te"`, `"co"`, `"el"`, `" s"`
- `"to"`, `"ll"`, `"ch"`, `"tt"`, `"nt"`, `"ro"`, `"ta"`, `"an"`
- `"ti"`, `"le"`, `"al"`, `"si"`, `"ca"`, `"mo"`, `"en"`, `"st"`

### 2. Runtime ASM Patch (`patches/<lang>/digraph_decoder.py`)
In the GBA FireRed engine, text rendering is handled by `TextPrinter_RenderText` / `sub_8003...` (around `0x08003F60` or CFRU expanded text hook).
When the printer reads a character byte B:
1. If B in [DTE_START, DTE_END]:
   - Look up the 2-character tuple (char_1, char_2) from DTE_TABLE.
   - Push char_2 onto a 1-byte lookahead stack (or render char_1 and decrement text pointer).
   - Render char_1.
2. The patch is injected via `005_hybrid_injector.py` patch loader (`patches/<language>/*.py`).

### 3. Codec Encoding (`lib/pcs_text.py`)
In `lib/pcs_text.py`, the `Charmap` class can define target-language bigram replacements:
- During `.encode(text)`:
  Run a greedy substring replacement for each defined DTE bigram into its corresponding byte code before standard character substitution.
- During `.decode(bytes)`:
  Expand DTE byte codes back into their 2-character string representations.

### 4. Projected Space Savings
- Across **~2.5 MB** of Italian text, bigrams account for ~300,000 character occurrences.
- Compressing each bigram from 2 bytes to 1 byte yields:
  approx 180 KB to 260 KB of space reduction across the ROM.
- 100% lossless: no text is removed or truncated.
