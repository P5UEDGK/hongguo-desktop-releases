"""Owner scheduling regressions: no polling delay for transport controls."""
import queue
import threading
import unittest
from types import SimpleNamespace

from desktop_native import NativeSession


class FastHandoffTests(unittest.TestCase):
    def session(self):
        host=SimpleNamespace(hardware=True)
        job=SimpleNamespace(start_seconds=0,duration=90)
        return NativeSession(host,job,1)

    def test_submit_wakes_owner_without_poll_wait(self):
        session=self.session()
        self.assertFalse(session.wake.is_set())
        revision=session.submit({'paused':False,'muted':False,'rate':3})
        self.assertTrue(session.wake.wait(0))
        self.assertEqual(session.commands.get_nowait(),(revision,{'paused':False,'muted':False,'rate':3}))
        self.assertEqual(session.desired_state()['rate'],3)

    def test_full_queue_does_not_change_revision_intent_or_wake(self):
        session=self.session()
        for _ in range(64):session.submit({'paused':True})
        revision=session.revision;session.wake.clear()
        with self.assertRaises(queue.Full):session.submit({'paused':False})
        self.assertEqual(session.revision,revision)
        self.assertTrue(session.desired_state()['paused'])
        self.assertFalse(session.wake.is_set())

    def test_close_wakes_owner(self):
        session=self.session()
        self.assertTrue(session.close())
        self.assertTrue(session.stop.is_set())
        self.assertTrue(session.wake.is_set())


if __name__=='__main__':unittest.main()
