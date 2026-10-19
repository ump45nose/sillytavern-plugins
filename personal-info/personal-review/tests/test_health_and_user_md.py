"""Report projection of canonical health summaries and USER.md conflict checks."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from review.domain import TimeWindow
from review.projections import UserMdProjection
from review.sources.health import HealthSource

class Reader:
    base_url = 'http://records'
    def health_summary(self, first, last):
        self.dates = first, last
        return {'days': 1, 'metrics': {'steps': {'total': 6783}, 'active_calories_kcal': {'total': 420},
            'total_calories_kcal': {'total': None}, 'heart_rate': {'average': 60}, 'resting_heart_rate': {'average': 45},
            'oxygen_saturation': {'average': 98}, 'sleep': {'duration_seconds': 19800}, 'exercise': {'duration_seconds': None}}}

class HealthAndUserMdTests(unittest.TestCase):
    def test_business_api_metrics_and_half_open_window(self):
        reader = Reader()
        start = datetime(2026, 8, 29, tzinfo=timezone(timedelta(hours=8)))
        result = HealthSource(client=reader).collect(TimeWindow(start, start+timedelta(days=1)), None)
        self.assertEqual(reader.dates, ('2026-08-29', '2026-08-29'))
        self.assertEqual(result.evidence[0].payload['sleep'], 5.5)
        self.assertEqual(result.evidence[0].payload['steps'], 6783)
        self.assertNotIn('exercise', result.evidence[0].payload)
        self.assertIn('血氧 98 %', result.evidence[0].fact)
        self.assertEqual(result.evidence[0].source_ref, 'http://records/api/v1/health/summary')

    def test_empty_day_has_no_evidence(self):
        reader = Reader()
        reader.health_summary = lambda *_: {'days': 0}
        start = datetime.now(timezone.utc)
        result = HealthSource(client=reader).collect(TimeWindow(start, start+timedelta(days=1)), None)
        self.assertEqual(result.evidence, [])
        self.assertTrue(result.warnings)

    def test_user_md_detects_manual_change(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'USER.md'
            projection = UserMdProjection(path)
            projection.apply('当前状态 A')
            path.write_text(path.read_text().replace('当前状态 A', '人工修改'))
            with self.assertRaises(ValueError): projection.apply('当前状态 B')
