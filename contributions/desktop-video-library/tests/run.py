from pathlib import Path
import argparse
import sys
import unittest

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description="Run video-library tests against the integrated cache dependency.")
parser.add_argument("--cache-source", type=Path, default=root.parent/"desktop-prefetch-cache"/"src")
args = parser.parse_args()
dependency = args.cache_source.resolve()
if not all((dependency/name).is_file() for name in ("desktop_cache_budget.py", "desktop_cache_settings.py", "desktop_playable_cache.py")):
    parser.error("先接入PR246及本材料补丁，或用--cache-source指定已接入的依赖源码目录。")
sys.path[:0] = [str(root/"src"), str(dependency), str(dependency.parent/"tests")]
result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover(str(root/"tests"), pattern="test_*.py"))
raise SystemExit(not result.wasSuccessful())
