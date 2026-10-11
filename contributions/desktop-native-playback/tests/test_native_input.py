"""Input ownership: both Windows hit-test paths use the host WebView handler."""
import ctypes as C
import ctypes.wintypes as W
from types import SimpleNamespace
import unittest
from desktop_native import NativeSession

class InputTests(unittest.TestCase):
    def test_webview_target_recreation_redirects_existing_surface_hooks(self):
        session,user=self.make_session([11]);user.widgets=[200];session.forward_input(10)
        session.input_hooks[10][1](10,0x0100,32,0);self.assertEqual(user.posts[-1][0],200)
        user.widgets=[201];user.IsWindow=lambda hwnd:hwnd in (10,11,201)
        session.forward_input(10)
        for surface in (10,11):
            session.input_hooks[surface][1](surface,0x0100,32,0);self.assertEqual(user.posts[-1][0],201)
        self.assertEqual(user.hooks,[10,11],'unchanged surfaces keep one WNDPROC while target follows current WebView')

    def test_recreated_renderer_is_hooked_and_dead_callback_is_removed(self):
        children=[11];session,user=self.make_session(children);session.forward_input(10)
        children[:]=[12];user.IsWindow=lambda hwnd:hwnd in (10,12,200)
        session.forward_input(10)
        self.assertNotIn(11,session.input_hooks);self.assertIn(12,session.input_hooks)
        self.assertEqual(user.hooks,[10,11,12]);session.input_hooks[12][1](12,0x0100,32,0)
        self.assertEqual(user.posts[-1],(200,0x0100,32,0))

    def test_ready_worker_refreshes_input_hooks_even_when_container_is_hooked(self):
        import ast,inspect
        tree=ast.parse(inspect.getsource(NativeSession))
        call=next(n for n in ast.walk(tree) if isinstance(n,ast.If) and any(isinstance(x,ast.Call) and isinstance(x.func,ast.Attribute) and x.func.attr=='forward_input' for x in n.body for x in ast.walk(x)))
        calls=[];session=SimpleNamespace(input_hooks={10:object()},forward_input=lambda hwnd:(calls.append(hwnd) or True))
        exec(compile(ast.fix_missing_locations(ast.Module(body=[call],type_ignores=[])),'<actual-input-refresh>','exec'),dict(output_ready=True,self=session,hwnd=10))
        self.assertEqual(calls,[10])

    def make_session(self, children):
        class User:
            hooks=[];posts=[]
            def IsWindow(self,hwnd):return True
            def EnumChildWindows(self,parent,callback,_):
                for hwnd in (getattr(self,'widgets',[200]) if parent==1 else children):callback(hwnd,0)
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
