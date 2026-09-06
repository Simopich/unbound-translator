#!/usr/bin/env python3
"""Extract verified text-bearing graphics in their reconstructed screen layout."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from lib.gba_graphics import write_png_indexed
from lib.graphics_assets import encode_asset, parts, read_blob, render_asset


def extract_graphics(rom_path: Path, manifest_path: Path, output_dir: Path) -> int:
    try:
        rom = rom_path.read_bytes()
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        if manifest.get('version') != 2:
            raise ValueError('Unsupported graphics manifest; rebuild the verified version-2 manifest')
        if hashlib.md5(rom).hexdigest() != manifest['rom_md5']:
            raise ValueError('Wrong source ROM MD5')
        assets = manifest['assets']
        names = [a['filename'] for a in assets]
        if len(set(names)) != len(names) or any(Path(n).name != n or not n.endswith('.png') for n in names):
            raise ValueError('Duplicate or unsafe graphics filenames')
        # Validate every asset before writing anything. A rendered map must round-trip.
        rendered = []
        for asset in assets:
            grid, palette = render_asset(rom, asset)
            for part, encoded in encode_asset(rom, asset, grid):
                if encoded != read_blob(rom, part):
                    raise ValueError(f"Lossy graphics view: {asset['id']}")
            rendered.append((asset, grid, palette))
        output_dir.mkdir(parents=True, exist_ok=True)
        for asset, grid, palette in rendered:
            write_png_indexed(str(output_dir / asset['filename']), asset['width_px'], asset['height_px'], grid, palette)
            print(f"[OK] {asset['filename']} ({asset['width_px']}x{asset['height_px']})")
        print(f'Extracted {len(rendered)} verified text graphics; see manifest coverage limitations.')
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print(f'Graphics extraction failed: {exc}', file=sys.stderr)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('rom', type=Path)
    parser.add_argument('-o', '--output-dir', type=Path, default=Path('graphics/source'))
    parser.add_argument('--manifest', type=Path, default=Path('graphics/manifest.json'))
    args = parser.parse_args()
    return extract_graphics(args.rom, args.manifest, args.output_dir)


if __name__ == '__main__':
    sys.exit(main())
