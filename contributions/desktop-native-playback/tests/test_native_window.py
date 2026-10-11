"""Bind authenticated host geometry to one actual process-owned window."""
import ctypes as C
from ctypes import wintypes as W
from pathlib import Path
from types import SimpleNamespace
import threading,time,unittest
from unittest.mock import patch
from desktop_native import NativeHost

class WindowTests(unittest.TestCase):
    def host(self):
        host=NativeHost(dll_path=Path('missing-owned-fixture.dll'),parent_pid=42)
        rows={1:(42,[0,0,1400,900],False),2:(42,[100,150,600,400],True),3:(99,[100,150,600,400],False)}
        def pid(hwnd,out):out._obj.value=rows[hwnd][0];return 1
        def rect(hwnd,out):out._obj.right,out._obj.bottom=rows[hwnd][1][2:];return True
        def origin(hwnd,out):out._obj.x,out._obj.y=rows[hwnd][1][:2];return True
        host.enum_callback=lambda fn:fn
        host.user=SimpleNamespace(EnumWindows=lambda fn,_:[fn(h,0) for h in rows],GetWindowThreadProcessId=pid,
            GetClientRect=rect,ClientToScreen=origin,GetWindow=lambda h,_:1 if rows[h][2] else 0,
            IsWindow=lambda h:h in rows,SetThreadDpiAwarenessContext=lambda _:1)
        return host,rows

    def test_owned_smaller_player_binds_instead_of_larger_main_window(self):
        host,rows=self.host()
        parent=host.bind_window({'rect':[100,150,600,400]})
        self.assertEqual(parent,2)
        self.assertEqual(host.parent_window(SimpleNamespace(native_parent=parent)),2)
        rows[2]=(99,[100,150,600,400],True)
        with self.assertRaises(RuntimeError):host.parent_window(SimpleNamespace(native_parent=parent))

    def test_multiple_unbound_windows_are_not_chosen_by_area(self):
        host,rows=self.host();rows[2]=(42,[100,150,600,400],False)
        with self.assertRaises(RuntimeError):host.parent_window()
        rows.pop(2);self.assertEqual(host.parent_window(),1)

    def test_ambiguous_or_arbitrary_window_context_is_rejected(self):
        host,rows=self.host();rows[4]=rows[2]
        for context in ({'rect':[100,150,600,400]},{'hwnd':2},{'rect':[True,0,600,400]}, {'rect':[0,0,1,1]}):
            with self.subTest(context=context),self.assertRaises(ValueError):host.bind_window(context)

class PrepareTests(unittest.TestCase):
    def test_slow_previous_owner_keeps_new_job_pending_and_does_not_hold_host_lock(self):
        host=NativeHost(dll_path=Path('missing-owned-fixture.dll'));host.available=True
        entered,release=threading.Event(),threading.Event();errors=[]
        def close():entered.set();release.wait(2);return release.is_set()
        host.sessions={'old':SimpleNamespace(close=close)}
        job=SimpleNamespace(id='new',cancelled=threading.Event())
        with patch.object(host,'parent_window',return_value=1),patch('desktop_native.NativeSession') as factory:
            thread=threading.Thread(target=lambda:self.prepare(host,job,errors));thread.start()
            try:
                self.assertTrue(entered.wait(1))
                acquired=host.guard.acquire(timeout=.2)
                if acquired:host.guard.release()
                self.assertTrue(acquired,'slow close must not block status or cancellation')
                self.assertEqual(host.snapshot(job.id),{'state':'preparing'})
                self.assertTrue(thread.is_alive());factory.assert_not_called()
            finally:release.set();thread.join(2)
            self.assertFalse(thread.is_alive());self.assertEqual(errors,[])
            factory.return_value.thread.start.assert_called_once()
            self.assertEqual(set(host.sessions),{'new'})

    def test_previous_owner_pending_can_be_cancelled_without_starting_new_session(self):
        host=NativeHost(dll_path=Path('missing-owned-fixture.dll'));host.available=True
        entered=threading.Event();errors=[]
        host.sessions={'old':SimpleNamespace(close=lambda:(entered.set() or False))}
        job=SimpleNamespace(id='new',cancelled=threading.Event())
        with patch('desktop_native.NativeSession') as factory:
            thread=threading.Thread(target=lambda:self.prepare(host,job,errors));thread.start()
            try:self.assertTrue(entered.wait(1));job.cancelled.set()
            finally:thread.join(1)
            self.assertFalse(thread.is_alive());self.assertEqual(errors,['RuntimeError']);factory.assert_not_called()
            self.assertEqual(set(host.sessions),{'old'});self.assertNotIn('new',host.preparing)

    @staticmethod
    def prepare(host,job,errors):
        try:host.prepare(job)
        except Exception as exc:errors.append(type(exc).__name__)

if __name__=='__main__':unittest.main()
