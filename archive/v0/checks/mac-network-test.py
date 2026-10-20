"""Offline accounting, failed upload, racing updates and unified ingestion checks."""
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from personal_data_hub.contracts import digest
from personal_data_hub.network_ingest import ingest_network
from personal_data_hub.storage import Store

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("network", root / "agents/mac/network/collector.py")
network = importlib.util.module_from_spec(spec); spec.loader.exec_module(network)


class NetworkTests(unittest.TestCase):
    def test_baseline_increment_reset_and_ack_race(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "traffic.db"
            config = {"device_id": "a" * 32, "timezone": "Asia/Shanghai", "host": "nas"}
            accounting = network.Accounting(path, config)
            def sample(up, down):
                accounting.sample([{"id": "flow", "upload": up, "download": down, "metadata": {"host": "example.invalid", "process": "Test", "sourceIP": "127.0.0.1", "destinationIP": "192.0.2.1"}, "chains": ["DIRECT"]}], "2026-10-09T12:00:01+08:00")
            sample(100, 200); sample(120, 250); sample(2, 3)
            self.assertEqual(accounting.db.execute("SELECT upload_bytes,download_bytes FROM traffic_hourly").fetchone(), (22, 53))
            def fail(*_, **__): return SimpleNamespace(returncode=1, stdout=b"")
            with self.assertRaises(OSError): network.upload_once(path, config, fail)
            self.assertEqual(accounting.db.execute("SELECT COUNT(*) FROM upload_outbox").fetchone()[0], 2)
            def race(_args, **kwargs):
                body = json.loads(kwargs["input"]); sample(4, 6)
                return SimpleNamespace(returncode=0, stdout=json.dumps({"batch_id": body["batch_id"], "committed": True, "accepted": len(body["records"])}).encode())
            network.upload_once(path, config, race)
            # The acknowledged earlier fact does not remove its newer local version.
            self.assertEqual(accounting.db.execute("SELECT COUNT(*) FROM upload_outbox WHERE kind='traffic_hourly'").fetchone()[0], 1)
            accounting.db.close()

    def test_resume_does_not_attribute_offline_bytes_to_current_hour(self):
        with tempfile.TemporaryDirectory() as folder:
            accounting = network.Accounting(Path(folder) / "traffic.db", {"timezone": "Asia/Shanghai"})
            def row(up): return [{"id": "long", "upload": up, "download": 0, "metadata": {}, "chains": []}]
            accounting.sample(row(100), "2026-10-09T12:00:00+08:00")
            accounting.sample(row(1000), "2026-10-09T13:00:00+08:00")
            self.assertEqual(accounting.db.execute("SELECT COUNT(*) FROM traffic_hourly").fetchone()[0], 0)
            self.assertEqual(accounting.db.execute("SELECT COUNT(*) FROM collector_gaps WHERE ended_at IS NOT NULL").fetchone()[0], 1)
            accounting.sample(row(1005), "2026-10-09T13:00:01+08:00")
            self.assertEqual(accounting.db.execute("SELECT upload_bytes FROM traffic_hourly").fetchone()[0], 5)
            accounting.db.close()

    def test_source_isolation_retry_and_out_of_order_counters(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store("sqlite://", Path(folder))
            raw = dict(zip(("bucket", "destination_ip", "host", "process", "source_ip", "category", "pool", "source_tag", "exit_node", "rule"), ("2026-10-09T12:00", "192.0.2.1", "example.invalid", "Test", "127.0.0.1", "DIRECT", "direct", "unknown", "DIRECT", "unknown")))
            eid = "hour:" + digest(raw); raw.update(upload_bytes=10, download_bytes=20)
            def payload(device, up=10):
                body = {"device_id": device * 32, "timezone": "Asia/Shanghai", "records": [{"external_id": eid, "kind": "traffic_hourly", "raw": {**raw, "upload_bytes": up}}]}
                return {**body, "batch_id": digest(body)}
            first = ingest_network(store, payload("a")); again = ingest_network(store, payload("a"))
            self.assertEqual(first["changed"], 1); self.assertEqual(again["duplicates"], 1)
            ingest_network(store, payload("a", 40)); ingest_network(store, payload("a", 5)); ingest_network(store, payload("b"))
            from sqlalchemy import select
            from personal_data_hub.storage import records
            with store.engine.connect() as c:
                values = list(c.execute(select(records.c.source, records.c.raw)))
            self.assertEqual(len(values), 2)
            self.assertEqual(dict(values)["network-mac-" + "a" * 32]["upload_bytes"], 40)
            from personal_data_hub.display import Display
            view = Display(store)
            overview = view.overview("2026-10-09", modules="network")
            # Two observation sources remain selectable, never silently added together.
            self.assertIn(overview["modules"][0]["metrics"][0]["value"], (10, 40))
            detail = view.network("2026-10-09", source="network-mac-" + "a" * 32)
            self.assertEqual(detail["totals"]["upload_bytes"], 40)
            self.assertEqual(detail["dimensions"]["process"][0]["name"], "Test")
            bad = payload("a"); bad["records"][0]["raw"]["secret"] = "must reject"; bad["batch_id"] = digest({k:v for k,v in bad.items() if k != "batch_id"})
            with self.assertRaises(ValueError): ingest_network(store, bad)


if __name__ == "__main__": unittest.main()
