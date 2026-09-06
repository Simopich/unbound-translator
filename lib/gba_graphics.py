"""GBA graphics utilities: 4bpp/8bpp tiles, BGR555 palettes, LZ77, indexed PNGs."""

from __future__ import annotations

import os
import struct
import zlib
from typing import List, Optional, Sequence, Tuple

PNG_SIGNATURE = bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A])


# --- GBA BGR555 Palette Utilities ---

def gba_color_to_rgb(c16: int) -> Tuple[int, int, int]:
    """Convert a 15-bit BGR555 integer into an (R, G, B) 8-bit tuple."""
    r5 = c16 & 0x1F
    g5 = (c16 >> 5) & 0x1F
    b5 = (c16 >> 10) & 0x1F
    r8 = (r5 * 527 + 23) >> 6
    g8 = (g5 * 527 + 23) >> 6
    b8 = (b5 * 527 + 23) >> 6
    return (r8, g8, b8)


def rgb_to_gba_color(r: int, g: int, b: int) -> int:
    """Convert an (R, G, B) 8-bit triplet into a 15-bit BGR555 integer."""
    r5 = (r >> 3) & 0x1F
    g5 = (g >> 3) & 0x1F
    b5 = (b >> 3) & 0x1F
    return r5 | (g5 << 5) | (b5 << 10)


def parse_gba_palette(raw_bytes: bytes, count: int = 16) -> List[Tuple[int, int, int]]:
    """Parse raw ROM bytes into a list of (R, G, B) tuples."""
    palette = []
    for i in range(count):
        offset = i * 2
        if offset + 2 <= len(raw_bytes):
            val = struct.unpack('<H', raw_bytes[offset : offset + 2])[0]
            palette.append(gba_color_to_rgb(val))
        else:
            palette.append((0, 0, 0))
    return palette


def serialize_gba_palette(palette: Sequence[Tuple[int, int, int]], count: int = 16) -> bytes:
    """Serialize a list of (R, G, B) tuples into BGR555 little-endian bytes."""
    out = bytearray()
    for i in range(count):
        if i < len(palette):
            r, g, b = palette[i][:3]
            c16 = rgb_to_gba_color(r, g, b)
        else:
            c16 = 0
        out.extend(struct.pack('<H', c16))
    return bytes(out)


# --- 4bpp Tile Encoding and Decoding ---

def decode_8bpp_tiles(tile_data, width_tiles, height_tiles):
    """Decode complete 64-byte tiles without changing palette indices."""
    if width_tiles <= 0 or height_tiles <= 0 or len(tile_data) != width_tiles * height_tiles * 64:
        raise ValueError('8bpp tile dimensions do not match data')
    return [[tile_data[((y // 8) * width_tiles + x // 8) * 64 + (y % 8) * 8 + x % 8]
             for x in range(width_tiles * 8)] for y in range(height_tiles * 8)]


def encode_8bpp_tiles(grid, width_tiles, height_tiles):
    """Encode complete tiles, rejecting invalid dimensions or palette indices."""
    if width_tiles <= 0 or height_tiles <= 0 or len(grid) != height_tiles * 8 or any(len(row) != width_tiles * 8 for row in grid):
        raise ValueError('8bpp grid dimensions mismatch')
    if any(not isinstance(p, int) or not 0 <= p <= 255 for row in grid for p in row):
        raise ValueError('Invalid 8bpp palette index')
    return bytes(grid[ty * 8 + y][tx * 8 + x] for ty in range(height_tiles)
                 for tx in range(width_tiles) for y in range(8) for x in range(8))


def decode_4bpp_tiles(
    tile_data: bytes, width_tiles: int, height_tiles: int
) -> List[List[int]]:
    """Decode raw GBA 4bpp tiles into a 2D grid of color indices [y][x]."""
    width_px = width_tiles * 8
    height_px = height_tiles * 8
    grid = [[0] * width_px for _ in range(height_px)]

    num_tiles = len(tile_data) // 32
    tile_idx = 0
    for ty in range(height_tiles):
        for tx in range(width_tiles):
            if tile_idx >= num_tiles:
                break
            t_bytes = tile_data[tile_idx * 32 : (tile_idx + 1) * 32]
            for py in range(8):
                for px in range(4):
                    b = t_bytes[py * 4 + px]
                    grid[ty * 8 + py][tx * 8 + px * 2] = b & 0x0F
                    grid[ty * 8 + py][tx * 8 + px * 2 + 1] = (b >> 4) & 0x0F
            tile_idx += 1
    return grid


def encode_4bpp_tiles(
    grid: Sequence[Sequence[int]], width_tiles: int, height_tiles: int
) -> bytes:
    """Encode a 2D grid of color indices [y][x] into raw GBA 4bpp tile bytes."""
    out = bytearray()
    for ty in range(height_tiles):
        for tx in range(width_tiles):
            for py in range(8):
                y = ty * 8 + py
                row = grid[y] if y < len(grid) else []
                for px in range(4):
                    x1 = tx * 8 + px * 2
                    x2 = x1 + 1
                    p1 = (row[x1] & 0x0F) if x1 < len(row) else 0
                    p2 = (row[x2] & 0x0F) if x2 < len(row) else 0
                    out.append(p1 | (p2 << 4))
    return bytes(out)


# --- GBA LZ77 (Type 0x10) Compression and Decompression ---

def lz77_decompress(data: bytes, offset: int = 0) -> bytes:
    """Decompress GBA BIOS LZ77 (type 0x10) data starting at offset."""
    if offset >= len(data) or data[offset] != 0x10:
        raise ValueError(f'Invalid LZ77 header byte at offset 0x{offset:X}: {data[offset:offset+1]!r}')

    decomp_size = struct.unpack('<I', data[offset : offset + 4])[0] >> 8
    pos = offset + 4
    out = bytearray()

    while len(out) < decomp_size and pos < len(data):
        flags = data[pos]
        pos += 1
        for bit in range(8):
            if len(out) >= decomp_size:
                break
            if flags & (0x80 >> bit):
                if pos + 1 >= len(data):
                    raise ValueError('Truncated LZ77 compressed stream')
                b1 = data[pos]
                b2 = data[pos + 1]
                pos += 2
                length = (b1 >> 4) + 3
                disp = (((b1 & 0x0F) << 8) | b2) + 1
                if disp > len(out):
                    raise ValueError(
                        f'LZ77 invalid back-reference displacement {disp} > current size {len(out)}'
                    )
                for _ in range(length):
                    if len(out) >= decomp_size:
                        break
                    out.append(out[-disp])
            else:
                if pos >= len(data):
                    raise ValueError('Truncated LZ77 compressed stream')
                out.append(data[pos])
                pos += 1

    if len(out) != decomp_size:
        raise ValueError(
            f'Decompressed size mismatch: got {len(out)}, expected {decomp_size}'
        )
    return bytes(out)


def lz77_compress(data: bytes) -> bytes:
    """Compress data using GBA BIOS LZ77 (type 0x10)."""
    decomp_size = len(data)
    if decomp_size > 0x00FFFFFF:
        raise ValueError(f'Data too large for GBA LZ77 (max 16MB): {decomp_size} bytes')

    out = bytearray()
    out.extend(struct.pack('<I', (decomp_size << 8) | 0x10))

    pos = 0
    while pos < decomp_size:
        flag_pos = len(out)
        out.append(0)
        flag_byte = 0

        for bit in range(8):
            if pos >= decomp_size:
                break

            win_start = max(0, pos - 4096)
            best_len = 0
            best_disp = 0
            max_search_len = min(18, decomp_size - pos)

            if max_search_len >= 3:
                for candidate in range(pos - 1, win_start - 1, -1):
                    if data[candidate] != data[pos]:
                        continue
                    match_len = 0
                    while (
                        match_len < max_search_len
                        and data[candidate + match_len] == data[pos + match_len]
                    ):
                        match_len += 1
                    if match_len > best_len:
                        best_len = match_len
                        best_disp = pos - candidate
                        if best_len == 18:
                            break

            if best_len >= 3:
                flag_byte |= 0x80 >> bit
                b1 = ((best_len - 3) << 4) | (((best_disp - 1) >> 8) & 0x0F)
                b2 = (best_disp - 1) & 0xFF
                out.extend([b1, b2])
                pos += best_len
            else:
                out.append(data[pos])
                pos += 1

        out[flag_pos] = flag_byte

    while len(out) % 4 != 0:
        out.append(0)

    return bytes(out)


# --- Pure-Python Indexed PNG Writer and Reader ---

def _png_chunk(tag: bytes, data: bytes) -> bytes:
    c = tag + data
    crc = zlib.crc32(c) & 0xFFFFFFFF
    return struct.pack('>I', len(data)) + c + struct.pack('>I', crc)


def write_png_indexed(
    filepath: str,
    width: int,
    height: int,
    grid: Sequence[Sequence[int]],
    palette: Sequence[Tuple[int, int, int]],
) -> None:
    """Write an 8-bit indexed PNG with a color palette (PLTE)."""
    raw_scanlines = bytearray()
    for y in range(height):
        raw_scanlines.append(0)
        row = grid[y] if y < len(grid) else []
        for x in range(width):
            raw_scanlines.append(row[x] if x < len(row) else 0)

    compressed_idat = zlib.compress(bytes(raw_scanlines), level=9)

    plte_data = bytearray()
    for i in range(min(256, max(16, len(palette)))):
        if i < len(palette):
            r, g, b = palette[i][:3]
        else:
            r, g, b = 0, 0, 0
        plte_data.extend([r & 0xFF, g & 0xFF, b & 0xFF])

    png = bytearray(PNG_SIGNATURE)
    ihdr = struct.pack('>IIBBBBB', width, height, 8, 3, 0, 0, 0)
    png.extend(_png_chunk(b'IHDR', ihdr))
    png.extend(_png_chunk(b'PLTE', bytes(plte_data)))
    png.extend(_png_chunk(b'IDAT', compressed_idat))
    png.extend(_png_chunk(b'IEND', b''))

    os.makedirs(os.path.dirname(filepath) or '.', exist_ok=True)
    with open(filepath, 'wb') as f:
        f.write(png)


def read_png_indexed(
    filepath: str,
    target_palette: Optional[Sequence[Tuple[int, int, int]]] = None,
) -> Tuple[int, int, List[List[int]], List[Tuple[int, int, int]]]:
    """Read an indexed or RGBA PNG. Returns (width, height, grid, palette)."""
    with open(filepath, 'rb') as f:
        data = f.read()

    if not data.startswith(PNG_SIGNATURE):
        raise ValueError(f'Not a valid PNG file: {filepath}')

    pos = 8
    width = height = bit_depth = color_type = 0
    palette: List[Tuple[int, int, int]] = []
    idat_parts = []

    while pos < len(data):
        length = struct.unpack('>I', data[pos : pos + 4])[0]
        tag = data[pos + 4 : pos + 8]
        chunk_data = data[pos + 8 : pos + 8 + length]
        pos += 12 + length

        if tag == b'IHDR':
            width, height, bit_depth, color_type = struct.unpack(
                '>IIBB', chunk_data[:10]
            )
        elif tag == b'PLTE':
            for i in range(0, len(chunk_data), 3):
                palette.append(
                    (chunk_data[i], chunk_data[i + 1], chunk_data[i + 2])
                )
        elif tag == b'IDAT':
            idat_parts.append(chunk_data)
        elif tag == b'IEND':
            break

    raw = zlib.decompress(b''.join(idat_parts))
    grid = [[0] * width for _ in range(height)]

    if color_type == 3:
        if bit_depth == 8:
            stride = width
        elif bit_depth == 4:
            stride = (width + 1) // 2
        else:
            raise ValueError(f'Unsupported indexed bit depth: {bit_depth}')

        bytes_per_row = stride + 1
        recon_rows: List[bytearray] = []

        for y in range(height):
            filter_type = raw[y * bytes_per_row]
            scanline = raw[y * bytes_per_row + 1 : (y + 1) * bytes_per_row]
            recon = bytearray(stride)
            prev_row = recon_rows[y - 1] if y > 0 else bytearray(stride)

            for x in range(stride):
                filt = scanline[x]
                a = recon[x - 1] if x > 0 else 0
                b = prev_row[x]
                c = prev_row[x - 1] if x > 0 else 0

                if filter_type == 0:
                    val = filt
                elif filter_type == 1:
                    val = (filt + a) & 0xFF
                elif filter_type == 2:
                    val = (filt + b) & 0xFF
                elif filter_type == 3:
                    val = (filt + ((a + b) >> 1)) & 0xFF
                elif filter_type == 4:
                    p = a + b - c
                    pa = abs(p - a)
                    pb = abs(p - b)
                    pc = abs(p - c)
                    pr = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                    val = (filt + pr) & 0xFF
                else:
                    val = filt
                recon[x] = val
            recon_rows.append(recon)

            if bit_depth == 8:
                for px in range(width):
                    grid[y][px] = recon[px]
            elif bit_depth == 4:
                for px in range(width):
                    byte_val = recon[px // 2]
                    grid[y][px] = (byte_val >> 4) if px % 2 == 0 else (byte_val & 0x0F)

    elif color_type in (2, 6):
        bpp = 3 if color_type == 2 else 4
        stride = width * bpp
        bytes_per_row = stride + 1
        recon_rows = []

        effective_pal = target_palette or palette
        if not effective_pal:
            raise ValueError('Truecolor PNG requires a palette for color-matching')

        def closest_color(rgb: Tuple[int, int, int]) -> int:
            r, g, b = rgb
            best_idx = 0
            best_dist = float('inf')
            for idx, (pr, pg, pb) in enumerate(effective_pal):
                dist = (r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2
                if dist < best_dist:
                    best_dist = dist
                    best_idx = idx
            return best_idx

        for y in range(height):
            filter_type = raw[y * bytes_per_row]
            scanline = raw[y * bytes_per_row + 1 : (y + 1) * bytes_per_row]
            recon = bytearray(stride)
            prev_row = recon_rows[y - 1] if y > 0 else bytearray(stride)

            for x in range(stride):
                filt = scanline[x]
                a = recon[x - bpp] if x >= bpp else 0
                b = prev_row[x]
                c = prev_row[x - bpp] if x >= bpp else 0

                if filter_type == 0:
                    val = filt
                elif filter_type == 1:
                    val = (filt + a) & 0xFF
                elif filter_type == 2:
                    val = (filt + b) & 0xFF
                elif filter_type == 3:
                    val = (filt + ((a + b) >> 1)) & 0xFF
                elif filter_type == 4:
                    p = a + b - c
                    pa = abs(p - a)
                    pb = abs(p - b)
                    pc = abs(p - c)
                    pr = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                    val = (filt + pr) & 0xFF
                else:
                    val = filt
                recon[x] = val
            recon_rows.append(recon)

            for px in range(width):
                r = recon[px * bpp]
                g = recon[px * bpp + 1]
                b = recon[px * bpp + 2]
                grid[y][px] = closest_color((r, g, b))

    else:
        raise ValueError(f'Unsupported PNG color type: {color_type}')

    return width, height, grid, palette
