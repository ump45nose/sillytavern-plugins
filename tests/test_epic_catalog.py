import copy
from datetime import datetime, timezone
import unittest
from platforms.epic.catalog import parse_catalog, purchase_candidates, storefront_owned


NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)
ROW = {
    "id": "offer",
    "namespace": "ns",
    "offerType": "BASE_GAME",
    "productSlug": "fixture",
    "price": {"totalPrice": {"discountPrice": 0, "currencyCode": "USD"}},
    "promotions": {
        "promotionalOffers": [
            {
                "promotionalOffers": [
                    {
                        "startDate": "2026-09-30T00:00:00Z",
                        "endDate": "2026-10-02T00:00:00Z",
                        "discountSetting": {"discountPercentage": 0},
                    }
                ]
            }
        ]
    },
}


def payload(rows):
    return {"data": {"Catalog": {"searchStore": {"elements": rows}}}}


class CatalogTests(unittest.TestCase):
    def test_explicit_free(self):
        inv = parse_catalog(payload([ROW]), now=NOW)
        self.assertTrue(inv.complete)
        self.assertEqual(inv.offers[0].id, "ns:offer")

    def test_paid_conflict_unknown(self):
        row = copy.deepcopy(ROW)
        row["price"]["totalPrice"]["discountPrice"] = 1
        inv = parse_catalog(payload([row]), now=NOW)
        self.assertFalse(inv.complete)
        self.assertEqual(inv.offers, [])

    def test_future_not_active(self):
        row = copy.deepcopy(ROW)
        row["promotions"]["promotionalOffers"][0]["promotionalOffers"][0][
            "startDate"
        ] = "2026-10-02T00:00:00Z"
        inv = parse_catalog(payload([row]), now=NOW)
        self.assertTrue(inv.complete)
        self.assertEqual(inv.offers, [])

    def test_missing_not_empty(self):
        self.assertFalse(parse_catalog({}, now=NOW).complete)
        self.assertTrue(parse_catalog(payload([]), now=NOW).complete)

    def test_bundle_route(self):
        row = copy.deepcopy(ROW)
        row["offerType"] = "BUNDLE"
        row["offerMappings"] = [{"pageSlug": "bundle-fixture"}]
        self.assertIn(
            "/bundles/bundle-fixture",
            parse_catalog(payload([row]), now=NOW).offers[0].url,
        )

    def test_slug_cannot_change_origin(self):
        row = copy.deepcopy(ROW)
        row["productSlug"] = "https://fixture.invalid/"
        self.assertFalse(parse_catalog(payload([row]), now=NOW).complete)

    def test_duplicate_ambiguous(self):
        self.assertFalse(parse_catalog(payload([ROW, ROW]), now=NOW).complete)

    def test_order_unknown_and_known_empty(self):
        self.assertIsNone(purchase_candidates({}))
        self.assertEqual(purchase_candidates({"orders": []}), set())

    def test_order_exact_namespace(self):
        self.assertEqual(
            purchase_candidates(
                {
                    "orders": [
                        {
                            "orderType": "PURCHASE",
                            "items": [{"namespace": "ns", "offerId": "offer"}],
                        }
                    ]
                }
            ),
            {"ns:offer"},
        )

    def test_missing_promotion_field_unknown(self):
        row = copy.deepcopy(ROW)
        del row["promotions"]
        self.assertFalse(parse_catalog(payload([row]), now=NOW).complete)

    def test_invalid_discount_unknown(self):
        for value in (float("nan"), float("inf"), -1, 101, False):
            row = copy.deepcopy(ROW)
            row["promotions"]["promotionalOffers"][0]["promotionalOffers"][0][
                "discountSetting"
            ]["discountPercentage"] = value
            self.assertFalse(parse_catalog(payload([row]), now=NOW).complete)

    def test_refund_inventory_requires_current_readback(self):
        self.assertIsNone(
            purchase_candidates({"orders": [{"orderType": "REFUND", "items": []}]})
        )

    def test_bounded_order_items(self):
        self.assertIsNone(
            purchase_candidates(
                {"orders": [{"orderType": "PURCHASE", "items": [{}] * 101}]}
            )
        )

    def test_owned_marker_not_disabled(self):
        self.assertTrue(storefront_owned(" In Library "))
        self.assertTrue(storefront_owned("已在库中"))
        for text in ("Unavailable", "Coming Soon", "Get", None, ""):
            self.assertFalse(storefront_owned(text))


if __name__ == "__main__":
    unittest.main()
