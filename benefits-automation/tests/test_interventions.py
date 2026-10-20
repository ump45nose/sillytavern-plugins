import unittest
from datetime import datetime, timezone
from common.interventions import (
    request,
    fingerprint,
    validate_request,
    validate_resume,
    IDENTITY,
)


class InterventionTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
        self.req = request(
            {"run_id": "r", "platform": "fixture", "account": "default"},
            "claim",
            "checkout",
            "terms",
            "https://example.test/terms",
            fingerprint("terms text fixture", "version1"),
            expires_at="2026-10-01T13:00:00Z",
        )
        self.grant = {k: self.req[k] for k in IDENTITY}
        self.grant.update(decision="approve", expires_at="2026-10-01T12:30:00Z")

    def test_exact_scope(self):
        self.assertIsNone(
            validate_resume(self.req, self.grant, self.req["fingerprint"], now=self.now)
        )

    def test_missing(self):
        self.assertEqual(
            validate_resume(self.req, None, self.req["fingerprint"], now=self.now),
            "approval_missing",
        )

    def test_deny(self):
        self.grant["decision"] = "deny"
        self.assertEqual(
            validate_resume(
                self.req, self.grant, self.req["fingerprint"], now=self.now
            ),
            "approval_not_granted",
        )

    def test_scope_each_field(self):
        for key in IDENTITY:
            g = {**self.grant, key: "different"}
            self.assertEqual(
                validate_resume(self.req, g, self.req["fingerprint"], now=self.now),
                "approval_scope_mismatch",
            )

    def test_same_request_and_fingerprint_cannot_change_origin_or_phase(self):
        for key in ("origin_run_id", "phase"):
            with self.subTest(field=key):
                grant = {**self.grant, key: "different"}
                self.assertEqual(grant["request_id"], self.req["request_id"])
                self.assertEqual(grant["fingerprint"], self.req["fingerprint"])
                self.assertEqual(
                    validate_resume(
                        self.req, grant, self.req["fingerprint"], now=self.now
                    ),
                    "approval_scope_mismatch",
                )
                grant.pop(key)
                self.assertEqual(
                    validate_resume(
                        self.req, grant, self.req["fingerprint"], now=self.now
                    ),
                    "approval_scope_mismatch",
                )

    def test_changed_terms(self):
        self.assertEqual(
            validate_resume(
                self.req, self.grant, fingerprint("new terms"), now=self.now
            ),
            "site_state_changed",
        )

    def test_expired(self):
        self.grant["expires_at"] = "2026-10-01T11:00:00Z"
        self.assertEqual(
            validate_resume(
                self.req, self.grant, self.req["fingerprint"], now=self.now
            ),
            "approval_expired",
        )

    def test_no_secret_payload(self):
        with self.assertRaises(ValueError):
            validate_request({**self.req, "cookie": "dummy"})

    def test_no_implicit_age(self):
        self.assertNotIn("age", self.req)
        self.assertNotIn("date_of_birth", self.req)

    def test_missing_timezone(self):
        self.grant["expires_at"] = "2026-10-01T12:30:00"
        self.assertEqual(
            validate_resume(
                self.req, self.grant, self.req["fingerprint"], now=self.now
            ),
            "invalid_approval_or_checkpoint",
        )

    def test_bounded_evidence(self):
        with self.assertRaises(ValueError):
            fingerprint("x" * 65537)


if __name__ == "__main__":
    unittest.main()
