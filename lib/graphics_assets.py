"""Validated, reversible views of ROM graphics; no guessed tile arrangements."""
from __future__ import annotations

import hashlib
from lib.gba_graphics import decode_4bpp_tiles, encode_4bpp_tiles, decode_8bpp_tiles, encode_8bpp_tiles, lz77_decompress, parse_gba_palette


def graphics_format(asset):
    fmt = asset.get('format', '4bpp')
    if fmt == '4bpp':
        return 32, 16, decode_4bpp_tiles, encode_4bpp_tiles
    if fmt == '8bpp':
        return 64, 256, decode_8bpp_tiles, encode_8bpp_tiles
    raise ValueError('Only verified 4bpp/8bpp layouts are supported')


def address(value):
    return int(value, 0) if isinstance(value, str) else value


def read_blob(rom, spec):
    offset = address(spec['offset'])
    size = spec['decompressed_size']
    capacity = spec.get('compressed_size', size)
    if offset < 0 or capacity <= 0 or offset + capacity > len(rom):
        raise ValueError('Graphics source outside ROM')
    raw = bytes(rom[offset:offset + capacity])
    compression = spec.get('compressed', 'lz77')
    if compression not in ('lz77', 'none'):
        raise ValueError(f'Unsupported compression: {compression}')
    if compression == 'lz77' and len(raw) < 4:
        raise ValueError('Truncated graphics LZ77 header')
    data = lz77_decompress(raw) if compression == 'lz77' else raw
    if len(data) != size:
        raise ValueError(f'Graphics size mismatch: {len(data)} != {size}')
    if spec.get('sha256') and hashlib.sha256(data).hexdigest() != spec['sha256']:
        raise ValueError('Graphics source digest mismatch')
    for source in spec.get('pointer_sources', []):
        source = address(source)
        if source < 0 or source + 4 > len(rom) or int.from_bytes(rom[source:source + 4], 'little') != offset + 0x08000000:
            raise ValueError('Graphics pointer mismatch')
    return data


def parts(asset):
    return asset.get('parts', [asset])


def tile_cells(rom, part):
    """Yield (screen x, screen y, tile index, flips); maps use GBA screen blocks."""
    width, height = part['width_tiles'], part['height_tiles']
    if width <= 0 or height <= 0:
        raise ValueError('Invalid graphics dimensions')
    if part.get('tilemaps'):
        row = 0
        for spec in part['tilemaps']:
            view = dict(part, height_tiles=spec['height_tiles'], tilemap=spec)
            view.pop('tilemaps')
            for x, y, index, hf, vf in tile_cells(rom, view):
                yield x, y + row, index, hf, vf
            row += spec['height_tiles']
        if row != height:
            raise ValueError('Tilemap views do not fill canvas')
        return
    tilemap = part.get('tilemap')
    if tilemap:
        raw = read_blob(rom, tilemap)
        if len(raw) != width * height * 2:
            raise ValueError('Tilemap dimensions do not match its byte length')
        for y in range(height):
            for x in range(width):
                if tilemap.get('order', 'linear') == 'screenblocks':
                    if width % 32 or height % 32:
                        raise ValueError('Screenblock maps require multiples of 32 tiles')
                    i = ((y // 32) * (width // 32) + x // 32) * 1024 + (y % 32) * 32 + x % 32
                elif tilemap.get('order', 'linear') == 'linear':
                    i = y * width + x
                else:
                    raise ValueError('Unknown tilemap order')
                value = int.from_bytes(raw[i*2:i*2+2], 'little')
                # One palette per view. Preserve palette-bank bits in the original map.
                if part.get('format', '4bpp') != '8bpp' and value >> 12 not in tilemap.get('palette_banks', [tilemap.get('palette_bank', 0)]) and value != 0:
                    raise ValueError('Unexpected tilemap palette bank')
                yield x, y, (value & 1023) - tilemap.get('tile_base', 0), bool(value & 1024), bool(value & 2048)
    else:
        for y in range(height):
            for x in range(width):
                yield x, y, y * width + x, False, False


def render_asset(rom, asset):
    tile_bytes, color_limit, decode, _ = graphics_format(asset)
    width, height = asset['width_px'], asset['height_px']
    grid = [[0] * width for _ in range(height)]
    occupied = set()
    for part in parts(asset):
        raw = read_blob(rom, part)
        if len(raw) % tile_bytes:
            raise ValueError('Partial graphics tile')
        if not part.get('tilemap') and not part.get('tilemaps') and len(raw) != part['width_tiles'] * part['height_tiles'] * tile_bytes:
            raise ValueError('Tile grid would truncate or pad source data')
        tiles = decode(raw, 1, len(raw) // tile_bytes)
        ox, oy = part.get('x', 0), part.get('y', 0)
        for x, y, index, hf, vf in tile_cells(rom, dict(part, format=asset.get('format', '4bpp'))):
            if index < 0 or index >= len(raw) // tile_bytes:
                raise ValueError('Tilemap references missing tile')
            for py in range(8):
                for px in range(8):
                    dx, dy = ox + x*8 + px, oy + y*8 + py
                    if not (0 <= dx < width and 0 <= dy < height) or (dx, dy) in occupied:
                        raise ValueError('Graphics parts overlap or exceed canvas')
                    occupied.add((dx, dy))
                    grid[dy][dx] = tiles[index*8 + (7-py if vf else py)][7-px if hf else px]
    if len(occupied) != width * height:
        raise ValueError('Graphics parts do not cover canvas')
    if 'palette' in asset:
        palette = [tuple(c) for c in asset['palette']]
    elif 'palette_source' in asset:
        palette = parse_gba_palette(read_blob(rom, asset['palette_source']), asset.get('palette_count', color_limit))
    else:
        raise ValueError('Asset requires an explicit palette')
    if (color_limit == 16 and len(palette) != 16) or not 16 <= len(palette) <= color_limit:
        raise ValueError('Palette size does not match graphics format')
    if any(p >= len(palette) for row in grid for p in row):
        raise ValueError('Pixel references missing palette color')
    return grid, palette


def encode_asset(rom, asset, grid):
    """Invert the view, preserving unused tiles and rejecting conflicting shared tiles."""
    tile_bytes, color_limit, _, encode = graphics_format(asset)
    if len(grid) != asset['height_px'] or any(len(row) != asset['width_px'] for row in grid):
        raise ValueError('Localized PNG dimensions mismatch')
    palette_count = len(asset['palette']) if 'palette' in asset else asset.get('palette_count', color_limit)
    if any(not 0 <= p < min(color_limit, palette_count) for row in grid for p in row):
        raise ValueError('Localized PNG must use original palette indices')
    payloads = []
    for part in parts(asset):
        raw = bytearray(read_blob(rom, part))
        seen = {}
        ox, oy = part.get('x', 0), part.get('y', 0)
        for x, y, index, hf, vf in tile_cells(rom, dict(part, format=asset.get('format', '4bpp'))):
            if index < 0 or (index+1)*tile_bytes > len(raw):
                raise ValueError('Tilemap references missing tile')
            tile = [[grid[oy+y*8+(7-py if vf else py)][ox+x*8+(7-px if hf else px)] for px in range(8)] for py in range(8)]
            encoded = encode(tile, 1, 1)
            if index in seen and seen[index] != encoded:
                raise ValueError(f'Conflicting edits to shared tile {index}; all occurrences must agree')
            seen[index] = encoded
            raw[index*tile_bytes:(index+1)*tile_bytes] = encoded
        payloads.append((part, bytes(raw)))
    return payloads
