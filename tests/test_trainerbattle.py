import unittest

from lib.trainerbattle import (
    TRAINERBATTLE_TEXT_OPERAND_OFFSETS,
    is_trainerbattle_text_pointer_source,
)


class TrainerBattleTextPointerTests(unittest.TestCase):
    def test_accepts_every_firered_and_cfru_text_operand_layout(self):
        command = 32
        for battle_type, operand_offsets in TRAINERBATTLE_TEXT_OPERAND_OFFSETS.items():
            with self.subTest(battle_type=battle_type):
                rom = bytearray(96)
                rom[command] = 0x5C
                rom[command + 1] = battle_type
                for operand_offset in operand_offsets:
                    self.assertTrue(
                        is_trainerbattle_text_pointer_source(
                            rom,
                            command + operand_offset,
                        )
                    )

    def test_rejects_event_script_operands_and_unknown_layouts(self):
        command = 32
        cases = (
            (1, 14),
            (2, 14),
            (6, 18),
            (8, 18),
            (10, 10),
            (11, 6),
            (12, 12),
            (17, 6),
        )
        for battle_type, operand_offset in cases:
            with self.subTest(battle_type=battle_type, offset=operand_offset):
                rom = bytearray(96)
                rom[command] = 0x5C
                rom[command + 1] = battle_type
                self.assertFalse(
                    is_trainerbattle_text_pointer_source(
                        rom,
                        command + operand_offset,
                    )
                )

    def test_rejects_non_command_unaligned_and_out_of_bounds_sources(self):
        rom = bytearray(32)
        rom[0:2] = b"\x5C\x0E"

        self.assertFalse(is_trainerbattle_text_pointer_source(rom, 7))
        self.assertFalse(is_trainerbattle_text_pointer_source(rom, -1))
        self.assertFalse(is_trainerbattle_text_pointer_source(rom, len(rom) - 3))


if __name__ == "__main__":
    unittest.main()
