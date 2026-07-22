"""Product matching pipeline for the Market Intelligence MVP.

The first version is deliberately explainable: candidates are constrained by
country/category/shop, names are cleaned and parsed into attributes, and a
text vector is combined with structured similarity features. ``tfidf`` is the
zero-install baseline; ``sentence-transformers`` is an optional multilingual
backend.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from .pipeline import finish_run, start_run


PARSER_VERSION = "attributes-v0.2"
TFIDF_VERSION = "hybrid-tfidf-charword-v0.2"
ST_VERSION = "hybrid-multilingual-minilm-v0.2"

MARKETING_PATTERNS = [
    r"\b(?:official\s*(?:store|shop)|officialstore|official)\b",
    r"\b(?:free\s*gift|gift|hadiah|quà\s*tặng|tặng\s*quà|quà\s*tặng\s*không\s*bán)\b",
    r"\b(?:flash\s*sale|hot\s*sale|new\s*launch|mua\s*\d+\s*tặng\s*\d+)\b",
    r"\b(?:hỏa\s*tốc|giao\s*hàng|date\s*mới|jadian|promo)\b",
]

PRODUCT_TYPES = {
    "vn": [
        ("thuc_pham_bo_sung", r"thực phẩm bổ sung|thuc pham bo sung|supplement"),
        ("sua_bot", r"sữa bột|sua bot|milk powder"),
        ("dau_hao", r"dầu hào|dau hao|oyster sauce"),
        ("ca_phe", r"cà phê|ca phe|coffee|nescafe"),
        ("banh_kem_xop", r"bánh kem xốp|banh kem xop|wafer"),
        ("banh_bong_lan", r"bánh bông lan|banh bong lan|solite|hura"),
        ("banh_karo", r"karo|bánh trứng|banh trung"),
        ("banh_yen_mach", r"yến mạch|yen mach|oatmeal|oat milk"),
        ("banh_que", r"bánh que|banh que|breadstick"),
        ("banh_quy", r"bánh quy|banh quy|biscuit|cookie"),
        ("banh_snack", r"bánh snack|banh snack|snack"),
        ("banh_gao", r"bánh gạo|banh gao|rice cracker"),
        ("banh_mi", r"bánh mì|banh mi|bread"),
        ("keo_cao_su", r"kẹo cao su|keo cao su|chewing gum|gum"),
        ("keo", r"kẹo|keo|candy|gummy"),
        ("gia_vi", r"gia vị|seasoning|nước tương|soy sauce"),
        ("nuoc_uong", r"nước uống|drink|beverage"),
        ("banh", r"bánh|banh"),
    ],
    "id": [
        ("micellar_water", r"micellar"),
        ("facial_wash", r"facial wash|cleanser|cleansing|pembersih"),
        ("moisturizer", r"moisturizer|pelembab|moisturising"),
        ("sunscreen", r"sunscreen|sun screen|spf"),
        ("serum", r"serum"),
        ("toner", r"toner"),
        ("acne_treatment", r"acne|jerawat|spot"),
        ("shampoo", r"shampoo"),
        ("hair_mask", r"hair mask|masker rambut"),
        ("body_mist", r"body mist|fragrance"),
        ("makeup", r"cushion|foundation|concealer|make up"),
        ("cream", r"cream|krim"),
        ("skincare", r"skincare|skin care|perawatan kulit"),
    ],
}

WEIGHT_RE = re.compile(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(kg|g|gr|gram|grams)\b", re.I)
VOLUME_RE = re.compile(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(l|liter|ml)\b", re.I)
QUANTITY_RE = re.compile(
    r"(?<!\d)(\d+)\s*(?:pcs?|pieces?|gói|goi|hộp|hop|bịch|bich|chai|lon|hũ|hu|pack|packs|cái|cai|viên|unit)\b",
    re.I,
)
BUNDLE_RE = re.compile(r"\b(?:combo|bộ|bo|set|bundle|paket)\s*(\d+)?|\b(\d+)\s*in\s*1\b", re.I)
TOKEN_RE = re.compile(r"[a-z0-9]+", re.I)
GENERIC_TYPES = {"banh", "skincare", "unknown"}


@dataclass
class Product:
    country_code: str
    currency: str
    snapshot_date: str
    shop_id: int
    shop_name: str | None
    item_id: int
    product_name: str
    brand: str | None
    price: float | None
    catid: int | None
    monthly_sold_value: float | None
    rating: float | None
    rating_count: int | None
    liked_count: int | None
    is_ad: bool | None
    is_sold_out: bool | None
    product_name_clean: str = ""
    brand_clean: str = ""
    product_type: str = "unknown"
    weight_g: float | None = None
    volume_ml: float | None = None
    quantity: int | None = None
    bundle_count: int | None = None
    is_bundle: bool = False
    is_gift: bool = False
    embedding_text: str = ""


def remove_accents(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in value if not unicodedata.combining(ch))


def normalize_brand(value: str | None) -> str:
    if not value:
        return ""
    text = remove_accents(value.lower())
    text = re.sub(r"\b(?:official\s*(?:store|shop)|officialstore|store|shop)\b", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def clean_product_name(value: str | None) -> str:
    if not value:
        return ""
    text = remove_accents(value.lower())
    text = re.sub(r"\[[^\]]*\]", " ", text)
    for pattern in MARKETING_PATTERNS:
        text = re.sub(pattern, " ", text, flags=re.I)
    text = re.sub(r"https?://\S+|www\.\S+", " ", text)
    text = re.sub(r"[^a-z0-9%+./x\s-]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def first_number(pattern: re.Pattern[str], text: str) -> float | None:
    match = pattern.search(text)
    if not match:
        return None
    try:
        value = float(match.group(1).replace(",", "."))
    except ValueError:
        return None
    unit = (match.group(2) or "").lower()
    if unit == "kg":
        value *= 1000
    if unit in {"l", "liter"}:
        value *= 1000
    return value


def first_int(pattern: re.Pattern[str], text: str) -> int | None:
    match = pattern.search(text)
    return int(match.group(1)) if match else None


def detect_product_type(country: str, text: str) -> str:
    for product_type, pattern in PRODUCT_TYPES.get(country, []):
        if re.search(pattern, text, re.I):
            return product_type
    return "unknown"


def parse_product(product: Product) -> Product:
    raw_search = remove_accents(product.product_name.lower())
    product.product_name_clean = clean_product_name(product.product_name)
    product.brand_clean = normalize_brand(product.brand)
    search_text = f"{product.brand_clean} {product.product_name_clean}"
    product.product_type = detect_product_type(product.country_code, search_text)
    product.weight_g = first_number(WEIGHT_RE, search_text)
    product.volume_ml = first_number(VOLUME_RE, search_text)
    product.quantity = first_int(QUANTITY_RE, search_text)
    bundle = BUNDLE_RE.search(search_text)
    if bundle:
        product.bundle_count = int(bundle.group(1) or bundle.group(2) or 1)
    product.is_bundle = bool(bundle or re.search(r"\b(?:thung|thùng|box|case)\b", search_text))
    product.is_gift = bool(re.search(
        r"qu[aà]\s*t[ặa]ng\s*kh[oô]ng\s*b[aá]n|free\s*gift|hadiah|\bgift\b|\bbalo\b|\bv[oợ]t\s*cầu\s*l[oô]ng\b",
        raw_search,
        re.I,
    ))
    product.embedding_text = " ".join(part for part in [
        product.product_type, product.brand_clean, product.product_name_clean,
        f"weight {product.weight_g:g}g" if product.weight_g else "",
        f"volume {product.volume_ml:g}ml" if product.volume_ml else "",
        f"quantity {product.quantity}" if product.quantity else "",
        "bundle" if product.is_bundle else "",
    ] if part)
    return product


def load_latest_products(conn: duckdb.DuckDBPyConnection) -> list[Product]:
    rows = conn.execute("""
        SELECT country_code, currency, CAST(snapshot_date AS VARCHAR), shop_id,
               shop_name, item_id, product_name, brand, price, catid,
               monthly_sold_value, rating, rating_count, liked_count,
               is_ad, is_sold_out
        FROM products
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY country_code, shop_id, item_id
            ORDER BY snapshot_date DESC
        ) = 1
        ORDER BY country_code, shop_id, item_id
    """).fetchall()
    return [parse_product(Product(*row)) for row in rows]


def safe_ratio(a: float | None, b: float | None) -> float:
    if not a or not b or a <= 0 or b <= 0:
        return 0.5
    return max(0.0, min(1.0, math.exp(-abs(math.log(a / b)))))


def token_set(value: str) -> set[str]:
    return set(TOKEN_RE.findall(value))


def attribute_similarity(a: Product, b: Product) -> float:
    scores: list[float] = []
    if a.weight_g and b.weight_g:
        scores.append(safe_ratio(a.weight_g, b.weight_g))
    if a.volume_ml and b.volume_ml:
        scores.append(safe_ratio(a.volume_ml, b.volume_ml))
    if a.quantity and b.quantity:
        scores.append(safe_ratio(a.quantity, b.quantity))
    a_tokens = token_set(a.product_name_clean)
    b_tokens = token_set(b.product_name_clean)
    if a_tokens and b_tokens:
        scores.append(len(a_tokens & b_tokens) / max(1, len(a_tokens | b_tokens)))
    return sum(scores) / len(scores) if scores else 0.5


def pack_similarity(a: Product, b: Product) -> float:
    scores: list[float] = []
    if a.weight_g and b.weight_g:
        scores.append(safe_ratio(a.weight_g, b.weight_g))
    if a.volume_ml and b.volume_ml:
        scores.append(safe_ratio(a.volume_ml, b.volume_ml))
    scores.append(1.0 if a.is_bundle == b.is_bundle else 0.35)
    return sum(scores) / len(scores)


def brand_relation(a: Product, b: Product) -> float:
    if a.brand_clean and b.brand_clean:
        return 1.0 if a.brand_clean == b.brand_clean else 0.5
    return 0.4


def type_score(a: Product, b: Product) -> float:
    if a.product_type == "unknown" or b.product_type == "unknown":
        return 0.45
    if a.product_type != b.product_type:
        return 0.0
    return 0.55 if a.product_type in GENERIC_TYPES else 1.0


def match_row(a: Product, b: Product, text_similarity: float, model_version: str) -> dict[str, Any]:
    features = {
        "semantic": round(float(text_similarity), 6),
        "product_type": round(type_score(a, b), 6),
        "attributes": round(attribute_similarity(a, b), 6),
        "pack_size": round(pack_similarity(a, b), 6),
        "price": round(safe_ratio(a.price, b.price), 6),
        "brand_relation": "same" if a.brand_clean and a.brand_clean == b.brand_clean else "different_or_unknown",
        "gates": ["same_country", "same_category", "different_shop"],
    }
    score = (
        0.35 * features["semantic"]
        + 0.25 * features["product_type"]
        + 0.20 * features["attributes"]
        + 0.10 * features["pack_size"]
        + 0.05 * features["price"]
        + 0.05 * brand_relation(a, b)
    )
    same_type = a.product_type != "unknown" and a.product_type == b.product_type
    specific_type = same_type and a.product_type not in GENERIC_TYPES
    if same_type and a.brand_clean and a.brand_clean == b.brand_clean and features["attributes"] >= 0.65:
        match_type = "same_product"
    elif specific_type and score >= 0.60:
        match_type = "substitute"
    elif score >= 0.52:
        match_type = "near_match"
    else:
        match_type = "not_comparable"
    confidence = "high" if score >= 0.80 else "medium" if score >= 0.70 else "low" if score >= 0.60 else "not_enough_evidence"
    return {
        "country_code": a.country_code, "snapshot_date": a.snapshot_date,
        "source_shop_id": a.shop_id, "source_item_id": a.item_id,
        "target_shop_id": b.shop_id, "target_item_id": b.item_id,
        "match_score": round(float(score), 6), "match_type": match_type,
        "confidence": confidence,
        "matching_features": json.dumps(features, ensure_ascii=False, sort_keys=True),
        "source_product_type": a.product_type, "target_product_type": b.product_type,
        "source_brand": a.brand_clean or None, "target_brand": b.brand_clean or None,
        "model_version": model_version,
    }


def create_embeddings(products: list[Product], backend: str) -> tuple[Any, str]:
    texts = [p.embedding_text for p in products]
    if backend == "sentence-transformers":
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError("Install sentence-transformers or use --backend tfidf") from exc
        model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
        return np.asarray(model.encode(texts, normalize_embeddings=True, show_progress_bar=True)), ST_VERSION
    vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=1, sublinear_tf=True, max_features=50000, norm="l2")
    return vectorizer.fit_transform(texts), TFIDF_VERSION


def build_similarity_matrix(embeddings: Any) -> np.ndarray:
    """Materialize the small (1157x1157) similarity matrix once."""
    if hasattr(embeddings, "toarray"):
        return (embeddings @ embeddings.T).toarray()
    return np.asarray(embeddings @ embeddings.T)


def candidate_pairs(products: list[Product]) -> list[tuple[int, int]]:
    pairs: list[tuple[int, int]] = []
    for i, source in enumerate(products):
        if source.is_gift:
            continue
        for j, target in enumerate(products):
            if i == j or target.is_gift or source.country_code != target.country_code:
                continue
            if source.shop_id == target.shop_id or source.catid != target.catid:
                continue
            pairs.append((i, j))
    return pairs


def create_tables(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute("DROP TABLE IF EXISTS product_attributes")
    conn.execute("DROP TABLE IF EXISTS product_matches")
    conn.execute("""
        CREATE TABLE product_attributes (
            country_code VARCHAR NOT NULL, snapshot_date DATE NOT NULL,
            shop_id BIGINT NOT NULL, item_id BIGINT NOT NULL,
            product_name_raw VARCHAR, product_name_clean VARCHAR,
            brand_clean VARCHAR, product_type VARCHAR, weight_g DOUBLE,
            volume_ml DOUBLE, quantity BIGINT, bundle_count BIGINT,
            is_bundle BOOLEAN, is_gift BOOLEAN, embedding_text VARCHAR,
            parser_version VARCHAR NOT NULL,
            PRIMARY KEY (country_code, shop_id, item_id)
        )
    """)
    conn.execute("""
        CREATE TABLE product_matches (
            country_code VARCHAR NOT NULL, snapshot_date DATE NOT NULL,
            source_shop_id BIGINT NOT NULL, source_item_id BIGINT NOT NULL,
            target_shop_id BIGINT, target_item_id BIGINT, rank INTEGER NOT NULL,
            match_score DOUBLE NOT NULL, match_type VARCHAR NOT NULL,
            confidence VARCHAR NOT NULL, source_status VARCHAR NOT NULL,
            matching_features JSON, source_product_type VARCHAR,
            target_product_type VARCHAR, source_brand VARCHAR, target_brand VARCHAR,
            model_version VARCHAR NOT NULL, created_at TIMESTAMP NOT NULL
        )
    """)


def insert_attributes(conn: duckdb.DuckDBPyConnection, products: list[Product]) -> None:
    rows = [(
        p.country_code, p.snapshot_date, p.shop_id, p.item_id, p.product_name,
        p.product_name_clean, p.brand_clean or None, p.product_type, p.weight_g,
        p.volume_ml, p.quantity, p.bundle_count, p.is_bundle, p.is_gift,
        p.embedding_text, PARSER_VERSION,
    ) for p in products]
    conn.executemany("INSERT INTO product_attributes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)


def rank_matches(products: list[Product], matrix: np.ndarray, model_version: str, top_k: int, min_score: float) -> list[dict[str, Any]]:
    by_source: dict[int, list[dict[str, Any]]] = {}
    for i, j in candidate_pairs(products):
        row = match_row(products[i], products[j], float(matrix[i, j]), model_version)
        by_source.setdefault(i, []).append(row)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    output: list[dict[str, Any]] = []
    for i, source in enumerate(products):
        rows = sorted(by_source.get(i, []), key=lambda x: x["match_score"], reverse=True)[:top_k]
        accepted = [r for r in rows if r["match_type"] in {"same_product", "substitute"} and r["match_score"] >= min_score]
        status = "matchable" if accepted else "not_enough_evidence"
        if not rows:
            rows = [{
                "country_code": source.country_code, "snapshot_date": source.snapshot_date,
                "source_shop_id": source.shop_id, "source_item_id": source.item_id,
                "target_shop_id": None, "target_item_id": None, "match_score": 0.0,
                "match_type": "not_enough_evidence", "confidence": "not_enough_evidence",
                "matching_features": json.dumps({"reason": "no_same_country_category_peer"}),
                "source_product_type": source.product_type, "target_product_type": None,
                "source_brand": source.brand_clean or None, "target_brand": None,
                "model_version": model_version,
            }]
        for rank, row in enumerate(rows, start=1):
            row["rank"] = rank; row["source_status"] = status; row["created_at"] = now
            output.append(row)
    return output


def insert_matches(conn: duckdb.DuckDBPyConnection, rows: list[dict[str, Any]]) -> None:
    values = [(
        r["country_code"], r["snapshot_date"], r["source_shop_id"], r["source_item_id"],
        r["target_shop_id"], r["target_item_id"], r["rank"], r["match_score"], r["match_type"],
        r["confidence"], r["source_status"], r["matching_features"], r["source_product_type"],
        r["target_product_type"], r["source_brand"], r["target_brand"], r["model_version"], r["created_at"],
    ) for r in rows]
    conn.executemany("INSERT INTO product_matches VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", values)


def review_candidates(products: list[Product], ranked_rows: list[dict[str, Any]], size: int) -> list[dict[str, Any]]:
    """Create source products x top-5 candidates for ranking evaluation."""
    by_key = {(p.country_code, p.shop_id, p.item_id): p for p in products}
    by_source: dict[tuple[str, int, int], list[dict[str, Any]]] = {}
    for row in ranked_rows:
        if row["target_item_id"] is not None:
            key = (row["country_code"], row["source_shop_id"], row["source_item_id"])
            by_source.setdefault(key, []).append(row)
    source_keys = list(by_source)
    matchable_keys = [k for k in source_keys if by_source[k][0]["source_status"] == "matchable"]
    # Ranking precision is evaluated on sources for which the system claims
    # it has enough evidence. Abstention is reported separately.
    source_keys = matchable_keys or source_keys
    randomizer = random.Random(42)
    randomizer.shuffle(source_keys)
    source_count = max(1, size // 5)
    selected_sources: list[tuple[str, int, int]] = []
    country_quota = max(1, source_count // 2)
    for country in ["vn", "id"]:
        types = sorted({by_key[k].product_type for k in source_keys if k[0] == country})
        groups = []
        for product_type in types:
            group = [k for k in source_keys if k[0] == country and by_key[k].product_type == product_type]
            randomizer.shuffle(group)
            if group:
                groups.append(group)
        cursor = 0
        while len([k for k in selected_sources if k[0] == country]) < country_quota and groups:
            group = groups[cursor % len(groups)]
            if group:
                selected_sources.append(group.pop())
            groups = [group for group in groups if group]
            cursor += 1
    selected_sources = list(dict.fromkeys(selected_sources))
    selected_sources.extend(k for k in source_keys if k not in selected_sources)
    selected_sources = selected_sources[:source_count]

    selected: list[dict[str, Any]] = []
    for source_key in selected_sources:
        source = by_key[source_key]
        rows = sorted(by_source[source_key], key=lambda r: r["rank"])
        for row in rows[:5]:
            target = by_key.get((row["country_code"], row["target_shop_id"], row["target_item_id"]))
            enriched = dict(row)
            enriched.update({
                "review_id": len(selected) + 1,
                "source_product_name": source.product_name,
                "target_product_name": target.product_name if target else "",
                "source_is_bundle": source.is_bundle,
                "target_is_bundle": target.is_bundle if target else False,
                "review_label": "",
                "review_notes": "",
            })
            selected.append(enriched)
            if len(selected) >= size:
                return selected
    return selected


def write_review_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "review_id", "country_code", "source_shop_id", "source_item_id", "source_product_name",
        "target_shop_id", "target_item_id", "target_product_name", "rank", "match_score", "match_type",
        "source_product_type", "target_product_type", "source_brand", "target_brand", "source_status",
        "source_is_bundle", "target_is_bundle", "matching_features", "review_label", "review_notes",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader()
        writer.writerows({field: row.get(field) for field in fields} for row in rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", default=os.environ.get("DB_PATH", "./warehouse/market.duckdb"), type=Path)
    parser.add_argument("--backend", choices=["tfidf", "sentence-transformers"], default="tfidf")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--min-score", type=float, default=0.70)
    parser.add_argument("--review-size", type=int, default=100)
    parser.add_argument("--review-file", default=None, type=Path)
    args = parser.parse_args()
    conn = duckdb.connect(str(args.db_path))
    run_id = start_run(conn, "product_matching", {
        "backend": args.backend,
        "top_k": args.top_k,
        "min_score": args.min_score,
        "db_path": str(args.db_path),
    })
    try:
        products = load_latest_products(conn)
        embeddings, model_version = create_embeddings(products, args.backend)
        matrix = build_similarity_matrix(embeddings)
        create_tables(conn); insert_attributes(conn, products)
        rows = rank_matches(products, matrix, model_version, args.top_k, args.min_score); insert_matches(conn, rows)
        review = review_candidates(products, rows, args.review_size)
        review_path = args.review_file or (
            args.db_path.parent / ("matching_review.csv" if args.db_path.stem == "market" else f"{args.db_path.stem}_matching_review.csv")
        )
        write_review_csv(review_path, review)
        conn.execute("CHECKPOINT")
        finish_run(conn, run_id, "success", {
            "latest_products": len(products),
            "product_attributes": conn.execute("SELECT COUNT(*) FROM product_attributes").fetchone()[0],
            "product_matches": conn.execute("SELECT COUNT(*) FROM product_matches").fetchone()[0],
            "model_version": model_version,
        })
        print(json.dumps({
            "database": str(args.db_path), "backend": args.backend, "model_version": model_version,
            "latest_products": len(products), "product_attributes": conn.execute("SELECT COUNT(*) FROM product_attributes").fetchone()[0],
            "product_match_rows": conn.execute("SELECT COUNT(*) FROM product_matches").fetchone()[0],
            "matchable_sources": conn.execute("SELECT COUNT(DISTINCT source_item_id) FROM product_matches WHERE source_status='matchable'").fetchone()[0],
            "not_enough_evidence_sources": conn.execute("SELECT COUNT(DISTINCT source_item_id) FROM product_matches WHERE source_status='not_enough_evidence'").fetchone()[0],
            "review_pairs": len(review), "review_file": str(review_path),
            "match_types": conn.execute("SELECT match_type, COUNT(*) FROM product_matches GROUP BY 1 ORDER BY 1").fetchall(),
        }, ensure_ascii=False, indent=2, default=str))
    except Exception as exc:
        finish_run(conn, run_id, "failed", error_message=str(exc)[:500])
        raise
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
