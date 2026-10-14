import concurrent.futures
import io
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest

from PIL import Image
from desktop_posters import PosterCache, cover_url, MAX_BYTES

SID = '9000000000000001'
OTHER = '9000000000000002'
URL = 'https://p3-reading-sign.fqnovelpic.com/fixture.jpg'


def picture():
    target = io.BytesIO()
    Image.new('RGB', (30, 40), 'red').save(target, 'JPEG')
    return target.getvalue()


class PosterTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.downloads = []
        self.now = 1000
        self.cache = PosterCache(self.directory, self.fetch, lambda: self.now)

    def fetch(self, url):
        self.downloads.append(url)
        return picture()

    def test_existing_native_bytes_need_no_url_or_download(self):
        self.cache.path(SID).write_bytes(picture())
        self.assertTrue(self.cache.get(SID, None).startswith('data:image/jpeg;base64,'))
        self.assertEqual(self.downloads, [])

    def test_first_fetch_then_restart_has_no_download(self):
        first = self.cache.get(SID, URL)
        self.assertTrue(first)
        restarted = PosterCache(self.directory, lambda _: self.fail('Unexpected upstream call'))
        self.assertEqual(restarted.get(SID, None), first)
        self.assertEqual(self.downloads, [URL])

    def test_concurrent_identity_downloads_once(self):
        entered, release = threading.Event(), threading.Event()
        def slow(url):
            entered.set()
            release.wait(3)
            return self.fetch(url)
        self.cache.fetch = slow
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            first = pool.submit(self.cache.get, SID, URL)
            self.assertTrue(entered.wait(2))
            second = pool.submit(self.cache.get, SID, URL)
            release.set()
            self.assertEqual(first.result(4), second.result(4))
        self.assertEqual(self.downloads, [URL])

    def test_corrupt_one_repairs_and_preserves_other(self):
        self.cache.path(SID).write_bytes(b'broken')
        valid = picture()
        self.cache.path(OTHER).write_bytes(valid)
        self.assertTrue(self.cache.get(SID, URL))
        self.assertEqual(self.cache.path(OTHER).read_bytes(), valid)
        self.assertEqual(self.downloads, [URL])
        self.assertFalse(list(self.cache.root.glob('*.tmp')))

    def test_failure_cooldown_then_recovery(self):
        calls = []
        def failed(url):
            calls.append(url)
            raise OSError('Offline fixture')
        self.cache.fetch = failed
        self.assertIsNone(self.cache.get(SID, URL))
        self.assertIsNone(self.cache.get(SID, URL))
        self.assertEqual(calls, [URL])
        self.now += 301
        self.cache.fetch = self.fetch
        self.assertTrue(self.cache.get(SID, URL))

    def test_identity_url_and_image_validation(self):
        for sid in (int(SID), '../x', '9000000', '9' * 25):
            with self.assertRaises(ValueError):
                self.cache.read(sid)
        for value in ('https://fqnovelpic.com.evil.test/a', 'file:///x', 'http://x@fqnovelpic.com/a'):
            self.assertIsNone(cover_url(value))
        self.assertEqual(cover_url(URL), URL)
        for value in (b'<html>error</html>', b'x' * (MAX_BYTES + 1)):
            with self.assertRaises((ValueError, OSError)):
                self.cache.encode(value)

    def test_mapped_directory_reuses_native_file(self):
        physical = self.directory / 'physical'
        physical.mkdir()
        link = self.directory / 'poster-cache-v1'
        link.rmdir()
        if os.name == 'nt':
            subprocess.run(['pwsh', '-NoProfile', '-Command',
                            'New-Item -ItemType Junction -Path $env:POSTER_TEST_LINK -Target $env:POSTER_TEST_TARGET | Out-Null'],
                           env={**os.environ, 'POSTER_TEST_LINK': str(link), 'POSTER_TEST_TARGET': str(physical)},
                           check=True, capture_output=True)
        else:
            link.symlink_to(physical, target_is_directory=True)
        try:
            (physical / (SID + '.cover')).write_bytes(picture())
            cache = PosterCache(self.directory, self.fetch)
            self.assertTrue(cache.get(SID, None))
            self.assertEqual(self.downloads, [])
        finally:
            if os.name == 'nt':
                link.rmdir()
            else:
                link.unlink()

    def test_bad_response_leaves_no_new_file(self):
        self.cache.fetch = lambda _: b'<html>error</html>'
        self.assertIsNone(self.cache.get(SID, URL))
        self.assertFalse(self.cache.path(SID).exists())
        self.assertFalse(list(self.cache.root.glob('*.tmp')))

    def test_profiles_do_not_share_wrong_identity(self):
        self.assertTrue(self.cache.get(SID, URL))
        isolated = PosterCache(self.directory / 'isolated', self.fetch)
        self.assertIsNone(isolated.read(SID))
        self.assertIsNone(self.cache.read(OTHER))

    def test_selected_root_copies_existing_images_and_restarts(self):
        first = self.cache.get(SID, URL)
        candidate = self.cache.prepare_directory(self.directory / 'selected')
        self.assertEqual(candidate.read(SID), first)
        self.cache.activate(candidate)
        restarted = PosterCache(self.directory / 'selected', lambda _: self.fail('Unexpected download'))
        self.assertEqual(restarted.get(SID, None), first)
        self.assertEqual(self.downloads, [URL])

    def test_inflight_download_follows_selected_root_without_duplicate(self):
        entered, release = threading.Event(), threading.Event()
        def slow(url):
            entered.set()
            release.wait(3)
            return self.fetch(url)
        self.cache.fetch = slow
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            first = pool.submit(self.cache.get, SID, URL)
            self.assertTrue(entered.wait(2))
            candidate = self.cache.prepare_directory(self.directory / 'selected')
            self.cache.activate(candidate)
            second = pool.submit(candidate.get, SID, URL)
            release.set()
            self.assertEqual(first.result(4), second.result(4))
        self.assertTrue(candidate.path(SID).is_file())
        self.assertEqual(self.downloads, [URL])

    def test_prepare_failure_does_not_redirect_current_cache(self):
        first = self.cache.get(SID, URL)
        invalid = self.directory / 'file'
        invalid.write_bytes(b'keep')
        with self.assertRaises(OSError):
            self.cache.prepare_directory(invalid)
        self.assertIsNone(self.cache._next)
        self.assertEqual(self.cache.read(SID), first)


if __name__ == '__main__':
    unittest.main()
