#!/usr/bin/env python3
"""自包含测试：python3 tests/run_tests.py"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from workbuddy_updater import core  # noqa: E402

SAMPLE_JSON = {
    "version": "5.5.4.38151288",
    "url": "https://download.codebuddy.cn/workbuddy/saas/linux-x64-deb/"
    "WorkBuddy-linux-x64-deb-5.5.4.38151288-1ca4889a.deb",
    "productVersion": "5.5.4.38151288",
    "sha256hash": "03d756b259d7086c22098fa077589a032d60948d1de7313473360eefe11e240f",
}


class FilenameTests(unittest.TestCase):
    def test_parse_filename_version(self) -> None:
        name = "WorkBuddy-linux-x64-deb-5.5.4.38151288-1ca4889a.deb"
        self.assertEqual(core.parse_filename_version(name), "5.5.4.38151288")

    def test_parse_filename_fallback(self) -> None:
        self.assertEqual(core.parse_filename_version("workbuddy_5.5.4_amd64.deb"), "5.5.4")

    def test_release_filename(self) -> None:
        release = core.Release(version="x", url=SAMPLE_JSON["url"])
        self.assertEqual(release.filename, "WorkBuddy-linux-x64-deb-5.5.4.38151288-1ca4889a.deb")


class VersionLogicTests(unittest.TestCase):
    def test_same_build(self) -> None:
        self.assertTrue(core.is_same_build("5.5.4.38151288", "5.5.4.38151288"))
        self.assertTrue(core.is_same_build("5.5.4", "5.5.4.38151288"))
        self.assertFalse(core.is_same_build("5.5.3", "5.5.4.38151288"))
        self.assertFalse(core.is_same_build("", "5.5.4.38151288"))

    def test_human_size(self) -> None:
        self.assertEqual(core.human_size(512), "512 B")
        self.assertEqual(core.human_size(429286148), "409.4 MiB")


class ParseTests(unittest.TestCase):
    def test_parse_release(self) -> None:
        release = core.parse_release(json.dumps(SAMPLE_JSON).encode())
        self.assertIsNotNone(release)
        assert release
        self.assertEqual(release.version, "5.5.4.38151288")
        self.assertTrue(release.sha256.startswith("03d756b2"))

    def test_empty_payload(self) -> None:
        self.assertIsNone(core.parse_release(b""))
        self.assertIsNone(core.parse_release(b"   "))

    def test_api_error(self) -> None:
        with self.assertRaises(core.UpdaterError):
            core.parse_release(json.dumps({"code": 10001, "msg": "invalid platform"}).encode())

    def test_rejects_http_url(self) -> None:
        bad = dict(SAMPLE_JSON, url="http://example.com/x.deb")
        with self.assertRaises(core.UpdaterError):
            core.parse_release(json.dumps(bad).encode())


class CheckTests(unittest.TestCase):
    def test_204_means_up_to_date(self) -> None:
        with mock.patch.object(core, "_http_request", return_value=(204, b"")):
            self.assertIsNone(core.check_latest(installed="5.5.4.38151288"))

    def test_update_available(self) -> None:
        with mock.patch.object(core, "_http_request", return_value=(200, json.dumps(SAMPLE_JSON).encode())):
            release = core.check_latest(installed="5.5.3")
        self.assertIsNotNone(release)
        assert release
        self.assertEqual(release.version, "5.5.4.38151288")

    def test_short_version_is_treated_as_same_build(self) -> None:
        with mock.patch.object(core, "_http_request", return_value=(200, json.dumps(SAMPLE_JSON).encode())):
            self.assertIsNone(core.check_latest(installed="5.5.4"))

    def test_request_parameters(self) -> None:
        captured: dict = {}

        def fake(url, params=None, timeout=30):
            captured["url"] = url
            captured["params"] = params
            return 204, b""

        with mock.patch.object(core, "_http_request", side_effect=fake):
            core.check_latest(installed="5.5.4.38151288")
        self.assertEqual(captured["url"], core.API_URL)
        self.assertEqual(captured["params"]["platform"], core.PLATFORM)
        self.assertEqual(captured["params"]["version"], "5.5.4.38151288")


class StateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self._old = os.environ.get("WORKBUDDY_UPDATER_STATE_DIR")
        os.environ["WORKBUDDY_UPDATER_STATE_DIR"] = self.tmp.name

    def tearDown(self) -> None:
        if self._old is None:
            os.environ.pop("WORKBUDDY_UPDATER_STATE_DIR", None)
        else:
            os.environ["WORKBUDDY_UPDATER_STATE_DIR"] = self._old
        self.tmp.cleanup()

    def test_record_and_load(self) -> None:
        core.record_install("5.5.4.38151288", "/tmp/workbuddy.deb")
        state = core.load_state()
        self.assertEqual(state["installed_version"], "5.5.4.38151288")
        self.assertEqual(state["installed_deb"], "/tmp/workbuddy.deb")

    def test_log(self) -> None:
        line = core.log("hello")
        self.assertIn("hello", line)
        self.assertTrue((Path(self.tmp.name) / "updater.log").is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
