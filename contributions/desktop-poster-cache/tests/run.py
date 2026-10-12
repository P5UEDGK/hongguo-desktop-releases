import sys
import unittest
from pathlib import Path

package = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(package / 'src'))
suite = unittest.defaultTestLoader.discover(str(package / 'tests'), pattern='test_*.py')
raise SystemExit(not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful())
