from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.pcs_text import Charmap, decode_pcs


@pytest.mark.parametrize(
    "text",
    [
        "ABC xyz 012!?.-",
        "Ciao [player]!\n[black]Premi \\btn01",
        "\\pk\\mn \\qoOK\\qc",
        "\\CC100102\\?2A\\9AA\\\\AA",
    ],
)
def test_pcs_encode_decode_roundtrip_for_text_and_controls(text):
    cmap = Charmap(target_lang="it")

    encoded = cmap.encode(text)
    decoded = decode_pcs(encoded)

    assert decoded.terminated
    assert decoded.byte_length == len(encoded)
    assert decoded.text == text


def test_pcs_byte_length_excludes_terminator():
    cmap = Charmap(target_lang="it")

    encoded = cmap.encode("AB[player]")

    assert encoded.endswith(bytes([0xFF]))
    assert cmap.byte_length("AB[player]") == len(encoded) - 1
