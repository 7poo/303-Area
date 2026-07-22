"""Load the Shopee snapshots into a clean DuckDB warehouse.

The source files are partitioned by country, dataset and shop.  This script
keeps the source partition as metadata, normalizes the business fields, and
creates day-over-day promotion/price events for downstream features.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import duckdb

from .pipeline import ensure_manifest, finish_run, start_run


DATASETS = {
    "products",
    "shop_info",
    "category_list",
    "product_categories",
    "category_platform",
}


def scalar(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def integer(value: str | None) -> int | None:
    value = scalar(value)
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def number(value: str | None) -> float | None:
    value = scalar(value)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def boolean(value: str | None) -> bool | None:
    value = scalar(value)
    if value is None:
        return None
    return value.lower() in {"true", "1", "yes", "y", "t"}


def json_text(value: str | None, default: str | None = None) -> str | None:
    value = scalar(value)
    if value is None:
        return default
    try:
        json.loads(value)
        return value
    except json.JSONDecodeError:
        # Keep malformed source values inspectable instead of failing the load.
        return json.dumps(value, ensure_ascii=False)


def timestamp_from_epoch(value: str | None) -> datetime | None:
    value = number(value)
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc).replace(tzinfo=None)
    except (OverflowError, OSError, ValueError):
        return None


def normalized_name(value: str | None) -> str | None:
    value = scalar(value)
    if value is None:
        return None
    value = value.lower()
    value = re.sub(r"[^\w\s]", " ", value, flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip()


def source_metadata(path: Path) -> tuple[str, str, int | None]:
    parts = path.parts
    country = next((x.split("=", 1)[1] for x in parts if x.startswith("country_code=")), None)
    dataset = next((x.split("=", 1)[1] for x in parts if x.startswith("dataset=")), None)
    shop = next((x.split("=", 1)[1] for x in parts if x.startswith("shop_id=")), None)
    if not country or dataset not in DATASETS:
        raise ValueError(f"Cannot infer source partition from {path}")
    return country, dataset, integer(shop)


def read_rows(data_dir: Path) -> Iterable[tuple[str, str, int | None, Path, dict[str, str]]]:
    for path in sorted(data_dir.rglob("*.csv")):
        country, dataset, shop_id = source_metadata(path)
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                yield country, dataset, shop_id, path, row


def create_schema(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute("DROP TABLE IF EXISTS promotion_events")
    conn.execute("DROP TABLE IF EXISTS products")
    conn.execute("DROP TABLE IF EXISTS product_categories")
    conn.execute("DROP TABLE IF EXISTS shop_categories")
    conn.execute("DROP TABLE IF EXISTS platform_categories")
    conn.execute("DROP TABLE IF EXISTS shops")
    conn.execute("DROP TABLE IF EXISTS ingestion_quality")

    conn.execute("""
        CREATE TABLE products (
            country_code VARCHAR NOT NULL,
            currency VARCHAR NOT NULL,
            snapshot_date DATE NOT NULL,
            platform VARCHAR,
            shop_id BIGINT NOT NULL,
            shop_slug VARCHAR,
            shop_name VARCHAR,
            location VARCHAR,
            item_id BIGINT NOT NULL,
            product_name VARCHAR,
            product_name_normalized VARCHAR,
            url VARCHAR,
            image_url VARCHAR,
            images JSON,
            seller_flag JSON,
            seller_flag_hash JSON,
            image_overlay VARCHAR,
            image_overlay_hash VARCHAR,
            is_ad BOOLEAN,
            is_sold_out BOOLEAN,
            shopee_verified BOOLEAN,
            ctime TIMESTAMP,
            price BIGINT,
            price_original BIGINT,
            price_before_promo BIGINT,
            discount_percent DOUBLE,
            promotion_id VARCHAR,
            voucher_code VARCHAR,
            voucher_discount DOUBLE,
            voucher_start_time TIMESTAMP,
            voucher_end_time TIMESTAMP,
            voucher_min_spend DOUBLE,
            history_sold_value DOUBLE,
            monthly_sold_value DOUBLE,
            rating DOUBLE,
            rating_count BIGINT,
            rating_count_detail JSON,
            vouchers JSON,
            brand VARCHAR,
            brand_id VARCHAR,
            catid BIGINT,
            global_catids JSON,
            liked_count BIGINT,
            tier_variation_name VARCHAR,
            tier_variation_options JSON,
            source_file VARCHAR,
            PRIMARY KEY (country_code, shop_id, item_id, snapshot_date)
        )
    """)

    conn.execute("""
        CREATE TABLE shops (
            country_code VARCHAR NOT NULL,
            snapshot_date DATE NOT NULL,
            shop_id BIGINT NOT NULL,
            shop_name VARCHAR,
            username VARCHAR,
            rating_star DOUBLE,
            follower_count BIGINT,
            item_count BIGINT,
            is_official_shop BOOLEAN,
            response_rate DOUBLE,
            response_time DOUBLE,
            rating_good BIGINT,
            rating_normal BIGINT,
            rating_bad BIGINT,
            cancellation_rate DOUBLE,
            created_at TIMESTAMP,
            vacation BOOLEAN,
            source_file VARCHAR,
            PRIMARY KEY (country_code, shop_id, snapshot_date)
        )
    """)

    conn.execute("""
        CREATE TABLE shop_categories (
            country_code VARCHAR NOT NULL,
            snapshot_date DATE NOT NULL,
            shop_id BIGINT NOT NULL,
            shop_category_id BIGINT NOT NULL,
            display_name VARCHAR,
            total BIGINT,
            is_parent_category BOOLEAN,
            is_sub_category BOOLEAN,
            parent_shop_category_id BIGINT,
            image VARCHAR,
            category_type VARCHAR,
            source_file VARCHAR,
            PRIMARY KEY (country_code, shop_id, shop_category_id, snapshot_date)
        )
    """)

    conn.execute("""
        CREATE TABLE product_categories (
            country_code VARCHAR NOT NULL,
            snapshot_date DATE NOT NULL,
            shop_id BIGINT NOT NULL,
            item_id BIGINT NOT NULL,
            category_slug VARCHAR,
            category_id BIGINT NOT NULL,
            source_file VARCHAR,
            PRIMARY KEY (country_code, shop_id, item_id, category_id, snapshot_date)
        )
    """)

    conn.execute("""
        CREATE TABLE platform_categories (
            country_code VARCHAR NOT NULL,
            platform VARCHAR,
            client VARCHAR,
            category_key VARCHAR,
            category_id BIGINT NOT NULL,
            parent_category_id BIGINT,
            original_category_name VARCHAR,
            display_category_name VARCHAR,
            has_children BOOLEAN,
            debug_message VARCHAR,
            source_file VARCHAR,
            PRIMARY KEY (country_code, category_id)
        )
    """)

    conn.execute("""
        CREATE TABLE ingestion_quality (
            dataset VARCHAR NOT NULL,
            source_rows BIGINT NOT NULL,
            loaded_rows BIGINT NOT NULL,
            duplicate_rows BIGINT NOT NULL,
            null_price_rows BIGINT,
            invalid_price_rows BIGINT,
            outlier_price_rows BIGINT,
            generated_at TIMESTAMP NOT NULL
        )
    """)


def load_data(conn: duckdb.DuckDBPyConnection, data_dir: Path) -> dict[str, dict[str, int]]:
    buckets: dict[str, dict[tuple[Any, ...], tuple[Any, ...]]] = defaultdict(dict)
    source_counts: dict[str, int] = defaultdict(int)
    duplicate_counts: dict[str, int] = defaultdict(int)

    for country, dataset, partition_shop_id, path, row in read_rows(data_dir):
        source_counts[dataset] += 1
        date = scalar(row.get("date"))
        if dataset != "category_platform" and not date:
            raise ValueError(f"Missing date in {path}")
        shop_id = integer(row.get("shop_id")) or partition_shop_id

        if dataset == "products":
            item_id = integer(row.get("item_id"))
            key = (country, shop_id, item_id, date)
            values = (
                country, "VND" if country == "vn" else "IDR", date,
                scalar(row.get("platform")), shop_id, scalar(row.get("shop_slug")),
                scalar(row.get("shop_name")), scalar(row.get("location")), item_id,
                scalar(row.get("product_name")), normalized_name(row.get("product_name")),
                scalar(row.get("url")), scalar(row.get("image_url")), json_text(row.get("images"), "[]"),
                json_text(row.get("seller_flag"), "[]"), json_text(row.get("seller_flag_hash"), "[]"),
                scalar(row.get("image_overlay")), scalar(row.get("image_overlay_hash")),
                boolean(row.get("is_ad")), boolean(row.get("is_sold_out")), boolean(row.get("shopee_verified")),
                timestamp_from_epoch(row.get("ctime")), integer(row.get("price")), integer(row.get("price_original")),
                integer(row.get("price_before_promo")), number(row.get("discount_percent")), scalar(row.get("promotion_id")),
                scalar(row.get("voucher_code")), number(row.get("voucher_discount")), timestamp_from_epoch(row.get("voucher_start_time")),
                timestamp_from_epoch(row.get("voucher_end_time")), number(row.get("voucher_min_spend")), number(row.get("history_sold_value")),
                number(row.get("monthly_sold_value")), number(row.get("rating")), integer(row.get("rating_count")),
                json_text(row.get("rating_count_detail"), "[]"), json_text(row.get("vouchers"), "[]"), scalar(row.get("brand")),
                scalar(row.get("brand_id")), integer(row.get("catid")), json_text(row.get("global_catids"), "[]"),
                integer(row.get("liked_count")), scalar(row.get("tier_variation_name")),
                json_text(row.get("tier_variation_options"), "[]"), str(path),
            )
        elif dataset == "shop_info":
            key = (country, shop_id, date)
            values = (
                country, date, shop_id, scalar(row.get("shop_name")), scalar(row.get("username")), number(row.get("rating_star")),
                integer(row.get("follower_count")), integer(row.get("item_count")), boolean(row.get("is_official_shop")),
                number(row.get("response_rate")), number(row.get("response_time")), integer(row.get("rating_good")),
                integer(row.get("rating_normal")), integer(row.get("rating_bad")), number(row.get("cancellation_rate")),
                scalar(row.get("created_at")), boolean(row.get("vacation")), str(path),
            )
        elif dataset == "category_list":
            category_id = integer(row.get("shop_category_id"))
            key = (country, shop_id, category_id, date)
            values = (
                country, date, shop_id, category_id, scalar(row.get("display_name")), integer(row.get("total")),
                boolean(row.get("is_parent_category")), boolean(row.get("is_sub_category")),
                integer(row.get("parent_shop_category_id")), scalar(row.get("image")), scalar(row.get("category_type")), str(path),
            )
        elif dataset == "product_categories":
            item_id = integer(row.get("item_id")); category_id = integer(row.get("category_id"))
            key = (country, shop_id, item_id, category_id, date)
            values = (country, date, shop_id, item_id, scalar(row.get("category_slug")), category_id, str(path))
        else:
            category_id = integer(row.get("category_id"))
            # Platform taxonomy has no snapshot date and is keyed by country/category.
            key = (country, category_id)
            values = (
                country, scalar(row.get("platform")), scalar(row.get("client")), scalar(row.get("key")), category_id,
                integer(row.get("parent_category_id")), scalar(row.get("original_category_name")),
                scalar(row.get("display_category_name")), boolean(row.get("has_children")), scalar(row.get("debug_message")), str(path),
            )

        if key in buckets[dataset]:
            duplicate_counts[dataset] += 1
        else:
            buckets[dataset][key] = values

    inserts = {
        "products": ("products", "?"),
        "shop_info": ("shops", "?"),
        "category_list": ("shop_categories", "?"),
        "product_categories": ("product_categories", "?"),
        "category_platform": ("platform_categories", "?"),
    }
    for dataset, rows in buckets.items():
        table = inserts[dataset][0]
        if rows:
            placeholders = ",".join("?" for _ in next(iter(rows.values())))
            conn.executemany(f"INSERT INTO {table} VALUES ({placeholders})", list(rows.values()))

    # One row per changed field makes the event table easy to consume downstream.
    conn.execute("""
        CREATE TABLE promotion_events AS
        WITH ordered AS (
            SELECT *,
                LAG(snapshot_date) OVER w AS previous_date,
                LAG(price) OVER w AS previous_price,
                LAG(discount_percent) OVER w AS previous_discount_percent,
                LAG(promotion_id) OVER w AS previous_promotion_id,
                LAG(voucher_code) OVER w AS previous_voucher_code
            FROM products
            WINDOW w AS (PARTITION BY country_code, shop_id, item_id ORDER BY snapshot_date)
        ), events AS (
            SELECT country_code, shop_id, item_id, snapshot_date, 'price_changed' AS event_type,
                   previous_date, previous_price AS old_value, CAST(price AS DOUBLE) AS new_value
            FROM ordered WHERE previous_date IS NOT NULL AND price IS DISTINCT FROM previous_price
            UNION ALL
            SELECT country_code, shop_id, item_id, snapshot_date, 'discount_changed',
                   previous_date, previous_discount_percent, discount_percent
            FROM ordered WHERE previous_date IS NOT NULL AND discount_percent IS DISTINCT FROM previous_discount_percent
            UNION ALL
            SELECT country_code, shop_id, item_id, snapshot_date, 'promotion_changed',
                   previous_date, previous_promotion_id, promotion_id
            FROM ordered WHERE previous_date IS NOT NULL AND promotion_id IS DISTINCT FROM previous_promotion_id
            UNION ALL
            SELECT country_code, shop_id, item_id, snapshot_date, 'voucher_changed',
                   previous_date, previous_voucher_code, voucher_code
            FROM ordered WHERE previous_date IS NOT NULL AND voucher_code IS DISTINCT FROM previous_voucher_code
        )
        SELECT * FROM events
    """)
    return {
        dataset: {"source_rows": source_counts[dataset], "loaded_rows": len(buckets[dataset]), "duplicate_rows": duplicate_counts[dataset]}
        for dataset in DATASETS
    }


def write_quality(conn: duckdb.DuckDBPyConnection, stats: dict[str, dict[str, int]]) -> None:
    generated = datetime.now(timezone.utc).replace(tzinfo=None)
    for dataset, values in stats.items():
        null_price = invalid_price = outlier_price = None
        if dataset == "products":
            null_price = conn.execute("SELECT COUNT(*) FROM products WHERE price IS NULL").fetchone()[0]
            invalid_price = conn.execute("SELECT COUNT(*) FROM products WHERE price <= 0").fetchone()[0]
            outlier_price = conn.execute("SELECT COUNT(*) FROM products WHERE price >= 10000000").fetchone()[0]
        conn.execute("INSERT INTO ingestion_quality VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                     [dataset, values["source_rows"], values["loaded_rows"], values["duplicate_rows"],
                      null_price, invalid_price, outlier_price, generated])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=os.environ.get("DATA_DIR", "./Data"), type=Path)
    parser.add_argument("--db-path", default=os.environ.get("DB_PATH", "./warehouse/market.duckdb"), type=Path)
    parser.add_argument("--reset", action="store_true", help="Recreate the DuckDB file before loading")
    args = parser.parse_args()
    data_dir = args.data_dir.resolve()
    db_path = args.db_path.resolve()
    if not data_dir.exists():
        raise FileNotFoundError(f"Data directory does not exist: {data_dir}")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if args.reset and db_path.exists():
        db_path.unlink()

    conn = duckdb.connect(str(db_path))
    run_id = None
    try:
        create_schema(conn)
        ensure_manifest(conn)
        run_id = start_run(conn, "data_foundation", {"data_dir": str(data_dir), "db_path": str(db_path)})
        stats = load_data(conn, data_dir)
        write_quality(conn, stats)
        conn.execute("CHECKPOINT")
        finish_run(conn, run_id, "success", {
            "products": conn.execute("SELECT COUNT(*) FROM products").fetchone()[0],
            "promotion_events": conn.execute("SELECT COUNT(*) FROM promotion_events").fetchone()[0],
        })
        print(json.dumps({
            "database": str(db_path),
            "tables": {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                       for table in ["products", "shops", "shop_categories", "product_categories", "platform_categories", "promotion_events"]},
            "quality": stats,
        }, ensure_ascii=False, indent=2, default=str))
    except Exception as exc:
        if run_id:
            finish_run(conn, run_id, "failed", error_message=str(exc)[:500])
        raise
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ETL failed: {exc}", file=sys.stderr)
        raise
