"""Exact-source loader checks and optional real ICR synthetic-image check."""

import os
import importlib.util
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from platforms.rainyun.browser import Browser, click_offsets
from platforms.rainyun.provider import read_provider


class LoaderTests(unittest.TestCase):
    def test_unverified_source_is_not_executed(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            sentinel = directory / "executed"
            (directory / "ICR.py").write_text(f"open({str(sentinel)!r}, 'w').write('unexpected')")
            (directory / "stealth.min.js").write_text("unverified")
            with self.assertRaisesRegex(ValueError, "dependency_incompatible"):
                read_provider(directory)
            self.assertFalse(sentinel.exists())

    def test_missing_external_source_is_explicit(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(ValueError, "upstream_missing"):
                read_provider(root)


@unittest.skipUnless(importlib.util.find_spec("selenium"), "Install the locked Selenium environment")
class ChromiumRuntimeTests(unittest.TestCase):
    def test_long_common_tmpdir_uses_short_private_socket_directory(self):
        with tempfile.TemporaryDirectory(prefix="rainyun-long-" + "x" * 70) as directory:
            config = {"chromium_path": "/not-started/chrome", "chromedriver_path": "/not-started/chromedriver",
                      "provider_root": "/not-imported/provider"}
            browser = Browser(config, directory)
            driver = MagicMock()
            with patch("platforms.rainyun.browser.verify_runtime"), \
                 patch("platforms.rainyun.browser.read_provider", return_value=(lambda *_: [], "/* fixture */")), \
                 patch("selenium.webdriver.Chrome", return_value=driver) as launch, \
                 patch.dict(os.environ, {"TMPDIR": directory}):
                browser.open()
                kwargs = launch.call_args.kwargs
                temporary = Path(kwargs["service"].env["TMPDIR"])
                self.assertNotEqual(str(temporary), directory)
                self.assertEqual(os.environ["TMPDIR"], directory)
                self.assertNotIn("--no-sandbox", kwargs["options"].arguments)
                self.assertIn("--user-data-dir=" + str(Path(directory) / "browser"),
                              kwargs["options"].arguments)
                socket_directory = temporary / "org.chromium.Chromium.fixture"
                socket_directory.mkdir()
                with socket.socket(socket.AF_UNIX) as connection:
                    connection.bind(str(socket_directory / "SingletonSocket"))
                with socket.socket(socket.AF_UNIX) as connection:
                    with self.assertRaises(OSError):
                        connection.bind(str(Path(directory) / "SingletonSocket"))
                browser.close()
                self.assertFalse(temporary.exists())


@unittest.skipUnless(os.getenv("RAINYUN_TEST_PROVIDER_ROOT"),
                     "Set RAINYUN_TEST_PROVIDER_ROOT to the pinned external checkout")
class SyntheticICRTests(unittest.TestCase):
    def test_reviewed_algorithm_matches_ordered_synthetic_shapes(self):
        import cv2
        import numpy as np
        solve, script = read_provider(os.environ["RAINYUN_TEST_PROVIDER_ROOT"])
        self.assertTrue(script)
        background = np.full((220, 420, 3), 255, np.uint8)
        sprite = np.full((42, 120, 3), 255, np.uint8)
        cv2.circle(sprite, (20, 20), 9, (0, 0, 0), -1)
        cv2.fillPoly(sprite, [np.array([[60, 8], [49, 31], [71, 31]])], (0, 0, 0))
        cv2.rectangle(sprite, (94, 9), (102, 31), (0, 0, 0), -1)
        cv2.rectangle(sprite, (87, 17), (109, 23), (0, 0, 0), -1)
        for crop, destination in [((5, 5, 30, 32), (50, 65)),
                                  ((43, 5, 34, 32), (190, 65)),
                                  ((81, 5, 34, 32), (330, 65))]:
            x, y, w, h = crop
            shape = cv2.resize(sprite[y:y+h, x:x+w], (round(w*1.55), round(h*1.55)),
                               interpolation=cv2.INTER_NEAREST)
            tx, ty = destination
            background[ty:ty+shape.shape[0], tx:tx+shape.shape[1]] = shape
        matches = solve(background, sprite)
        self.assertEqual([match["sprite_idx"] for match in matches], [0, 1, 2])
        self.assertEqual(len(click_offsets(matches, (420, 220), (420, 220))), 3)
        for match, target in zip(matches, [(74, 90), (218, 90), (358, 90)]):
            x, y, w, h = match["bg_rect"]
            self.assertLessEqual(abs(x+w/2-target[0]), 5)
            self.assertLessEqual(abs(y+h/2-target[1]), 5)


if __name__ == "__main__":
    unittest.main()
