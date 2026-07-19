from __future__ import annotations

from lib.pcs_text import Charmap
from tests.helpers import REPO_ROOT, load_script_module

injector = load_script_module("005_hybrid_injector.py", "hybrid_injector_runtime_patch")
FIXTURE_PATCHES = REPO_ROOT / "tests" / "fixtures" / "runtime_patches"


def test_language_patch_loader_applies_files_for_selected_language():
    context = injector.RuntimePatchContext(bytearray(), Charmap(), [], 4, False)

    reports = injector.apply_language_patches(FIXTURE_PATCHES, "it", context)

    assert reports == [{"file": "runtime_patches/it/fixture_patch.py", "kind": "fixture"}]


def test_language_without_patch_directory_applies_nothing():
    context = injector.RuntimePatchContext(bytearray(), Charmap(), [], 4, False)

    assert injector.apply_language_patches(FIXTURE_PATCHES, "fr", context) == []


def test_italian_pokedex_category_patch_swaps_render_order_and_owns_suffix():
    rom = bytearray(0x1F56080)
    mission_suffix = Charmap(target_lang="it").encode(" Missions")
    rom[0x1EBE988: 0x1EBE98C] = (0x08000000 + 0x1F56040).to_bytes(4, "little")
    rom[0x1F56040: 0x1F56040 + len(mission_suffix)] = mission_suffix
    rom[0x10588C: 0x10588E] = b"\x02\xAA"
    rom[0x105896: 0x105898] = b"\x02\xA9"
    rom[0x1058A4: 0x1058A6] = b"\x06\x4A"
    rom[0x415F8F: 0x415F98] = b"\x00\xCA\xE3\xDF\x1B\xE1\xE3\xE2\xFF"
    context = injector.RuntimePatchContext(rom, Charmap(target_lang="it"), [], 4, False)

    reports = injector.apply_language_patches(REPO_ROOT / "patches", "it", context)

    assert reports == [
        {
            "file": "patches/it/mission_log_tab_titles.py",
            "kind": "mission_log_tab_titles",
            "writes": 1,
            "pointer_offset": "0x1EBE988",
            "target_offset": "0x1F56040",
        },
        {
            "file": "patches/it/pokedex_category_order.py",
            "kind": "pokedex_category_order",
            "writes": 4,
            "offsets": ["0x10588C", "0x105896", "0x1058A4", "0x415F8F"],
        },
    ]
    assert rom[0x1F56040] == 0xFF
    assert bytes(rom[0x10588C: 0x10588E]) == b"\x0C\x4A"
    assert bytes(rom[0x105896: 0x105898]) == b"\x0A\x49"
    assert bytes(rom[0x1058A4: 0x1058A6]) == b"\x02\xAA"
    assert bytes(rom[0x415F8F: 0x415F98]) == b"\xCA\xE3\xDF\x1B\xE1\xE3\xE2\x00\xFF"
    assert context.handled_entry_ids == {
        "scr_415F8F",
        "tbl_mission_log_00000_1F56040",
    }
