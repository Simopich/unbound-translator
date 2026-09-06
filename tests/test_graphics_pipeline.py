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


from lib.graphics_assets import encode_asset, read_blob, render_asset
import hashlib
import importlib.util


class TestVerifiedGraphics(unittest.TestCase):
    def fixture(self):
        # Asymmetric tile referenced normally, flipped horizontally and vertically.
        raw = encode_4bpp_tiles([[x+y for x in range(8)] for y in range(8)], 1, 1)
        rom = bytearray(4096)
        rom[64:96] = raw
        rom[128:134] = b'\x00\x00\x00\x04\x00\x08'
        rom[16:20] = (0x08000040).to_bytes(4, 'little')
        asset = dict(id='test', filename='test.png', offset=64, compressed='none',
                     decompressed_size=32, compressed_size=32, pointer_sources=[16],
                     width_tiles=3, height_tiles=1, width_px=24, height_px=8,
                     palette=[(i*17,)*3 for i in range(16)],
                     tilemap=dict(offset=128, compressed='none', decompressed_size=6))
        return rom, asset

    def test_map_flips_and_roundtrip(self):
        rom, asset = self.fixture()
        grid, _ = render_asset(rom, asset)
        self.assertEqual(grid[0][:8], list(range(8)))
        self.assertEqual(grid[0][8:16], list(reversed(range(8))))
        self.assertEqual(grid[0][16:24], list(range(7,15)))
        self.assertEqual(encode_asset(rom, asset, grid)[0][1], bytes(rom[64:96]))

    def test_conflicting_shared_tile_edit_rejected(self):
        rom, asset = self.fixture()
        grid, _ = render_asset(rom, asset)
        grid[0][0] = 15
        with self.assertRaisesRegex(ValueError, 'shared tile'):
            encode_asset(rom, asset, grid)

    def test_unused_tiles_preserved(self):
        rom, asset = self.fixture()
        rom[96:128] = bytes([123])*32
        asset.update(decompressed_size=64, compressed_size=64)
        grid, _ = render_asset(rom, asset)
        self.assertEqual(encode_asset(rom, asset, grid)[0][1], bytes(rom[64:128]))

    def test_bad_map_pointer_size_and_indices_rejected(self):
        for error in ['pointer', 'size', 'map', 'index']:
            rom, asset = self.fixture()
            if error == 'pointer': rom[16] = 0
            elif error == 'size': asset['tilemap']['decompressed_size'] = 4
            elif error == 'map': rom[128] = 5
            else: asset['decompressed_size'] = 31
            with self.subTest(error=error), self.assertRaises(ValueError):
                render_asset(rom, asset)

    def test_raw_grid_cannot_silently_drop_tiles(self):
        rom, asset = self.fixture()
        asset.pop('tilemap')
        with self.assertRaisesRegex(ValueError, 'truncate or pad'):
            render_asset(rom, asset)

    def test_multipart_roundtrip(self):
        rom, part = self.fixture()
        part.pop('tilemap')
        part.update(width_tiles=1, height_tiles=1)
        second = dict(part, x=8)
        asset = dict(id='parts', width_px=16, height_px=8, parts=[part, second], palette=part['palette'])
        grid, _ = render_asset(rom, asset)
        self.assertEqual(grid[0], list(range(8))*2)
        self.assertTrue(all(raw == bytes(rom[64:96]) for _, raw in encode_asset(rom, asset, grid)))

    def test_patch_transaction_and_dimensions(self):
        rom, asset = self.fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root/'it').mkdir()
            (root/'manifest.json').write_text(json.dumps(dict(version=2, assets=[asset])))
            grid, palette = render_asset(rom, asset)
            # Change every instance consistently.
            grid = [[(p+1)%16 for p in row] for row in grid]
            write_png_indexed(str(root/'it/test.png'),24,8,grid,palette)
            before = bytes(rom)
            patch_graphics(rom, root, 'it', [])
            self.assertNotEqual(rom[64:96], before[64:96])
            self.assertEqual(rom[128:134], before[128:134])
            rom[:] = before
            write_png_indexed(str(root/'it/test.png'),23,8,grid,palette)
            with self.assertRaises(ValueError):patch_graphics(rom, root, 'it', [])
            self.assertEqual(bytes(rom), before)

    def test_later_bad_asset_rolls_back_earlier_plan(self):
        rom, asset = self.fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp);(root/'it').mkdir()
            second = dict(asset, id='bad', filename='bad.png')
            (root/'manifest.json').write_text(json.dumps(dict(version=2, assets=[asset,second])))
            grid,pal=render_asset(rom,asset)
            grid=[[(p+1)%16 for p in row] for row in grid]
            write_png_indexed(str(root/'it/test.png'),24,8,grid,pal)
            write_png_indexed(str(root/'it/bad.png'),16,8,grid,pal)
            before=bytes(rom);blocks=[FreeBlock(2048,4096,2048)]
            with self.assertRaises(ValueError):patch_graphics(rom,root,'it',blocks)
            self.assertEqual(bytes(rom),before)
            self.assertEqual(blocks[0].cursor,2048)

    def test_relocation_and_dry_run_reserve_same_space(self):
        rom, asset = self.fixture()
        asset.pop('tilemap')
        asset.update(width_tiles=1, height_tiles=1, width_px=8, compressed='lz77')
        old = lz77_compress(bytes(32))
        rom[64:64+len(old)] = old
        asset['compressed_size'] = len(old)
        rom[2048:] = bytes([255])*2048
        grid = [[(x*3+y*7)%16 for x in range(8)] for y in range(8)]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root/'it').mkdir()
            (root/'manifest.json').write_text(json.dumps(dict(version=2, assets=[asset])))
            write_png_indexed(str(root/'it/test.png'),8,8,grid,asset['palette'])
            before=bytes(rom)
            dry_blocks=[FreeBlock(2048,4096,2048)]
            dry=patch_graphics(rom,root,'it',dry_blocks,dry_run=True)
            self.assertEqual(bytes(rom),before)
            blocks=[FreeBlock(2048,4096,2048)]
            reports=patch_graphics(rom,root,'it',blocks)
            self.assertEqual(reports,dry)
            self.assertEqual(blocks[0].cursor,dry_blocks[0].cursor)
            self.assertEqual(reports[0]['status'],'relocated')
            self.assertEqual(int.from_bytes(rom[16:20],'little'),0x08000800)
            self.assertEqual(lz77_decompress(rom,2048),encode_4bpp_tiles(grid,1,1))
            self.assertEqual(rom[64:64+len(old)],old)
            rom[:]=before
            with self.assertRaises(RuntimeError):
                patch_graphics(rom,root,'it',[],fail_on_no_space=True)
            self.assertEqual(bytes(rom),before)

    def test_extraction_wrong_rom_writes_nothing(self):
        spec=importlib.util.spec_from_file_location('graphics_extractor',REPO_ROOT/'007_extract_graphics.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'rom.gba').write_bytes(bytes(256))
            self.assertEqual(module.extract_graphics(root/'rom.gba',MANIFEST_PATH,root/'output'),1)
            self.assertFalse((root/'output').exists())

    def test_checked_in_manifest_and_sources(self):
        manifest=json.loads(MANIFEST_PATH.read_text())
        self.assertEqual(manifest['version'],2)
        self.assertFalse(manifest['coverage']['complete'])
        expected={a['filename'] for a in manifest['assets']}
        self.assertIn('pokemon_types.png', expected, 'Type-label sheet must remain in translation assets')
        self.assertEqual(expected,{p.name for p in (GRAPHICS_DIR/'source').glob('*.png')})
        self.assertFalse(list((GRAPHICS_DIR/'fr').glob('*.png')))
        for asset in manifest['assets']:
            w,h,_,_=read_png_indexed(str(GRAPHICS_DIR/'source'/asset['filename']))
            self.assertEqual((w,h),(asset['width_px'],asset['height_px']))

    def test_italian_type_sheet_preserves_other_pixels(self):
        w,h,source,palette=read_png_indexed(str(GRAPHICS_DIR/'source/pokemon_types.png'))
        iw,ih,localized,ipalette=read_png_indexed(str(GRAPHICS_DIR/'it/pokemon_types.png'))
        self.assertEqual((iw,ih,ipalette),(w,h,palette))
        rectangles=[((i%4)*32,16+(i//4)*16,32,12) for i in range(17)] + [(0,128,32,12)]
        rectangles += [(64,80,64,12),(0,96,64,12),(64,96,64,12),(64,112,64,12)]
        # PP is identical in both languages; its pixels must remain unchanged.
        allowed={(x+dx,y+dy) for x,y,rw,rh in rectangles for dx in range(rw) for dy in range(rh)}
        for y in range(h):
            for x in range(w):
                self.assertIn(localized[y][x],range(16))
                if (x,y) not in allowed:self.assertEqual(localized[y][x],source[y][x])
        for x,y,rw,rh in rectangles:
            self.assertTrue(any(localized[yy][xx]!=source[yy][xx]
                                for yy in range(y,y+rh) for xx in range(x,x+rw)))

    @unittest.skipUnless(ROM_PATH.is_file(), 'private source ROM unavailable')
    def test_italian_type_sheet_injects_only_its_original_slot(self):
        rom=bytearray(ROM_PATH.read_bytes());before=bytes(rom)
        reports=patch_graphics(rom,GRAPHICS_DIR,'it',[])
        self.assertEqual(len(reports),1)
        self.assertEqual(reports[0]['id'],'pokemon_types')
        self.assertEqual(reports[0]['status'],'patched_in_place')
        self.assertEqual(reports[0]['pointers_updated'],0)
        self.assertEqual(rom[:0xB1EE64],before[:0xB1EE64])
        self.assertEqual(rom[0xB21264:],before[0xB21264:])
        _,_,grid,_=read_png_indexed(str(GRAPHICS_DIR/'it/pokemon_types.png'))
        self.assertEqual(bytes(rom[0xB1EE64:0xB21264]),encode_4bpp_tiles(grid,16,18))

    @unittest.skipUnless(ROM_PATH.is_file(), 'private source ROM unavailable')
    def test_real_rom_all_views_roundtrip(self):
        rom=ROM_PATH.read_bytes()
        manifest=json.loads(MANIFEST_PATH.read_text())
        self.assertEqual(hashlib.md5(rom).hexdigest(),manifest['rom_md5'])
        for asset in manifest['assets']:
            with self.subTest(asset=asset['id']):
                grid,palette=render_asset(rom,asset)
                w,h,source,source_palette=read_png_indexed(str(GRAPHICS_DIR/'source'/asset['filename']))
                self.assertEqual(grid,source)
                self.assertEqual(palette,source_palette)
                for part,raw in encode_asset(rom,asset,grid):self.assertEqual(raw,read_blob(rom,part))


if __name__ == '__main__':
    unittest.main()
