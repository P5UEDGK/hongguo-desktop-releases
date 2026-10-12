"""Exercise the documented LF patch baseline after an autocrlf Windows clone."""
from pathlib import Path
import argparse,json,shutil,subprocess,tempfile
parser=argparse.ArgumentParser();parser.add_argument('--native-package',type=Path,required=True);parser.add_argument('--package',type=Path)
args=parser.parse_args();package=(args.package or Path(__file__).resolve().parents[1]).resolve()
def git(root,*args):
    result=subprocess.run(['git','-C',str(root),*map(str,args)],capture_output=True)
    assert result.returncode==0,result.stdout+result.stderr
with tempfile.TemporaryDirectory() as directory:
    root=Path(directory);fixture=root/'source';fixture.mkdir();git(fixture,'init','-q')
    shutil.copyfile(package/'.gitattributes',fixture/'.gitattributes');(fixture/'src').mkdir()
    entries=json.loads((package/'BASELINES.json').read_text(encoding='utf8'))['files']
    for entry in entries:
        leaf=Path(entry['path']).stem+'.patch';shutil.copyfile(package/'src'/leaf,fixture/'src'/leaf)
    git(fixture,'-c','core.autocrlf=false','add','--','.gitattributes','src')
    git(fixture,'-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','LF patch fixture')
    clone=root/'windows-clone';result=subprocess.run(['git','-c','core.autocrlf=true','clone','-q','--no-hardlinks',str(fixture),str(clone)],capture_output=True);assert result.returncode==0,result.stderr
    baseline=root/'baseline';baseline.mkdir()
    for entry in entries:
        target=baseline/entry['path'];target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes((args.native_package/'src'/target.name).read_bytes())
        patch=clone/'src'/(target.stem+'.patch')
        assert b'\r\n' not in patch.read_bytes(),'Windows checkout must preserve LF unified diff context'
        git(baseline,'-c','core.autocrlf=false','apply','--check',patch)
print('PASS core.autocrlf=true real clone preserves LF bridge patches and applies to LF baselines')
