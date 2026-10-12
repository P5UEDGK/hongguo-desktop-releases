"""Input ownership: both Windows hit-test paths use the host WebView handler."""
import ctypes as C
import ctypes.wintypes as W
from types import SimpleNamespace
import unittest
from desktop_native import NativeSession

class InputTests(unittest.TestCase):
    def make_session(self, children):
        class User:
            hooks=[];posts=[]
            def EnumChildWindows(self,parent,callback,_):
                for hwnd in ([200] if parent==1 else children):callback(hwnd,0)
            def GetClassNameW(self,hwnd,name,_):name.value='Chrome_RenderWidgetHostHWND'
            def SetWindowLongPtrW(self,hwnd,_,procedure):self.hooks.append(hwnd);return 99
            def MapWindowPoints(self,source,target,point,_):
                p=C.cast(point,C.POINTER(W.POINT));p.contents.x+=9;p.contents.y+=7
            def PostMessageW(self,*args):self.posts.append(args);return True
            def CallWindowProcW(self,*_):return 123
        user=User();session=object.__new__(NativeSession)
        session.parent=1;session.input_hooks={};session.host=SimpleNamespace(user=user,
            enum_callback=lambda fn:fn,window_callback=getattr(C,'WINFUNCTYPE',C.CFUNCTYPE)(C.c_ssize_t,W.HWND,W.UINT,W.WPARAM,W.LPARAM))
        return session,user
    def test_outer_container_and_renderer_forward_once_without_duplicate_hooks(self):
        session,user=self.make_session([11]);self.assertTrue(session.forward_input(10))
        self.assertEqual(user.hooks,[10,11]);session.forward_input(10);self.assertEqual(user.hooks,[10,11])
        for hwnd in (10,11):
            procedure=session.input_hooks[hwnd][1];before=len(user.posts)
            self.assertEqual(procedure(hwnd,0x0201,1,(20<<16)|10),0)
            self.assertEqual(len(user.posts),before+1)
            self.assertEqual(user.posts[-1],(200,0x0201,1,(27<<16)|19))
            self.assertEqual(procedure(hwnd,0x0021,0,0),3)
            self.assertEqual(procedure(hwnd,0x0084,0,0),1 if hwnd==10 else 123)
            self.assertEqual(procedure(hwnd,0x000F,0,0),123)
        self.assertEqual(len(user.posts),2)
    def test_container_without_renderer_child_still_forwards_input(self):
        session,user=self.make_session([]);self.assertTrue(session.forward_input(10))
        self.assertEqual(user.hooks,[10]);session.input_hooks[10][1](10,0x0100,32,0)
        self.assertEqual(user.posts[-1],(200,0x0100,32,0))

if __name__=='__main__':unittest.main()
