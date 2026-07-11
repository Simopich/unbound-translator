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
