import json
import os
import tempfile
import unittest
from pathlib import Path

from lib.gba_graphics import (
    decode_4bpp_tiles,
    encode_4bpp_tiles,
    lz77_compress,
    lz77_decompress,
    read_png_indexed,
    write_png_indexed,
)
from lib.graphics_patcher import FreeBlock, patch_graphics

REPO_ROOT = Path(__file__).resolve().parents[1]
GRAPHICS_DIR = REPO_ROOT / "graphics"
MANIFEST_PATH = GRAPHICS_DIR / "manifest.json"
ROM_PATH = REPO_ROOT / "rom" / "unbound.gba"


class TestGbaGraphicsCodec(unittest.TestCase):
    def test_lz77_roundtrip_simple(self):
        data = b"HELLO WORLD! HELLO POKEMON! HELLO UNBOUND! " * 10
        compressed = lz77_compress(data)
        self.assertEqual(compressed[0], 0x10)
        decompressed = lz77_decompress(compressed)
        self.assertEqual(decompressed, data)

    def test_lz77_roundtrip_binary(self):
        # Semi-random pattern with repeating runs
        data = bytearray()
        for i in range(256):
            data.extend(bytes([i % 16]) * 8)
        raw = bytes(data)
        compressed = lz77_compress(raw)
        decompressed = lz77_decompress(compressed)
        self.assertEqual(decompressed, raw)

    def test_4bpp_tile_roundtrip(self):
        # 16x8 image (2x1 tiles = 2 tiles)
        width_tiles = 2
        height_tiles = 1
        grid = [
            [x % 16 for x in range(16)]
            for _ in range(8)
        ]
        encoded = encode_4bpp_tiles(grid, width_tiles, height_tiles)
        self.assertEqual(len(encoded), 2 * 32)
        decoded_grid = decode_4bpp_tiles(encoded, width_tiles, height_tiles)
        self.assertEqual(decoded_grid, grid)

    def test_png_indexed_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            png_path = Path(tmpdir) / "test.png"
            palette = [(i * 16, i * 16, i * 16) for i in range(16)]
            grid = [[(x + y) % 16 for x in range(16)] for y in range(16)]
            write_png_indexed(str(png_path), 16, 16, grid, palette)
            self.assertTrue(png_path.is_file())

            w, h, read_grid, read_pal = read_png_indexed(str(png_path))
            self.assertEqual((w, h), (16, 16))
            self.assertEqual(read_grid, grid)
            self.assertEqual(read_pal[:16], palette)


class TestGraphicsManifestAndSource(unittest.TestCase):
    def setUp(self):
        self.assertTrue(MANIFEST_PATH.is_file(), "manifest.json must exist")
        with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
            self.manifest = json.load(f)

    def test_manifest_structure(self):
        assets = self.manifest.get("assets", [])
        self.assertEqual(len(assets), 17, "Expected 17 text graphics assets")
        for asset in assets:
            self.assertIn("id", asset)
            self.assertIn("filename", asset)
            self.assertIn("offset", asset)
            self.assertIn("pointer_sources", asset)
            self.assertIn("width_tiles", asset)
            self.assertIn("height_tiles", asset)
            self.assertIn("width_px", asset)
            self.assertIn("height_px", asset)
            self.assertIn("compressed", asset)
            self.assertEqual(asset["width_px"], asset["width_tiles"] * 8)
            self.assertEqual(asset["height_px"], asset["height_tiles"] * 8)

    def test_all_source_pngs_exist(self):
        source_dir = GRAPHICS_DIR / "source"
        self.assertTrue(source_dir.is_dir(), "graphics/source/ must exist")
        for asset in self.manifest["assets"]:
            png_path = source_dir / asset["filename"]
            self.assertTrue(
                png_path.is_file(),
                f"Missing extracted source PNG: {png_path}",
            )

    @unittest.skipUnless(ROM_PATH.is_file(), "rom/unbound.gba not present")
    def test_all_pointers_match_rom(self):
        rom = ROM_PATH.read_bytes()
        for asset in self.manifest["assets"]:
            asset_off = int(asset["offset"], 16)
            expected_ptr = 0x08000000 + asset_off
            for src in asset["pointer_sources"]:
                src_off = int(src, 16)
                actual_ptr = int.from_bytes(rom[src_off : src_off + 4], "little")
                self.assertEqual(
                    actual_ptr,
                    expected_ptr,
                    f"Pointer mismatch for {asset['id']}: 0x{src_off:07X} -> 0x{actual_ptr:08X}, expected 0x{expected_ptr:08X}",
                )


class TestGraphicsPatcher(unittest.TestCase):
    def setUp(self):
        with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
            self.manifest = json.load(f)

    def test_fallback_when_language_folder_missing(self):
        fake_rom = bytearray(b"\x00" * 0x10000)
        free_blocks = [FreeBlock(0x8000, 0xA000, 0x8000)]
        reports = patch_graphics(fake_rom, GRAPHICS_DIR, "nonexistent_lang", free_blocks)
        self.assertEqual(reports, [])
        self.assertEqual(fake_rom, bytearray(b"\x00" * 0x10000))

    def test_skip_when_identical_to_source(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            test_dir = Path(tmpdir)
            # copy manifest
            (test_dir / "manifest.json").write_text(json.dumps(self.manifest), encoding="utf-8")
            # copy source folder
            src_dir = test_dir / "source"
            src_dir.mkdir()
            first_asset = self.manifest["assets"][0]
            real_src_png = GRAPHICS_DIR / "source" / first_asset["filename"]
            (src_dir / first_asset["filename"]).write_bytes(real_src_png.read_bytes())

            # language folder with identical file
            lang_dir = test_dir / "it"
            lang_dir.mkdir()
            (lang_dir / first_asset["filename"]).write_bytes(real_src_png.read_bytes())

            fake_rom = bytearray(0x2000000)
            free_blocks = [FreeBlock(0x1F00000, 0x1F10000, 0x1F00000)]
            reports = patch_graphics(fake_rom, test_dir, "it", free_blocks)
            self.assertEqual(reports, [])

    def test_patch_in_place_when_fits(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            test_dir = Path(tmpdir)
            first_asset = self.manifest["assets"][0]
            test_manifest = {"version": 1, "assets": [first_asset]}
            (test_dir / "manifest.json").write_text(json.dumps(test_manifest), encoding="utf-8")

            src_dir = test_dir / "source"
            src_dir.mkdir()
            real_src_png = GRAPHICS_DIR / "source" / first_asset["filename"]
            (src_dir / first_asset["filename"]).write_bytes(real_src_png.read_bytes())

            # modified image in language folder
            lang_dir = test_dir / "it"
            lang_dir.mkdir()
            w, h, grid, pal = read_png_indexed(str(real_src_png))
            # fill with a single color index
            for r in range(h):
                for c in range(w):
                    grid[r][c] = 1
            write_png_indexed(str(lang_dir / first_asset["filename"]), w, h, grid, pal)

            fake_rom = bytearray(0x2000000)
            free_blocks = [FreeBlock(0x1F00000, 0x1F10000, 0x1F00000)]
            asset_off = int(first_asset["offset"], 16)

            reports = patch_graphics(fake_rom, test_dir, "it", free_blocks)
            self.assertEqual(len(reports), 1)
            self.assertEqual(reports[0]["status"], "patched_in_place")
            self.assertEqual(reports[0]["original_offset"], f"0x{asset_off:07X}")
            self.assertEqual(reports[0]["injected_offset"], f"0x{asset_off:07X}")
            # Ensure fake_rom at asset_off is modified (starts with 0x10 LZ77 header)
            self.assertEqual(fake_rom[asset_off], 0x10)

    def test_relocation_when_oversized(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            test_dir = Path(tmpdir)
            first_asset = dict(self.manifest["assets"][0])
            # Artificial tiny slot size to force relocation
            first_asset["compressed_size"] = 10
            test_manifest = {"version": 1, "assets": [first_asset]}
            (test_dir / "manifest.json").write_text(json.dumps(test_manifest), encoding="utf-8")

            src_dir = test_dir / "source"
            src_dir.mkdir()
            real_src_png = GRAPHICS_DIR / "source" / first_asset["filename"]
            (src_dir / first_asset["filename"]).write_bytes(real_src_png.read_bytes())

            lang_dir = test_dir / "it"
            lang_dir.mkdir()
            w, h, grid, pal = read_png_indexed(str(real_src_png))
            # modify image
            grid[0][0] = (grid[0][0] + 1) % 16
            write_png_indexed(str(lang_dir / first_asset["filename"]), w, h, grid, pal)

            fake_rom = bytearray(0x2000000)
            free_blocks = [FreeBlock(0x1F00000, 0x1F10000, 0x1F00000)]
            ptr_src = int(first_asset["pointer_sources"][0], 16)

            reports = patch_graphics(fake_rom, test_dir, "it", free_blocks)
            self.assertEqual(len(reports), 1)
            self.assertEqual(reports[0]["status"], "relocated")
            self.assertEqual(reports[0]["injected_offset"], "0x1F00000")
            # Pointer source in fake_rom should now point to 0x08000000 + 0x1F00000
            new_ptr = int.from_bytes(fake_rom[ptr_src : ptr_src + 4], "little")
            self.assertEqual(new_ptr, 0x08000000 + 0x1F00000)


if __name__ == "__main__":
    unittest.main()
