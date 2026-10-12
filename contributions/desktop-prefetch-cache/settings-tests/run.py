from pathlib import Path
import sys,unittest
root=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root/'src'),str(root/'tests')]
result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover(str(root/'settings-tests'),pattern='test_*.py'))
raise SystemExit(not result.wasSuccessful())
