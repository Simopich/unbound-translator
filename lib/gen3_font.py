"""Pixel metrics for the FireRed normal Latin font."""

from __future__ import annotations

from lib.pcs_text import Charmap, fc_arg_count

# sFontNormalLatinGlyphWidths from pret/pokefirered src/text.c. Values are
# glyph advances, including inter-glyph spacing, indexed by encoded byte.
NORMAL_GLYPH_WIDTHS = (
    6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6,
    8, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6,
    6, 6, 6, 6, 6, 8, 6, 6, 6, 6, 6, 6, 9, 8, 8, 6,
    6, 6, 6, 6, 10, 8, 5, 6, 6, 6, 6, 6, 6, 6, 6, 6,
    6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6,
    6, 6, 6, 8, 8, 8, 8, 8, 8, 4, 6, 8, 5, 5, 6, 6,
    6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6,
    6, 6, 6, 6, 6, 6, 6, 6, 6, 12, 12, 12, 12, 6, 6, 6,
    6, 6, 6, 6, 8, 8, 8, 6, 6, 6, 6, 6, 6, 6, 6, 6,
    6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6,
    8, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 5, 6, 5,
    6, 6, 6, 3, 3, 6, 6, 8, 5, 9, 6, 6, 6, 6, 6, 6,
    6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6,
    6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 5, 6, 6, 4, 6, 5,
    5, 6, 5, 6, 6, 6, 5, 5, 5, 6, 6, 6, 6, 6, 6, 8,
    5, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6,
)

RUNTIME_BUFFER_WIDTH = 54


def text_pixel_width(text: str, cmap: Charmap | None = None) -> int:
    """Return the rendered width of one line, ignoring layout/control bytes."""
    cmap = cmap or Charmap("it")
    encoded = cmap.encode(text)
    width = 0
    index = 0
    while index < len(encoded):
        byte = encoded[index]
        index += 1
        if byte == 0xFF:
            break
        if byte == 0xFC:
            if index >= len(encoded):
                break
            command = encoded[index]
            index += 1 + fc_arg_count(command)
            continue
        if byte == 0xFD:
            width += RUNTIME_BUFFER_WIDTH
            index += 1
            continue
        if byte in {0xFA, 0xFB, 0xFE}:
            continue
        width += NORMAL_GLYPH_WIDTHS[byte]
    return width
