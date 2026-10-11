"""Regression cases for the public probe, without starting mpv or a server."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
import threading
import ast
import inspect
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('probe', Path(__file__).with_name('verify_preload.py'))
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class ProbeTests(unittest.TestCase):
    def test_incomplete_bootstrap_reads_must_fit_seconds_and_byte_envelope(self):
        tree=ast.parse(inspect.getsource(probe));gate=next(n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='check' and n.args and isinstance(n.args[0],ast.Constant) and n.args[0].value=='bootstrap-completion-within-envelope')
        code=compile(ast.fix_missing_locations(ast.Expression(gate.args[1])),'<actual-bootstrap-gate>','eval')
        for seconds,size,valid in ((12,32*1024**2,True),(30,100,False),(5,64*1024**2,False)):
            bounded={'duration':100,'sourceProgress':{'receivedBytes':size,'totalBytes':128*1024**2},'native':{'cacheComplete':False,'bufferStart':0,'bufferEnd':seconds,'cacheFileBytes':size}}
            self.assertEqual(eval(code,dict(vars(probe),bootstrap_complete=False,bounded=bounded)),valid)

    def test_source_hash_streams_bounded_chunks_and_main_uses_it(self):
        import io,hashlib
        payload=b'x'*(2*1024*1024+17)
        sizes=[]
        class Source(io.BytesIO):
            def read(self,size=-1):
                self_outer.assertTrue(0<size<=1024*1024);sizes.append(size)
                return super().read(size)
        self_outer=self
        source=SimpleNamespace(open=lambda mode:Source(payload))
        self.assertEqual(probe.source_sha256(source),hashlib.sha256(payload).hexdigest());self.assertGreater(len(sizes),2)
        tree=ast.parse(inspect.getsource(probe));calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call)]
        self.assertTrue(any(isinstance(n.func,ast.Name) and n.func.id=='source_sha256' and ast.unparse(n.args[0])=='args.source' for n in calls))
        self.assertFalse(any(isinstance(n.func,ast.Attribute) and n.func.attr=='read_bytes' and ast.unparse(n.func.value)=='args.source' for n in calls))


    def test_bootstrap_complete_is_limited_to_documented_envelope(self):
        good={'duration':12.,'sourceProgress':{'totalBytes':32*1024**2}}
        self.assertTrue(probe.bootstrap_within_envelope(good))
        for value in ({**good,'duration':12.01},{**good,'sourceProgress':{'totalBytes':32*1024**2+1}},{**good,'duration':float('nan')},{**good,'duration':True},{**good,'sourceProgress':{}},{**good,'duration':0}):
            self.assertFalse(probe.bootstrap_within_envelope(value))
        tree=ast.parse(inspect.getsource(probe));gate=next(n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='check' and n.args and isinstance(n.args[0],ast.Constant) and n.args[0].value=='bootstrap-completion-within-envelope')
        code=compile(ast.fix_missing_locations(ast.Expression(gate.args[1])),'<actual-bootstrap-gate>','eval')
        self.assertFalse(eval(code,dict(vars(probe),bootstrap_complete=True,bounded={**good,'duration':60})))
        self.assertFalse(eval(code,dict(vars(probe),bootstrap_complete=False,bounded={**good,'duration':60})))

    def test_initial_source_and_ready_waits_use_scaled_timeout(self):
        tree=ast.parse(inspect.getsource(probe));scenario=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='scenario')
        calls=[n for n in ast.walk(scenario) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='wait'][:2]
        self.assertEqual(len(calls),2)
        def wait(identifier,predicate,timeout=15):self.assertEqual(timeout,60);return {}
        for call in calls:eval(compile(ast.fix_missing_locations(ast.Expression(call)),'<actual-ready-wait>','eval'),{'wait':wait,'identifier':'owned','timeout':60})

    def test_probe_rejects_preload_started_before_user_pause(self):
        tree=ast.parse(inspect.getsource(probe));call=next(n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='check' and n.args and isinstance(n.args[0],ast.Constant) and n.args[0].value=='no-preload-before-user-pause')
        expression=compile(ast.fix_missing_locations(ast.Expression(call.args[1])),'<actual-startup-preload-gate>','eval');event=threading.Event()
        self.assertTrue(eval(expression,{'preload_entered':event}));event.set();self.assertFalse(eval(expression,{'preload_entered':event}))

    def test_replay_checks_reject_cache_io_after_successful_preload(self):
        tree=ast.parse(inspect.getsource(probe))
        checks=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='check' and 'preload_outcome' in ast.unparse(n)]
        self.assertEqual(len(checks),2,'rate and final seek must verify cache health')
        for check in checks:
            expr=compile(ast.fix_missing_locations(ast.Expression(check.args[1])),'<actual-replay-cache-check>','eval')
            for limited in (False,True):
                healthy={'cacheComplete':not limited,'preloadLimited':limited,'preloadReason':'budget' if limited else None}
                self.assertTrue(eval(expr,dict(vars(probe),state=healthy,seek_state=healthy,limited=limited)))
                failed={**healthy,'cacheComplete':False,'preloadLimited':True,'preloadReason':'cache-io'}
                self.assertFalse(eval(expr,dict(vars(probe),state=failed,seek_state=failed,limited=limited)))

    def test_final_seek_wait_uses_scaled_timeout(self):
        tree=ast.parse(inspect.getsource(probe))
        call=next(n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='wait' and 'target' in ast.unparse(n))
        timeout=next((k.value for k in call.keywords if k.arg=='timeout'),ast.Constant(15))
        self.assertEqual(eval(compile(ast.fix_missing_locations(ast.Expression(timeout)),'<actual-seek-budget>','eval'),{'timeout':60}),60)

    def test_actual_rate_loop_accepts_one_second_fixture_twice(self):
        tree=ast.parse(inspect.getsource(probe));scenario=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='scenario')
        loop=next(n for n in ast.walk(scenario) if isinstance(n,ast.For) and isinstance(n.target,ast.Name) and n.target.id=='rate')
        native=dict(time=0,rate=1,paused=True,seeking=False,buffering=False,avsync=0,audioDevice='auto',audioOutput='wasapi',hwdec='dxva2-copy')
        checks=[];seeks=[]
        def request(path,method='GET',body=None):
            if body:
                native.update({k:v for k,v in body.items() if k!='seek'})
                if 'seek' in body:native['time']=body['seek'];seeks.append(body['seek'])
        def wait(identifier,predicate,**kw):
            for _ in range(25):
                sample={'duration':1,'native':dict(native)}
                if predicate(sample):return sample
                if not native['paused']:native['time']=min(1,native['time']+.05)
            raise AssertionError('no progress within one-second clip')
        def check(name,condition,*_):self.assertTrue(condition,name);checks.append(name)
        native.update(cacheComplete=True,preloadLimited=False)
        scope=dict(vars(probe),identifier='owned',request=request,wait=wait,check=check,value={'duration':1},args=SimpleNamespace(software=False),limited=False,timeout=60)
        exec(compile(ast.fix_missing_locations(ast.Module(body=[loop],type_ignores=[])),'<actual-one-second-rate-loop>','exec'),scope)
        self.assertEqual(checks,['2x-resumes-default-audio','2x-reuses-preload-cache','3x-resumes-default-audio','3x-reuses-preload-cache']);self.assertEqual(seeks,[0,0])

    def test_actual_scenario_accepts_bootstrap_eof_without_claiming_pause_fill(self):
        report,checks=self.run_bootstrap_scenario()
        self.assertEqual(report['inputOutcome'],'bootstrap-complete')
        self.assertNotIn('pause-worker-ran',[name for name,_ in checks]);self.assertNotIn('user-pause-starts-additional-cache-work',[name for name,_ in checks])

    def test_actual_scenario_rejects_outside_bootstrap_envelope(self):
        for duration,size in ((13,100),(5,32*1024**2+1)):
            with self.subTest(duration=duration,size=size):
                with self.assertRaisesRegex(AssertionError,'bootstrap-completion-within-envelope'):
                    self.run_bootstrap_scenario(duration,size)

    def run_bootstrap_scenario(self,duration=5,size=100):
        tree=ast.parse(inspect.getsource(probe));scenario=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='scenario')
        body=next(n for n in scenario.body if isinstance(n,ast.Try)).body
        start=next(i for i,n in enumerate(body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='initial' for t in n.targets))
        stop=next(i for i,n in enumerate(body) if isinstance(n,ast.For) and isinstance(n.target,ast.Name) and n.target.id=='rate')
        value={'duration':duration,'sourceProgress':{'complete':True,'receivedBytes':size,'totalBytes':size},'native':{'outputReady':True,'cacheComplete':True,'cacheFileBytes':size,'bufferEnd':duration,'preloadLimited':False,'paused':True,'time':0}}
        checks=[];report={'pausedSamples':[]}
        def check(name,condition,evidence=None):checks.append((name,condition));self.assertTrue(condition,name)
        source=SimpleNamespace(reading=threading.Event());host=SimpleNamespace(sessions={'owned':SimpleNamespace(job=SimpleNamespace(source=source))})
        scope=dict(vars(probe),identifier='owned',wait=lambda *a,**k:value,request=lambda *a,**k:value,host=host,
            wait_bootstrap_quiet=lambda *a,**k:value,timeout=1,fixture=SimpleNamespace(delay=0),args=SimpleNamespace(cache_budget=None),
            report=report,preload_entered=threading.Event(),check=check,encodes=[],module=SimpleNamespace(CACHE_FILE_BUDGET=1000),ProgressiveSource=SimpleNamespace(block_size=64))
        exec(compile(ast.fix_missing_locations(ast.Module(body=body[start:stop],type_ignores=[])),'<actual-bootstrap-eof-scenario>','exec'),scope)
        return report,checks

    def test_budget_validation_uses_actual_served_fixture_after_remux(self):
        tree=ast.parse(inspect.getsource(probe));main=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
        selected=[]
        for node in main.body:
            if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='fixture' for t in node.targets):selected.append(node)
            if isinstance(node,ast.Expr) and isinstance(node.value,ast.Call) and isinstance(node.value.func,ast.Name) and node.value.func.id=='validate_budget':selected.append(node)
        code=compile(ast.fix_missing_locations(ast.Module(body=selected,type_ignores=[])),'<actual-fixture-setup>','exec')
        def path(size):return SimpleNamespace(stat=lambda:SimpleNamespace(st_size=size))
        for original,served,valid in [(60000,80000,True),(80000,60000,False)]:
            scope=dict(vars(probe),args=SimpleNamespace(cache_budget=65536,source=path(original)),
                ProgressiveSource=SimpleNamespace(block_size=65536),app=None,work=None,
                ProgressiveFixture=lambda *_:SimpleNamespace(files=[path(served)]))
            if valid:exec(code,scope)
            else:
                with self.assertRaises(ValueError):exec(code,scope)

    def test_full_preload_check_accepts_a_short_complete_clip(self):
        tree=ast.parse(inspect.getsource(probe))
        call=next(node for node in ast.walk(tree) if isinstance(node,ast.Call) and isinstance(node.func,ast.Name)
                  and node.func.id=='check' and isinstance(node.args[0],ast.Constant)
                  and node.args[0].value=='paused-preload-past-12-seconds-to-eof')
        expression=compile(ast.fix_missing_locations(ast.Expression(call.args[1])),'<actual-short-clip-check>','eval')
        value={'duration':5,'sourceProgress':{'complete':True},'native':{'cacheComplete':True,'bufferEnd':5}}
        self.assertTrue(eval(expression,{'value':value}))
        value['native']['bufferEnd']=4;self.assertFalse(eval(expression,{'value':value}))

    def test_bootstrap_must_be_quiet_after_growth_and_active_reads(self):
        now=[0];sizes=iter([1,2,3,3,3,3,3,3,3,3]);reads=iter([True,True,True,False,False,False,False,False,False,False])
        value=probe.wait_bootstrap_quiet(lambda:{'native':{'cacheFileBytes':next(sizes)}},lambda:next(reads),
            timeout=3,quiet_seconds=.3,clock=lambda:now[0],sleep=lambda amount:now.__setitem__(0,now[0]+amount))
        self.assertEqual(value['native']['cacheFileBytes'],3);self.assertGreaterEqual(now[0],.6)

    def test_budget_input_and_seek_stay_inside_owned_fixture(self):
        for budget in (0,1,65535,131072,200000):
            with self.assertRaises(ValueError):probe.validate_budget(budget,65536,131072)
        probe.validate_budget(65536,65536,131072);probe.validate_budget(None,65536,1)
        for duration in (13,24,90):self.assertTrue(0<probe.seek_target(duration)<duration)

    def test_actual_scenario_finally_cannot_skip_completion(self):
        tree=ast.parse(inspect.getsource(probe))
        scenario=next(node for node in ast.walk(tree) if isinstance(node,ast.FunctionDef) and node.name=='scenario')
        block=next(node for node in scenario.body if isinstance(node,ast.Try) and node.finalbody)
        module=ast.fix_missing_locations(ast.Module(body=block.finalbody,type_ignores=[]))
        def fail(*_):raise OSError('fixture teardown failure')
        done=threading.Event();report={'pass':True};errors=[]
        scope=dict(vars(probe),identifier='owned',jobs=SimpleNamespace(release=fail,close=lambda:None),
                   prefetch=SimpleNamespace(close=lambda:None),done=done,report=report,errors=errors)
        try:exec(compile(module,'<actual-scenario-finally>','exec'),scope)
        except OSError:pass
        self.assertTrue(done.is_set(),'the actual verifier finally must signal despite release failure')
        self.assertFalse(report['pass'])
    def test_cleanup_failure_always_signals_and_attempts_every_owner(self):
        for fault in ('release','jobs.close','prefetch.close'):
            with self.subTest(fault=fault):
                called=[];report={'pass':True};errors=[];done=threading.Event()
                def action(name):
                    called.append(name)
                    if name==fault:raise OSError('fixture teardown failure')
                jobs=SimpleNamespace(release=lambda _:action('release'),close=lambda:action('jobs.close'))
                prefetch=SimpleNamespace(close=lambda:action('prefetch.close'))
                worker=threading.Thread(target=probe.cleanup_probe,args=(jobs,prefetch,'owned',report,errors,done))
                worker.start();worker.join(1)
                self.assertTrue(done.is_set());self.assertFalse(worker.is_alive())
                self.assertEqual(called,['release','jobs.close','prefetch.close'])
                self.assertFalse(report['pass']);self.assertEqual(errors,['OSError'])
                self.assertEqual(report['cleanupErrors'],[{'action':fault,'errorType':'OSError'}])
    def test_budget_probe_rejects_bootstrap_only_and_requires_post_pause_work(self):
        def state(size,limited=False,complete=False):
            return {'native':{'cacheFileBytes':size,'preloadLimited':limited,'cacheComplete':complete}}
        self.assertFalse(probe.pause_fill_advanced(state(1000,True),state(1000,True)))
        self.assertFalse(probe.pause_fill_advanced(state(1000),state(1000,True)))
        self.assertFalse(probe.pause_fill_advanced(state(1000,True),state(1100,True)))
        self.assertFalse(probe.pause_fill_advanced(state(1000,complete=True),state(1100,complete=True)))
        self.assertTrue(probe.pause_fill_advanced(state(1000),state(2000,True)))
        self.assertTrue(probe.pause_fill_advanced(state(1000),state(2000,complete=True)))

    def test_observed_cap_is_valid_without_cli_override(self):
        self.assertEqual(probe.preload_outcome({'native': {'preloadLimited': True, 'preloadReason':'budget', 'cacheComplete': False}}), 'limited')
        for reason in ('cache-io','cache-open','worker-start',None):
            self.assertEqual(probe.preload_outcome({'native': {'preloadLimited': True,'preloadReason':reason}}),'failed')
        self.assertEqual(probe.preload_outcome({'native': {'preloadLimited': False, 'cacheComplete': True}}), 'complete')
        self.assertIsNone(probe.preload_outcome({'native': {'preloadLimited': False, 'cacheComplete': False}}))

    def test_budget_requires_stable_bytes_without_overshoot(self):
        self.assertTrue(probe.budget_stable([1000] * 16, 1000, 100))
        self.assertFalse(probe.budget_stable([1050 + i * 2 for i in range(16)], 1000, 100))
        self.assertFalse(probe.budget_stable([1101] * 16, 1000, 100))
        self.assertFalse(probe.budget_stable([1050], 1000, 100))
        self.assertFalse(probe.budget_stable([0]*16,1000,100))
        self.assertFalse(probe.budget_stable([100]*16,1000,100))

    def test_deadline_scales_with_100mib_rate_and_is_bounded(self):
        self.assertGreater(probe.preload_timeout(100*1024**2,.12),100*1024**2/65536*.12)
        self.assertLessEqual(probe.preload_timeout(2*1024**3,.12),3600)
        self.assertEqual(probe.preload_timeout(100*1024**2,0,60),60)
        for value in (0,-1,3601,float('nan')):
            with self.assertRaises(ValueError):probe.preload_timeout(100,0,value)

    def test_waits_for_delayed_server_start(self):
        server = SimpleNamespace(started=False)
        thread = SimpleNamespace(is_alive=lambda: True)
        with patch.object(probe.time, 'sleep', side_effect=lambda _: setattr(server, 'started', True)) as sleep:
            probe.wait_server_started(server, thread)
        sleep.assert_called_once()

    def test_server_start_is_bounded_and_detects_dead_thread(self):
        server = SimpleNamespace(started=False)
        with self.assertRaises(RuntimeError):
            probe.wait_server_started(server, SimpleNamespace(is_alive=lambda: False))
        with patch.object(probe.time, 'monotonic', side_effect=[0, 6]):
            with self.assertRaises(TimeoutError):
                probe.wait_server_started(server, SimpleNamespace(is_alive=lambda: True), timeout=5)


if __name__ == '__main__':
    unittest.main()
