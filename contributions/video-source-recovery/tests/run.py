"""Network-free tests; optionally patch the existing public Range owner."""
from pathlib import Path
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

package=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument('--stream-base',type=Path,help='Existing unpatched desktop_stream.py')
parser.add_argument('--host-backend',type=Path,help='Optional patched private backend adapter acceptance')
args=parser.parse_args()
sys.path[:0]=[str(package/'src'),str(package/'tests')]
with tempfile.TemporaryDirectory() as temporary:
    fixture=Path(temporary)
    names=['test_desktop_video_resolver']
    if args.stream_base:
        (fixture/'backend').mkdir()
        shutil.copy2(args.stream_base,fixture/'backend/desktop_stream.py')
        patch=package/'patches/progressive-backups.patch'
        subprocess.run(['git','apply','--check',str(patch)],cwd=fixture,check=True)
        subprocess.run(['git','apply',str(patch)],cwd=fixture,check=True)
        sys.path.insert(0,str(fixture/'backend'))
        names.append('test_desktop_source_recovery')
    if args.host_backend:
        os.environ['RECOVERY_BACKEND']=str(args.host_backend.resolve())
        names.append('test_desktop_recovery_adapters')
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromNames(names))
raise SystemExit(not result.wasSuccessful())
