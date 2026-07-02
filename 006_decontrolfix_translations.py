#!/usr/bin/env python3

import argparse
import json
from pathlib import Path

from lib.translation_tokens import remove_layout_tokens


def iter_entries(data):
    for table in data.get("tables", []):
        for entry in table.get("entries", []):
            yield entry
    for entry in data.get("free_texts", []):
        yield entry
    for entry in data.get("entries", []):
        yield entry


def clean_translation(text, restore_apostrophes=False):
    clean, removed_layout = remove_layout_tokens(text)
    if restore_apostrophes:
        clean = clean.replace("{B4}", "'").replace("{B3}", "'")
    return clean, removed_layout


def main():
    parser = argparse.ArgumentParser(
        description="Remove controlfix layout from translated JSON so translations are easier to edit."
    )
    parser.add_argument(
        "input",
        help="Controlfixed translated JSON to clean.",
    )
    parser.add_argument(
        "-o",
        "--output",
        required=True,
        help="Clean editable output JSON.",
    )
    parser.add_argument(
        "--field",
        default="translated",
        help="Entry field to clean. Default: translated.",
    )
    parser.add_argument(
        "--backup-field",
        default="translated_controlfixed",
        help=(
            "Field where the original controlfixed value is saved when changed. "
            "Use an empty value to disable. Default: translated_controlfixed."
        ),
    )
    parser.add_argument(
        "--layout-field",
        default="removed_controlfix_layout",
        help=(
            "Field where removed layout tokens are saved when non-empty. "
            "Use an empty value to disable. Default: removed_controlfix_layout."
        ),
    )
    parser.add_argument(
        "--restore-apostrophes",
        action="store_true",
        help="Convert raw apostrophe bytes {B4}/{B3} back to ' for editing.",
    )
    args = parser.parse_args()

    data = json.loads(Path(args.input).read_text(encoding="utf-8"))

    stats = {
        "entries": 0,
        "translated": 0,
        "changed": 0,
        "layout_tokens_removed": 0,
        "apostrophes_restored": 0,
    }

    for entry in iter_entries(data):
        stats["entries"] += 1
        value = entry.get(args.field)
        if not isinstance(value, str) or not value:
            continue

        stats["translated"] += 1
        clean, removed_layout = clean_translation(value, args.restore_apostrophes)
        stats["layout_tokens_removed"] += len(removed_layout)
        if args.restore_apostrophes:
            stats["apostrophes_restored"] += value.count("{B4}") + value.count("{B3}")

        if clean == value:
            if args.layout_field:
                entry.pop(args.layout_field, None)
            continue

        if args.backup_field and args.backup_field not in entry:
            entry[args.backup_field] = value
        if args.layout_field:
            entry[args.layout_field] = removed_layout
        entry[args.field] = clean
        stats["changed"] += 1

    Path(args.output).write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    for key, value in stats.items():
        print(f"{key}: {value}")
    print(f"output: {args.output}")


if __name__ == "__main__":
    main()
