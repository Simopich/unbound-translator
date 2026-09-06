"""Localized graphics patcher for Pokémon Unbound ROM."""

from __future__ import annotations

from dataclasses import dataclass

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from lib.gba_graphics import (
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
    """Patch verified indexed views; missing language files leave ROM unchanged."""
    if not (graphics_dir / target_lang).is_dir():
        return []
    manifest_path = graphics_dir / "manifest.json"
    if not manifest_path.is_file():
        return []
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("version") != 2:
        raise ValueError("Graphics patching requires a verified version-2 manifest")
    return patch_verified_graphics(
        rom, graphics_dir, target_lang, free_blocks, manifest, dry_run, fail_on_no_space
    )


def patch_verified_graphics(rom, graphics_dir, target_lang, free_blocks, manifest, dry_run, fail_on_no_space):
    """Plan all view edits before committing ROM bytes or allocator cursors."""
    import copy
    from lib.graphics_assets import address, encode_asset, read_blob, render_asset

    planned_blocks = copy.deepcopy(free_blocks)
    writes = []
    reports = []
    for asset in manifest['assets']:
        path = graphics_dir / target_lang / asset['filename']
        if not path.is_file():
            continue
        source_grid, source_palette = render_asset(rom, asset)
        w, h, grid, palette = read_png_indexed(str(path))
        if (w, h) != (asset['width_px'], asset['height_px']) or palette != source_palette:
            raise ValueError(f"{asset['id']}: preserve dimensions and indexed palette")
        if grid == source_grid:
            continue
        for index, (part, raw) in enumerate(encode_asset(rom, asset, grid)):
            if raw == read_blob(rom, part):
                continue
            payload = lz77_compress(raw, vram_safe=part.get('vram_safe', asset.get('vram_safe', False))) if part.get('compressed', 'lz77') == 'lz77' else raw
            offset = address(part['offset'])
            capacity = part.get('compressed_size', len(raw))
            destination = offset
            pointers = []
            status = 'patched_in_place'
            if len(payload) > capacity:
                if not part.get('pointer_sources'):
                    raise ValueError(f"{asset['id']}: relocation requires proven pointer sources")
                destination = allocate_from_free_blocks(planned_blocks, len(payload))
                if destination is None:
                    if fail_on_no_space:
                        raise RuntimeError(f"No free space for graphic {asset['id']}")
                    raise ValueError(f"Cannot partially patch multipart graphic {asset['id']}: no free space")
                if not (0 <= destination <= len(rom) - len(payload)) or any(b != 255 for b in rom[destination:destination+len(payload)]):
                    raise ValueError('Graphics relocation requires untouched FF space')
                status = 'relocated'
                pointers = [address(p) for p in part['pointer_sources']]
            writes.append((destination, payload))
            for pointer in pointers:
                writes.append((pointer, (destination + GBA_POINTER_BASE).to_bytes(4, 'little')))
            reports.append(dict(id=asset['id'], part=index, filename=asset['filename'], status=status,
                                original_offset=f'0x{offset:07X}', injected_offset=f'0x{destination:07X}',
                                bytes=len(payload), original_capacity=capacity, pointers_updated=len(pointers)))
    ordered = sorted(writes)
    for (start, data), (next_start, _) in zip(ordered, ordered[1:]):
        if start + len(data) > next_start:
            raise ValueError('Overlapping graphics writes')
    if not dry_run:
        for start, data in writes:
            rom[start:start + len(data)] = data
    for actual, planned in zip(free_blocks, planned_blocks):
        actual.cursor = planned.cursor
    return reports
