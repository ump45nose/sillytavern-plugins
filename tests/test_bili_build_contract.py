import json
from pathlib import Path
import unittest


class BiliBuildContract(unittest.TestCase):
    def test_legacy_build_paths_resolve_to_one_pinned_subsection(self):
        root = Path(__file__).resolve().parents[1]
        section = root / "bili-sync"
        pin = json.loads((section / "UPSTREAM.json").read_text())
        for name in ("Dockerfile.bili-sync", "bili-sync-v2.11.1-flat.patch"):
            self.assertTrue((root / name).is_symlink())
            self.assertEqual((root / name).resolve(), section / name)
        dockerfile = (section / "Dockerfile.bili-sync").read_text()
        self.assertIn(pin["upstream_commit"], dockerfile)
        self.assertIn(pin["upstream_commit"], (section / "scripts/test-flat-output.sh").read_text())
        compose = (root / "compose.yaml").read_text()
        self.assertIn("./state/bili-sync:/app/.config/bili-sync", compose)
        self.assertIn("/Bilibili:/downloads/Bilibili", compose)


if __name__ == "__main__":
    unittest.main()
