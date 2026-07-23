"""Dependency-free HTTP wrapper for the agent harness (development/API MVP)."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from .agent import AgentConfig, AgentHarness, AgentRequest
from .agent_tools import MarketToolRegistry


def parse_scope(value: str | None) -> set[tuple[str, int]]:
    scopes: set[tuple[str, int]] = set()
    for token in (value or "").split(","):
        token = token.strip()
        if not token:
            continue
        try:
            country, shop_id = token.split(":", 1)
            country = country.strip().lower()
            shop = int(shop_id)
            if country not in {"vn", "id"} or shop <= 0:
                raise ValueError
            scopes.add((country, shop))
        except ValueError as exc:
            raise ValueError("AGENT_SHOP_SCOPE must use country:shop_id,country:shop_id") from exc
    return scopes


class RateLimiter:
    def __init__(self, limit: int = 60, window_seconds: int = 60) -> None:
        self.limit = max(1, limit)
        self.window_seconds = max(1, window_seconds)
        self.events: dict[str, deque[float]] = defaultdict(deque)
        self.lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self.lock:
            events = self.events[key]
            while events and now - events[0] > self.window_seconds:
                events.popleft()
            if len(events) >= self.limit:
                return False
            events.append(now)
            return True


class AgentHandler(BaseHTTPRequestHandler):
    harness: AgentHarness | None = None
    api_token: str | None = None
    production = False
    rate_limiter = RateLimiter()
    max_body_bytes = 128 * 1024

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        origin = self.headers.get("Origin")
        allowed_origin = os.getenv("AGENT_CORS_ORIGIN", "http://localhost:5173")
        if origin and origin == allowed_origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _path_query(self) -> tuple[str, dict[str, str]]:
        parsed = urlparse(self.path)
        query = {key: values[-1] for key, values in parse_qs(parsed.query).items() if values}
        return parsed.path.rstrip("/") or "/", query

    def _api_auth(self) -> bool:
        if not self._authorized():
            self._json(401, {"ok": False, "error": "unauthorized"})
            return False
        if not self.rate_limiter.allow(self.client_address[0]):
            self._json(429, {"ok": False, "error": "rate_limit_exceeded"})
            return False
        return True

    @staticmethod
    def _int_query(query: dict[str, str], key: str, required: bool = True) -> int | None:
        value = query.get(key)
        if value is None and not required:
            return None
        try:
            parsed = int(value or "")
        except ValueError as exc:
            raise ValueError(f"{key} must be a positive integer") from exc
        if parsed <= 0:
            raise ValueError(f"{key} must be a positive integer")
        return parsed

    def _api_result(self, result: dict[str, Any], many: bool = True) -> None:
        if not result.get("ok"):
            error = result.get("error", "data_unavailable")
            status = 503 if error == "stage_not_published" or error == "data_unavailable" else 400
            self._json(status, {"ok": False, "error": error, "detail": result.get("detail")})
            return
        rows = result.get("rows", [])
        data: Any = rows if many else (rows[0] if rows else None)
        if not many and data is None:
            self._json(404, {"ok": False, "error": "not_found", "data": None})
            return
        self._json(200, {
            "ok": True,
            "data": data,
            "meta": {
                "count": len(rows),
                "total_count": result.get("total_count", len(rows)),
                "published_run_id": result.get("published_run_id"),
            },
        })

    def _api_get(self, path: str, query: dict[str, str]) -> None:
        """Handle read-only v1 resources. IDs are item IDs; country/shop disambiguate them."""
        if path == "/api/v1/companies":
            country = (query.get("country_code") or "").lower().strip()
            if country not in {"vn", "id"}:
                raise ValueError("country_code must be vn or id")
            self._api_result(self.harness.registry.list_companies({"country_code": country}))  # type: ignore[union-attr]
            return
        if path == "/api/v1/products":
            country = (query.get("country_code") or "").lower().strip()
            if country not in {"vn", "id"}:
                raise ValueError("country_code must be vn or id")
            args: dict[str, Any] = {"country_code": country, "limit": int(query.get("limit", "20"))}
            if query.get("shop_id"):
                args["shop_id"] = self._int_query(query, "shop_id")
            if query.get("query"):
                args["query"] = query["query"]
            if query.get("company_id"):
                args["company_id"] = query["company_id"]
            self._api_result(self.harness.registry.list_products(args))  # type: ignore[union-attr]
            return
        if path in {"/api/v1/alerts", "/api/v1/recommendations"}:
            country = (query.get("country_code") or "").lower().strip()
            if country not in {"vn", "id"}:
                raise ValueError("country_code must be vn or id")
            args: dict[str, Any] = {"country_code": country, "limit": int(query.get("limit", "50"))}
            if query.get("shop_id"):
                args["shop_id"] = self._int_query(query, "shop_id")
            if query.get("severity"):
                args["severity"] = query["severity"]
            if query.get("company_id"):
                args["company_id"] = query["company_id"]
            if path.endswith("/recommendations") and query.get("recommendation_status"):
                args["recommendation_status"] = query["recommendation_status"]
            registry = self.harness.registry  # type: ignore[union-attr]
            result = registry.list_alerts(args) if path.endswith("/alerts") else registry.list_recommendations(args)
            self._api_result(result)
            return

        parts = path.split("/")
        if len(parts) not in {5, 6} or parts[:4] != ["", "api", "v1", "products"]:
            self._json(404, {"ok": False, "error": "not_found"})
            return
        try:
            item_id = int(parts[4])
        except ValueError as exc:
            raise ValueError("product id must be a positive integer") from exc
        if item_id <= 0:
            raise ValueError("product id must be a positive integer")
        country = (query.get("country_code") or "").lower().strip()
        if country not in {"vn", "id"}:
            raise ValueError("country_code must be vn or id")
        shop_id = self._int_query(query, "shop_id")
        args = {"country_code": country, "shop_id": shop_id, "item_id": item_id}
        resource = parts[5] if len(parts) == 6 else None
        if resource is None:
            self._api_result(self.harness.registry.get_product_snapshot(args), many=False)  # type: ignore[union-attr]
        elif resource == "peers":
            args["limit"] = int(query.get("limit", "5"))
            self._api_result(self.harness.registry.get_peers(args))  # type: ignore[union-attr]
        elif resource == "signals":
            self._api_result(self.harness.registry.get_market_signals(args), many=False)  # type: ignore[union-attr]
        elif resource == "alerts":
            args["limit"] = int(query.get("limit", "10"))
            self._api_result(self.harness.registry.get_competitor_alerts(args))  # type: ignore[union-attr]
        elif resource == "recommendation":
            self._api_result(self.harness.registry.get_recommendation(args), many=False)  # type: ignore[union-attr]
        else:
            self._json(404, {"ok": False, "error": "not_found"})

    def _authorized(self) -> bool:
        if not self.api_token:
            return not self.production
        header = self.headers.get("Authorization", "")
        return header == f"Bearer {self.api_token}"

    def do_GET(self) -> None:  # noqa: N802
        path, query = self._path_query()
        if path == "/health" or path == "/api/v1/health":
            configured = bool(self.harness and getattr(self.harness.client, "configured", False))
            ready = bool(self.harness) and (not self.production or (bool(self.api_token) and bool(getattr(self.harness.registry, "allowed_scopes", None))))
            self._json(200, {"ok": ready, "deepseek_configured": configured, "auth_configured": bool(self.api_token), "production": self.production})
            return
        if path.startswith("/api/v1/"):
            if not self._api_auth():
                return
            try:
                self._api_get(path, query)
            except (TypeError, ValueError) as exc:
                self._json(400, {"ok": False, "error": "invalid_request", "detail": str(exc)[:200]})
            return
        self._json(404, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        path, _ = self._path_query()
        if path not in {"/chat", "/api/v1/chat"}:
            self._json(404, {"ok": False, "error": "not_found"})
            return
        if not self._api_auth():
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0
        if content_length <= 0 or content_length > self.max_body_bytes:
            self._json(413, {"ok": False, "error": "request_body_too_large_or_empty"})
            return
        try:
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
            message = str(payload.get("message", "")).strip()
            if not message or len(message) > 12000:
                raise ValueError("message is required and must be <= 12000 characters")
            request = AgentRequest(
                message=message,
                user_id=str(payload.get("user_id", "anonymous"))[:120],
                session_id=str(payload.get("session_id") or "")[:120] or uuid.uuid4().hex,
                country_code=payload.get("country_code"),
                shop_id=payload.get("shop_id"),
                item_id=payload.get("item_id"),
            )
            result = self.harness.handle(request)  # type: ignore[union-attr]
            self._json(200, result)
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError) as exc:
            self._json(400, {"ok": False, "error": "invalid_request", "detail": str(exc)[:200]})

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", os.getenv("AGENT_CORS_ORIGIN", "http://localhost:5173"))
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        # Do not log request bodies or authorization headers.
        return


def main() -> None:
    host = os.getenv("AGENT_HOST", "0.0.0.0")
    port = int(os.getenv("AGENT_PORT", "8080"))
    production = os.getenv("AGENT_ENV", "development").lower() == "production"
    api_token = os.getenv("AGENT_API_TOKEN") or None
    scopes = parse_scope(os.getenv("AGENT_SHOP_SCOPE"))
    if production and (not api_token or not scopes):
        raise SystemExit("Production agent requires AGENT_API_TOKEN and AGENT_SHOP_SCOPE")
    config = AgentConfig(
        db_path=os.getenv("DB_PATH", "./warehouse/market.duckdb"),
        memory_path=os.getenv("MEMORY_PATH", "./warehouse/agent_memory.sqlite"),
    )
    registry = MarketToolRegistry(config.db_path, scopes if production else (scopes or None))
    AgentHandler.harness = AgentHarness(config=config, registry=registry)
    AgentHandler.api_token = api_token
    AgentHandler.production = production
    # A dashboard refresh fans out to several read-only endpoints. Keep the
    # production default conservative, but do not make local development fail
    # after a handful of refreshes. Both remain explicitly configurable.
    default_rate_limit = "60" if production else "600"
    AgentHandler.rate_limiter = RateLimiter(int(os.getenv("AGENT_RATE_LIMIT", default_rate_limit)), 60)
    server = ThreadingHTTPServer((host, port), AgentHandler)
    print(json.dumps({"listening": f"{host}:{port}", "auth_configured": bool(AgentHandler.api_token)}))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
