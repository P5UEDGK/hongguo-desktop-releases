"""Validate the bounded region protocol against the composed native package."""
import importlib.util
from pathlib import Path
import sys
import unittest

source = Path(sys.argv.pop(1)).resolve()
sys.path[:0] = [str(source.parent), str(source.parents[2] / 'desktop-danmaku-backend/src')]
spec = importlib.util.spec_from_file_location('overlay_native', source)
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)


class OverlayControl(unittest.TestCase):
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
