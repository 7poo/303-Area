"""Generate explainable, constraint-aware recommendation cards.

The engine is intentionally rule based.  It turns observed market signals into
candidate actions, but never claims a causal sales or profit effect.  Cost and
minimum-margin inputs are optional; without them, price-changing actions are
held for validation rather than silently violating a margin constraint.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

from .pipeline import finish_run, start_run


RULE_VERSION = "recommendation-rules-v0.4-seeded-cost-scenarios"
DEFAULT_MARGIN_MIN_PCT = 10.0


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None


def _round_price(value: float | None) -> float | None:
    if value is None:
        return None
    # Marketplace prices in this dataset are integer local-currency units.
    return float(round(value / 100.0) * 100)


def _round_safe_price(value: float) -> float:
    """Round a price target upward so rounding cannot breach its floor."""
    return float(math.ceil(value / 100.0) * 100)


def _floor_percent(value: float, decimals: int = 2) -> float:
    """Truncate a discount cap so display rounding never makes it unsafe."""
    scale = 10 ** decimals
    return math.floor(max(0.0, value) * scale + 1e-9) / scale


def _confidence(signal_confidence: str | None, has_cost: bool) -> str:
    if signal_confidence == "high" and has_cost:
        return "high"
    if signal_confidence in {"high", "medium"}:
        return "medium"
    return "low"


def decide_recommendation(signal: dict[str, Any], cost_input: dict[str, Any] | None = None) -> dict[str, Any]:
    """Apply the v0.1 rules to one latest market signal."""
    current_price = _number(signal.get("source_price"))
    market_price = _number(signal.get("peer_median_price"))
    price_gap = _number(signal.get("price_gap_pct"))
    discount_gap = _number(signal.get("discount_gap_pct"))
    peer_discount = _number(signal.get("peer_median_discount_percent"))
    current_discount = _number(signal.get("source_discount_percent")) or 0.0
    pressure_score = _number(signal.get("competitive_pressure_score")) or 0.0
    peer_count = int(signal.get("peer_count") or 0)
    peer_status = signal.get("peer_status")
    is_outlier = bool(signal.get("is_price_outlier"))
    benchmark_peer_count = int(signal.get("benchmark_peer_count") or 0)
    benchmark_best_score = _number(signal.get("benchmark_best_score"))
    promotion_terms_verified = bool(signal.get("promotion_terms_verified"))

    cost = _number(cost_input.get("cost_value")) if cost_input else None
    cost_source = str(cost_input.get("cost_source") or "verified_input") if cost_input else "missing"
    is_seeded_cost = cost_source == "seeded_scenario"
    margin_min_pct = _number(cost_input.get("margin_min_pct")) if cost_input else None
    margin_min_pct = DEFAULT_MARGIN_MIN_PCT if margin_min_pct is None else margin_min_pct
    if not 0 <= margin_min_pct < 100:
        raise ValueError("margin_min_pct phải nằm trong khoảng từ 0 đến dưới 100")
    has_cost = cost is not None and cost > 0
    # Gross margin = (price - cost) / price.  Therefore the minimum safe
    # selling price is cost / (1 - required gross-margin rate).
    price_floor = cost / (1.0 - margin_min_pct / 100.0) if has_cost else None

    reasons: list[str] = []
    status = "recommended"
    action = "hold_price"
    priority = "low"
    recommended_price: float | None = current_price
    recommended_discount: float | None = current_discount
    constraint_status = "verified" if has_cost else "unverified_cost_missing"

    if peer_status != "peer_found" or peer_count < 1 or market_price is None:
        if benchmark_peer_count > 0:
            return {
                "status": "monitoring_only",
                "action": "review_competitors",
                "priority": "medium" if benchmark_peer_count >= 3 else "low",
                "confidence": "medium" if (benchmark_best_score or 0) >= 0.70 else "low",
                "recommended_price": None,
                "recommended_discount_percent": None,
                "price_floor": price_floor,
                "cost_value": cost,
                "margin_min_pct": margin_min_pct,
                "estimated_margin_pct": None,
                "constraint_status": "not_applicable",
                "reason_codes": ["substitute_benchmark_available", "price_target_not_comparable"],
                "recommendation_text": (
                    f"Theo dõi {benchmark_peer_count} sản phẩm thay thế từ đơn vị bán khác. "
                    "Các sản phẩm này hữu ích để quan sát cạnh tranh nhưng chưa đủ tương đương để làm giá mục tiêu."
                ),
            }
        return {
            "status": "insufficient_evidence",
            "action": "no_response",
            "priority": "low",
            "confidence": "low",
            "recommended_price": None,
            "recommended_discount_percent": None,
            "price_floor": price_floor,
            "cost_value": cost,
            "margin_min_pct": margin_min_pct,
            "estimated_margin_pct": None,
            "constraint_status": "not_applicable",
            "reason_codes": ["not_enough_evidence"],
            "recommendation_text": "Chưa có đủ sản phẩm đối thủ tương đồng và đáng tin cậy; hệ thống chưa đề xuất thay đổi.",
        }

    if is_outlier:
        return {
            "status": "insufficient_evidence",
            "action": "no_response",
            "priority": "medium",
            "confidence": "low",
            "recommended_price": None,
            "recommended_discount_percent": None,
            "price_floor": price_floor,
            "cost_value": cost,
            "margin_min_pct": margin_min_pct,
            "estimated_margin_pct": None,
            "constraint_status": "outlier_review_required",
            "reason_codes": ["price_outlier"],
            "recommendation_text": "Giá hiện tại nằm ngoài khoảng so sánh thông thường; cần kiểm tra lại dữ liệu trước khi hành động.",
        }

    if price_gap is not None and price_gap >= 20:
        priority = "high"
    elif (price_gap is not None and price_gap >= 10) or (discount_gap is not None and discount_gap <= -10):
        priority = "medium"

    # A price reduction is only executable when its floor can be verified.
    if price_gap is not None and price_gap >= 10 and current_price and market_price < current_price:
        reasons.append("price_above_peer_median")
        if not has_cost:
            status = "needs_cost_validation"
            action = "hold_price"
            recommended_price = current_price
            constraint_status = "blocked_cost_missing"
            reasons.append("cost_required_before_price_change")
        elif market_price >= price_floor:
            action = "reduce_price"
            recommended_price = min(current_price, _round_safe_price(max(market_price, price_floor)))
            reasons.append("target_respects_margin_floor")
        else:
            status = "constraint_blocked"
            action = "hold_price"
            recommended_price = current_price
            constraint_status = "market_below_margin_floor"
            reasons.append("peer_median_below_margin_floor")

    elif discount_gap is not None and discount_gap <= -10:
        reasons.append("discount_below_peer_median")
        target_discount = min(90.0, max(current_discount, peer_discount or current_discount))
        if not has_cost:
            status = "needs_cost_validation"
            action = "hold_price"
            constraint_status = "blocked_cost_missing"
            reasons.append("cost_required_before_voucher")
        elif not promotion_terms_verified:
            status = "needs_promotion_validation"
            action = "hold_price"
            constraint_status = "blocked_promotion_terms_missing"
            reasons.append("promotion_terms_required_before_voucher")
        elif current_price and price_floor is not None:
            max_discount = max(0.0, (1.0 - price_floor / current_price) * 100.0)
            recommended_discount = _floor_percent(min(target_discount, max_discount))
            if recommended_discount > current_discount:
                action = "use_voucher"
                reasons.append("voucher_respects_margin_floor")
            else:
                status = "constraint_blocked"
                action = "hold_price"
                constraint_status = "margin_floor_leaves_no_discount_room"
                reasons.append("no_safe_discount_room")

    elif pressure_score >= 0.55 or int(signal.get("promotion_peer_count") or 0) > 0:
        reasons.append("competitive_pressure_observed")
        if not has_cost:
            status = "needs_cost_validation"
            action = "hold_price"
            constraint_status = "blocked_cost_missing"
            reasons.append("cost_required_before_voucher")
        elif not promotion_terms_verified:
            status = "needs_promotion_validation"
            action = "hold_price"
            constraint_status = "blocked_promotion_terms_missing"
            reasons.append("promotion_terms_required_before_voucher")
        elif current_price and price_floor is not None:
            max_discount = max(0.0, (1.0 - price_floor / current_price) * 100.0)
            target_discount = min(90.0, max(current_discount, peer_discount or current_discount))
            recommended_discount = _floor_percent(min(target_discount, max_discount))
            if recommended_discount > current_discount:
                action = "use_voucher"
                reasons.append("voucher_respects_margin_floor")
            else:
                status = "constraint_blocked"
                action = "hold_price"
                constraint_status = "margin_floor_leaves_no_discount_room"
                reasons.append("no_safe_discount_room")

    if action == "hold_price" and not reasons:
        reasons.append("price_close_to_peer_median")

    if is_seeded_cost and status in {"recommended", "constraint_blocked"}:
        status = "scenario_only"
        constraint_status = "seeded_cost_not_verified"
        reasons.append("seeded_cost_scenario_not_executable")

    effective_price = recommended_price
    if action == "use_voucher" and current_price is not None and recommended_discount is not None:
        effective_price = current_price * (1.0 - recommended_discount / 100.0)
    estimated_margin_pct = None
    if has_cost and effective_price is not None and effective_price > 0:
        estimated_margin_pct = round((effective_price - cost) / effective_price * 100.0, 2)

    text_by_action = {
        "reduce_price": "Cân nhắc điều chỉnh giá về gần mức giá trung vị của nhóm đối thủ, sau khi xác nhận giá sàn.",
        "use_voucher": "Cân nhắc dùng mã giảm giá để thu hẹp chênh lệch khuyến mãi mà vẫn bảo đảm biên lợi nhuận.",
        "hold_price": "Giữ nguyên giá hiện tại và tiếp tục theo dõi tín hiệu thị trường.",
        "no_response": "Chưa đề xuất thay đổi vì bằng chứng hiện tại chưa đủ tin cậy.",
    }
    return {
        "status": status,
        "action": action,
        "priority": priority,
        "confidence": "low" if status == "scenario_only" else _confidence(signal.get("signal_confidence"), has_cost and not is_seeded_cost),
        "recommended_price": recommended_price,
        "recommended_discount_percent": recommended_discount,
        "price_floor": price_floor,
        "cost_value": cost,
        "margin_min_pct": margin_min_pct,
        "estimated_margin_pct": estimated_margin_pct,
        "constraint_status": constraint_status,
        "reason_codes": reasons,
        "recommendation_text": text_by_action[action],
    }


def create_table(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute("DROP TABLE IF EXISTS recommendations")
    conn.execute("""
        CREATE TABLE recommendations (
            country_code VARCHAR NOT NULL,
            snapshot_date DATE NOT NULL,
            source_shop_id BIGINT NOT NULL,
            source_item_id BIGINT NOT NULL,
            currency VARCHAR NOT NULL,
            recommendation_status VARCHAR NOT NULL,
            action VARCHAR NOT NULL,
            priority VARCHAR NOT NULL,
            confidence VARCHAR NOT NULL,
            source_price DOUBLE,
            market_reference_price DOUBLE,
            recommended_price DOUBLE,
            source_discount_percent DOUBLE,
            recommended_discount_percent DOUBLE,
            price_floor DOUBLE,
            cost_value DOUBLE,
            margin_min_pct DOUBLE,
            estimated_margin_pct DOUBLE,
            constraint_status VARCHAR NOT NULL,
            reason_codes JSON NOT NULL,
            recommendation_text VARCHAR NOT NULL,
            evidence JSON NOT NULL,
            rule_version VARCHAR NOT NULL,
            created_at TIMESTAMP NOT NULL
        )
    """)


def load_costs(cost_file: str | None) -> dict[tuple[str, int, int], dict[str, Any]]:
    if not cost_file:
        return {}
    result: dict[tuple[str, int, int], dict[str, Any]] = {}
    with Path(cost_file).open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                key = (row["country_code"].strip().lower(), int(row["shop_id"]), int(row["item_id"]))
                cost_value = float(row["cost_value"])
                margin_min_pct = float(row.get("margin_min_pct") or DEFAULT_MARGIN_MIN_PCT)
                if cost_value <= 0:
                    raise ValueError("cost_value phải lớn hơn 0")
                if not 0 <= margin_min_pct < 100:
                    raise ValueError("margin_min_pct phải nằm trong khoảng từ 0 đến dưới 100")
                result[key] = {
                    "cost_value": cost_value,
                    "margin_min_pct": margin_min_pct,
                    "cost_low": _number(row.get("cost_low")),
                    "cost_high": _number(row.get("cost_high")),
                    "cost_seed_pct": _number(row.get("cost_seed_pct")),
                    "cost_reference_price": _number(row.get("cost_reference_price")),
                    "cost_source": str(row.get("cost_source") or "verified_input"),
                    "cost_confidence": str(row.get("cost_confidence") or "verified"),
                    "baseline_type": str(row.get("baseline_type") or "unknown"),
                }
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("Cost CSV cần country_code, shop_id, item_id, cost_value và tùy chọn margin_min_pct") from exc
    return result


def _latest_signals(conn: duckdb.DuckDBPyConnection, shop_id: int | None = None) -> list[dict[str, Any]]:
    where = "" if shop_id is None else "WHERE source_shop_id = ?"
    params = [] if shop_id is None else [shop_id]
    rows = conn.execute(f"""
        SELECT * EXCLUDE (created_at)
        FROM market_signals
        {where}
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY country_code, source_shop_id, source_item_id
            ORDER BY snapshot_date DESC
        ) = 1
        ORDER BY country_code, source_shop_id, source_item_id
    """, params)
    columns = [item[0] for item in rows.description]
    return [dict(zip(columns, row)) for row in rows.fetchall()]


def build_recommendations(
    conn: duckdb.DuckDBPyConnection,
    costs: dict[tuple[str, int, int], dict[str, Any]],
    created_at: datetime,
    shop_id: int | None = None,
) -> int:
    signals = _latest_signals(conn, shop_id)
    benchmark_rows = conn.execute("""
        SELECT country_code, source_shop_id, source_item_id,
               COUNT(*) FILTER (WHERE relation = 'substitute')::INTEGER AS benchmark_peer_count,
               MAX(match_score) FILTER (WHERE relation = 'substitute') AS benchmark_best_score
        FROM peer_groups
        WHERE peer_status = 'peer_found'
        GROUP BY 1, 2, 3
    """).fetchall()
    benchmark_by_key = {
        (str(country), int(source_shop), int(source_item)): {
            "benchmark_peer_count": int(count or 0),
            "benchmark_best_score": _number(best_score),
        }
        for country, source_shop, source_item, count, best_score in benchmark_rows
    }
    insert_sql = """
        INSERT INTO recommendations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    for signal in signals:
        key = (str(signal["country_code"]), int(signal["source_shop_id"]), int(signal["source_item_id"]))
        signal.update(benchmark_by_key.get(key, {"benchmark_peer_count": 0, "benchmark_best_score": None}))
        cost_input = costs.get(key)
        decision = decide_recommendation(signal, cost_input)
        evidence = {
            "peer_count": signal.get("peer_count"),
            "peer_median_price": signal.get("peer_median_price"),
            "source_list_price": signal.get("source_list_price"),
            "source_historical_median_price": signal.get("source_historical_median_price"),
            "source_price_observation_count": signal.get("source_price_observation_count"),
            "price_baseline_value": signal.get("price_baseline_value"),
            "price_baseline_type": signal.get("price_baseline_type"),
            "price_baseline_actionable": signal.get("price_baseline_actionable"),
            "price_gap_pct": signal.get("price_gap_pct"),
            "discount_gap_pct": signal.get("discount_gap_pct"),
            "pressure_score": signal.get("competitive_pressure_score"),
            "price_down_peer_count": signal.get("price_down_peer_count"),
            "promotion_peer_count": signal.get("promotion_peer_count"),
            "signal_confidence": signal.get("signal_confidence"),
            "signal_model_version": signal.get("model_version"),
            "benchmark_peer_count": signal.get("benchmark_peer_count"),
            "benchmark_best_score": signal.get("benchmark_best_score"),
            "benchmark_usage": "context_only_not_price_target",
            "cost_assumption": cost_input,
        }
        conn.execute(insert_sql, [
            signal["country_code"], signal["snapshot_date"], signal["source_shop_id"], signal["source_item_id"],
            signal["currency"], decision["status"], decision["action"], decision["priority"], decision["confidence"],
            signal.get("source_price"), signal.get("peer_median_price"), decision["recommended_price"],
            signal.get("source_discount_percent"), decision["recommended_discount_percent"], decision["price_floor"],
            decision["cost_value"], decision["margin_min_pct"], decision["estimated_margin_pct"], decision["constraint_status"],
            json.dumps(decision["reason_codes"], ensure_ascii=False), decision["recommendation_text"],
            json.dumps(evidence, ensure_ascii=False, default=str), RULE_VERSION, created_at,
        ])
    return len(signals)


def export_review(conn: duckdb.DuckDBPyConnection, review_file: str, sample_size: int = 20) -> int:
    path = Path(review_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = conn.execute("""
        SELECT country_code, snapshot_date, source_shop_id, source_item_id,
               action, recommendation_status, priority, confidence,
               recommended_price, recommended_discount_percent,
               recommendation_text, CAST(evidence AS VARCHAR)
        FROM recommendations
        ORDER BY priority DESC, recommendation_status, country_code, source_item_id
        LIMIT ?
    """, [sample_size]).fetchall()
    fields = ["review_id", "country_code", "snapshot_date", "source_shop_id", "source_item_id",
              "action", "recommendation_status", "priority", "confidence", "recommended_price",
              "recommended_discount_percent", "recommendation_text", "evidence", "review_label",
              "review_notes", "annotator"]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(fields)
        for index, row in enumerate(rows, 1):
            writer.writerow([index, *row, "", "", ""])
    return len(rows)


def run(db_path: str, cost_file: str | None = None, shop_id: int | None = None, review_file: str | None = None) -> dict[str, Any]:
    path = Path(db_path)
    conn = duckdb.connect(str(path))
    created_at = _now()
    run_id = start_run(conn, "recommendations", {
        "cost_file": cost_file,
        "shop_id": shop_id,
        "db_path": str(path),
    })
    try:
        create_table(conn)
        costs = load_costs(cost_file)
        recommendation_rows = build_recommendations(conn, costs, created_at, shop_id)
        if review_file is None:
            review_file = str(path.with_name("recommendations_review.csv"))
        review_rows = export_review(conn, review_file)
        conn.commit()
        result = {
            "run_id": run_id,
            "recommendation_rows": recommendation_rows,
            "cost_inputs": len(costs),
            "review_rows": review_rows,
            "review_file": review_file,
            "actions": conn.execute("SELECT action, COUNT(*) FROM recommendations GROUP BY 1 ORDER BY 1").fetchall(),
            "statuses": conn.execute("SELECT recommendation_status, COUNT(*) FROM recommendations GROUP BY 1 ORDER BY 1").fetchall(),
        }
        finish_run(conn, run_id, "success", {"recommendations": recommendation_rows})
        return result
    except Exception as exc:
        finish_run(conn, run_id, "failed", error_message=str(exc)[:500])
        raise
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", default=os.getenv("DB_PATH", "./warehouse/market.duckdb"))
    parser.add_argument("--cost-file", default=None, help="CSV country_code,shop_id,item_id,cost_value,margin_min_pct")
    parser.add_argument("--shop-id", type=int, default=None)
    parser.add_argument("--review-file", default=None)
    args = parser.parse_args()
    print(json.dumps(run(args.db_path, args.cost_file, args.shop_id, args.review_file), ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
