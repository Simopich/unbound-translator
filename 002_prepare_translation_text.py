#!/usr/bin/env python3

import argparse
import json
from pathlib import Path

from lib.translation_tokens import (
    remove_layout_tokens,
    replace_semantic_tokens_with_placeholders,
    strip_hma_quotes,
)


def iter_entries(data):
    for table in data.get("tables", []):
        for entry in table.get("entries", []):
            yield entry
    for entry in data.get("free_texts", []):
        yield entry
    for entry in data.get("entries", []):
        yield entry


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Prepare extracted Pokemon Unbound text for translation by adding "
            "layout-free translation_source fields."
        )
    )
    parser.add_argument("input", help="Extracted JSON file.")
    parser.add_argument(
        "-o",
        "--output",
        required=True,
        help="Prepared output JSON path.",
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        help="JSON indentation. Default: 2.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)

    data = json.loads(input_path.read_text(encoding="utf-8"))

    stats = {
        "entries": 0,
        "translation_sources": 0,
        "entries_with_layout_removed": 0,
        "layout_tokens_removed": 0,
        "semantic_tokens": 0,
    }

    for entry in iter_entries(data):
        stats["entries"] += 1
        original = strip_hma_quotes(entry.get("original", ""))
        translation_source, removed_layout = remove_layout_tokens(original)
        translation_source, placeholders = replace_semantic_tokens_with_placeholders(
            translation_source
        )
        entry["translation_source"] = translation_source
        if placeholders:
            entry["semantic_token_placeholders"] = placeholders
        else:
            entry.pop("semantic_token_placeholders", None)

        stats["translation_sources"] += int(bool(translation_source))
        stats["entries_with_layout_removed"] += int(bool(removed_layout))
        stats["layout_tokens_removed"] += len(removed_layout)
        stats["semantic_tokens"] += len(placeholders)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=args.indent) + "\n",
        encoding="utf-8",
    )

    for key, value in stats.items():
        print(f"{key}: {value}")
    print(f"output: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
