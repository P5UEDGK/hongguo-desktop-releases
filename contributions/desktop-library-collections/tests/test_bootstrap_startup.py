"""The parent must receive its endpoint even while cache preparation is blocked."""
import builtins
import importlib.util
import io
import os
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "src/desktop_bootstrap.py"

class PreparationFailed(RuntimeError):
    pass

class BootstrapStartupTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("startup_under_test", SOURCE)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        config = self.root / "content-config.json"
        config.write_text("{}", encoding="utf-8")
        self.env = {"HONGGUO_SESSION_API_KEY": "a" * 64,
                    "HONGGUO_BACKEND_DATA_DIR": str(self.root),
                    "HONGGUO_CONTENT_CONFIG": str(config),
                    "HONGGUO_HLS_WORK_DIR": str(self.root / "work")}

    def test_blocked_framework_or_cache_preparation_cannot_block_endpoint_control_line(self):
        blocked, release, announced = (threading.Event() for _ in range(3))
        original_import = builtins.__import__
        endpoints, errors = [], []
        def slow_import(name, *args, **kwargs):
            if name == "desktop_cache_settings":
                blocked.set()
                if not release.wait(3):
                    raise AssertionError("test failed to release its import gate")
                raise PreparationFailed("controlled initialization failure")
            return original_import(name, *args, **kwargs)
        def announce(listener):
            endpoints.append(listener.getsockname())
            announced.set()
            return endpoints[-1][1]
        def run():
            try:
                self.module.main()
            except BaseException as error:
                errors.append(error)
        with patch.dict(os.environ, self.env), patch("sys.stdin", io.StringIO("START\n")), \
             patch("builtins.__import__", slow_import), patch.object(self.module, "announce_endpoint", announce):
            worker = threading.Thread(target=run)
            worker.start()
            try:
                self.assertTrue(blocked.wait(1), "initialization gate was not reached")
                received_while_blocked = announced.wait(.2)
            finally:
                release.set()
                worker.join(3)
            self.assertFalse(worker.is_alive())
            self.assertTrue(received_while_blocked, "slow initialization blocked the parent's endpoint deadline")
        self.assertIsInstance(errors[0], PreparationFailed)
        # Announcing a bound port is not service readiness. On failure its socket
        # must be released rather than advertising an abandoned listener.
        with socket.socket() as check:
            check.bind(endpoints[0])

    def test_missing_handshake_creates_no_socket_or_framework_import(self):
        with patch("sys.stdin", io.StringIO("")), patch.object(self.module, "api_socket") as bind:
            with self.assertRaisesRegex(RuntimeError, "handshake"):
                self.module.main()
            bind.assert_not_called()

    def test_invalid_session_creates_no_socket(self):
        with patch.dict(os.environ, {**self.env, "HONGGUO_SESSION_API_KEY": "invalid"}), \
             patch("sys.stdin", io.StringIO("START\n")), patch.object(self.module, "api_socket") as bind:
            with self.assertRaisesRegex(RuntimeError, "credential"):
                self.module.main()
            bind.assert_not_called()

if __name__ == "__main__":
    unittest.main(verbosity=2)
