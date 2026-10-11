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
        original_options={'sub-ass-override':'force','secondary-sub-ass-override':'strip','sub-delay':'1.25','secondary-sub-delay':'-0.75','sub-visibility':'no','secondary-sub-visibility':'yes'}
        for name,value in original_options.items():player.command('set',name,value)
        original_options={name:player.get(name) for name in original_options}
        override=player.get('secondary-sub-ass-override')
        track=DanmakuTrack();track.update({'danmaku':[{'text':'overlay','offset_ms':0,'lane':1}]});track.apply(player)
        assert not track.failed and player.get('secondary-sid')==original and player.get('sid')==track.track_id
        assert player.get('sub-ass-override')=='no' and float(player.get('sub-delay'))==0
        assert player.get('sub-visibility')=='yes' and player.get('secondary-sub-visibility')=='no'
        assert player.get('secondary-sub-ass-override')=='force' and float(player.get('secondary-sub-delay'))==1.25
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
        track.update({'danmaku':[{'text':'schedule changed','offset_ms':0,'lane':1}]});track.apply(player)
        assert track.track_id is None and player.get('sid')==replacement and player.get('secondary-sid')==secondary
        assert {name:player.get(name) for name in original_options}==original_options
        print(json.dumps({'pass':True,'scope':'actual libmpv synthetic audio, subtitle selection/restoration; no pixel or Win32 claim'}))
finally:player.close()
