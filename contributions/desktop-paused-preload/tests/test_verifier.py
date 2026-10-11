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
