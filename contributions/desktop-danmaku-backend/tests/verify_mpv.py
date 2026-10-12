"""Optional real libmpv property check with synthetic local audio, no visible window."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import wave

parser=argparse.ArgumentParser()
parser.add_argument('--native-package',type=Path,required=True)
parser.add_argument('--dll',type=Path,required=True)
args=parser.parse_args()
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'src'),str(args.native_package/'src')]
from desktop_native import NativeHost,Mpv
from desktop_danmaku import ass_document
from desktop_danmaku_track import DanmakuTrack
import ast
policy=ast.parse((args.native_package/'src/desktop_native.py').read_text(encoding='utf8'))
options=next(node.value for node in ast.walk(policy) if isinstance(node,ast.Assign) and any(isinstance(target,ast.Name) and target.id=='options' for target in node.targets) and isinstance(node.value,ast.Dict))
options=eval(compile(ast.fix_missing_locations(ast.Expression(options)),'<actual-native-policy>','eval'),{'hwnd':1})
assert all(options[name]=='no' for name in ('input-default-bindings','input-vo-keyboard','config','load-scripts')),'native keyboard and scripts stay disabled'
host=NativeHost(parent_pid=os.getpid(),dll_path=args.dll)
if not host.available:raise RuntimeError('Verified native package DLL unavailable')
player=Mpv(host.dll)
try:
    for name,value in {'vo':'null','ao':'null','terminal':'no','pause':'yes'}.items():player.option(name,value)
    player.check(player.dll.mpv_initialize(player.handle))
    with tempfile.TemporaryDirectory() as folder:
        path=os.path.join(folder,'fixture.wav')
        with wave.open(path,'wb') as w:
            w.setnchannels(1);w.setsampwidth(2);w.setframerate(8000);w.writeframes(b'\0\0'*8000*5)
        player.command('loadfile',path)
        deadline=time.monotonic()+5
        while not player.get('duration') and time.monotonic()<deadline:time.sleep(.05)
        assert player.get('duration')
        caption=ass_document([{'text':'fixture caption','offset_ms':0,'lane':0}])
        player.command('sub-add','memory://'+caption,'select','original caption')
        original=player.get('sid');assert original and original.isdigit()
        original_options={'sub-ass-override':'force','secondary-sub-ass-override':'strip','sub-delay':'1.25','secondary-sub-delay':'-0.75','sub-visibility':'no','secondary-sub-visibility':'yes','sub-pos':'90','secondary-sub-pos':'15'}
        for name,value in original_options.items():player.command('set',name,value)
        original_options={name:player.get(name) for name in original_options}
        override=player.get('secondary-sub-ass-override')
        track=DanmakuTrack();track.update({'danmaku':[{'text':'overlay','offset_ms':0,'lane':1}]});track.apply(player)
        assert not track.failed and player.get('secondary-sid')==original and player.get('sid')==track.track_id
        assert player.get('sub-ass-override')=='no' and float(player.get('sub-delay'))==0
        assert player.get('sub-visibility')=='yes' and player.get('secondary-sub-visibility')=='no'
        assert player.get('secondary-sub-ass-override')=='force' and float(player.get('secondary-sub-delay'))==1.25
        player.command('set','sub-pos','75');track.apply(player)
        assert float(player.get('secondary-sub-pos'))==75
        original_options['sub-pos']=player.get('sub-pos')
        track.update({'danmaku':[]});track.apply(player)
        assert not track.failed and player.get('sid')==original and player.get('secondary-sid')=='no'
        assert player.get('secondary-sub-ass-override')==override
        actual={name:player.get(name) for name in original_options}
        assert actual==original_options,(actual,original_options)
        player.command('set','sid','no');player.command('set','sub-ass-override','strip')
        track=DanmakuTrack();track.update({'danmaku':[{'text':'no caption overlay','offset_ms':0,'lane':1}]});track.apply(player)
        assert not track.failed and player.get('sub-ass-override')=='no'
        owned=track.track_id;player.command('set','sid',original);track.apply(player)
        assert not track.failed and player.get('sid')==owned and player.get('secondary-sid')==original
        track.update({'danmaku':[]});track.apply(player)
        assert not track.failed and player.get('sub-ass-override')=='strip' and player.get('sid')==original
        player.command('set','sub-ass-override','force')
        track.update({'danmaku':[{'text':'reload overlay','offset_ms':0,'lane':1}]});track.apply(player)
        assert player.get('secondary-sub-ass-override')=='force'
        player.command('loadfile',path)
        deadline=time.monotonic()+5
        while player.get('sid')!='no' and time.monotonic()<deadline:time.sleep(.02)
        assert player.get('sid')=='no','new source must discard subtitle tracks'
        player.command('sub-add','memory://'+caption,'select','new caption')
        replacement=player.get('sid')
        track.source_reloaded();track.apply(player)
        assert not track.failed and player.get('secondary-sid')==replacement
        track.update({'danmaku':[]});track.apply(player)
        assert not track.failed and player.get('sid')==replacement
        actual={name:player.get(name) for name in original_options}
        assert actual==original_options,(actual,original_options)
        for _ in range(2):
            track=DanmakuTrack();track.update({'danmaku':[{'text':'worker teardown overlay','offset_ms':0,'lane':1}]});track.apply(player)
            assert not track.failed and player.get('sid')==track.track_id
            track.close(player)
            assert player.get('sid')==replacement and player.get('secondary-sid')=='no'
            assert {name:player.get(name) for name in original_options}==original_options
        player.command('sub-add','memory://'+caption,'select','secondary replacement caption')
        secondary=player.get('sid');player.command('set','sid',replacement)
        track=DanmakuTrack();track.update({'danmaku':[{'text':'relinquish overlay','offset_ms':0,'lane':1}]});track.apply(player)
        assert not track.failed and player.get('secondary-sid')==replacement
        player.command('set','secondary-sid',secondary)
        track.apply(player)  # clean overlay must observe the changed secondary selection
        assert track.track_id is None and player.get('sid')==replacement and player.get('secondary-sid')==secondary
        assert {name:player.get(name) for name in original_options}==original_options
        player.command('set','secondary-sid','no')
        clear_track=DanmakuTrack();clear_track.update({'danmaku':[{'text':'clear promoted caption','offset_ms':0,'lane':1}]});clear_track.apply(player)
        assert clear_track.promoted
        player.command('set','secondary-sid','no');clear_track.apply(player)
        assert not clear_track.promoted
        secondary_options={name:value for name,value in original_options.items() if name.startswith('secondary-')}
        assert {name:player.get(name) for name in secondary_options}==secondary_options
        player.command('set','secondary-sid',secondary);clear_track.apply(player)
        assert {name:player.get(name) for name in secondary_options}==secondary_options
        clear_track.close(player)
        assert player.get('secondary-sid')==secondary
        player.command('set','sid','no');player.command('set','secondary-sid','no')
        player.command('set','sub-delay','0');player.command('set','sub-visibility','yes')
        for speed in (2,.5):
            player.command('set','sub-speed',str(speed))
            timed=DanmakuTrack();timed.update({'danmaku':[{'text':'speed compensated overlay','offset_ms':1000,'lane':0}], 'danmakuSettings':{'opacity':80,'lanes':3,'fontSize':28,'duration':4}});timed.apply(player)
            assert not timed.failed and float(player.get('sub-speed'))==speed
            for position,visible in ((.5,False),(2,True)):
                player.command('seek',str(position),'absolute+exact')
                deadline=time.monotonic()+3
                while time.monotonic()<deadline:
                    if abs(player.number('time-pos')-position)<.05 and ('speed compensated overlay' in (player.get('sub-text') or ''))==visible:break
                    time.sleep(.02)
                assert ('speed compensated overlay' in (player.get('sub-text') or ''))==visible,(speed,position,player.get('sub-text'))
            timed.close(player);assert float(player.get('sub-speed'))==speed
        player.command('set','sub-speed','1')
        live=DanmakuTrack();live.update({'danmaku':[{'text':'live option overlay','offset_ms':1000,'lane':0}], 'danmakuSettings':{'opacity':80,'lanes':3,'fontSize':28,'duration':4}});live.apply(player)
        for name,value in (('sub-delay','3'),('sub-ass-override','strip'),('sub-visibility','no')):player.command('set',name,value)
        live.apply(player)
        assert not live.failed and float(player.get('sub-delay'))==0 and player.get('sub-ass-override')=='no' and player.get('sub-visibility')=='yes'
        player.command('seek','2','absolute+exact');deadline=time.monotonic()+3
        live_text=''
        while time.monotonic()<deadline:
            live_text=player.get('sub-text') or ''
            if 'live option overlay' in live_text:break
            time.sleep(.02)
        assert 'live option overlay' in live_text,dict(failed=live.failed,sid=player.get('sid'),secondary=player.get('secondary-sid'),time=player.get('time-pos'),text=live_text,options={name:player.get(name) for name in ('sub-delay','sub-visibility','sub-pos','sub-ass-override','sub-speed')},document=live.document)
        live.close(player)
        assert float(player.get('sub-delay'))==3 and player.get('sub-ass-override')=='strip' and player.get('sub-visibility')=='no'
        player.command('set','sid','no');player.command('set','secondary-sid','no');player.command('set','sub-delay','2')
        player.command('sub-add','memory://'+caption,'select','caption before switch')
        switched=DanmakuTrack();switched.update({'danmaku':[{'text':'switch option overlay','offset_ms':0,'lane':0}]});switched.apply(player)
        player.command('sub-add','memory://'+caption,'select','caption after switch');selected=player.get('sid')
        player.command('set','sub-delay','3');switched.apply(player)
        assert not switched.failed and player.get('secondary-sid')==selected and float(player.get('secondary-sub-delay'))==3
        switched.close(player);assert player.get('sid')==selected and float(player.get('sub-delay'))==3
        print(json.dumps({'pass':True,'scope':'actual libmpv synthetic audio, simultaneous caption/option switch, subtitle restoration and sub-speed timing; no pixel or Win32 claim'}))
finally:player.close()
