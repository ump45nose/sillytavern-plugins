"""Small smoke of the optional source's site boundary; no service or secrets."""
import time
import unittest
from unittest.mock import patch
from common.cookiecloud import browser_cookies, cookie_header


class CookieCloudSmoke(unittest.TestCase):
    def test_site_boundary_expiry_and_specific_domain(self):
        rows = {"fixture": [
            {"domain": ".example.test", "name": "auth", "value": "parent"},
            {"domain": "example.test", "hostOnly": True, "name": "host_only", "value": "excluded"},
            {"domain": "sub.example.test", "name": "auth", "value": "specific"},
            {"domain": ".example.test", "name": "old", "value": "excluded", "expirationDate": time.time()-1},
            {"domain": ".unrelated.test", "name": "other", "value": "excluded"},
        ]}
        with patch("common.cookiecloud.read", return_value=rows):
            self.assertEqual(cookie_header("fixture", "sub.example.test", ("auth",)), "auth=specific")
            self.assertEqual([c["name"] for c in browser_cookies("fixture", "sub.example.test")], ["auth", "auth"])

    def test_missing_required_and_invalid_cookie_are_rejected(self):
        with patch("common.cookiecloud.read", return_value={"fixture": []}):
            with self.assertRaises(ValueError):
                cookie_header("fixture", "example.test", ("auth",))
        with patch("common.cookiecloud.read", return_value={"fixture": [
            {"domain": "example.test", "name": "auth", "value": "bad\r\nheader"}]}):
            with self.assertRaises(ValueError):
                browser_cookies("fixture", "example.test")
