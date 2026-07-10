from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.helpers import REPO_ROOT


def test_controlfix_cli_regression_fixture_preserves_tokens_and_layout(tmp_path):
    output_path = tmp_path / "controlfixed.json"
    report_path = tmp_path / "report.json"

    subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "004_controlfix_translations.py"),
            str(REPO_ROOT / "tests/fixtures/controlfix_input.json"),
            "-o",
            str(output_path),
            "--source",
            str(REPO_ROOT / "tests/fixtures/controlfix_source.json"),
            "--report",
            str(report_path),
            "--wrap-width",
            "18",
        ],
        check=True,
        cwd=REPO_ROOT,
    )

    data = json.loads(output_path.read_text(encoding="utf-8"))
    by_id = {entry["id"]: entry for entry in data["entries"]}

    assert by_id["scr_token_layout"]["translated"].startswith("[black]Ciao [player]!")
    assert "\n" in by_id["scr_token_layout"]["translated"]
    assert by_id["tbl_menu_yes_no"]["translated"] == "Sì\nNo"
    assert by_id["tbl_battle_messages_00412_3FE6D5"]["translated"] == "Cosa farà\n\\\\12?"

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["stats"]["remaining_control_mismatches"] == 0
    assert report["stats"]["menu_line_break_repairs"] == 1
    assert report["stats"]["battle_prompt_layout_repairs"] == 1
