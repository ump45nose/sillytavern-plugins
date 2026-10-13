import hashlib
from pathlib import Path
import tempfile
import unittest
from common.contracts import verify_files
from platforms.rewards.summary import aggregate, summarize
from platforms.rewards.compat import validate_config
from platforms.epic.guard import zero_total, cart_safe


class ContractTests(unittest.TestCase):
    def test_null_counter_regression(self):
        self.assertEqual(
            aggregate(
                [{"eligibility": "eligible", "current": None, "max": None}], True
            ),
            "unknown",
        )
        self.assertEqual(
            aggregate([{"eligibility": "eligible", "current": 0, "max": 0}], True),
            "unknown",
        )

    def test_empty_inventory_requires_evidence(self):
        self.assertEqual(aggregate([], False), "unknown")
        self.assertEqual(aggregate([], True), "not_applicable")
        self.assertEqual(aggregate([{"current": 100, "max": 100}], True), "unknown")

    def test_blocked_does_not_claim_earned(self):
        self.assertEqual(aggregate([{"eligibility": "blocked"}], True), "blocked")

    def test_stale_unknown(self):
        self.assertEqual(set(summarize({"fresh": False}).values()), {"unknown"})

    def test_parallelism_gate(self):
        cfg = {
            "clusters": 1,
            "headless": True,
            "searchSettings": {"parallelSearching": False, "clusterSearch": False},
            "workers": {"doDailySet": False},
        }
        self.assertIsNone(validate_config(cfg, [{}]))
        self.assertEqual(validate_config(cfg, [{}, {}]), "single_account_required")
        cfg["searchSettings"]["parallelSearching"] = True
        self.assertEqual(validate_config(cfg, [{}]), "parallel_browser_unsupported")

    def test_checkout_guard(self):
        self.assertTrue(zero_total("Order total\nUSD 0.00\n"))
        for text in [
            "Order total\nUSD 0.01",
            "Total unknown",
            "Subtotal\nUSD 0.00",
            "Total\n1,000.00",
            "Total 0.00\nTotal 9.99",
            "Total 0.00 pending",
        ]:
            self.assertFalse(zero_total(text))
        self.assertTrue(cart_safe([]))
        self.assertFalse(cart_safe(None))
        self.assertFalse(cart_safe([{"explicit_free": False}]))

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


class QueryClusteringTests(unittest.TestCase):
    def test_topic_clustering_is_not_browser_parallelism(self):
        config = {
            "clusters": 1,
            "headless": True,
            "searchSettings": {"parallelSearching": False, "clusterSearch": True},
            "workers": {"doDailySet": False},
        }
        self.assertIsNone(validate_config(config, [{}]))
