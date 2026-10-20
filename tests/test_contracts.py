import hashlib
from pathlib import Path
import tempfile
import unittest
from common.contracts import verify_files


class ContractTests(unittest.TestCase):
    def test_file_pin(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "source.py"
            p.write_text("pass\n")
            h = hashlib.sha256(p.read_bytes()).hexdigest()
            self.assertIsNone(verify_files(d, {"source.py": h}))
            p.write_text("change\n")
            self.assertEqual(
                verify_files(d, {"source.py": h}), "dependency_incompatible"
            )
