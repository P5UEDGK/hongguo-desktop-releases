"""Execute the real patched worker finally block before its player can be reused."""
import ast,sys,time
from pathlib import Path
from types import SimpleNamespace

def verify(path):
    tree=ast.parse(path.read_text(encoding='utf8'))
    owner=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='NativeSession')
    run=next(n for n in owner.body if isinstance(n,ast.FunctionDef) and n.name=='run')
    cleanup=next(n.finalbody for n in run.body if isinstance(n,ast.Try) and n.finalbody)
    code=compile(ast.fix_missing_locations(ast.Module(body=cleanup,type_ignores=[])),'<actual-worker-finally>','exec')
    for failure in (False,True):
        calls=[];resources={'owned':True}
        session=SimpleNamespace(input_hooks={},engine_resources=resources,data={'state':'ready'})
        def restore(player):
            calls.append('restore')
            if failure:raise RuntimeError('cannot restore captions')
        def command(*args):
            if args==('stop',):assert calls and calls[0]=='restore','pool stop must follow caption restoration'
            calls.append(args)
        player=SimpleNamespace(command=command,get=lambda _: 'yes',close=lambda:calls.append('destroy'),
            dll=SimpleNamespace(mpv_wait_event=lambda *_:SimpleNamespace(contents=SimpleNamespace(id=0))),handle=1)
        user=SimpleNamespace(IsWindow=lambda _:False,ShowWindow=lambda *_:None)
        scope=dict(self=session,player=player,hwnd=1,user=user,time=time,danmaku_track=SimpleNamespace(close=restore))
        exec(code,scope)
        assert calls[0]=='restore','worker must restore its subtitle owner'
        assert scope['reusable'] is not failure
        if failure:assert resources=={} and 'destroy' in calls,'failed restoration must destroy, never pool'
    print('PASS: real worker teardown restores subtitles before stop; failed restoration destroys pooled resources')

if __name__=='__main__':verify(Path(sys.argv[1]))
