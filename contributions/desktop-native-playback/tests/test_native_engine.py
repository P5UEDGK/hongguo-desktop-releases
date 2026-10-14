"""Thread affinity, bounded reuse, cancellation and shutdown ownership."""
import threading
import time
import unittest
from types import SimpleNamespace
from desktop_native_engine import EnginePool


class EngineTests(unittest.TestCase):
    def pool(self, cleanup=lambda _:None, **kw):
        pool = EnginePool(cleanup, lambda:None, **kw)
        self.addCleanup(pool.close)
        return pool

    def session(self, run):
        return SimpleNamespace(stop=threading.Event(), job=SimpleNamespace(cancelled=threading.Event()), run=run)

    def test_successive_episodes_reuse_resources_on_the_same_owner_thread(self):
        closed=[];pool=self.pool(lambda r:closed.append(dict(r)))
        owners=[];resources=[]
        for _ in range(12):
            session=self.session(lambda:None)
            def run(session=session):
                owners.append(threading.get_ident())
                session.engine_resources.setdefault('player',object())
                resources.append(session.engine_resources['player'])
            session.run=run;task=pool.task(session);task.start();task.join(1)
            self.assertFalse(task.is_alive())
        self.assertEqual(len(set(owners)),1)
        self.assertTrue(all(p is resources[0] for p in resources))
        self.assertEqual(pool.snapshot()['engineWorkersCreated'],1)
        self.assertEqual(pool.snapshot()['engineAssignmentsReused'],11)
        self.assertTrue(pool.close());self.assertEqual(len(closed),1)

    def test_current_and_standby_are_bounded_and_cannot_share_an_active_slot(self):
        pool=self.pool();release=threading.Event();started=[threading.Event(),threading.Event()]
        self.addCleanup(release.set)
        tasks=[];identities=[]
        for index in range(2):
            session=self.session(lambda:None)
            def run(session=session,index=index):
                identities.append(id(session.engine_resources));started[index].set();release.wait(2)
            session.run=run;task=pool.task(session);task.start();tasks.append(task)
        self.assertTrue(all(e.wait(1) for e in started));self.assertEqual(len(set(identities)),2)
        third=pool.task(self.session(lambda:None))
        with self.assertRaisesRegex(RuntimeError,'limit'):third.start()
        self.assertFalse(third.is_alive());release.set()
        for task in tasks:task.join(1)
        self.assertEqual(pool.snapshot()['engineSlots'],2)

    def test_cancelled_task_never_allocates_an_engine(self):
        pool=self.pool();session=self.session(lambda:self.fail('cancelled session ran'))
        session.job.cancelled.set()
        with self.assertRaises(RuntimeError):pool.task(session).start()
        self.assertEqual(pool.snapshot()['engineWorkersCreated'],0)

    def test_shutdown_cancels_active_task_and_rejects_new_work(self):
        pool=self.pool();entered=threading.Event();session=self.session(lambda:None)
        def run():entered.set();session.stop.wait(2)
        session.run=run;task=pool.task(session);task.start();self.assertTrue(entered.wait(1))
        self.assertTrue(pool.close());self.assertFalse(task.is_alive());self.assertEqual(pool.snapshot()['engineSlots'],0)
        with self.assertRaises(RuntimeError):pool.task(self.session(lambda:None)).start()

    def test_idle_resources_retire_on_their_owner_thread(self):
        destroyed=threading.Event();owner=[];cleanup=[]
        def close(_):cleanup.append(threading.get_ident());destroyed.set()
        pool=self.pool(close,idle_seconds=.05)
        task=pool.task(self.session(lambda:owner.append(threading.get_ident())));task.start();task.join(1)
        self.assertTrue(destroyed.wait(1));self.assertEqual(owner,cleanup)
        self.assertTrue(pool.close());self.assertEqual(pool.snapshot()['engineSlots'],0)

    def test_unfinished_shutdown_does_not_report_worker_released(self):
        entered=threading.Event();release=threading.Event();pool=self.pool()
        self.addCleanup(release.set)
        task=pool.task(self.session(lambda:(entered.set(),release.wait(2))))
        task.start();self.assertTrue(entered.wait(1))
        self.assertFalse(pool.close(timeout=.01));self.assertTrue(task.is_alive())
        release.set();self.assertTrue(pool.close());self.assertFalse(task.is_alive())
