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
