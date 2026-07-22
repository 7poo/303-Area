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
            SELECT country_code,currency,snapshot_date,shop_id,item_id,shop_name,
                   product_name,brand,price,price_original,discount_percent,
                   monthly_sold_value,rating,rating_count,liked_count,is_sold_out
            FROM products WHERE country_code=? AND shop_id=? AND item_id=?
            ORDER BY snapshot_date DESC LIMIT 1
        """, [country, shop_id, item_id], "data_foundation")

    def list_products(self, args: dict[str, Any]) -> dict[str, Any]:
        """Read-only product catalogue endpoint used by the API/overview UI."""
        country = _country(args)
        limit = self._bounded_limit(args.get("limit", 20), 100)
        query = str(args.get("query", "") or "").strip()
        if len(query) > 120:
            raise ToolValidationError("query must be <= 120 characters")
        conditions = ["country_code=?"]
        params: list[Any] = [country]
        if args.get("shop_id") is not None:
            shop_id = _positive_int(args, "shop_id")
            conditions.append("shop_id=?")
            params.append(shop_id)
            if self.allowed_scopes is not None and (country, shop_id) not in self.allowed_scopes:
                raise ToolValidationError("shop is outside the authenticated tenant scope")
        elif self.allowed_scopes is not None:
            scoped_shops = [shop_id for scope_country, shop_id in self.allowed_scopes if scope_country == country]
            if not scoped_shops:
                raise ToolValidationError("country is outside the authenticated tenant scope")
            conditions.append(f"shop_id IN ({','.join('?' for _ in scoped_shops)})")
            params.extend(scoped_shops)
        if query:
            conditions.append("product_name ILIKE ?")
            params.append(f"%{query}%")
        params.append(limit)
        base_conditions = " AND ".join(conditions)
        count_sql = f"""
            SELECT COUNT(*) FROM (
                SELECT country_code,shop_id,item_id
                FROM products
                WHERE {base_conditions}
                QUALIFY ROW_NUMBER() OVER (
                    PARTITION BY country_code,shop_id,item_id ORDER BY snapshot_date DESC
                ) = 1
            ) latest_products
        """
        return self._query(f"""
            SELECT country_code,currency,snapshot_date,shop_id,item_id,shop_name,
                   product_name,brand,price,price_original,discount_percent,
                   monthly_sold_value,rating,rating_count,liked_count,is_sold_out,
                   image_url,url
            FROM products
            WHERE {base_conditions}
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY country_code,shop_id,item_id ORDER BY snapshot_date DESC
            ) = 1
            ORDER BY snapshot_date DESC, monthly_sold_value DESC NULLS LAST
            LIMIT ?
        """, params, "data_foundation", count_sql, params[:-1])

    def list_alerts(self, args: dict[str, Any]) -> dict[str, Any]:
        """Latest actionable alerts across a tenant, for the control tower."""
        country = _country(args)
        limit = self._bounded_limit(args.get("limit", 50), 100)
        conditions = ["country_code=?"]
        params: list[Any] = [country]
        if args.get("shop_id") is not None:
            shop_id = _positive_int(args, "shop_id")
            if self.allowed_scopes is not None and (country, shop_id) not in self.allowed_scopes:
                raise ToolValidationError("shop is outside the authenticated tenant scope")
            conditions.append("source_shop_id=?")
            params.append(shop_id)
        elif self.allowed_scopes is not None:
            scoped_shops = [shop_id for scope_country, shop_id in self.allowed_scopes if scope_country == country]
            if not scoped_shops:
                raise ToolValidationError("country is outside the authenticated tenant scope")
            conditions.append(f"source_shop_id IN ({','.join('?' for _ in scoped_shops)})")
            params.extend(scoped_shops)
        if args.get("severity"):
            severity = str(args["severity"]).lower().strip()
            if severity not in {"low", "medium", "high"}:
                raise ToolValidationError("severity must be low, medium or high")
            conditions.append("severity=?")
            params.append(severity)
        params.append(limit)
        return self._query(f"""
            SELECT country_code,snapshot_date,source_shop_id,source_item_id,
                   alert_type,severity,metric_name,metric_value,threshold,
                   target_shop_id,target_item_id,evidence,model_version
            FROM competitor_alerts
            WHERE {' AND '.join(conditions)}
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY source_shop_id,source_item_id,alert_type,metric_name
                ORDER BY snapshot_date DESC
            ) = 1
            ORDER BY snapshot_date DESC,
                     CASE severity WHEN 'high' THEN 3 WHEN 'medium' THEN 2 ELSE 1 END DESC
            LIMIT ?
        """, params, "market_signals")

    def list_recommendations(self, args: dict[str, Any]) -> dict[str, Any]:
        """Latest recommendations across a tenant, for review workflows."""
        country = _country(args)
        limit = self._bounded_limit(args.get("limit", 50), 100)
        conditions = ["country_code=?"]
        params: list[Any] = [country]
        if args.get("shop_id") is not None:
            shop_id = _positive_int(args, "shop_id")
            if self.allowed_scopes is not None and (country, shop_id) not in self.allowed_scopes:
                raise ToolValidationError("shop is outside the authenticated tenant scope")
            conditions.append("source_shop_id=?")
            params.append(shop_id)
        elif self.allowed_scopes is not None:
            scoped_shops = [shop_id for scope_country, shop_id in self.allowed_scopes if scope_country == country]
            if not scoped_shops:
                raise ToolValidationError("country is outside the authenticated tenant scope")
            conditions.append(f"source_shop_id IN ({','.join('?' for _ in scoped_shops)})")
            params.extend(scoped_shops)
        params.append(limit)
        return self._query(f"""
            SELECT country_code,snapshot_date,source_shop_id,source_item_id,
                   currency,recommendation_status,action,priority,confidence,
                   source_price,market_reference_price,recommended_price,
                   recommended_discount_percent,price_floor,estimated_margin_pct,
                   constraint_status,reason_codes,recommendation_text,evidence,
                   rule_version
            FROM recommendations
            WHERE {' AND '.join(conditions)}
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY source_shop_id,source_item_id
                ORDER BY snapshot_date DESC
            ) = 1
            ORDER BY snapshot_date DESC,
                     CASE priority WHEN 'high' THEN 3 WHEN 'medium' THEN 2 ELSE 1 END DESC
            LIMIT ?
        """, params, "recommendations")

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
                   pg.match_score,pg.confidence,p.product_name,p.brand,p.price,p.currency
            FROM peer_groups pg
            LEFT JOIN (
                SELECT * FROM products
                QUALIFY ROW_NUMBER() OVER (
                    PARTITION BY country_code,shop_id,item_id ORDER BY snapshot_date DESC
                ) = 1
            ) p ON p.country_code=pg.country_code
                AND p.shop_id=pg.target_shop_id AND p.item_id=pg.target_item_id
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
            FROM competitor_alerts WHERE country_code=? AND source_shop_id=? AND source_item_id=?
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
