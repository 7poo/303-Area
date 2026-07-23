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

    def test_substitute_benchmark_recommends_monitoring_not_price(self):
        result = decide_recommendation(signal(
            peer_status="not_enough_evidence",
            peer_count=0,
            benchmark_peer_count=3,
            benchmark_best_score=0.66,
        ))
        self.assertEqual(result["status"], "monitoring_only")
        self.assertEqual(result["action"], "review_competitors")
        self.assertIsNone(result["recommended_price"])
        self.assertIn("price_target_not_comparable", result["reason_codes"])

    def test_price_change_is_blocked_without_cost(self):
        result = decide_recommendation(signal())
        self.assertEqual(result["status"], "needs_cost_validation")
        self.assertEqual(result["action"], "hold_price")
        self.assertIn("cost_required_before_price_change", result["reason_codes"])

    def test_reduction_respects_margin_floor(self):
        result = decide_recommendation(signal(), {"cost_value": 80000, "margin_min_pct": 10})
        self.assertEqual(result["action"], "reduce_price")
        self.assertEqual(result["status"], "recommended")
        self.assertAlmostEqual(result["price_floor"], 80000 / 0.9)
        self.assertGreaterEqual(result["recommended_price"], result["price_floor"])
        self.assertGreaterEqual(result["estimated_margin_pct"], 10)

    def test_discount_is_capped_by_margin_floor(self):
        result = decide_recommendation(signal(
            price_gap_pct=0,
            discount_gap_pct=-20,
            source_discount_percent=0,
            peer_median_discount_percent=30,
            promotion_terms_verified=True,
        ), {"cost_value": 100000, "margin_min_pct": 10})
        self.assertEqual(result["action"], "use_voucher")
        self.assertLessEqual(result["recommended_discount_percent"], 7.41)
        effective_price = 120000 * (1 - result["recommended_discount_percent"] / 100)
        self.assertGreaterEqual((effective_price - 100000) / effective_price * 100, 10)

    def test_voucher_is_blocked_without_verified_promotion_terms(self):
        result = decide_recommendation(signal(
            price_gap_pct=0,
            discount_gap_pct=-20,
            source_discount_percent=0,
            peer_median_discount_percent=30,
        ), {"cost_value": 100000, "margin_min_pct": 10})
        self.assertEqual(result["status"], "needs_promotion_validation")
        self.assertEqual(result["action"], "hold_price")
        self.assertIn("promotion_terms_required_before_voucher", result["reason_codes"])

    def test_invalid_gross_margin_is_rejected(self):
        with self.assertRaises(ValueError):
            decide_recommendation(signal(), {"cost_value": 80000, "margin_min_pct": 100})

    def test_seeded_cost_produces_non_executable_scenario(self):
        result = decide_recommendation(signal(), {
            "cost_value": 80000,
            "margin_min_pct": 15,
            "cost_source": "seeded_scenario",
        })
        self.assertEqual(result["status"], "scenario_only")
        self.assertEqual(result["action"], "reduce_price")
        self.assertEqual(result["constraint_status"], "seeded_cost_not_verified")
        self.assertEqual(result["confidence"], "low")

    def test_outlier_abstains(self):
        result = decide_recommendation(signal(is_price_outlier=True))
        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertEqual(result["action"], "no_response")


if __name__ == "__main__":
    unittest.main()
