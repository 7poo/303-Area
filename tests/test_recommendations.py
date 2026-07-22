import unittest

from src.recommendations import decide_recommendation


def signal(**overrides):
    value = {
        "source_price": 120000,
        "peer_median_price": 100000,
        "price_gap_pct": 20.0,
        "source_discount_percent": 10.0,
        "peer_median_discount_percent": 10.0,
        "discount_gap_pct": 0.0,
        "peer_status": "peer_found",
        "peer_count": 5,
        "is_price_outlier": False,
        "competitive_pressure_score": 0.2,
        "promotion_peer_count": 0,
        "signal_confidence": "high",
    }
    value.update(overrides)
    return value


class RecommendationRulesTest(unittest.TestCase):
    def test_abstains_without_peer(self):
        result = decide_recommendation(signal(peer_status="not_enough_evidence", peer_count=0))
        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertEqual(result["action"], "no_response")

    def test_price_change_is_blocked_without_cost(self):
        result = decide_recommendation(signal())
        self.assertEqual(result["status"], "needs_cost_validation")
        self.assertEqual(result["action"], "hold_price")
        self.assertIn("cost_required_before_price_change", result["reason_codes"])

    def test_reduction_respects_margin_floor(self):
        result = decide_recommendation(signal(), {"cost_value": 80000, "margin_min_pct": 10})
        self.assertEqual(result["action"], "reduce_price")
        self.assertEqual(result["status"], "recommended")
        self.assertGreaterEqual(result["recommended_price"], 88000)
        self.assertGreaterEqual(result["estimated_margin_pct"], 10)

    def test_discount_is_capped_by_margin_floor(self):
        result = decide_recommendation(signal(
            price_gap_pct=0,
            discount_gap_pct=-20,
            source_discount_percent=0,
            peer_median_discount_percent=30,
        ), {"cost_value": 100000, "margin_min_pct": 10})
        self.assertEqual(result["action"], "use_voucher")
        self.assertLessEqual(result["recommended_discount_percent"], 8.34)

    def test_outlier_abstains(self):
        result = decide_recommendation(signal(is_price_outlier=True))
        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertEqual(result["action"], "no_response")


if __name__ == "__main__":
    unittest.main()
