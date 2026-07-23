"""Allow-listed, read-only tools exposed to the Market Intelligence agent."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

import duckdb

from .pipeline import latest_successful_run


class ToolValidationError(ValueError):
    pass


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[[dict[str, Any]], dict[str, Any]]

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def _json_safe(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    return str(value)


def _rows(cursor: Any) -> list[dict[str, Any]]:
    columns = [item[0] for item in cursor.description]
    return [{column: _json_safe(value) for column, value in zip(columns, row)} for row in cursor.fetchall()]


def _country(args: dict[str, Any]) -> str:
    country = str(args.get("country_code", "")).lower().strip()
    if country not in {"vn", "id"}:
        raise ToolValidationError("country_code must be vn or id")
    return country


def _positive_int(args: dict[str, Any], name: str) -> int:
    try:
        value = int(args[name])
    except (KeyError, TypeError, ValueError) as exc:
        raise ToolValidationError(f"{name} must be a positive integer") from exc
    if value <= 0:
        raise ToolValidationError(f"{name} must be a positive integer")
    return value


class MarketToolRegistry:
    """Read-only tool registry with strict argument validation."""

    def __init__(self, db_path: str = "./warehouse/market.duckdb", allowed_scopes: set[tuple[str, int]] | None = None) -> None:
        self.db_path = db_path
        # None means unrestricted local development. An empty set is an
        # intentional deny-all scope for production misconfiguration safety.
        self.allowed_scopes = allowed_scopes
        self._tools = {
            "get_product_snapshot": Tool(
                "get_product_snapshot", "Get the latest observable product snapshot.",
                {"type": "object", "properties": {"country_code": {"type": "string"}, "shop_id": {"type": "integer"}, "item_id": {"type": "integer"}}, "required": ["country_code", "shop_id", "item_id"], "additionalProperties": False},
                self.get_product_snapshot,
            ),
            "get_market_signals": Tool(
                "get_market_signals", "Get the latest market signal and peer evidence for one SKU.",
                {"type": "object", "properties": {"country_code": {"type": "string"}, "shop_id": {"type": "integer"}, "item_id": {"type": "integer"}}, "required": ["country_code", "shop_id", "item_id"], "additionalProperties": False},
                self.get_market_signals,
            ),
            "get_peers": Tool(
                "get_peers", "Get matched peer products with score and relation.",
                {"type": "object", "properties": {"country_code": {"type": "string"}, "shop_id": {"type": "integer"}, "item_id": {"type": "integer"}, "limit": {"type": "integer", "minimum": 1, "maximum": 10}}, "required": ["country_code", "shop_id", "item_id"], "additionalProperties": False},
                self.get_peers,
            ),
            "get_competitor_alerts": Tool(
                "get_competitor_alerts", "Get recent competitor alerts for one SKU.",
                {"type": "object", "properties": {"country_code": {"type": "string"}, "shop_id": {"type": "integer"}, "item_id": {"type": "integer"}, "limit": {"type": "integer", "minimum": 1, "maximum": 20}}, "required": ["country_code", "shop_id", "item_id"], "additionalProperties": False},
                self.get_competitor_alerts,
            ),
            "get_recommendation": Tool(
                "get_recommendation", "Get the latest rule-based recommendation card for one SKU.",
                {"type": "object", "properties": {"country_code": {"type": "string"}, "shop_id": {"type": "integer"}, "item_id": {"type": "integer"}}, "required": ["country_code", "shop_id", "item_id"], "additionalProperties": False},
                self.get_recommendation,
            ),
            "search_products": Tool(
                "search_products", "Search product names within one country; never execute arbitrary SQL.",
                {"type": "object", "properties": {"country_code": {"type": "string"}, "query": {"type": "string", "minLength": 2}, "limit": {"type": "integer", "minimum": 1, "maximum": 10}}, "required": ["country_code", "query"], "additionalProperties": False},
                self.search_products,
            ),
        }

    def definitions(self) -> list[dict[str, Any]]:
        return [tool.schema() for tool in self._tools.values()]

    def execute(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        tool = self._tools.get(name)
        if tool is None:
            raise ToolValidationError("tool is not allow-listed")
        if not isinstance(args, dict):
            raise ToolValidationError("tool arguments must be an object")
        properties = tool.parameters.get("properties", {})
        required = set(tool.parameters.get("required", []))
        unknown = set(args) - set(properties)
        missing = required - set(args)
        if unknown:
            raise ToolValidationError(f"unknown arguments: {sorted(unknown)}")
        if missing:
            raise ToolValidationError(f"missing arguments: {sorted(missing)}")
        for key, schema in properties.items():
            if key not in args:
                continue
            expected = schema.get("type")
            value = args[key]
            if expected == "integer" and (isinstance(value, bool) or not isinstance(value, int)):
                raise ToolValidationError(f"{key} must be an integer")
            if expected == "string" and not isinstance(value, str):
                raise ToolValidationError(f"{key} must be a string")
        if name != "search_products":
            country = _country(args)
            shop_id = _positive_int(args, "shop_id")
            if self.allowed_scopes is not None and (country, shop_id) not in self.allowed_scopes:
                raise ToolValidationError("shop is outside the authenticated tenant scope")
        elif self.allowed_scopes is not None:
            country = _country(args)
            if not any(scope_country == country for scope_country, _ in self.allowed_scopes):
                raise ToolValidationError("country is outside the authenticated tenant scope")
        return tool.handler(args)

    def _query(
        self,
        sql: str,
        params: list[Any],
        stage: str | None = None,
        count_sql: str | None = None,
        count_params: list[Any] | None = None,
    ) -> dict[str, Any]:
        try:
            with duckdb.connect(self.db_path, read_only=True) as conn:
                publication = latest_successful_run(conn, stage) if stage else None
                if stage and publication is None:
                    return {"ok": False, "error": "stage_not_published", "stage": stage}
                cursor = conn.execute(sql, params)
                rows = _rows(cursor)
                total_count = None
                if count_sql:
                    total_count = int(conn.execute(count_sql, count_params if count_params is not None else params).fetchone()[0])
                return {
                    "ok": True,
                    "rows": rows,
                    "count": cursor.rowcount if cursor.rowcount >= 0 else None,
                    "total_count": total_count,
                    "published_run_id": publication["run_id"] if publication else None,
                }
        except (duckdb.Error, OSError) as exc:
            return {"ok": False, "error": "data_unavailable", "detail": str(exc)[:200]}

    def get_product_snapshot(self, args: dict[str, Any]) -> dict[str, Any]:
        country = _country(args)
        shop_id, item_id = _positive_int(args, "shop_id"), _positive_int(args, "item_id")
        return self._query("""
            SELECT p.country_code,p.currency,p.snapshot_date,p.shop_id,p.item_id,p.shop_name,
                   p.product_name,p.brand,p.price,p.price_original,p.discount_percent,
                   p.monthly_sold_value,p.rating,p.rating_count,p.liked_count,p.is_sold_out,
                   pa.product_type,pa.weight_g,pa.volume_ml,pa.quantity,pa.bundle_count,
                   pa.is_bundle,pa.total_weight_g,pa.total_volume_ml,pa.package_ambiguous,
                   pa.variation_count,pa.price_variant_ambiguous,
                   pa.variant_signature,pa.family_signature,pa.company_id,pa.company_name,
                   pa.seller_entity_id,pa.seller_entity_name
            FROM products p
            LEFT JOIN product_attributes pa ON pa.country_code=p.country_code
                                           AND pa.shop_id=p.shop_id AND pa.item_id=p.item_id
            WHERE p.country_code=? AND p.shop_id=? AND p.item_id=?
            ORDER BY p.snapshot_date DESC LIMIT 1
        """, [country, shop_id, item_id], "data_foundation")

    def list_products(self, args: dict[str, Any]) -> dict[str, Any]:
        """Read-only product catalogue endpoint used by the API/overview UI."""
        country = _country(args)
        limit = self._bounded_limit(args.get("limit", 20), 100)
        query = str(args.get("query", "") or "").strip()
        if len(query) > 120:
            raise ToolValidationError("query must be <= 120 characters")
        conditions = ["p.country_code=?"]
        params: list[Any] = [country]
        if args.get("shop_id") is not None:
            shop_id = _positive_int(args, "shop_id")
            conditions.append("p.shop_id=?")
            params.append(shop_id)
            if self.allowed_scopes is not None and (country, shop_id) not in self.allowed_scopes:
                raise ToolValidationError("shop is outside the authenticated tenant scope")
        elif self.allowed_scopes is not None:
            scoped_shops = [shop_id for scope_country, shop_id in self.allowed_scopes if scope_country == country]
            if not scoped_shops:
                raise ToolValidationError("country is outside the authenticated tenant scope")
            conditions.append(f"p.shop_id IN ({','.join('?' for _ in scoped_shops)})")
            params.extend(scoped_shops)
        company_id = str(args.get("company_id", "") or "").strip()
        if company_id:
            if len(company_id) > 80:
                raise ToolValidationError("company_id must be <= 80 characters")
            conditions.append("pa.company_id=?")
            params.append(company_id)
        if query:
            conditions.append("p.product_name ILIKE ?")
            params.append(f"%{query}%")
        params.append(limit)
        base_conditions = " AND ".join(conditions)
        count_sql = f"""
            SELECT COUNT(*) FROM (
                SELECT p.country_code,p.shop_id,p.item_id
                FROM products p
                LEFT JOIN product_attributes pa ON pa.country_code=p.country_code
                                               AND pa.shop_id=p.shop_id AND pa.item_id=p.item_id
                WHERE {base_conditions}
                QUALIFY ROW_NUMBER() OVER (
                    PARTITION BY p.country_code,p.shop_id,p.item_id ORDER BY p.snapshot_date DESC
                ) = 1
            ) latest_products
        """
        return self._query(f"""
            SELECT p.country_code,p.currency,p.snapshot_date,p.shop_id,p.item_id,p.shop_name,
                   p.product_name,p.brand,p.price,p.price_original,p.discount_percent,
                   p.monthly_sold_value,p.rating,p.rating_count,p.liked_count,p.is_sold_out,
                   p.image_url,p.url,pa.company_id,pa.company_name,
                   pa.seller_entity_id,pa.seller_entity_name,pa.family_signature,
                   pa.variant_signature,pa.weight_g,pa.volume_ml,pa.quantity,pa.bundle_count,
                   pa.is_bundle,pa.total_weight_g,pa.total_volume_ml,pa.package_ambiguous,
                   pa.variation_count,pa.price_variant_ambiguous
            FROM products p
            LEFT JOIN product_attributes pa ON pa.country_code=p.country_code
                                           AND pa.shop_id=p.shop_id AND pa.item_id=p.item_id
            WHERE {base_conditions}
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY p.country_code,p.shop_id,p.item_id ORDER BY p.snapshot_date DESC
            ) = 1
            ORDER BY p.snapshot_date DESC, p.monthly_sold_value DESC NULLS LAST
            LIMIT ?
        """, params, "product_matching", count_sql, params[:-1])

    def list_companies(self, args: dict[str, Any]) -> dict[str, Any]:
        country = _country(args)
        conditions = ["pa.country_code=?"]
        params: list[Any] = [country]
        if self.allowed_scopes is not None:
            scoped_shops = [shop_id for scope_country, shop_id in self.allowed_scopes if scope_country == country]
            if not scoped_shops:
                raise ToolValidationError("country is outside the authenticated tenant scope")
            conditions.append(f"pa.shop_id IN ({','.join('?' for _ in scoped_shops)})")
            params.extend(scoped_shops)
        return self._query(f"""
            SELECT pa.country_code,pa.company_id,pa.company_name,
                   COUNT(DISTINCT (pa.shop_id,pa.item_id)) AS sku_count,
                   LIST(DISTINCT pa.shop_id ORDER BY pa.shop_id) AS shop_ids,
                   LIST(DISTINCT pa.seller_entity_name ORDER BY pa.seller_entity_name) AS distributor_names
            FROM product_attributes pa
            WHERE {' AND '.join(conditions)}
            GROUP BY 1,2,3 ORDER BY sku_count DESC,company_name
        """, params, "product_matching")

    def list_alerts(self, args: dict[str, Any]) -> dict[str, Any]:
        """Latest actionable alerts across a tenant, for the control tower."""
        country = _country(args)
        limit = self._bounded_limit(args.get("limit", 50), 100)
        conditions = ["a.country_code=?"]
        params: list[Any] = [country]
        if args.get("shop_id") is not None:
            shop_id = _positive_int(args, "shop_id")
            if self.allowed_scopes is not None and (country, shop_id) not in self.allowed_scopes:
                raise ToolValidationError("shop is outside the authenticated tenant scope")
            conditions.append("a.source_shop_id=?")
            params.append(shop_id)
        elif self.allowed_scopes is not None:
            scoped_shops = [shop_id for scope_country, shop_id in self.allowed_scopes if scope_country == country]
            if not scoped_shops:
                raise ToolValidationError("country is outside the authenticated tenant scope")
            conditions.append(f"a.source_shop_id IN ({','.join('?' for _ in scoped_shops)})")
            params.extend(scoped_shops)
        company_id = str(args.get("company_id", "") or "").strip()
        if company_id:
            conditions.append("pa.company_id=?")
            params.append(company_id)
        if args.get("severity"):
            severity = str(args["severity"]).lower().strip()
            if severity not in {"low", "medium", "high"}:
                raise ToolValidationError("severity must be low, medium or high")
            conditions.append("a.severity=?")
            params.append(severity)
        base_conditions = " AND ".join(conditions)
        base_conditions += """ AND a.snapshot_date = (
            SELECT MAX(ms.snapshot_date) FROM market_signals ms
            WHERE ms.country_code=a.country_code
              AND ms.source_shop_id=a.source_shop_id
              AND ms.source_item_id=a.source_item_id
        )"""
        latest_sql = f"""
            SELECT a.country_code,a.snapshot_date,a.source_shop_id,a.source_item_id,
                   a.alert_type,a.severity,a.metric_name,a.metric_value,a.threshold,
                   a.target_shop_id,a.target_item_id,a.evidence,a.model_version,
                   pa.company_id,pa.company_name,pa.seller_entity_id,pa.seller_entity_name,
                   tpa.company_id AS target_company_id,
                   tpa.company_name AS target_company_name,
                   tpa.seller_entity_id AS target_seller_entity_id,
                   tpa.seller_entity_name AS target_seller_entity_name
            FROM competitor_alerts a
            LEFT JOIN product_attributes pa ON pa.country_code=a.country_code
                                           AND pa.shop_id=a.source_shop_id
                                           AND pa.item_id=a.source_item_id
            LEFT JOIN product_attributes tpa ON tpa.country_code=a.country_code
                                            AND tpa.shop_id=a.target_shop_id
                                            AND tpa.item_id=a.target_item_id
            WHERE {base_conditions}
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY a.source_shop_id,a.source_item_id,a.alert_type,a.metric_name
                ORDER BY a.snapshot_date DESC
            ) = 1
        """
        params.append(limit)
        return self._query(f"""
            SELECT * FROM ({latest_sql}) latest_alerts
            ORDER BY snapshot_date DESC,
                     CASE severity WHEN 'high' THEN 3 WHEN 'medium' THEN 2 ELSE 1 END DESC
            LIMIT ?
        """, params, "market_signals",
        f"SELECT COUNT(*) FROM ({latest_sql}) latest_alerts", params[:-1])

    def list_recommendations(self, args: dict[str, Any]) -> dict[str, Any]:
        """Latest recommendations across a tenant, for review workflows."""
        country = _country(args)
        limit = self._bounded_limit(args.get("limit", 50), 100)
        conditions = ["r.country_code=?"]
        params: list[Any] = [country]
        if args.get("shop_id") is not None:
            shop_id = _positive_int(args, "shop_id")
            if self.allowed_scopes is not None and (country, shop_id) not in self.allowed_scopes:
                raise ToolValidationError("shop is outside the authenticated tenant scope")
            conditions.append("r.source_shop_id=?")
            params.append(shop_id)
        elif self.allowed_scopes is not None:
            scoped_shops = [shop_id for scope_country, shop_id in self.allowed_scopes if scope_country == country]
            if not scoped_shops:
                raise ToolValidationError("country is outside the authenticated tenant scope")
            conditions.append(f"r.source_shop_id IN ({','.join('?' for _ in scoped_shops)})")
            params.extend(scoped_shops)
        company_id = str(args.get("company_id", "") or "").strip()
        if company_id:
            conditions.append("pa.company_id=?")
            params.append(company_id)
        recommendation_status = str(args.get("recommendation_status", "") or "").lower().strip()
        allowed_statuses = {
            "recommended",
            "scenario_only",
            "monitoring_only",
            "needs_cost_validation",
            "needs_promotion_validation",
            "constraint_blocked",
            "insufficient_evidence",
        }
        if recommendation_status and recommendation_status not in allowed_statuses:
            raise ToolValidationError("recommendation_status is invalid")
        base_conditions = " AND ".join(conditions)
        status_clause = "WHERE recommendation_status=?" if recommendation_status else ""
        status_params: list[Any] = [recommendation_status] if recommendation_status else []
        params.append(limit)
        latest_sql = f"""
            SELECT r.country_code,r.snapshot_date,r.source_shop_id,r.source_item_id,
                   r.currency,r.recommendation_status,r.action,r.priority,r.confidence,
                   r.source_price,r.market_reference_price,r.recommended_price,
                   r.recommended_discount_percent,r.price_floor,r.cost_value,r.margin_min_pct,
                   r.estimated_margin_pct,
                   r.constraint_status,r.reason_codes,r.recommendation_text,r.evidence,
                   r.rule_version,pa.company_id,pa.company_name,
                   pa.seller_entity_id,pa.seller_entity_name
            FROM recommendations r
            LEFT JOIN product_attributes pa ON pa.country_code=r.country_code
                                           AND pa.shop_id=r.source_shop_id
                                           AND pa.item_id=r.source_item_id
            WHERE {base_conditions}
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY r.source_shop_id,r.source_item_id ORDER BY r.snapshot_date DESC
            ) = 1
        """
        count_sql = f"""
            SELECT COUNT(*) FROM ({latest_sql}) latest_recommendations
            {status_clause}
        """
        query_params = [*params[:-1], *status_params, limit]
        return self._query(f"""
            SELECT * FROM ({latest_sql}) latest_recommendations
            {status_clause}
            ORDER BY snapshot_date DESC,
                     CASE priority WHEN 'high' THEN 3 WHEN 'medium' THEN 2 ELSE 1 END DESC
            LIMIT ?
        """, query_params, "recommendations", count_sql, [*params[:-1], *status_params])

    def get_market_signals(self, args: dict[str, Any]) -> dict[str, Any]:
        country = _country(args)
        shop_id, item_id = _positive_int(args, "shop_id"), _positive_int(args, "item_id")
        return self._query("""
            SELECT * EXCLUDE(created_at)
            FROM market_signals WHERE country_code=? AND source_shop_id=? AND source_item_id=?
            ORDER BY snapshot_date DESC LIMIT 1
        """, [country, shop_id, item_id], "market_signals")

    def get_peers(self, args: dict[str, Any]) -> dict[str, Any]:
        country = _country(args)
        shop_id, item_id = _positive_int(args, "shop_id"), _positive_int(args, "item_id")
        limit = self._bounded_limit(args.get("limit", 5), 10)
        return self._query("""
            SELECT pg.peer_rank,pg.target_shop_id,pg.target_item_id,pg.relation,
                   pg.match_score,pg.confidence,p.product_name,p.brand,p.price,p.currency,
                   pa.product_type,pa.weight_g,pa.volume_ml,pa.quantity,pa.bundle_count,
                   pa.is_bundle,pa.total_weight_g,pa.total_volume_ml,pa.package_ambiguous,
                   pa.variation_count,pa.price_variant_ambiguous,
                   pa.variant_signature,pa.family_signature,pa.company_id,pa.company_name,
                   pa.seller_entity_id,pa.seller_entity_name,
                   pg.model_version
            FROM peer_groups pg
            LEFT JOIN (
                SELECT * FROM products
                QUALIFY ROW_NUMBER() OVER (
                    PARTITION BY country_code,shop_id,item_id ORDER BY snapshot_date DESC
                ) = 1
            ) p ON p.country_code=pg.country_code
                AND p.shop_id=pg.target_shop_id AND p.item_id=pg.target_item_id
            LEFT JOIN product_attributes pa ON pa.country_code=pg.country_code
                                           AND pa.shop_id=pg.target_shop_id
                                           AND pa.item_id=pg.target_item_id
            WHERE pg.country_code=? AND pg.source_shop_id=? AND pg.source_item_id=?
              AND pg.peer_status='peer_found'
            ORDER BY pg.peer_rank LIMIT ?
        """, [country, shop_id, item_id, limit], "product_matching")

    def get_competitor_alerts(self, args: dict[str, Any]) -> dict[str, Any]:
        country = _country(args)
        shop_id, item_id = _positive_int(args, "shop_id"), _positive_int(args, "item_id")
        limit = self._bounded_limit(args.get("limit", 10), 20)
        return self._query("""
            SELECT snapshot_date,alert_type,severity,metric_name,metric_value,
                   threshold,target_shop_id,target_item_id,evidence
            FROM competitor_alerts a
            WHERE country_code=? AND source_shop_id=? AND source_item_id=?
              AND snapshot_date = (
                  SELECT MAX(ms.snapshot_date) FROM market_signals ms
                  WHERE ms.country_code=a.country_code
                    AND ms.source_shop_id=a.source_shop_id
                    AND ms.source_item_id=a.source_item_id
              )
            ORDER BY snapshot_date DESC, severity DESC LIMIT ?
        """, [country, shop_id, item_id, limit], "market_signals")

    def get_recommendation(self, args: dict[str, Any]) -> dict[str, Any]:
        country = _country(args)
        shop_id, item_id = _positive_int(args, "shop_id"), _positive_int(args, "item_id")
        return self._query("""
            SELECT * EXCLUDE(created_at)
            FROM recommendations WHERE country_code=? AND source_shop_id=? AND source_item_id=?
            ORDER BY snapshot_date DESC LIMIT 1
        """, [country, shop_id, item_id], "recommendations")

    def search_products(self, args: dict[str, Any]) -> dict[str, Any]:
        country = _country(args)
        query = str(args.get("query", "")).strip()
        if len(query) < 2 or len(query) > 120:
            raise ToolValidationError("query must be between 2 and 120 characters")
        limit = self._bounded_limit(args.get("limit", 10), 10)
        scope_clause = ""
        scope_params: list[Any] = []
        if self.allowed_scopes is not None:
            scoped_shops = [shop_id for scope_country, shop_id in self.allowed_scopes if scope_country == country]
            if not scoped_shops:
                raise ToolValidationError("country is outside the authenticated tenant scope")
            scope_clause = f" AND shop_id IN ({','.join('?' for _ in scoped_shops)})"
            scope_params = scoped_shops
        return self._query("""
            SELECT country_code,currency,snapshot_date,shop_id,item_id,shop_name,
                   product_name,brand,price,discount_percent
            FROM products WHERE country_code=? AND product_name ILIKE ?
        """ + scope_clause + """
            QUALIFY ROW_NUMBER() OVER (PARTITION BY country_code,shop_id,item_id ORDER BY snapshot_date DESC)=1
            ORDER BY shop_id,item_id LIMIT ?
        """, [country, f"%{query}%", *scope_params, limit], "data_foundation")

    @staticmethod
    def _bounded_limit(value: Any, maximum: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ToolValidationError("limit must be an integer")
        if value < 1 or value > maximum:
            raise ToolValidationError(f"limit must be between 1 and {maximum}")
        return value
