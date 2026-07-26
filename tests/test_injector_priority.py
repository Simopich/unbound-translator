import importlib.util
import sys
import unittest
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "005_hybrid_injector.py"
SPEC = importlib.util.spec_from_file_location("hybrid_injector", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
INJECTOR = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = INJECTOR
SPEC.loader.exec_module(INJECTOR)


class InjectionPriorityTests(unittest.TestCase):
    def test_free_blocks_exclude_engine_ranges_and_keep_edge_margins(self):
        rom = bytearray(b"\x00" * 0x1FE2000)
        rom[0x220000:0x240000] = b"\xFF" * 0x20000
        rom[0xFFF000:0x1002000] = b"\xFF" * 0x3000
        rom[0x165000:0x167000] = b"\xFF" * 0x2000
        rom[0x19A000:0x19C000] = b"\xFF" * 0x2000
        rom[0x1FDF000:0x1FE2000] = b"\xFF" * 0x3000

        blocks = INJECTOR.build_free_blocks(rom, [], 0x1000, 0x100)
        ranges = {(block.start, block.end) for block in blocks}

        self.assertIn((0x220008, 0x22FFF8), ranges)
        self.assertIn((0x1FE0008, 0x1FE1FF8), ranges)
        self.assertTrue(
            all(end <= 0x16586A or start >= 0x166C9A for start, end in ranges)
        )
        self.assertTrue(
            all(end <= 0x19A837 or start >= 0x19B86A for start, end in ranges)
        )
        self.assertTrue(all(not (0x230000 <= start < 0x500000) for start, _ in ranges))
        self.assertTrue(all(not (0x1000000 <= start < 0x1FE0000) for start, _ in ranges))

    def test_pointer_source_requires_alignment_or_known_script_shape(self):
        rom = bytearray(64)

        self.assertTrue(INJECTOR.plausible_pointer_source(rom, 16))
        self.assertFalse(INJECTOR.plausible_pointer_source(rom, 17))

        rom[20] = 0x67
        self.assertTrue(INJECTOR.plausible_pointer_source(rom, 21))

        rom[27:31] = (0x02000010).to_bytes(4, "little")
        self.assertTrue(INJECTOR.plausible_pointer_source(rom, 31))

    def test_allocator_uses_first_suitable_block_in_address_order(self):
        blocks = [
            INJECTOR.FreeBlock(0x1000, 0x1100, 0x1000),
            INJECTOR.FreeBlock(0x2000, 0x2100, 0x2000),
        ]

        self.assertEqual(INJECTOR.allocate(blocks, 0x20, 4), 0x1000)
        self.assertEqual(INJECTOR.allocate(blocks, 0xF0, 4), 0x2000)

    def test_free_blocks_can_be_clipped_to_vetted_ranges(self):
        rom = bytearray(b"\x00" * 0x4000)
        rom[0x1000:0x3000] = b"\xFF" * 0x2000

        blocks = INJECTOR.build_free_blocks(
            rom,
            [],
            0x400,
            0x100,
            ((0x1800, 0x2000), (0x2800, 0x2900)),
        )

        self.assertEqual(
            [(block.start, block.end) for block in blocks],
            [(0x1800, 0x2000), (0x2800, 0x2900)],
        )

    def test_ability_description_compaction_is_bounded_at_word_boundary(self):
        encoded = b"Aumenta\x00Attacco\x00se\x00colpito\x00da\x00una\x00mossa\x00Erba\xFF"

        compacted = INJECTOR.compact_ability_description(encoded, b".\xFF", 32)

        self.assertLessEqual(len(compacted), 32)
        self.assertTrue(compacted.endswith(b"Erba\xFF"))
        self.assertIn(b"\x00...\x00", compacted)

    def test_structured_menu_text_precedes_scripts_and_pointer_discoveries(self):
        entries = [
            {"id": "discovery", "category": "pointer_texts"},
            {"id": "dialogue", "category": "scripts"},
            {"id": "menu", "category": "menu_save"},
            {"id": "card", "category": "menu_trainer_card"},
        ]
        ordered = INJECTOR.prioritize_entries(entries)
        self.assertEqual([entry["id"] for entry in ordered], ["card", "menu", "dialogue", "discovery"])

    def test_keeps_original_order_within_a_priority_group(self):
        entries = [
            {"id": "first", "category": "menu_save"},
            {"id": "second", "category": "menu_pc"},
        ]
        self.assertEqual(INJECTOR.prioritize_entries(entries), entries)


if __name__ == "__main__":
    unittest.main()
