"""Tests for lightweight subscription remaining traffic reading."""
import unittest
from unittest.mock import MagicMock, patch

from personal_data_hub.traffic_remaining import parse_userinfo_header, fetch_remaining_traffic


class TrafficRemainingTest(unittest.TestCase):
    def test_parse_userinfo_header(self):
        header = "upload=17592976986; download=53027039199; total=322122547200; expire=1817049600"
        parsed = parse_userinfo_header(header)
        self.assertEqual(parsed["total_bytes"], 322122547200)
        self.assertEqual(parsed["upload_bytes"], 17592976986)
        self.assertEqual(parsed["download_bytes"], 53027039199)
        self.assertEqual(parsed["used_bytes"], 70620016185)
        self.assertEqual(parsed["remaining_bytes"], 251502531015)
        self.assertEqual(parsed["total_gb"], 300.0)
        self.assertEqual(parsed["used_gb"], 65.77)
        self.assertEqual(parsed["remaining_gb"], 234.23)
        self.assertEqual(parsed["usage_percent"], 21.9)
        self.assertIn("2027-08-01", parsed["expires_at"])
        self.assertTrue(parsed["checked_at"])

    def test_parse_userinfo_empty_or_malformed(self):
        parsed = parse_userinfo_header("invalid; format=abc")
        self.assertEqual(parsed["total_bytes"], 0)
        self.assertEqual(parsed["remaining_bytes"], 0)
        self.assertEqual(parsed["usage_percent"], 0.0)
        self.assertIsNone(parsed["expires_at"])

    def test_fetch_remaining_traffic_mock(self):
        mock_resp = MagicMock()
        mock_resp.headers = {
            "Subscription-Userinfo": "upload=1000; download=2000; total=10000; expire=1800000000"
        }
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = None

        with patch("urllib.request.urlopen", return_value=mock_resp):
            res = fetch_remaining_traffic("https://example.com/clash/sub")
            self.assertEqual(res["total_bytes"], 10000)
            self.assertEqual(res["used_bytes"], 3000)
            self.assertEqual(res["remaining_bytes"], 7000)
            self.assertEqual(res["url"], "https://example.com/clash/sub")


if __name__ == "__main__":
    unittest.main()
