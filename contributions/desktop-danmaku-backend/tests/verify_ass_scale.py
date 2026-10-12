from pathlib import Path
import sys,time,json
import argparse
parser=argparse.ArgumentParser();parser.add_argument('--native-package',type=Path,required=True);parser.add_argument('--dll',type=Path,required=True);parser.add_argument('--run',type=Path,required=True);args=parser.parse_args()
sys.path[:0]=[str(args.native_package/'src'),str(Path(__file__).resolve().parents[1]/'src')]
from desktop_native import NativeHost,Mpv
from desktop_danmaku import ass_document
from PIL import Image,ImageChops
out=args.run;out.mkdir(exist_ok=True,parents=True)
host=NativeHost(parent_pid=__import__('os').getpid(),dll_path=args.dll);assert host.available
p=Mpv(host.dll)
try:
 for k,v in {'vo':'gpu','gpu-api':'d3d11','ao':'null','terminal':'no','pause':'yes','force-window':'yes','geometry':'1000x562-10000-10000','input-default-bindings':'no','config':'no','load-scripts':'no','sub-ass-override':'no'}.items():p.option(k,v)
 p.check(p.dll.mpv_initialize(p.handle));p.command('loadfile','av://lavfi:color=c=black:s=1000x562:r=25:d=10')
 until=time.monotonic()+8
 while not p.get('video-out-params') and time.monotonic()<until:time.sleep(.05)
 assert p.get('video-out-params')
 p.command('sub-add','memory://'+ass_document([dict(text='测试TEST',offset_ms=0,lane=0)]),'select','owned scale probe')
 p.command('seek','5','absolute+exact');time.sleep(.5)
 rows=[]
 for scale in (1,2):
  p.command('set','sub-scale',str(scale));time.sleep(.4);path=out/f'ass-scale-{scale}.png';p.command('screenshot-to-file',str(path),'subtitles');im=Image.open(path).convert('RGB');bbox=ImageChops.difference(im,Image.new('RGB',im.size,(0,0,0))).getbbox();assert bbox
  rows.append(dict(scale=scale,bbox=bbox,override=p.get('sub-ass-override'),image=str(path)))
 report=dict(rows=rows,unchanged=rows[0]['bbox']==rows[1]['bbox']);(out/'ass-scale.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8');assert report['unchanged'],'ASS no override must preserve geometry with scale 1/2';print(json.dumps(report))
finally:p.close()
