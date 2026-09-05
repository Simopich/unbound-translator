#!/usr/bin/env python3
"""Extract localized text graphics from Pokémon Unbound ROM into PNG files."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from lib.gba_graphics import (
    decode_4bpp_tiles,
    lz77_decompress,
    parse_gba_palette,
    write_png_indexed,
)

DEFAULT_PALETTE = [
    (0, 0, 0),
    (248, 248, 248),
    (200, 200, 200),
    (152, 152, 152),
    (104, 104, 104),
    (56, 56, 56),
    (248, 88, 88),
    (88, 248, 88),
    (88, 88, 248),
    (248, 248, 88),
    (248, 88, 248),
    (88, 248, 248),
    (176, 40, 40),
    (40, 176, 40),
    (40, 40, 176),
    (176, 176, 40),
]


def parse_address(val: str | int) -> int:
    if isinstance(val, int):
        return val
    return int(val, 16) if val.lower().startswith("0x") else int(val)


def extract_graphics(
    rom_path: Path,
    manifest_path: Path,
    output_dir: Path,
) -> int:
    if not rom_path.is_file():
        print(f"Error: ROM file not found: {rom_path}", file=sys.stderr)
        return 1

    with open(rom_path, "rb") as f:
        rom = f.read()

    if not manifest_path.is_file():
        print(f"Error: Manifest file not found: {manifest_path}", file=sys.stderr)
        return 1

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    assets = manifest.get("assets", [])
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Extracting {len(assets)} assets to {output_dir}...")
    extracted_count = 0

    for asset in assets:
        asset_id = asset["id"]
        filename = asset.get("filename", f"{asset_id}.png")
        offset = parse_address(asset["offset"])
        width_tiles = asset["width_tiles"]
        height_tiles = asset["height_tiles"]
        width_px = asset.get("width_px", width_tiles * 8)
        height_px = asset.get("height_px", height_tiles * 8)
        compressed = asset.get("compressed", "lz77")

        # Palette
        palette = DEFAULT_PALETTE
        pal_off_str = asset.get("palette_offset")
        if pal_off_str:
            pal_off = parse_address(pal_off_str)
            if 0 <= pal_off + 32 <= len(rom):
                raw_pal = parse_gba_palette(rom[pal_off : pal_off + 32])
                if any(c != (0, 0, 0) for c in raw_pal):
                    palette = raw_pal

        # Tile data
        try:
            if compressed == "lz77":
                tile_data = lz77_decompress(rom, offset)
            else:
                decomp_size = asset.get("decompressed_size", width_tiles * height_tiles * 32)
                tile_data = rom[offset : offset + decomp_size]
        except Exception as exc:
            print(f"  [FAIL] {asset_id} at 0x{offset:07X}: {exc}", file=sys.stderr)
            continue

        # Decode tiles to grid
        grid = decode_4bpp_tiles(tile_data, width_tiles, height_tiles)

        # Write PNG
        out_file = output_dir / filename
        write_png_indexed(str(out_file), width_px, height_px, grid, palette)
        extracted_count += 1
        print(
            f"  [OK] {filename:<28} offset=0x{offset:07X} "
            f"{width_px}x{height_px} ({len(tile_data)} bytes, {len(tile_data)//32} tiles)"
        )

    print(f"\nExtracted {extracted_count}/{len(assets)} graphics successfully.")
    return 0 if extracted_count == len(assets) else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract localized text graphics from Pokémon Unbound ROM"
    )
    parser.add_argument("rom", type=Path, help="Path to source ROM (e.g. rom/unbound.gba)")
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=Path("graphics/source"),
        help="Output directory for extracted PNGs (default: graphics/source)",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("graphics/manifest.json"),
        help="Path to graphics manifest JSON (default: graphics/manifest.json)",
    )
    args = parser.parse_args()
    return extract_graphics(args.rom, args.manifest, args.output_dir)


if __name__ == "__main__":
    sys.exit(main())
