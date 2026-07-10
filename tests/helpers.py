from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def load_script_module(script_name: str, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, REPO_ROOT / script_name)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module
