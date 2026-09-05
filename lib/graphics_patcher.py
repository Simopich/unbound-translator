"""Localized graphics patcher for Pokémon Unbound ROM."""

from __future__ import annotations

from dataclasses import dataclass

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from lib.gba_graphics import (
    encode_4bpp_tiles,
    lz77_compress,
    read_png_indexed,
)

GBA_POINTER_BASE = 0x08000000

@dataclass
class FreeBlock:
    start: int
    end: int
    cursor: int
    kind: str = "vetted_ff"


def parse_address(val: str | int) -> int:
    if isinstance(val, int):
        return val
    return int(val, 16) if val.lower().startswith("0x") else int(val)


def align_up(val: int, alignment: int) -> int:
    if alignment <= 1:
        return val
    return (val + alignment - 1) // alignment * alignment


def allocate_from_free_blocks(blocks: List[Any], size: int, alignment: int = 4) -> Optional[int]:
    best_idx = None
    best_waste = float("inf")
    best_offset = None

    for i, block in enumerate(blocks):
        aligned = align_up(block.cursor, alignment)
        if aligned + size <= block.end:
            waste = (block.end - block.cursor) - size
            if waste < best_waste:
                best_waste = waste
                best_idx = i
                best_offset = aligned

    if best_idx is not None and best_offset is not None:
        block = blocks[best_idx]
        block.cursor = best_offset + size
        return best_offset
    return None


def patch_graphics(
    rom: bytearray,
    graphics_dir: Path,
    target_lang: str,
    free_blocks: List[Any],
    dry_run: bool = False,
    fail_on_no_space: bool = False,
) -> List[Dict[str, Any]]:
    """Patch localized graphics for target_lang into rom.

    If a graphic is not present in graphics/<target_lang>/, falls back to source (does not patch).
    """
    lang_dir = graphics_dir / target_lang
    if not lang_dir.is_dir():
        return []

    manifest_path = graphics_dir / "manifest.json"
    if not manifest_path.is_file():
        return []

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    source_dir = graphics_dir / "source"
    assets = manifest.get("assets", [])
    reports: List[Dict[str, Any]] = []

    for asset in assets:
        filename = asset.get("filename", f"{asset['id']}.png")
        target_png = lang_dir / filename

        # Fallback to source: if not present in specific language, don't patch
        if not target_png.is_file():
            continue

        source_png = source_dir / filename
        if source_png.is_file():
            # Check if identical to source (no changes needed)
            if target_png.read_bytes() == source_png.read_bytes():
                continue

        # Load translated PNG
        width_tiles = asset["width_tiles"]
        height_tiles = asset["height_tiles"]
        decomp_size = asset.get("decompressed_size", width_tiles * height_tiles * 32)
        compressed = asset.get("compressed", "lz77")
        asset_offset = parse_address(asset["offset"])
        slot_size = asset.get("compressed_size", decomp_size)

        w, h, grid, pal = read_png_indexed(str(target_png))
        tile_bytes = encode_4bpp_tiles(grid, width_tiles, height_tiles)
        if decomp_size:
            tile_bytes = tile_bytes[:decomp_size]

        if compressed == "lz77":
            payload = lz77_compress(tile_bytes)
        else:
            payload = tile_bytes

        # Determine placement: in-place vs relocated
        pointers_updated = 0
        if len(payload) <= slot_size:
            status = "patched_in_place"
            dest_offset = asset_offset
            if not dry_run:
                rom[dest_offset : dest_offset + len(payload)] = payload
                pad_len = slot_size - len(payload)
                if pad_len > 0:
                    rom[dest_offset + len(payload) : dest_offset + slot_size] = bytes(pad_len)
        else:
            dest_offset = allocate_from_free_blocks(free_blocks, len(payload), alignment=4)
            if dest_offset is None:
                if fail_on_no_space:
                    raise RuntimeError(
                        f"No free space to allocate {len(payload)} bytes for oversized graphic '{asset['id']}'"
                    )
                status = "skipped_no_space"
                dest_offset = asset_offset
            else:
                status = "relocated"
                if not dry_run:
                    rom[dest_offset : dest_offset + len(payload)] = payload
                    new_ptr = GBA_POINTER_BASE + dest_offset
                    for src_str in asset.get("pointer_sources", []):
                        src_off = parse_address(src_str)
                        if 0 <= src_off + 4 <= len(rom):
                            rom[src_off : src_off + 4] = new_ptr.to_bytes(4, "little")
                            pointers_updated += 1
                else:
                    pointers_updated = len(asset.get("pointer_sources", []))

        reports.append(
            {
                "id": asset["id"],
                "filename": filename,
                "status": status,
                "original_offset": f"0x{asset_offset:07X}",
                "injected_offset": f"0x{dest_offset:07X}",
                "bytes": len(payload),
                "original_capacity": slot_size,
                "pointers_updated": pointers_updated,
            }
        )

    return reports
