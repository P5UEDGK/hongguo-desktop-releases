"""Real owned native/API pause preloading; no user process is controlled."""
import argparse
import ctypes as C
from ctypes import wintypes as W
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import tempfile
import socket
import sys
import threading
import time
import urllib.request
from unittest.mock import patch


def source_sha256(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()

def wait_bootstrap_quiet(sample, reading, *, timeout, quiet_seconds, clock=time.monotonic, sleep=time.sleep):
    until=clock()+timeout;last=None;stable=None
    while clock()<until:
        value=sample();size=value['native']['cacheFileBytes'];now=clock()
        if reading() or size!=last: stable=None
        elif stable is None: stable=now
        elif now-stable>=quiet_seconds: return value
        last=size;sleep(.1)
    raise AssertionError('Bootstrap readahead did not become quiet; use a longer fixture or timeout')


def validate_budget(budget, block_size, source_size):
    if budget is not None and not block_size<=budget<source_size:
        raise ValueError('Budget probe requires at least one source block and a source larger than the budget')


def seek_target(duration):
    if not math.isfinite(duration) or duration<=0:raise ValueError('Invalid fixture duration')
    return min(25.,duration/2)


def bootstrap_within_envelope(value):
    duration=value.get('duration');size=value.get('sourceProgress',{}).get('totalBytes')
    return (isinstance(duration,(int,float)) and not isinstance(duration,bool) and math.isfinite(duration)
            and 0 < duration <= 12 and isinstance(size,int) and not isinstance(size,bool) and 0 < size <= 32*1024**2)


def preload_outcome(value):
    native = value['native']
    if native['preloadLimited']:
        return 'limited' if native.get('preloadReason') == 'budget' else 'failed'
    if native['cacheComplete']:
        return 'complete'


def pause_fill_advanced(before, after):
    previous, current = before['native'], after['native']
    return (not previous['preloadLimited'] and not previous['cacheComplete']
            and current['cacheFileBytes'] > previous['cacheFileBytes'])


def budget_stable(byte_samples, budget, range_bytes):
    # Sample actual bytes for three seconds: no write may exceed the budget,
    # and the last second (six samples) must remain stable.
    return (len(byte_samples) >= 16 and
            budget - range_bytes < max(byte_samples) <= budget and min(byte_samples) > 0 and
            len(set(byte_samples[-6:])) == 1)


def preload_timeout(total_bytes, range_delay, override=None):
    if (type(total_bytes) is not int or total_bytes <= 0 or
            not math.isfinite(range_delay) or range_delay < 0):
        raise ValueError('Invalid fixture size/delay')
    if override is not None:
        if not math.isfinite(override) or not 1 <= override <= 3600:
            raise ValueError('Preload timeout must be between 1 and 3600 seconds')
        return override
    return min(3600, 30 + math.ceil(total_bytes / 65536) * range_delay * 3
               + total_bytes / (8 * 1024 ** 2))


def wait_server_started(server, thread, timeout=5):
    deadline = time.monotonic() + timeout
    while not server.started:
        if not thread.is_alive():
            raise RuntimeError('Test API exited before listening')
        if time.monotonic() >= deadline:
            raise TimeoutError('Test API did not start')
        time.sleep(.01)


def cleanup_probe(jobs, prefetch, identifier, report, errors, done):
    try:
        actions = [('release', lambda: jobs.release(identifier))] if identifier else []
        actions += [('jobs.close', jobs.close), ('prefetch.close', prefetch.close)]
        for name, action in actions:
            try:
                action()
            except BaseException as exc:
                errors.append(type(exc).__name__)
                report['pass'] = False
                report.setdefault('cleanupErrors', []).append({'action': name, 'errorType': type(exc).__name__})
    finally:
        done.set()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--native-package', type=Path, required=True)
    parser.add_argument('--prefetch-package', type=Path, required=True)
    parser.add_argument('--mpv', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--sha', required=True)
    parser.add_argument('--software', action='store_true')
    parser.add_argument('--cache-budget', type=int)
    parser.add_argument('--range-delay', type=float, default=.12)
    parser.add_argument('--preload-timeout', type=float)
    args = parser.parse_args()
    if args.cache_budget is not None and args.cache_budget <= 0:
        parser.error('--cache-budget must be positive')
    if not math.isfinite(args.range_delay) or args.range_delay < 0:
        parser.error('--range-delay must be finite and non-negative')
    staging = tempfile.TemporaryDirectory()
    stage = Path(staging.name); backend = stage/'backend'; backend.mkdir()
    for source in (args.native_package.resolve()/'src',args.prefetch_package.resolve()/'src'):
        for file in source.glob('*.py'):
            (backend/file.name).write_text(file.read_text(encoding='utf-8'),encoding='utf-8',newline='\n')
    for file in (Path(__file__).resolve().parents[1]/'src').glob('*.py'):
        shutil.copyfile(file,backend/file.name)
    patch_file=Path(__file__).resolve().parents[1]/'enable-paused-preload.patch'
    subprocess.run(['git','-c','core.autocrlf=false','-C',str(stage),'apply',str(patch_file)],check=True)
    sys.path[:0] = [str(backend),str(Path(__file__).resolve().parent)]
    import desktop_native as module
    from desktop_native import NativeHost, NativeSession
    from desktop_hls_service import HlsJobs, make_router
    from desktop_prefetch import EpisodePrefetcher
    from desktop_stream import ProgressiveSource, source_progress
    import desktop_range_cache as range_module
    from progressive_fixture import ProgressiveFixture
    from fastapi import FastAPI
    import uvicorn
    assert source_sha256(args.source) == args.sha
    if args.cache_budget is not None: module.CACHE_FILE_BUDGET = args.cache_budget
    run = args.run.resolve()
    (run/'reports').mkdir(parents=True,exist_ok=True)
    work = run/('pause-work-'+str(time.time_ns()))
    work.mkdir(parents=True)
    app = FastAPI()
    fixture = ProgressiveFixture(app, work, [args.source])
    validate_budget(args.cache_budget,ProgressiveSource.block_size,fixture.files[0].stat().st_size)
    fixture.delay = args.range_delay
    timeout = preload_timeout(fixture.files[0].stat().st_size, fixture.delay, args.preload_timeout)
    host = NativeHost(parent_pid=os.getpid(), hardware=not args.software,
                      dll_path=args.mpv.resolve())
    assert host.available
    hwnd = host.user.CreateWindowExW(0x08000080, 'STATIC', 'Owned pause preload test',
                                    0x00CF0000, -20000, -20000, 960, 640, None, None, None, None)
    assert hwnd
    encodes = []
    def encode(*a, **kw): encodes.append(True); raise AssertionError('Unexpected encoding')
    listener = socket.socket(); listener.bind(('127.0.0.1',0))
    origin = 'http://127.0.0.1:'+str(listener.getsockname()[1])
    prefetch = EpisodePrefetcher(lambda _:fixture.source(origin,0),
        lambda _:({},[{'index':i,'vid':str(1234567890123456+i)} for i in range(1,5)]),
        work/'cache', encoder=encode, download_loader=lambda _:args.source, source_status=source_progress)
    jobs = HlsJobs(work,prefetch.load_source,native=host,encoder=encode,
                   on_start=prefetch.begin,before_work=prefetch.before_work,on_finish=prefetch.finish)
    key = secrets.token_hex(32)
    app.include_router(make_router(jobs,lambda value:value==key))
    server = uvicorn.Server(uvicorn.Config(app,log_level='critical'))
    server_thread = threading.Thread(target=lambda:server.run(sockets=[listener]),daemon=True)
    server_thread.start()
    report = {'pass':False,'forcedSoftware':args.software,'cacheBudget':module.CACHE_FILE_BUDGET,
              'sourceSha256':args.sha,'rangeDelay':fixture.delay,'preloadTimeout':timeout,
              'checks':[],'pausedSamples':[]}
    done = threading.Event()
    preload_entered=threading.Event();original_preload=range_module.preload
    def observed_preload(*a,**kw):
        preload_entered.set();return original_preload(*a,**kw)
    errors = []
    def request(path,method='GET',body=None):
        headers={'x-api-key':key,'x-desktop-codec-negotiation':'1'}
        if body is not None: headers['content-type']='application/json'
        with urllib.request.urlopen(urllib.request.Request(origin+'/desktop/hls'+path,method=method,
                headers=headers,data=json.dumps(body).encode() if body is not None else None),timeout=6) as response:
            return None if response.status==204 else json.load(response)
    def check(name,condition,evidence=None):
        row={'name':name,'pass':bool(condition),'evidence':evidence}
        report['checks'].append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
        assert condition,name
    def wait(identifier,predicate,timeout=15):
        until=time.monotonic()+timeout
        while time.monotonic()<until:
            value=request('/'+identifier+'/status')
            if predicate(value): return value
            if value.get('native',{}).get('state')=='failed': raise AssertionError('Native failed')
            time.sleep(.1)
        raise AssertionError('Native timeout')
    def scenario():
        identifier=None
        try:
            identifier=request('?series_id=1234567890123456&ep=1','POST')['id']
            wait(identifier,lambda s:bool(s.get('source')),timeout=timeout)
            request('/'+identifier+'/mode','POST',{'mode':'native'})
            initial=wait(identifier,lambda s:s.get('native',{}).get('state')=='ready',timeout=timeout)
            session=host.sessions[identifier]
            check('first-frame-ready',initial['native']['outputReady'],initial)
            report['fullSourceAtFirstFrame']=initial['sourceProgress']['complete']
            bounded=wait_bootstrap_quiet(lambda:request('/'+identifier+'/status'),
                session.job.source.reading.is_set,timeout=timeout,quiet_seconds=max(1.,fixture.delay*3+.5))
            bootstrap_complete=bounded['native']['cacheComplete']
            check('bootstrap-completion-within-envelope',not bootstrap_complete or bootstrap_within_envelope(bounded),bounded)
            report['inputOutcome']='bootstrap-complete' if bootstrap_complete else 'requires-paused-fill'
            check('no-preload-before-user-pause',not preload_entered.is_set())
            request('/'+identifier+'/control','POST',{'paused':True})
            started=time.monotonic()
            while time.monotonic()-started<timeout:
                value=request('/'+identifier+'/status');report['pausedSamples'].append(value)
                if preload_outcome(value):break
                time.sleep(.2)
            limited = preload_outcome(value) == 'limited'
            if preload_outcome(value) == 'failed':
                raise AssertionError('Preloading failed: '+str(value['native'].get('preloadReason')))
            if args.cache_budget is not None:
                check('explicit-budget-reaches-cap',limited and value['native']['cacheFileBytes']<=module.CACHE_FILE_BUDGET,value['native'])
            if not bootstrap_complete:
                check('pause-worker-ran',preload_entered.is_set())
            if limited:
                # Observe actual file bytes after the writer reports its cap.
                # A state flag alone cannot prove the hard budget.
                byte_samples = [value['native']['cacheFileBytes']]
                for _ in range(15):
                    time.sleep(.2)
                    value = request('/'+identifier+'/status')
                    report['pausedSamples'].append(value)
                    byte_samples.append(value['native']['cacheFileBytes'])
                check('disk-budget-growth-stabilizes',
                      budget_stable(byte_samples, module.CACHE_FILE_BUDGET, ProgressiveSource.block_size),
                      {'bytes': byte_samples, 'observationSeconds': 3,
                       'allowedOvershootBytes': 0})
            samples=report['pausedSamples']
            report['beforePause']=bounded
            if not bootstrap_complete:
                check('user-pause-starts-additional-cache-work',pause_fill_advanced(bounded,value),
                      {'before':bounded['native'],'after':value['native'],
                       'hint':'If bootstrap already exhausts the cap, increase --cache-budget to exercise paused fill.'})
            check('pause-position-fixed',all(s['native']['paused'] and abs(s['native']['time'])<.1 for s in samples))
            if not limited and not bootstrap_complete:
                check('paused-bytes-and-range-advance',value['sourceProgress']['receivedBytes']>initial['sourceProgress']['receivedBytes'] and
                      value['native']['bufferEnd']>initial['native']['bufferEnd'],{'initial':initial,'last':value})
            if limited:
                check('disk-budget-keeps-original-decoder',value['native']['preloadLimited'] and
                      value['native']['state']=='ready' and not encodes,value)
            else:
                check('paused-preload-past-12-seconds-to-eof',value['sourceProgress']['complete'] and
                      value['native']['cacheComplete'] and value['native']['bufferEnd']==value['duration'] and
                      value['native']['bufferEnd']>=min(12,value['duration']),value)
                check('payload-cached-on-disk',value['native']['cacheFileBytes']>0 and not value['native']['preloadLimited'])
            for rate in (2,3):
                if value['duration'] < 1:raise ValueError('Rate checks require a fixture of at least one second')
                advance=min(1.,value['duration']/4)
                request('/'+identifier+'/control','POST',{'paused':True,'seek':0})
                state=wait(identifier,lambda s:s['native']['paused'] and not s['native']['seeking'] and abs(s['native']['time'])<.15)
                position=state['native']['time']
                request('/'+identifier+'/control','POST',{'paused':False,'rate':rate,'volume':0})
                # Resuming software output can take longer than a fixed sleep.
                # This checks eventual progress/sync, not real-time throughput.
                state=wait(identifier,lambda s:s['native']['rate']==rate and s['native']['time']>position+advance and
                           not s['native']['buffering'],timeout=timeout)['native']
                check(str(rate)+'x-resumes-default-audio',state['time']>position+advance and abs(state['avsync'])<.1 and
                      state['audioDevice']=='auto' and state['audioOutput']=='wasapi' and
                      (not args.software or state['hwdec']=='no'),state)
                check(str(rate)+'x-reuses-preload-cache',preload_outcome({'native':state})==('limited' if limited else 'complete'),state)
            target=seek_target(value['duration'])
            request('/'+identifier+'/control','POST',{'paused':True,'seek':target})
            seek_state=wait(identifier,lambda s:s['native']['paused'] and not s['native']['seeking'] and abs(s['native']['time']-target)<.15,timeout=timeout)['native']
            check('seek-reuses-preload-cache',preload_outcome({'native':seek_state})==('limited' if limited else 'complete'),seek_state)
            check('future-three-downloads-zero-encoding',prefetch.wait_idle(3) and
                  prefetch.snapshot()['downloadCompletedEpisodes']==[2,3,4] and not encodes,prefetch.snapshot())
            directory=jobs.get(identifier).directory
            request('/'+identifier,'DELETE');identifier=None
            check('release-closes-thread-and-temporary-cache',not session.thread.is_alive() and
                  not directory.exists() and not jobs.jobs and not host.sessions)
            report['pass']=True
        except BaseException as exc: errors.append(type(exc).__name__);report['errorType']=type(exc).__name__
        finally:
            cleanup_probe(jobs, prefetch, identifier, report, errors, done)
    with patch.object(NativeSession,'forward_input',return_value=True), patch.object(range_module,'preload',side_effect=observed_preload):
        try:
            wait_server_started(server, server_thread)
        except (RuntimeError, TimeoutError):
            prefetch.close()
            server.should_exit = True
            server_thread.join(5)
            listener.close()
            host.user.DestroyWindow(hwnd)
            raise
        client=threading.Thread(target=scenario,daemon=True);client.start()
        message=W.MSG()
        while not done.is_set():
            while host.user.PeekMessageW(C.byref(message),None,0,0,1):
                host.user.TranslateMessage(C.byref(message));host.user.DispatchMessageW(C.byref(message))
            time.sleep(.005)
        client.join(2)
    server.should_exit=True;server_thread.join(5);host.user.DestroyWindow(hwnd)
    name='paused-preload'+('-budget' if args.cache_budget else '')+('-software' if args.software else '')+'.json'
    target=run/'reports'/name
    if target.exists():target.rename(target.with_name(target.stem+'-attempt-'+str(time.time_ns())+'.json'))
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    assert report['pass'],errors


if __name__=='__main__': main()
