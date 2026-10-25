#!/usr/bin/env python3
"""Exercise catalog download limits without network or desktop side effects."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
LIMIT = 4 * 1024 * 1024
CATALOG = {"channels": [{"id": "bossa", "title": "Bossa Beyond",
                         "description": "Radio", "playlists": [
                             {"format": "mp3", "url": "https://ice6.somafm.com/bossa-128-mp3"}]}]}


class CatalogSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="somafm-security-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.bin = self.base / "bin"
        self.bin.mkdir()
        self.data = self.base / "data" / "somafm-bar"
        self.data.mkdir(parents=True)
        self.runtime = self.base / "runtime"
        self.runtime.mkdir(mode=0o700)
        self.args = self.base / "curl-args.json"
        self.cache = self.data / "channels-cache.json"
        self.env = {**os.environ, "PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
                    "XDG_RUNTIME_DIR": str(self.runtime), "XDG_DATA_HOME": str(self.data.parent),
                    "SOMA_TEST_ARGS": str(self.args), "SOMA_TEST_CATALOG": json.dumps(CATALOG),
                    "SOMA_TEST_MODE": "valid"}
        curl = self.bin / "curl"
        curl.write_text('''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
Path(os.environ["SOMA_TEST_ARGS"]).write_text(json.dumps(sys.argv[1:]))
mode = os.environ["SOMA_TEST_MODE"]
if mode == "fail":
    sys.exit(22)
if mode == "oversized":
    # Ignore curl's own limit to exercise the post-download check too.
    sys.stdout.write(" " * (4 * 1024 * 1024 + 1))
sys.stdout.write(os.environ["SOMA_TEST_CATALOG"])
''')
        curl.chmod(0o700)

    def stations(self):
        result = subprocess.run([str(ROOT / "player"), "stations"], env=self.env,
                                capture_output=True, text=True, timeout=10, check=True)
        return json.loads(result.stdout)

    def test_valid_download_is_https_and_bounded(self):
        self.assertEqual(self.stations()[0]["name"], "Bossa Beyond")
        args = json.loads(self.args.read_text())
        self.assertEqual(args[args.index("--proto") + 1], "=https")
        self.assertEqual(args[args.index("--max-filesize") + 1], str(LIMIT))
        self.assertIn("-fsS", args)
        self.assertEqual(json.loads(self.cache.read_text()), CATALOG)
        self.assertEqual(self.cache.stat().st_mode & 0o777, 0o600)

    def test_fresh_valid_cache_avoids_download(self):
        self.cache.write_text(json.dumps(CATALOG))
        self.assertEqual(len(self.stations()), 1)
        self.assertFalse(self.args.exists())

    def test_oversized_fresh_cache_is_ignored(self):
        self.cache.write_text(" " * (LIMIT + 1) + json.dumps(CATALOG))
        self.env["SOMA_TEST_MODE"] = "fail"
        self.assertEqual(self.stations(), [])
        self.assertTrue(self.args.exists())

    def test_stale_valid_cache_survives_download_failure(self):
        self.cache.write_text(json.dumps(CATALOG))
        old = time.time() - 7200
        os.utime(self.cache, (old, old))
        self.env["SOMA_TEST_MODE"] = "fail"
        self.assertEqual(len(self.stations()), 1)

    def test_oversized_download_is_not_cached(self):
        self.env["SOMA_TEST_MODE"] = "oversized"
        self.assertEqual(self.stations(), [])
        self.assertFalse(self.cache.exists())
        self.assertEqual(list(self.data.glob("ch.*.json")), [])


if __name__ == "__main__":
    unittest.main()
