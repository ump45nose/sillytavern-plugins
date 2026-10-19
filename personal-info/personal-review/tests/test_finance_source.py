"""Finance report keeps canonical types, exact strings, and pending counts."""
from datetime import datetime, timedelta, timezone
import unittest
from review.daily import DailyReviewService
from review.domain import TimeWindow
from review.sources.finance import FinanceSource

class Reader:
    base_url = 'http://records'
    def bill_summary(self, first, last):
        return {'count': 2, 'pending_count': 1, 'totals': [
            {'currency': 'CNY', 'type': 'expense', 'amount': '5.98', 'fee': '0', 'count': 1},
            {'currency': 'USD', 'type': 'income_refund', 'amount': '3.99', 'fee': '0', 'count': 1}]}
    def iter_bills(self, *dates, **filters):
        assert filters == {'type': 'expense', 'status': 'confirmed'}
        return iter([{'merchant': '公交', 'amount': '5.98', 'currency': 'CNY'}])

class FinanceSourceTest(unittest.TestCase):
    def test_api_evidence_and_display(self):
        start = datetime(2026, 9, 3, tzinfo=timezone(timedelta(hours=8)))
        result = FinanceSource(Reader()).collect(TimeWindow(start, start+timedelta(days=1)), None)
        self.assertEqual(result.evidence[0].payload['pending_count'], 1)
        output = '\n'.join(DailyReviewService._finance_blocks(result.evidence))
        self.assertIn('公交', output)
        self.assertIn('¥5.98', output)
        self.assertIn('$3.99', output)
        self.assertIn('待确认', output)
