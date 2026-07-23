"""Build explainable market signals and competitor alerts from matched peers.

This is a snapshot-oriented batch step for the MVP.  It deliberately keeps
currencies and countries separate and treats ``monthly_sold_value`` and
engagement counters as observed proxies, not causal demand or profit.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from .pipeline import finish_run, start_run


SIGNALS_VERSION = "market-signals-v0.6-price-baseline"
VALID_MATCH_TYPES = ("same_product", "same_product_variant", "substitute", "near_match")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def create_tables(conn: duckdb.DuckDBPyConnection) -> None:
    """Create the Stage 3 output tables from scratch (idempotent batch)."""
    conn.execute("DROP TABLE IF EXISTS competitor_alerts")
    conn.execute("DROP TABLE IF EXISTS market_signals")
    conn.execute("DROP TABLE IF EXISTS peer_groups")

    conn.execute("""
        CREATE TABLE peer_groups (
            country_code VARCHAR NOT NULL,
            source_snapshot_date DATE NOT NULL,
            source_shop_id BIGINT NOT NULL,
            source_item_id BIGINT NOT NULL,
            peer_rank INTEGER NOT NULL,
            target_shop_id BIGINT,
            target_item_id BIGINT,
            relation VARCHAR NOT NULL,
            match_score DOUBLE NOT NULL,
            confidence VARCHAR NOT NULL,
            peer_status VARCHAR NOT NULL,
            evidence_count INTEGER NOT NULL,
            model_version VARCHAR NOT NULL,
            created_at TIMESTAMP NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE market_signals (
            country_code VARCHAR NOT NULL,
            snapshot_date DATE NOT NULL,
            source_shop_id BIGINT NOT NULL,
            source_item_id BIGINT NOT NULL,
            currency VARCHAR NOT NULL,
            source_price DOUBLE,
            source_list_price DOUBLE,
            source_historical_median_price DOUBLE,
            source_price_observation_count INTEGER NOT NULL,
            price_baseline_value DOUBLE,
            price_baseline_type VARCHAR NOT NULL,
            price_baseline_actionable BOOLEAN NOT NULL,
            source_discount_percent DOUBLE,
            price_comparison_basis VARCHAR,
            source_normalized_price DOUBLE,
            peer_median_normalized_price DOUBLE,
            peer_status VARCHAR NOT NULL,
            peer_count INTEGER NOT NULL,
            benchmark_peer_count INTEGER NOT NULL,
            peer_min_price DOUBLE,
            peer_median_price DOUBLE,
            peer_max_price DOUBLE,
            price_index DOUBLE,
            price_gap_pct DOUBLE,
            is_price_outlier BOOLEAN NOT NULL,
            outlier_reason VARCHAR,
            peer_median_discount_percent DOUBLE,
            discount_gap_pct DOUBLE,
            source_monthly_sold DOUBLE,
            peer_median_monthly_sold DOUBLE,
            source_sales_momentum_pct DOUBLE,
            peer_sales_momentum_pct DOUBLE,
            source_engagement_momentum_pct DOUBLE,
            peer_engagement_momentum_pct DOUBLE,
            price_down_peer_count INTEGER NOT NULL,
            promotion_peer_count INTEGER NOT NULL,
            competitive_pressure_score DOUBLE NOT NULL,
            competitive_pressure_level VARCHAR NOT NULL,
            signal_confidence VARCHAR NOT NULL,
            evidence_count INTEGER NOT NULL,
            model_version VARCHAR NOT NULL,
            created_at TIMESTAMP NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE competitor_alerts (
            country_code VARCHAR NOT NULL,
            snapshot_date DATE NOT NULL,
            source_shop_id BIGINT NOT NULL,
            source_item_id BIGINT NOT NULL,
            alert_type VARCHAR NOT NULL,
            severity VARCHAR NOT NULL,
            metric_name VARCHAR NOT NULL,
            metric_value DOUBLE,
            threshold DOUBLE,
            target_shop_id BIGINT,
            target_item_id BIGINT,
            evidence JSON NOT NULL,
            model_version VARCHAR NOT NULL,
            created_at TIMESTAMP NOT NULL
        )
    """)


def build_peer_groups(conn: duckdb.DuckDBPyConnection, min_score: float, created_at: datetime) -> None:
    """Materialize valid peers and one explicit abstention row per source."""
    params = [min_score, *VALID_MATCH_TYPES]
    conn.execute(f"""
        INSERT INTO peer_groups
        SELECT country_code, snapshot_date, source_shop_id, source_item_id,
               rank, target_shop_id, target_item_id, match_type, match_score,
               confidence, 'peer_found', 1, model_version, ?
        FROM product_matches
        WHERE source_status = 'matchable'
          AND target_item_id IS NOT NULL
          AND match_score >= ?
          AND match_type IN ({','.join('?' for _ in VALID_MATCH_TYPES)})
    """, [created_at, *params])

    conn.execute("""
        INSERT INTO peer_groups
        SELECT s.country_code, s.snapshot_date, s.source_shop_id, s.source_item_id,
               1, NULL, NULL, 'not_enough_evidence', 0.0,
               'not_enough_evidence', 'not_enough_evidence', 0,
               'product-matching', ?
        FROM (
            SELECT DISTINCT country_code, snapshot_date, source_shop_id, source_item_id
            FROM product_matches
        ) s
        WHERE NOT EXISTS (
            SELECT 1 FROM peer_groups p
            WHERE p.country_code = s.country_code
              AND p.source_snapshot_date = s.snapshot_date
              AND p.source_shop_id = s.source_shop_id
              AND p.source_item_id = s.source_item_id
              AND p.peer_status = 'peer_found'
        )
    """, [created_at])


def build_signals(conn: duckdb.DuckDBPyConnection, created_at: datetime) -> None:
    """Compute daily source/peer aggregates and momentum from snapshots."""
    conn.execute("""
        INSERT INTO market_signals
        WITH source_keys AS (
            SELECT DISTINCT country_code, source_shop_id, source_item_id
            FROM peer_groups
        ), source_profiles AS (
            SELECT s.*, pa.total_weight_g, pa.total_volume_ml, pa.quantity,
                   pa.package_ambiguous, pa.price_variant_ambiguous,
                   CASE
                     WHEN NOT pa.package_ambiguous AND NOT pa.price_variant_ambiguous AND pa.total_weight_g > 0 THEN '100_g'
                     WHEN NOT pa.package_ambiguous AND NOT pa.price_variant_ambiguous AND pa.total_volume_ml > 0 THEN '100_ml'
                     WHEN NOT pa.package_ambiguous AND NOT pa.price_variant_ambiguous AND pa.quantity > 0 THEN 'mỗi_đơn_vị'
                   END AS price_comparison_basis,
                   CASE
                     WHEN NOT pa.package_ambiguous AND NOT pa.price_variant_ambiguous AND pa.total_weight_g > 0 THEN pa.total_weight_g / 100.0
                     WHEN NOT pa.package_ambiguous AND NOT pa.price_variant_ambiguous AND pa.total_volume_ml > 0 THEN pa.total_volume_ml / 100.0
                     WHEN NOT pa.package_ambiguous AND NOT pa.price_variant_ambiguous AND pa.quantity > 0 THEN pa.quantity::DOUBLE
                   END AS source_basis_units
            FROM source_keys s
            LEFT JOIN product_attributes pa ON pa.country_code=s.country_code
                                           AND pa.shop_id=s.source_shop_id
                                           AND pa.item_id=s.source_item_id
        ), source_snapshots AS (
            SELECT p.*, sp.price_comparison_basis, sp.source_basis_units,
                   CASE WHEN sp.price_comparison_basis IS NOT NULL
                        THEN MEDIAN(p.price) FILTER (WHERE p.price > 0) OVER (
                            PARTITION BY p.country_code,p.shop_id,p.item_id
                        ) END AS source_historical_median_price,
                   CASE WHEN sp.price_comparison_basis IS NOT NULL
                        THEN COUNT(p.price) FILTER (WHERE p.price > 0) OVER (
                            PARTITION BY p.country_code,p.shop_id,p.item_id
                        ) ELSE 0 END AS source_price_observation_count,
                   CASE WHEN p.price > 0 AND sp.source_basis_units > 0
                        THEN p.price / sp.source_basis_units END AS source_normalized_price
            FROM products p
            JOIN source_profiles sp ON sp.country_code=p.country_code
                                   AND sp.source_shop_id=p.shop_id
                                   AND sp.source_item_id=p.item_id
        ), valid_peers AS (
            SELECT country_code, source_shop_id, source_item_id,
                   target_shop_id, target_item_id, relation
            FROM peer_groups
            WHERE peer_status = 'peer_found'
        ), peer_observations AS (
            SELECT v.country_code, v.source_shop_id, v.source_item_id,
                   v.target_shop_id, v.target_item_id, ta.seller_entity_id AS target_seller_entity_id,
                   p.snapshot_date,
                   p.price, p.discount_percent, p.monthly_sold_value,
                   COALESCE(p.rating_count, 0) + COALESCE(p.liked_count, 0) AS engagement,
                   sp.price_comparison_basis, sp.source_basis_units,
                   CASE
                     WHEN sp.price_comparison_basis='100_g' AND NOT ta.package_ambiguous AND NOT ta.price_variant_ambiguous AND ta.total_weight_g > 0 THEN ta.total_weight_g / 100.0
                     WHEN sp.price_comparison_basis='100_ml' AND NOT ta.package_ambiguous AND NOT ta.price_variant_ambiguous AND ta.total_volume_ml > 0 THEN ta.total_volume_ml / 100.0
                     WHEN sp.price_comparison_basis='mỗi_đơn_vị' AND NOT ta.package_ambiguous AND NOT ta.price_variant_ambiguous AND ta.quantity > 0 THEN ta.quantity::DOUBLE
                   END AS target_basis_units,
                   CASE
                     WHEN p.price > 0 AND target_basis_units > 0 THEN p.price / target_basis_units
                   END AS target_normalized_price
            FROM valid_peers v
            JOIN source_profiles sp ON sp.country_code=v.country_code
                                   AND sp.source_shop_id=v.source_shop_id
                                   AND sp.source_item_id=v.source_item_id
            JOIN products p ON p.country_code=v.country_code
                           AND p.shop_id=v.target_shop_id
                           AND p.item_id=v.target_item_id
            LEFT JOIN product_attributes ta ON ta.country_code=v.country_code
                                           AND ta.shop_id=v.target_shop_id
                                           AND ta.item_id=v.target_item_id
            WHERE v.relation IN ('same_product', 'same_product_variant')
        ), activity_peers AS (
            SELECT DISTINCT v.country_code,v.source_shop_id,v.source_item_id,
                   v.target_shop_id,v.target_item_id,ta.seller_entity_id AS target_seller_entity_id
            FROM valid_peers v
            JOIN product_attributes ta ON ta.country_code=v.country_code
                                      AND ta.shop_id=v.target_shop_id
                                      AND ta.item_id=v.target_item_id
            WHERE relation IN ('same_product', 'same_product_variant', 'substitute')
        ), activity_counts AS (
            SELECT country_code,source_shop_id,source_item_id,
                   COUNT(DISTINCT target_seller_entity_id)::INTEGER AS benchmark_peer_count
            FROM activity_peers
            GROUP BY 1,2,3
        ), seller_daily AS (
            SELECT country_code,source_shop_id,source_item_id,target_seller_entity_id,
                   snapshot_date,ANY_VALUE(source_basis_units) AS source_basis_units,
                   MEDIAN(target_normalized_price) AS target_normalized_price,
                   MEDIAN(discount_percent) AS discount_percent,
                   MEDIAN(monthly_sold_value) AS monthly_sold_value,
                   MEDIAN(engagement) AS engagement
            FROM peer_observations
            WHERE target_normalized_price IS NOT NULL
            GROUP BY 1,2,3,4,5
        ), peer_daily AS (
            SELECT country_code, source_shop_id, source_item_id, snapshot_date,
                   COUNT(target_normalized_price) AS peer_count,
                   MIN(target_normalized_price * source_basis_units) AS peer_min_price,
                   MEDIAN(target_normalized_price * source_basis_units) AS peer_median_price,
                   MAX(target_normalized_price * source_basis_units) AS peer_max_price,
                   MEDIAN(target_normalized_price) AS peer_median_normalized_price,
                   MEDIAN(discount_percent) FILTER (WHERE target_normalized_price IS NOT NULL AND discount_percent IS NOT NULL) AS peer_median_discount_percent,
                   MEDIAN(monthly_sold_value) FILTER (WHERE target_normalized_price IS NOT NULL AND monthly_sold_value IS NOT NULL) AS peer_median_monthly_sold,
                   MEDIAN(engagement) FILTER (WHERE target_normalized_price IS NOT NULL) AS peer_median_engagement
            FROM seller_daily
            GROUP BY 1, 2, 3, 4
        ), event_target_day AS (
            SELECT country_code, shop_id, item_id, snapshot_date,
                   MAX(CASE WHEN event_type = 'promotion_changed'
                              AND LOWER(COALESCE(new_value, '')) NOT IN ('', 'none', 'null')
                            THEN 1 ELSE 0 END) AS promotion_started,
                   MAX(CASE WHEN event_type = 'price_changed'
                              AND TRY_CAST(old_value AS DOUBLE) > TRY_CAST(new_value AS DOUBLE)
                            THEN 1 ELSE 0 END) AS price_down
            FROM promotion_events
            GROUP BY 1, 2, 3, 4
        ), seller_event_day AS (
            SELECT v.country_code,v.source_shop_id,v.source_item_id,v.target_seller_entity_id,
                   e.snapshot_date,MAX(COALESCE(e.price_down,0)) AS price_down,
                   MAX(COALESCE(e.promotion_started,0)) AS promotion_started
            FROM activity_peers v
            JOIN event_target_day e ON e.country_code = v.country_code
                                   AND e.shop_id = v.target_shop_id
                                   AND e.item_id = v.target_item_id
            GROUP BY 1,2,3,4,5
        ), event_daily AS (
            SELECT country_code,source_shop_id,source_item_id,snapshot_date,
                   SUM(price_down)::INTEGER AS price_down_peer_count,
                   SUM(promotion_started)::INTEGER AS promotion_peer_count
            FROM seller_event_day
            GROUP BY 1,2,3,4
        ), base AS (
            SELECT s.country_code, s.snapshot_date, s.shop_id AS source_shop_id,
                   s.item_id AS source_item_id, s.currency, s.price AS source_price,
                   s.price_original AS source_list_price,
                   s.source_historical_median_price,
                   s.source_price_observation_count::INTEGER AS source_price_observation_count,
                   s.discount_percent AS source_discount_percent,
                   s.price_comparison_basis, s.source_normalized_price,
                   pd.peer_median_normalized_price,
                   CASE WHEN pd.peer_count > 0 THEN 'peer_found' ELSE 'not_enough_evidence' END AS peer_status,
                   COALESCE(pd.peer_count, 0)::INTEGER AS peer_count,
                   COALESCE(ac.benchmark_peer_count, 0)::INTEGER AS benchmark_peer_count,
                   pd.peer_min_price, pd.peer_median_price, pd.peer_max_price,
                   pd.peer_median_discount_percent, s.monthly_sold_value AS source_monthly_sold,
                   pd.peer_median_monthly_sold,
                   COALESCE(ed.price_down_peer_count, 0)::INTEGER AS price_down_peer_count,
                   COALESCE(ed.promotion_peer_count, 0)::INTEGER AS promotion_peer_count,
                   COALESCE(s.rating_count, 0) + COALESCE(s.liked_count, 0) AS source_engagement,
                   pd.peer_median_engagement
            FROM source_snapshots s
            LEFT JOIN peer_daily pd ON pd.country_code = s.country_code
                                   AND pd.source_shop_id = s.shop_id
                                   AND pd.source_item_id = s.item_id
                                   AND pd.snapshot_date = s.snapshot_date
            LEFT JOIN activity_counts ac ON ac.country_code = s.country_code
                                        AND ac.source_shop_id = s.shop_id
                                        AND ac.source_item_id = s.item_id
            LEFT JOIN event_daily ed ON ed.country_code = s.country_code
                                    AND ed.source_shop_id = s.shop_id
                                    AND ed.source_item_id = s.item_id
                                    AND ed.snapshot_date = s.snapshot_date
        ), lagged AS (
            SELECT b.*, LAG(source_monthly_sold) OVER w AS prev_source_sold,
                   LAG(peer_median_monthly_sold) OVER w AS prev_peer_sold,
                   LAG(source_engagement) OVER w AS prev_source_engagement,
                   LAG(peer_median_engagement) OVER w AS prev_peer_engagement,
                   COUNT(source_monthly_sold) OVER w AS source_history_count,
                   COUNT(peer_median_monthly_sold) OVER w AS peer_history_count
            FROM base b
            WINDOW w AS (PARTITION BY country_code, source_shop_id, source_item_id ORDER BY snapshot_date)
        ), calculated AS (
            SELECT l.*,
                   CASE WHEN peer_median_price > 0 AND source_price > 0
                        THEN source_price / peer_median_price END AS price_index,
                   CASE WHEN peer_median_price > 0 AND source_price > 0
                        THEN (source_price / peer_median_price - 1.0) * 100 END AS price_gap_pct,
                   CASE WHEN peer_median_discount_percent IS NOT NULL
                        AND source_discount_percent IS NOT NULL
                        THEN source_discount_percent - peer_median_discount_percent END AS discount_gap_pct,
                   CASE WHEN source_history_count >= 7 AND prev_source_sold >= 20 AND source_monthly_sold IS NOT NULL
                        THEN GREATEST(-100.0, LEAST(100.0, 100.0 * LN((1.0 + source_monthly_sold) / (1.0 + prev_source_sold)))) END AS source_sales_momentum_pct,
                   CASE WHEN peer_history_count >= 7 AND prev_peer_sold >= 20 AND peer_median_monthly_sold IS NOT NULL
                        THEN GREATEST(-100.0, LEAST(100.0, 100.0 * LN((1.0 + peer_median_monthly_sold) / (1.0 + prev_peer_sold)))) END AS peer_sales_momentum_pct,
                   CASE WHEN prev_source_engagement > 0
                        THEN (source_engagement / prev_source_engagement - 1.0) * 100 END AS source_engagement_momentum_pct,
                   CASE WHEN prev_peer_engagement > 0 AND peer_median_engagement IS NOT NULL
                        THEN (peer_median_engagement / prev_peer_engagement - 1.0) * 100 END AS peer_engagement_momentum_pct
            FROM lagged l
        ), scored AS (
            SELECT c.*,
                   LEAST(1.0, GREATEST(0.0, COALESCE(c.price_gap_pct, 0.0) / 25.0)) * 0.35
                   + CASE WHEN c.benchmark_peer_count > 0 THEN LEAST(1.0, c.price_down_peer_count::DOUBLE / c.benchmark_peer_count) ELSE 0 END * 0.25
                   + CASE WHEN c.benchmark_peer_count > 0 THEN LEAST(1.0, c.promotion_peer_count::DOUBLE / c.benchmark_peer_count) ELSE 0 END * 0.20
                   + LEAST(1.0, GREATEST(0.0, COALESCE(c.peer_sales_momentum_pct, 0.0)) / 50.0) * 0.20 AS pressure_score
            FROM calculated c
        )
        SELECT country_code, snapshot_date, source_shop_id, source_item_id, currency,
               source_price, source_list_price, source_historical_median_price,
               source_price_observation_count,
               CASE WHEN peer_median_price > 0 THEN peer_median_price
                    WHEN source_price_observation_count >= 3 THEN source_historical_median_price
                    WHEN source_list_price > 0 THEN source_list_price END,
               CASE WHEN peer_median_price > 0 THEN 'peer_market_median'
                    WHEN source_price_observation_count >= 3 THEN 'own_history_median'
                    WHEN source_list_price > 0 THEN 'listed_reference'
                    ELSE 'unavailable' END,
               CASE WHEN peer_median_price > 0 THEN TRUE ELSE FALSE END,
               source_discount_percent, price_comparison_basis,
               source_normalized_price, peer_median_normalized_price, peer_status, peer_count,
               benchmark_peer_count,
               peer_min_price, peer_median_price, peer_max_price, price_index, price_gap_pct,
               CASE WHEN price_index IS NOT NULL AND (price_index < 0.25 OR price_index > 4.0)
                    THEN TRUE ELSE FALSE END,
               CASE WHEN price_index IS NOT NULL AND (price_index < 0.25 OR price_index > 4.0)
                    THEN 'price_index_outside_0.25_4.0' END,
               peer_median_discount_percent, discount_gap_pct, source_monthly_sold,
               peer_median_monthly_sold, source_sales_momentum_pct, peer_sales_momentum_pct,
               source_engagement_momentum_pct, peer_engagement_momentum_pct,
               price_down_peer_count, promotion_peer_count, pressure_score,
               CASE WHEN pressure_score >= 0.55 THEN 'high'
                    WHEN pressure_score >= 0.25 THEN 'medium' ELSE 'low' END,
               CASE WHEN peer_count >= 3 THEN 'high'
                    WHEN peer_count >= 1 OR benchmark_peer_count >= 3 THEN 'medium'
                    WHEN benchmark_peer_count >= 1 THEN 'low' ELSE 'low' END,
               peer_count + benchmark_peer_count + price_down_peer_count + promotion_peer_count,
               ?, ?
        FROM scored
    """, [SIGNALS_VERSION, created_at])


def build_alerts(conn: duckdb.DuckDBPyConnection, created_at: datetime) -> None:
    """Turn signals into traceable, thresholded alerts."""
    conn.execute("""
        INSERT INTO competitor_alerts
        SELECT a.country_code, a.snapshot_date, a.source_shop_id, a.source_item_id,
               a.alert_type, a.severity, a.metric_name, a.metric_value, a.threshold,
               CASE
                    WHEN a.alert_type IN ('competitor_price_down', 'competitor_promotion_started')
                    THEN (SELECT pg.target_shop_id FROM peer_groups pg
                          JOIN promotion_events pe ON pe.country_code = pg.country_code
                                                   AND pe.shop_id = pg.target_shop_id
                                                   AND pe.item_id = pg.target_item_id
                                                   AND pe.snapshot_date = a.snapshot_date
                          WHERE pg.country_code = a.country_code
                            AND pg.source_shop_id = a.source_shop_id
                            AND pg.source_item_id = a.source_item_id
                            AND pg.peer_status = 'peer_found'
                            AND ((a.alert_type = 'competitor_price_down'
                                  AND pe.event_type = 'price_changed'
                                  AND TRY_CAST(pe.old_value AS DOUBLE) > TRY_CAST(pe.new_value AS DOUBLE))
                              OR (a.alert_type = 'competitor_promotion_started'
                                  AND pe.event_type = 'promotion_changed'))
                          ORDER BY pg.match_score DESC, pg.target_shop_id, pg.target_item_id
                          LIMIT 1)
                    WHEN a.alert_type IN ('our_price_above_market', 'our_discount_below_market')
                    THEN (SELECT pg.target_shop_id FROM peer_groups pg
                          WHERE pg.country_code = a.country_code
                            AND pg.source_shop_id = a.source_shop_id
                            AND pg.source_item_id = a.source_item_id
                            AND pg.peer_status = 'peer_found'
                            AND pg.relation IN ('same_product', 'same_product_variant')
                          ORDER BY pg.match_score DESC LIMIT 1)
               END,
               CASE
                    WHEN a.alert_type IN ('competitor_price_down', 'competitor_promotion_started')
                    THEN (SELECT pg.target_item_id FROM peer_groups pg
                          JOIN promotion_events pe ON pe.country_code = pg.country_code
                                                   AND pe.shop_id = pg.target_shop_id
                                                   AND pe.item_id = pg.target_item_id
                                                   AND pe.snapshot_date = a.snapshot_date
                          WHERE pg.country_code = a.country_code
                            AND pg.source_shop_id = a.source_shop_id
                            AND pg.source_item_id = a.source_item_id
                            AND pg.peer_status = 'peer_found'
                            AND ((a.alert_type = 'competitor_price_down'
                                  AND pe.event_type = 'price_changed'
                                  AND TRY_CAST(pe.old_value AS DOUBLE) > TRY_CAST(pe.new_value AS DOUBLE))
                              OR (a.alert_type = 'competitor_promotion_started'
                                  AND pe.event_type = 'promotion_changed'))
                          ORDER BY pg.match_score DESC, pg.target_shop_id, pg.target_item_id
                          LIMIT 1)
                    WHEN a.alert_type IN ('our_price_above_market', 'our_discount_below_market')
                    THEN (SELECT pg.target_item_id FROM peer_groups pg
                          WHERE pg.country_code = a.country_code
                            AND pg.source_shop_id = a.source_shop_id
                            AND pg.source_item_id = a.source_item_id
                            AND pg.peer_status = 'peer_found'
                            AND pg.relation IN ('same_product', 'same_product_variant')
                          ORDER BY pg.match_score DESC LIMIT 1)
               END,
               json_object('peer_count', a.peer_count,
                           'benchmark_peer_count', a.benchmark_peer_count,
                           'comparison_scope', CASE
                               WHEN a.alert_type IN ('competitor_price_down', 'competitor_promotion_started')
                               THEN 'qualified_substitute_activity'
                               ELSE 'normalized_price_equivalent' END,
                           'peer_median_price', a.peer_median_price,
                           'price_gap_pct', a.price_gap_pct,
                           'discount_gap_pct', a.discount_gap_pct,
                           'price_down_peer_count', a.price_down_peer_count,
                           'promotion_peer_count', a.promotion_peer_count,
                           'peer_sales_momentum_pct', a.peer_sales_momentum_pct,
                           'pressure_score', a.competitive_pressure_score,
                           'signal_confidence', a.signal_confidence),
               ?, ?
        FROM (
            SELECT *, 'our_price_above_market' AS alert_type,
                   CASE WHEN price_gap_pct >= 20 THEN 'high' ELSE 'medium' END AS severity,
                   'price_gap_pct' AS metric_name, price_gap_pct AS metric_value, 10.0 AS threshold
            FROM market_signals
            WHERE price_gap_pct >= 10 AND peer_status = 'peer_found' AND NOT is_price_outlier
            UNION ALL
            SELECT *, 'our_discount_below_market',
                   CASE WHEN discount_gap_pct <= -20 THEN 'high' ELSE 'medium' END,
                   'discount_gap_pct', discount_gap_pct, -10.0
            FROM market_signals
            WHERE discount_gap_pct <= -10 AND peer_status = 'peer_found' AND NOT is_price_outlier
            UNION ALL
            SELECT *, 'competitor_price_down', 'medium',
                   'price_down_peer_count', price_down_peer_count, 1.0
            FROM market_signals WHERE price_down_peer_count > 0
            UNION ALL
            SELECT *, 'competitor_promotion_started', 'medium',
                   'promotion_peer_count', promotion_peer_count, 1.0
            FROM market_signals WHERE promotion_peer_count > 0
            UNION ALL
            SELECT *, 'competitor_momentum_up',
                   CASE WHEN peer_sales_momentum_pct >= 40 THEN 'high' ELSE 'medium' END,
                   'peer_sales_momentum_pct', peer_sales_momentum_pct, 20.0
            FROM market_signals
            WHERE peer_sales_momentum_pct >= 20 AND peer_status = 'peer_found'
            UNION ALL
            SELECT *, 'high_competitive_pressure', 'high',
                   'competitive_pressure_score', competitive_pressure_score, 0.55
            FROM market_signals WHERE competitive_pressure_score >= 0.55
        ) a
    """, [SIGNALS_VERSION, created_at])


def export_alert_review(conn: duckdb.DuckDBPyConnection, review_file: str, sample_size: int = 20) -> int:
    """Export a deterministic, unlabeled alert sample for business review."""
    path = Path(review_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = conn.execute("""
        SELECT country_code, snapshot_date, source_shop_id, source_item_id,
               alert_type, severity, metric_name, metric_value, threshold,
               target_shop_id, target_item_id, CAST(evidence AS VARCHAR)
        FROM competitor_alerts
        ORDER BY snapshot_date DESC, severity DESC, alert_type, source_item_id
        LIMIT ?
    """, [sample_size]).fetchall()
    fields = [
        "review_id", "country_code", "snapshot_date", "source_shop_id",
        "source_item_id", "alert_type", "severity", "metric_name",
        "metric_value", "threshold", "target_shop_id", "target_item_id",
        "evidence", "review_label", "review_notes", "annotator",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(fields)
        for index, row in enumerate(rows, 1):
            writer.writerow([index, *row, "", "", ""])
    return len(rows)


def run(db_path: str, min_score: float = 0.60, review_file: str | None = None) -> dict[str, int | float]:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(path))
    created_at = _now()
    run_id = start_run(conn, "market_signals", {"min_peer_score": min_score, "db_path": str(path)})
    try:
        create_tables(conn)
        build_peer_groups(conn, min_score, created_at)
        build_signals(conn, created_at)
        build_alerts(conn, created_at)
        conn.commit()
        if review_file is None:
            review_file = str(path.with_name("market_signals_review.csv"))
        review_rows = export_alert_review(conn, review_file)
        result = {
            "run_id": run_id,
            "peer_group_rows": conn.execute("SELECT COUNT(*) FROM peer_groups").fetchone()[0],
            "peer_found_sources": conn.execute("SELECT COUNT(DISTINCT (country_code, source_shop_id, source_item_id)) FROM peer_groups WHERE peer_status='peer_found'").fetchone()[0],
            "not_enough_evidence_sources": conn.execute("SELECT COUNT(DISTINCT (country_code, source_shop_id, source_item_id)) FROM peer_groups WHERE peer_status='not_enough_evidence'").fetchone()[0],
            "market_signal_rows": conn.execute("SELECT COUNT(*) FROM market_signals").fetchone()[0],
            "alert_rows": conn.execute("SELECT COUNT(*) FROM competitor_alerts").fetchone()[0],
            "review_rows": review_rows,
            "review_file": review_file,
        }
        finish_run(conn, run_id, "success", {
            "peer_groups": result["peer_group_rows"],
            "market_signals": result["market_signal_rows"],
            "competitor_alerts": result["alert_rows"],
        })
        return result
    except Exception as exc:
        finish_run(conn, run_id, "failed", error_message=str(exc)[:500])
        raise
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", default=os.getenv("DB_PATH", "./warehouse/market.duckdb"))
    parser.add_argument(
        "--min-peer-score", type=float, default=0.60,
        help="Ngưỡng hiển thị benchmark; phép so giá vẫn chỉ dùng exact/variant có thể quy đổi.",
    )
    parser.add_argument("--review-file", default=None)
    args = parser.parse_args()
    print(json.dumps(run(args.db_path, args.min_peer_score, args.review_file), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
