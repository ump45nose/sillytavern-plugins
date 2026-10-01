import json
from pathlib import Path
import tempfile
import unittest
from common.intervention_signal import create_checkpoint


class LaowangSignalTests(unittest.TestCase):
    def test_exact_platform_scope(self):
        context = {
            "run_id": "test",
            "platform": "laowang",
            "account": "default",
            "business_date": "2026-10-01",
        }
        signal = {
            "schema_version": 1,
            "run_id": "test",
            "platform": "laowang",
            "account": "default",
            "capability": "tncode",
            "phase": "tncode_drag",
            "kind": "captcha",
            "target": "https://laowang.vip/plugin.php",
            "fingerprint": "a" * 64,
            "ttl_seconds": 300,
        }
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "signal.json"
            file.write_text(json.dumps(signal))
            request = create_checkpoint(file, context, "full")
            self.assertEqual(request["kind"], "captcha")
            self.assertEqual(request["capability"], "tncode")
            for changes in (
                {"target": "https://rewards.bing.com/earn"},
                {"capability": "daily"},
                {"kind": "terms"},
                {"target": "https://laowang.vip/plugin.php?secret=x"},
            ):
                file.write_text(json.dumps({**signal, **changes}))
                with self.assertRaises(ValueError):
                    create_checkpoint(file, context, "full")
