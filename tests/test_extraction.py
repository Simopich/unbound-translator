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
    def test_nature_names_have_both_summary_pointer_tables(self):
        nature_tables = [
            table
            for table in EXTRACTOR.POINTER_TABLES
            if table.category == "nature_names"
        ]
        self.assertEqual(
            [(table.start, table.count) for table in nature_tables],
            [(0x463E60, 25), (0x1FE65F4, 25)],
        )

    def test_pokedex_cry_control_has_explicit_owner(self):
        table_name, addresses = EXTRACTOR.MANUAL_TEXT_TABLES["menu_pokedex"]
        self.assertEqual(table_name, "data.menus.text.pokedex.controls")
        self.assertEqual(addresses, [0x415FAD])

    def test_opening_difficulty_selector_has_all_unaligned_labels(self):
        table_name, addresses = EXTRACTOR.MANUAL_TEXT_TABLES["menu_game_settings"]

        self.assertEqual(table_name, "data.menus.text.gameSettings")
        self.assertEqual(addresses[-2:], [0x75CE9A, 0x75CEA6])
        self.assertEqual(EXTRACTOR.MANUAL_TEXT_POINTER_SOURCES[0x75CE9A], [0x75CD61])
        self.assertEqual(EXTRACTOR.MANUAL_TEXT_POINTER_SOURCES[0x75CEA6], [0x75CDAF])

    def test_starter_confirmation_buffers_have_unaligned_type_owners(self):
        self.assertEqual(
            EXTRACTOR.MANUAL_TEXT_POINTER_SOURCES[0x1F97855],
            [0x1E90527],
        )
        self.assertEqual(
            EXTRACTOR.MANUAL_TEXT_POINTER_SOURCES[0x1F97864],
            [0x1E90546],
        )

    def test_gendered_dialogue_fragments_have_explicit_owners(self):
        table_name, addresses = EXTRACTOR.MANUAL_TEXT_TABLES[
            "gendered_dialogue_fragments"
        ]

        self.assertEqual(table_name, "data.dialogue.text.genderedFragments")
        self.assertEqual(len(addresses), 54)
        self.assertIn(0x789224, addresses)  # him
        self.assertIn(0x78922E, addresses)  # her
        self.assertIn(0x793FCB, addresses)  # boy
        self.assertIn(0x793FCF, addresses)  # girl
        self.assertIn(0x1EF97B3, addresses)  # dudette
        self.assertEqual(
            EXTRACTOR.MANUAL_TEXT_POINTER_SOURCES[0x1F8DD33],
            [0x1E709FB, 0x1E9EE30, 0x1EA34E9, 0x1EA5258, 0x1EA57C1, 0x1EAB91D],
        )

    def test_pokedex_unknown_fallback_label_cannot_relocate(self):
        result = decode("Unknown")
        entry = EXTRACTOR.make_entry(
            "scr_1A357CC",
            "pointer_texts",
            0x1A357CC,
            result,
            result.byte_length,
            True,
            [0x88E34, 0x165BC34],
        )

        self.assertTrue(entry["no_relocation"])

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

    def test_rejects_trainer_struct_and_adjacent_binary_targets(self):
        self.assertTrue(EXTRACTOR.is_aligned_pointer_target_excluded(0x24019A))
        self.assertTrue(EXTRACTOR.is_aligned_pointer_target_excluded(0x246AE0))
        self.assertFalse(EXTRACTOR.is_aligned_pointer_target_excluded(0x24F1A7))

    def test_rejects_thumb_instructions_that_look_like_text_pointers(self):
        false_sources = {0x3F2B0, 0x8BBBC8, 0x8BBC70}

        self.assertEqual(
            EXTRACTOR.ALIGNED_POINTER_TEXT_EXCLUDED_SOURCES,
            false_sources,
        )
        for source in false_sources:
            self.assertTrue(EXTRACTOR.is_aligned_pointer_source_excluded(source))
        self.assertFalse(EXTRACTOR.is_aligned_pointer_source_excluded(0x3F2B4))

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

    def test_pointer_alias_overlapping_structured_slot_is_rejected(self):
        rom = bytearray(128)
        source = 4
        target = 40
        encoded = Charmap().encode("    Dawn Stone")
        rom[source: source + 4] = (0x08000000 + target).to_bytes(4, "little")
        rom[target: target + len(encoded)] = encoded

        entries, stats = EXTRACTOR.scan_pointer_texts(
            bytes(rom),
            known_targets={44},
            known_pointer_sources=set(),
            min_target=1,
            max_length=64,
            start_index=0,
            occupied_ranges=[(44, 57)],
        )

        self.assertEqual(entries, [])
        self.assertEqual(stats["overlap_targets"], 1)

    def test_mid_string_manual_menu_owner_is_excluded(self):
        self.assertIn(0x41736B, EXTRACTOR.MANUAL_TEXT_EXCLUDED_ADDRESSES)

    def test_bounty_descriptions_use_non_scrolling_category(self):
        self.assertEqual(len(EXTRACTOR.MISSION_DESCRIPTION_TEXT_ADDRESSES), 82)
        for address in EXTRACTOR.MISSION_DESCRIPTION_TEXT_ADDRESSES:
            self.assertEqual(
                EXTRACTOR.pointer_text_category(b"", address, []),
                "mission_descriptions",
            )

    def test_mission_registration_title_source(self):
        rom = bytearray(32)
        source = 4
        rom[source - 2: source] = b"\x0F\x00"
        rom[source: source + 4] = (0x08123456).to_bytes(4, "little")
        rom[source + 4] = 0x04
        rom[source + 5: source + 9] = (
                0x08000000 + EXTRACTOR.MISSION_HANDLER_ROM_OFFSET
        ).to_bytes(4, "little")
        self.assertTrue(
            EXTRACTOR.is_mission_registration_title_pointer_source(rom, source)
        )
        rom[source + 4] = 0x05
        self.assertFalse(
            EXTRACTOR.is_mission_registration_title_pointer_source(rom, source)
        )

    def test_mission_registration_title_addresses_are_unique(self):
        rom = bytearray(64)
        source = 4
        title = 40
        rom[source - 2: source] = b"\x0F\x00"
        rom[source: source + 4] = (0x08000000 + title).to_bytes(4, "little")
        rom[source + 4] = 0x04
        rom[source + 5: source + 9] = (
                0x08000000 + EXTRACTOR.MISSION_HANDLER_ROM_OFFSET
        ).to_bytes(4, "little")
        self.assertEqual(
            EXTRACTOR.mission_registration_title_addresses(rom), {title}
        )


    def test_trainer_classes_fixed_table_uses_pointer_name(self):
        table = next(
            t for t in EXTRACTOR.FIXED_TABLES if t.category == "trainer_classes"
        )
        self.assertTrue(table.pointer_name)
        self.assertEqual(table.count, 107)

    def test_trainer_names_fixed_table_configuration(self):
        table = next(
            t for t in EXTRACTOR.FIXED_TABLES if t.category == "trainer_names"
        )
        self.assertEqual(table.start, 0x23EACC)
        self.assertEqual(table.count, 743)
        self.assertEqual(table.slot_size, 12)
        self.assertEqual(table.stride, 40)

    def test_cfru_battle_messages_manual_table(self):
        table_name, addresses = EXTRACTOR.MANUAL_TEXT_TABLES["battle_messages"]
        self.assertEqual(table_name, "data.battle.text.cfruMessages")
        self.assertEqual(len(addresses), 12)
        self.assertIn(0x905690, addresses)
        self.assertIn(0x905A30, addresses)

    def test_cfru_battle_message_source_detection(self):
        rom = bytearray(0x920000)
        source = 0x905572
        target = 0x905690
        rom[source - 1] = 0x02
        rom[source : source + 4] = (0x08000000 + target).to_bytes(4, "little")
        self.assertTrue(EXTRACTOR.is_cfru_battle_message_source(rom, source, target))
        self.assertTrue(EXTRACTOR.is_pointer_reference_source(rom, source, target))

    def test_intro_setup_and_dexnav_ranges(self):
        ranges = {
            r.table_name: (r.start, r.end, r.category)
            for r in EXTRACTOR.POST_POINTER_MANUAL_TEXT_RANGES
        }
        self.assertIn("data.menus.text.gameSettings.introSetup", ranges)
        self.assertEqual(
            ranges["data.menus.text.gameSettings.introSetup"],
            (0x1F10DC2, 0x1F11016, "menu_game_settings"),
        )
        self.assertIn("data.menus.text.dexnav", ranges)
        self.assertEqual(
            ranges["data.menus.text.dexnav"],
            (0xA43BA5, 0xA43D82, "menu_common"),
        )

    def test_cfru_trainerbattle_source_detection(self):
        source = 0x1E8637A
        rom = bytearray(source + 16)
        target = 0x1F600A3
        # 5C <type> F5 00 00 00 <ptr1>
        rom[source - 6] = 0x5C
        rom[source - 5] = 0x0D
        rom[source - 4] = 0xF5
        rom[source - 3] = 0x00
        rom[source - 2] = 0x00
        rom[source - 1] = 0x00
        rom[source : source + 4] = (0x08000000 + target).to_bytes(4, "little")
        self.assertTrue(
            EXTRACTOR.is_cfru_trainerbattle_source(rom, source, target)
        )
        # Rejects low target
        self.assertFalse(
            EXTRACTOR.is_cfru_trainerbattle_source(rom, source, 0x123)
        )

    def test_gendered_dialogue_fragment_78da8e_pointer_source(self):
        self.assertEqual(
            EXTRACTOR.MANUAL_TEXT_POINTER_SOURCES[0x78DA8E],
            [0x78A3E6],
        )


if __name__ == "__main__":
    unittest.main()
