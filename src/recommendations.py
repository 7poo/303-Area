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
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

from .pipeline import finish_run, start_run


RULE_VERSION = "recommendation-rules-v0.1"
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


def _confidence(signal_confidence: str | None, has_cost: bool) -> str:
    if signal_confidence == "high" and has_cost:
        return "high"
    if signal_confidence in {"high", "medium"}:
        return "medium"
    return "low"


def decide_recommendation(signal: dict[str, Any], cost_input: dict[str, float] | None = None) -> dict[str, Any]:
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

    cost = _number(cost_input.get("cost_value")) if cost_input else None
    margin_min_pct = _number(cost_input.get("margin_min_pct")) if cost_input else None
    margin_min_pct = DEFAULT_MARGIN_MIN_PCT if margin_min_pct is None else margin_min_pct
    price_floor = cost * (1.0 + margin_min_pct / 100.0) if cost is not None else None
    has_cost = cost is not None and cost > 0

    reasons: list[str] = []
    status = "recommended"
    action = "hold_price"
    priority = "low"
    recommended_price: float | None = current_price
    recommended_discount: float | None = current_discount
    constraint_status = "verified" if has_cost else "unverified_cost_missing"

    if peer_status != "peer_found" or peer_count < 1 or market_price is None:
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
            "recommendation_text": "Chưa có peer đủ tin cậy; không tự động đề xuất thay đổi.",
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
            "recommendation_text": "Giá nằm ngoài khoảng so sánh; cần kiểm tra dữ liệu trước khi hành động.",
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
            recommended_price = _round_price(min(current_price, market_price))
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
        elif current_price and price_floor is not None:
            max_discount = max(0.0, (1.0 - price_floor / current_price) * 100.0)
            recommended_discount = round(min(target_discount, max_discount), 2)
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
        elif current_price and price_floor is not None:
            max_discount = max(0.0, (1.0 - price_floor / current_price) * 100.0)
            target_discount = min(90.0, max(current_discount, peer_discount or current_discount))
            recommended_discount = round(min(target_discount, max_discount), 2)
            if recommended_discount > current_discount:
                action = "use_voucher"
                reasons.append("voucher_respects_margin_floor")

    if action == "hold_price" and not reasons:
        reasons.append("price_close_to_peer_median")

    effective_price = recommended_price
    if action == "use_voucher" and current_price is not None and recommended_discount is not None:
        effective_price = current_price * (1.0 - recommended_discount / 100.0)
    estimated_margin_pct = None
    if has_cost and effective_price is not None:
        estimated_margin_pct = round((effective_price / cost - 1.0) * 100.0, 2)

    text_by_action = {
        "reduce_price": "Cân nhắc giảm giá về gần median của peer, sau khi duyệt giá sàn.",
        "use_voucher": "Cân nhắc voucher để thu hẹp chênh lệch discount trong giới hạn margin.",
        "hold_price": "Giữ giá hiện tại trong khi theo dõi thêm bằng chứng thị trường.",
        "no_response": "Không tự động thay đổi khi bằng chứng chưa đủ.",
    }
    return {
        "status": status,
        "action": action,
        "priority": priority,
        "confidence": _confidence(signal.get("signal_confidence"), has_cost),
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


def load_costs(cost_file: str | None) -> dict[tuple[str, int, int], dict[str, float]]:
    if not cost_file:
        return {}
    result: dict[tuple[str, int, int], dict[str, float]] = {}
    with Path(cost_file).open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                key = (row["country_code"].strip().lower(), int(row["shop_id"]), int(row["item_id"]))
                result[key] = {
                    "cost_value": float(row["cost_value"]),
                    "margin_min_pct": float(row.get("margin_min_pct") or DEFAULT_MARGIN_MIN_PCT),
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
    costs: dict[tuple[str, int, int], dict[str, float]],
    created_at: datetime,
    shop_id: int | None = None,
) -> int:
    signals = _latest_signals(conn, shop_id)
    insert_sql = """
        INSERT INTO recommendations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    for signal in signals:
        key = (str(signal["country_code"]), int(signal["source_shop_id"]), int(signal["source_item_id"]))
        decision = decide_recommendation(signal, costs.get(key))
        evidence = {
            "peer_count": signal.get("peer_count"),
            "peer_median_price": signal.get("peer_median_price"),
            "price_gap_pct": signal.get("price_gap_pct"),
            "discount_gap_pct": signal.get("discount_gap_pct"),
            "pressure_score": signal.get("competitive_pressure_score"),
            "price_down_peer_count": signal.get("price_down_peer_count"),
            "promotion_peer_count": signal.get("promotion_peer_count"),
            "signal_confidence": signal.get("signal_confidence"),
            "signal_model_version": signal.get("model_version"),
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
