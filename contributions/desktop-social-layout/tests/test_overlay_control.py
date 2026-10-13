"""Validate the bounded region protocol against the composed native package."""
import importlib.util
from pathlib import Path
import sys
import unittest
import base64
import zlib

source = Path(sys.argv.pop(1)).resolve()
sys.path[:0] = [str(source.parent), str(source.parents[2] / 'desktop-danmaku-backend/src')]
spec = importlib.util.spec_from_file_location('overlay_native', source)
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)


class OverlayControl(unittest.TestCase):
    def test_compressed_alpha_bitmap(self):
        pixels = bytes([10, 20, 30, 40, 0, 0, 0, 0])
        payload = dict(x=0, y=600, width=2, height=1, data=base64.b64encode(zlib.compress(pixels)).decode())
        decoded = native.validate_control({'controlsOverlay': payload})['controlsOverlay']
        self.assertEqual(decoded['pixels'], pixels)
        self.assertEqual(decoded['y'], 600)

    def test_reject_bitmap_paths_pointers_and_decompression_overflow(self):
        valid = dict(x=0, y=0, width=1, height=1, data=base64.b64encode(zlib.compress(bytes(4))).decode())
        invalid = [dict(valid, data='&12345'), dict(valid, path='C:/file'), dict(valid, width=True),
                   dict(valid, width=8193), dict(valid, height=513), dict(valid, data='a'*524289),
                   dict(valid, data=base64.b64encode(zlib.compress(bytes(1000000))).decode()),
                   dict(valid, data=base64.b64encode(zlib.compress(bytes(4))+b'extra').decode()),
                   dict(valid, data=base64.b64encode(zlib.compress(bytes(3))).decode())]
        for value in invalid:
            with self.subTest(value_keys=list(value)), self.assertRaises(ValueError):
                native.validate_control({'controlsOverlay': value})

    def test_existing_single_and_empty_cutouts(self):
        for cutouts in ([], [0, 450, 800, 100]):
            self.assertEqual(native.validate_control({'occlusion': cutouts})['occlusion'], cutouts)

    def test_controls_and_settings_together(self):
        cutouts = [0, 450, 800, 100, 100, 200, 250, 260]
        self.assertEqual(native.validate_control({'occlusion': cutouts})['occlusion'], cutouts)

    def test_reject_unbounded_or_non_integer_input(self):
        for cutouts in ([0] * 12, [0] * 5, [False, 0, 1, 1], [-1, 0, 1, 1], [0, 0, 32769, 1], 'rect'):
            with self.subTest(cutouts=cutouts), self.assertRaises(ValueError):
                native.validate_control({'occlusion': cutouts})


if __name__ == '__main__':
    unittest.main()
