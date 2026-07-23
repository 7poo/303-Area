import unittest
from datetime import datetime

import duckdb

from src.signals import build_alerts, build_peer_groups, build_signals, create_tables


class SignalsIntegrationTest(unittest.TestCase):
    def test_peer_groups_signals_and_event_alerts_are_traceable(self):
        conn = duckdb.connect(":memory:")
        conn.execute("""
            CREATE TABLE products (
                country_code VARCHAR, currency VARCHAR, snapshot_date DATE,
                shop_id BIGINT, item_id BIGINT, price BIGINT, price_original BIGINT,
                discount_percent DOUBLE, monthly_sold_value DOUBLE,
                rating_count BIGINT, liked_count BIGINT
            )
        """)
        conn.execute("""
            CREATE TABLE product_matches (
                country_code VARCHAR, snapshot_date DATE, source_shop_id BIGINT,
                source_item_id BIGINT, target_shop_id BIGINT, target_item_id BIGINT,
                rank INTEGER, match_score DOUBLE, match_type VARCHAR,
                confidence VARCHAR, source_status VARCHAR, model_version VARCHAR
            )
        """)
        conn.execute("""
            CREATE TABLE product_attributes (
                country_code VARCHAR, shop_id BIGINT, item_id BIGINT,
                total_weight_g DOUBLE, total_volume_ml DOUBLE,
                quantity BIGINT, package_ambiguous BOOLEAN,
                price_variant_ambiguous BOOLEAN, seller_entity_id VARCHAR
            )
        """)
        conn.execute("""
            CREATE TABLE promotion_events (
                country_code VARCHAR, shop_id BIGINT, item_id BIGINT,
                snapshot_date DATE, event_type VARCHAR, previous_date DATE,
                old_value VARCHAR, new_value VARCHAR
            )
        """)
        conn.executemany("INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [
            ("vn", "VND", "2026-07-01", 1, 101, 100000, 220000, 10, 100, 10, 10),
            ("vn", "VND", "2026-07-02", 1, 101, 205000, 220000, 8, 120, 12, 12),
            ("vn", "VND", "2026-07-01", 2, 202, 90000, 100000, 5, 90, 9, 9),
            ("vn", "VND", "2026-07-02", 2, 202, 80000, 100000, 5, 110, 10, 10),
            ("vn", "VND", "2026-07-02", 2, 203, 100000, 110000, 5, 100, 8, 8),
            ("vn", "VND", "2026-07-02", 3, 303, 50000, 60000, 0, 20, 1, 1),
            ("vn", "VND", "2026-07-02", 4, 404, 70000, 80000, 0, 30, 2, 2),
            ("vn", "VND", "2026-07-02", 5, 505, 45000, 70000, 0, 30, 2, 2),
            ("vn", "VND", "2026-07-02", 6, 606, 50000, 60000, 0, 30, 2, 2),
        ])
        conn.execute("""
            INSERT INTO product_attributes VALUES
            ('vn', 1, 101, 100, NULL, 1, FALSE, FALSE, 'seller_source'),
            ('vn', 2, 202, 50, NULL, 1, FALSE, FALSE, 'seller_target'),
            ('vn', 2, 203, 50, NULL, 1, FALSE, FALSE, 'seller_target'),
            ('vn', 3, 303, 50, NULL, 1, FALSE, FALSE, 'seller_3')
            ,('vn', 4, 404, 50, NULL, 1, FALSE, FALSE, 'seller_4')
            ,('vn', 5, 505, 50, NULL, 1, FALSE, TRUE, 'seller_5')
            ,('vn', 6, 606, 50, NULL, 1, FALSE, FALSE, 'seller_6')
        """)
        conn.execute("""
            INSERT INTO product_matches VALUES
            ('vn', '2026-07-02', 1, 101, 2, 202, 1, 0.9, 'same_product', 'high', 'matchable', 'test'),
            ('vn', '2026-07-02', 1, 101, 2, 203, 2, 0.85, 'same_product', 'high', 'matchable', 'test'),
            ('vn', '2026-07-02', 3, 303, NULL, NULL, 1, 0.0, 'not_enough_evidence', 'not_enough_evidence', 'not_enough_evidence', 'test')
            ,('vn', '2026-07-02', 4, 404, 2, 202, 1, 0.7, 'substitute', 'medium', 'matchable', 'test')
            ,('vn', '2026-07-02', 5, 505, 6, 606, 1, 0.9, 'same_product', 'high', 'matchable', 'test')
        """)
        conn.execute("""
            INSERT INTO promotion_events VALUES
            ('vn', 2, 202, '2026-07-02', 'price_changed', '2026-07-01', '90000', '80000')
        """)

        created_at = datetime(2026, 7, 22)
        create_tables(conn)
        build_peer_groups(conn, 0.45, created_at)
        build_signals(conn, created_at)
        build_alerts(conn, created_at)

        self.assertEqual(conn.execute("SELECT COUNT(*) FROM peer_groups WHERE peer_status='peer_found'").fetchone()[0], 4)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM peer_groups WHERE peer_status='not_enough_evidence'").fetchone()[0], 1)
        signal = conn.execute("SELECT peer_count, price_index FROM market_signals WHERE source_item_id=101 AND snapshot_date='2026-07-02'").fetchone()
        self.assertEqual(signal[0], 1)
        # Two listings from the same distributor are first collapsed to one
        # seller-level median, so they do not count as two independent peers.
        self.assertAlmostEqual(signal[1], 205000 / (((80000 + 100000) / 2) * 2))
        baseline = conn.execute("""
            SELECT source_list_price,source_historical_median_price,
                   source_price_observation_count,price_baseline_value,
                   price_baseline_type,price_baseline_actionable
            FROM market_signals WHERE source_item_id=101 AND snapshot_date='2026-07-02'
        """).fetchone()
        self.assertEqual(baseline, (220000, 152500, 2, 180000, 'peer_market_median', True))
        ambiguous = conn.execute("""
            SELECT peer_status, peer_count, price_comparison_basis
            FROM market_signals WHERE source_item_id=505
        """).fetchone()
        self.assertEqual(ambiguous, ('not_enough_evidence', 0, None))
        alert = conn.execute("""
            SELECT target_shop_id, target_item_id FROM competitor_alerts
            WHERE alert_type='competitor_price_down' AND source_item_id=101
        """).fetchone()
        self.assertEqual(alert, (2, 202))
        price_alert = conn.execute("""
            SELECT target_shop_id, target_item_id FROM competitor_alerts
            WHERE alert_type='our_price_above_market' AND source_item_id=101
        """).fetchone()
        self.assertEqual(price_alert, (2, 202))
        substitute_signal = conn.execute("""
            SELECT peer_count, benchmark_peer_count, price_down_peer_count
            FROM market_signals WHERE source_item_id=404
        """).fetchone()
        self.assertEqual(substitute_signal, (0, 1, 1))
        self.assertEqual(conn.execute("""
            SELECT COUNT(*) FROM competitor_alerts
            WHERE source_item_id=404 AND alert_type='competitor_price_down'
        """).fetchone()[0], 1)
        self.assertEqual(conn.execute("""
            SELECT COUNT(*) FROM competitor_alerts
            WHERE source_item_id=404 AND alert_type='our_price_above_market'
        """).fetchone()[0], 0)
        conn.close()


if __name__ == "__main__":
    unittest.main()
