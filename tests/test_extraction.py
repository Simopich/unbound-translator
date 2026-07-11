import importlib.util
import sys
import unittest
from pathlib import Path

from lib.pcs_text import Charmap, decode_pcs

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "001_extract_unbound_text.py"
SPEC = importlib.util.spec_from_file_location("extract_unbound_text", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
EXTRACTOR = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = EXTRACTOR
SPEC.loader.exec_module(EXTRACTOR)


def decode(text: str):
    encoded = Charmap().encode(text)
    return decode_pcs(encoded, 0, len(encoded))


class AlignedPointerTextTests(unittest.TestCase):
    def test_accepts_sentence_and_short_label(self):
        self.assertTrue(
            EXTRACTOR.looks_like_aligned_pointer_text(
                decode("The Wireless Adapter is not connected.")
            )
        )
        self.assertTrue(EXTRACTOR.looks_like_aligned_pointer_text(decode("Bug Gem")))

    def test_rejects_control_only_and_repetitive_data(self):
        self.assertFalse(EXTRACTOR.looks_like_aligned_pointer_text(decode("\\CCF7î")))
        self.assertFalse(
            EXTRACTOR.looks_like_aligned_pointer_text(decode("zzzzizzjiiii"))
        )
        self.assertFalse(EXTRACTOR.looks_like_aligned_pointer_text(decode("AAAA")))

    def test_rejects_mid_string_fragment(self):
        self.assertFalse(
            EXTRACTOR.looks_like_aligned_pointer_text(
                decode("you gave me. It is so intriguing!")
            )
        )

    def test_address_merge_prefers_specific_entry_and_unions_sources(self):
        script = {
            "id": "scr_123456",
            "category": "scripts",
            "address": "0x123456",
            "byte_length": 8,
            "pointer_sources": ["0x100"],
            "is_pointer_based": True,
        }
        table = {
            "id": "tbl_menu_00000_123456",
            "category": "menu",
            "address": "0x123456",
            "byte_length": 8,
            "pointer_sources": ["0x200"],
            "is_pointer_based": True,
            "table_name": "data.menu",
        }
        merged = EXTRACTOR.merge_entries_by_address([script, table])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["category"], "menu")
        self.assertEqual(merged[0]["pointer_sources"], ["0x100", "0x200"])


if __name__ == "__main__":
    unittest.main()
