"""Verify public bridge deltas and run original frontend regressions."""
import argparse,hashlib,json,shutil,subprocess,tempfile
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--native-package',type=Path,required=True);a=p.parse_args()
package=Path(__file__).resolve().parents[1]
baselines=json.loads((package/'BASELINES.json').read_text(encoding='utf-8'))
policy=package/baselines['controlsPolicy']['path']
assert hashlib.sha256(policy.read_text(encoding='utf-8').encode()).hexdigest()==baselines['controlsPolicy']['sha256']
subprocess.run(['node','--check',str(policy)],check=True)
subprocess.run(['node',str(package/'tests/test_controls_visibility.cjs')],check=True)
with tempfile.TemporaryDirectory() as temp:
    root=Path(temp);frontend=root/'frontend';frontend.mkdir()
    for entry in json.loads((package/'BASELINES.json').read_text(encoding='utf-8'))['files']:
        target=root/entry['path']
        target.write_text((a.native_package/'src'/target.name).read_text(encoding='utf-8'),encoding='utf-8',newline='\n')
        assert hashlib.sha256(target.read_bytes()).hexdigest()==entry['baseSha256']
        patch=package/'src'/(target.stem+'.patch')
        subprocess.run(['git','-c','core.autocrlf=false','-C',str(root),'apply','--check',str(patch)],check=True)
        subprocess.run(['git','-c','core.autocrlf=false','-C',str(root),'apply',str(patch)],check=True)
        assert hashlib.sha256(target.read_bytes()).hexdigest()==entry['patchedSha256']
        subprocess.run(['node','--check',str(target)],check=True)
    # The original test discovers ../src relative to its file.
    (root/'src').mkdir();(root/'tests').mkdir()
    for file in frontend.glob('*.js'):shutil.copyfile(file,root/'src'/file.name)
    for file in (a.native_package/'tests').glob('*.cjs'):shutil.copyfile(file,root/'tests'/file.name)
    fixture=root/'tests/test_frontend.cjs'
    text=fixture.read_text(encoding='utf-8')
    # The base harness predates bounded requests; provide the browser API.
    assert text.count('const nc={')==1
    fixture.write_text(text.replace('const nc={','const nc={AbortController,'),encoding='utf-8')
    with fixture.open('a',encoding='utf-8') as output:
        output.write('\n(async()=>{const vm=require("node:vm"),fs=require("node:fs"),assert=require("node:assert/strict");const c={URL,Headers,fetch:async()=>({ok:true,clone(){return this},json:async()=>({videoMode:"h264"})})};vm.createContext(c);vm.runInContext(fs.readFileSync(require("node:path").join(__dirname,"../src/frontend-codec.js"),"utf8"),c);const f=c.desktopCreateCodecFetch();assert.equal(f.sessionId(),null);await f("http://127.0.0.1/desktop/hls/"+"e".repeat(32)+"/status");assert.equal(f.sessionId(),"e".repeat(32));console.log("PASS: claimed standby transport learns ID without POST");})().catch(e=>{console.error(e);process.exitCode=1});\n')
    subprocess.run(['node',str(root/'tests/test_frontend.cjs')],check=True)
    subprocess.run(['node',str(package/'tests/test_frontend.cjs')],check=True)
    subprocess.run(['node',str(package/'tests/test_surface_geometry.cjs')],check=True)
    subprocess.run(['node',str(package/'tests/test_picture_hold.cjs')],check=True)
    subprocess.run(['node',str(package/'tests/test_activation.cjs'),str(root/'src/frontend-native.js')],check=True)
    subprocess.run(['node',str(package/'tests/test_codec_handoff.cjs'),str(root/'src/frontend-codec.js')],check=True)
print('PASS: exact public bridge patches, syntax and frontend regressions')
