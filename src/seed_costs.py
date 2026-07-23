"""Create deterministic scenario-only cost inputs from observable price bases.

These values are not accounting costs. They exist so analysts can exercise
the recommendation workflow before verified ERP cost data is available.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import duckdb


def _round_100(value: float) -> int:
    return int(round(value / 100.0) * 100)


def seed_costs(db_path: Path, output: Path, company_id: str, margin_min_pct: float = 15.0) -> int:
    conn = duckdb.connect(str(db_path), read_only=True)
    rows = conn.execute("""
        WITH latest AS (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY country_code,source_shop_id,source_item_id
                ORDER BY snapshot_date DESC
            ) AS rn
            FROM market_signals
        )
        SELECT x.country_code,x.source_shop_id,x.source_item_id,x.currency,
               x.source_price,x.source_list_price,x.source_historical_median_price,
               x.price_baseline_value,x.price_baseline_type,x.price_baseline_actionable,
               pa.price_variant_ambiguous
        FROM latest x
        JOIN product_attributes pa ON pa.country_code=x.country_code
                                  AND pa.shop_id=x.source_shop_id
                                  AND pa.item_id=x.source_item_id
        WHERE x.rn=1 AND pa.company_id=?
        ORDER BY x.country_code,x.source_shop_id,x.source_item_id
    """, [company_id]).fetchall()
    conn.close()

    output.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "country_code", "shop_id", "item_id", "cost_value", "margin_min_pct",
        "cost_low", "cost_high", "cost_seed_pct", "cost_reference_price",
        "cost_source", "cost_confidence", "baseline_type", "currency",
    ]
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for country, shop, item, currency, current, listed, history, baseline, baseline_type, actionable, variation_ambiguous in rows:
            reference = float(baseline or history or current or listed or 0)
            if reference <= 0:
                continue
            if variation_ambiguous:
                low_pct, seed_pct, high_pct, confidence = 50.0, 70.0, 90.0, "very_low"
            elif actionable and baseline_type == "peer_market_median":
                low_pct, seed_pct, high_pct, confidence = 65.0, 72.0, 78.0, "low"
            elif baseline_type == "own_history_median":
                low_pct, seed_pct, high_pct, confidence = 60.0, 70.0, 80.0, "very_low"
            else:
                # A listed anchor is often inflated. Use current price as the
                # scenario reference and make the range deliberately wide.
                reference = float(current or baseline or listed)
                low_pct, seed_pct, high_pct, confidence = 55.0, 70.0, 85.0, "very_low"
            writer.writerow({
                "country_code": country,
                "shop_id": int(shop),
                "item_id": int(item),
                "cost_value": _round_100(reference * seed_pct / 100.0),
                "margin_min_pct": margin_min_pct,
                "cost_low": _round_100(reference * low_pct / 100.0),
                "cost_high": _round_100(reference * high_pct / 100.0),
                "cost_seed_pct": seed_pct,
                "cost_reference_price": _round_100(reference),
                "cost_source": "seeded_scenario",
                "cost_confidence": confidence,
                "baseline_type": baseline_type,
                "currency": currency,
            })
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", type=Path, default=Path("./warehouse/market.duckdb"))
    parser.add_argument("--output", type=Path, default=Path("./validation/cost_inputs.seeded.csv"))
    parser.add_argument("--company-id", default="richy_vietnam")
    parser.add_argument("--margin-min-pct", type=float, default=15.0)
    args = parser.parse_args()
    count = seed_costs(args.db_path, args.output, args.company_id, args.margin_min_pct)
    print({"rows": count, "output": str(args.output), "mode": "seeded_scenario"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
