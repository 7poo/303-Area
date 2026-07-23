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


PARSER_VERSION = "attributes-v0.6-owner-seller-variation-pack"
TFIDF_VERSION = "hybrid-tfidf-charword-v0.5"
ST_VERSION = "hybrid-multilingual-minilm-v0.5"

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
        ("keo_cao_su", r"kẹo cao su|keo cao su|chewing gum|\bgum\b"),
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
COUNT_UNIT = r"(?:pcs?|pieces?|goi|hop|bich|chai|lon|hu|pack|packs|cai|vien|unit|tui|banh)"
COMBO_COUNT_RE = re.compile(rf"\b(?:combo|bo|set|bundle|paket)\s*(\d+)\b", re.I)
CARTON_COUNT_RE = re.compile(rf"\b(?:thung|box|case)\s*(\d+)\s*{COUNT_UNIT}\b", re.I)
PER_CONTAINER_COUNT_RE = re.compile(rf"\b(\d+)\s*{COUNT_UNIT}\s*/\s*(?:thung|hop|bich|tui|pack)\b", re.I)
COUNT_RANGE_RE = re.compile(rf"\b(?:combo\s*)?(\d+)\s*[-–]\s*(\d+)\s*{COUNT_UNIT}\b", re.I)
WEIGHT_RANGE_RE = re.compile(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(kg|g|gr|gram|grams)\s*[-–]\s*(\d+(?:[.,]\d+)?)\s*(kg|g|gr|gram|grams)\b", re.I)
VOLUME_RANGE_RE = re.compile(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(l|liter|ml)\s*[-–]\s*(\d+(?:[.,]\d+)?)\s*(l|liter|ml)\b", re.I)
TOKEN_RE = re.compile(r"[a-z0-9]+", re.I)
GENERIC_TYPES = {"banh", "skincare", "unknown"}
VARIANT_TERMS = [
    ("bò nướng tiêu", r"bo nuong tieu"), ("muối hồng", r"muoi hong"),
    ("cốm sữa", r"com sua"), ("phô mai", r"pho mai|cheese"),
    ("chà bông", r"cha bong|soi ga"), ("rau củ", r"rau cu"),
    ("tôm", r"\btom\b|shrimp"), ("mật ong", r"mat ong|honey|ganjang"),
    ("sô-cô-la", r"socola|chocolate|cokelat"), ("dâu", r"\bdau\b|strawberry"),
    ("vani", r"vani|vanilla"), ("trà sữa", r"tra sua|milk tea"),
    ("đậu nành", r"dau nanh|soy"), ("niacinamide", r"niacinamide"),
    ("centella", r"centella|cica"), ("salicylic acid", r"salicylic"),
    ("ceramide", r"ceramide"), ("vitamin c", r"vitamin\s*c"),
]
FAMILY_TERMS = [
    ("Jinju", r"\bjinju\b"), ("Karo", r"\bkaro\b"), ("Kenju", r"\bkenju\b"),
    ("Peppie", r"\bpeppie\b"), ("Wismo", r"\bwismo\b"),
    ("Oatmeal", r"\boatmeal\b"), ("Mini Bite", r"\bmini\s*bite\b"),
    ("Solite", r"\bsolite\b"), ("Hura", r"\bhura\b"),
    ("ChocoPie", r"\bchoco\s*pie\b|\bchocopie\b"), ("Custas", r"\bcustas\b"),
    ("AFC", r"\bafc\b"), ("Oreo", r"\boreo\b"), ("Nescafé", r"\bnescafe\b"),
    ("KitKat", r"\bkit\s*kat\b|\bkitkat\b"), ("Milo", r"\bmilo\b"),
    ("Ensure", r"\bensure\b"), ("Cerelac", r"\bcerelac\b"),
    ("Alpenliebe", r"\balpenliebe\b"), ("Mentos", r"\bmentos\b"),
]


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
    tier_variation_name: str | None = None
    tier_variation_options_json: str | None = None
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
    total_weight_g: float | None = None
    total_volume_ml: float | None = None
    package_ambiguous: bool = False
    variant_signature: str = ""
    company_id: str = ""
    company_name: str = ""
    seller_entity_id: str = ""
    seller_entity_name: str = ""
    family_signature: str = ""
    variation_count: int = 0
    price_variant_ambiguous: bool = False


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
    # Keep commas because Vietnamese/Indonesian titles use them as decimal separators.
    text = re.sub(r"[^a-z0-9%+.,/x\s-]", " ", text)
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


def _measure_values(pattern: re.Pattern[str], text: str) -> list[float]:
    values: list[float] = []
    for match in pattern.finditer(text):
        value = float(match.group(1).replace(",", "."))
        unit = match.group(2).lower()
        if unit in {"kg", "l", "liter"}:
            value *= 1000
        values.append(value)
    return values


def _offer_count(text: str) -> tuple[int, bool]:
    """Return the sellable pack count and whether the listing exposes a range."""
    if COUNT_RANGE_RE.search(text):
        return 1, True
    for pattern in (COMBO_COUNT_RE, CARTON_COUNT_RE, PER_CONTAINER_COUNT_RE):
        match = pattern.search(text)
        if match:
            return max(1, int(match.group(1))), False
    quantity = first_int(QUANTITY_RE, text)
    return max(1, quantity or 1), False


def package_relation(a: Product, b: Product) -> str:
    """Describe pack comparability separately from product identity."""
    if a.package_ambiguous or b.package_ambiguous:
        return "ambiguous"
    for unit_a, unit_b, total_a, total_b in (
        (a.weight_g, b.weight_g, a.total_weight_g, b.total_weight_g),
        (a.volume_ml, b.volume_ml, a.total_volume_ml, b.total_volume_ml),
    ):
        if unit_a and unit_b:
            if safe_ratio(unit_a, unit_b) < 0.9:
                return "different_size"
            if total_a and total_b and safe_ratio(total_a, total_b) < 0.9:
                return "different_quantity"
            return "exact"
    if a.quantity and b.quantity:
        return "exact" if a.quantity == b.quantity else "different_quantity"
    return "unknown"


def detect_product_type(country: str, text: str) -> str:
    for product_type, pattern in PRODUCT_TYPES.get(country, []):
        if re.search(pattern, text, re.I):
            return product_type
    return "unknown"


def detect_variants(text: str) -> str:
    return " | ".join(label for label, pattern in VARIANT_TERMS if re.search(pattern, text, re.I))


def detect_family(text: str) -> str:
    matched = [label for label, pattern in FAMILY_TERMS if re.search(pattern, text, re.I)]
    return " | ".join(matched)


def parse_product(product: Product) -> Product:
    raw_search = remove_accents(product.product_name.lower())
    product.product_name_clean = clean_product_name(product.product_name)
    product.brand_clean = normalize_brand(product.brand)
    search_text = f"{product.brand_clean} {product.product_name_clean}"
    product.product_type = detect_product_type(product.country_code, search_text)
    product.variant_signature = detect_variants(search_text)
    product.family_signature = detect_family(search_text)
    try:
        options = json.loads(product.tier_variation_options_json or "[]")
    except (TypeError, json.JSONDecodeError):
        options = []
    if not isinstance(options, list):
        options = []
    product.variation_count = len([value for value in options if str(value or "").strip()])
    product.price_variant_ambiguous = product.variation_count > 1
    weight_values = _measure_values(WEIGHT_RE, search_text)
    volume_values = _measure_values(VOLUME_RE, search_text)
    product.weight_g = weight_values[0] if weight_values else None
    product.volume_ml = volume_values[0] if volume_values else None
    product.quantity, count_ambiguous = _offer_count(search_text)
    bundle = BUNDLE_RE.search(search_text)
    if bundle:
        product.bundle_count = int(bundle.group(1) or bundle.group(2) or 1)
    elif re.search(r"\b(?:thung|box|case)\b", search_text):
        product.bundle_count = product.quantity
    product.is_bundle = bool(bundle or product.quantity > 1 or re.search(r"\b(?:thung|box|case)\b", search_text))
    distinct_weights = {round(value, 3) for value in weight_values}
    distinct_volumes = {round(value, 3) for value in volume_values}
    product.package_ambiguous = bool(
        count_ambiguous
        or WEIGHT_RANGE_RE.search(search_text)
        or VOLUME_RANGE_RE.search(search_text)
        or len(distinct_weights) > 1
        or len(distinct_volumes) > 1
    )
    if not product.package_ambiguous:
        product.total_weight_g = product.weight_g * product.quantity if product.weight_g else None
        product.total_volume_ml = product.volume_ml * product.quantity if product.volume_ml else None
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
        f"total_weight {product.total_weight_g:g}g" if product.total_weight_g else "",
        f"total_volume {product.total_volume_ml:g}ml" if product.total_volume_ml else "",
        "bundle" if product.is_bundle else "",
    ] if part)
    return product


def load_latest_products(conn: duckdb.DuckDBPyConnection) -> list[Product]:
    rows = conn.execute("""
        SELECT country_code, currency, CAST(snapshot_date AS VARCHAR), shop_id,
               shop_name, item_id, product_name, brand, price, catid,
               monthly_sold_value, rating, rating_count, liked_count,
               is_ad, is_sold_out, tier_variation_name,
               CAST(tier_variation_options AS VARCHAR)
        FROM products
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY country_code, shop_id, item_id
            ORDER BY snapshot_date DESC
        ) = 1
        ORDER BY country_code, shop_id, item_id
    """).fetchall()
    return [parse_product(Product(*row)) for row in rows]


def load_company_registry(path: Path | None) -> dict[tuple[str, int], tuple[str, str, str, str]]:
    if path is None or not path.exists():
        return {}
    registry: dict[tuple[str, int], tuple[str, str, str, str]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                key = (row["country_code"].strip().lower(), int(row["shop_id"]))
                registry[key] = (
                    row["company_id"].strip(), row["company_name"].strip(),
                    row["seller_entity_id"].strip(), row["seller_entity_name"].strip(),
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(
                    "Company registry cần country_code, shop_id, company_id, company_name, "
                    "seller_entity_id, seller_entity_name"
                ) from exc
    return registry


def assign_companies(products: list[Product], registry: dict[tuple[str, int], tuple[str, str, str, str]]) -> None:
    for product in products:
        company = registry.get((product.country_code, product.shop_id))
        if company:
            product.company_id, product.company_name, product.seller_entity_id, product.seller_entity_name = company
        else:
            product.company_id = f"shop_{product.shop_id}"
            product.company_name = product.shop_name or f"Shop {product.shop_id}"
            product.seller_entity_id = f"shop_{product.shop_id}"
            product.seller_entity_name = product.shop_name or f"Shop {product.shop_id}"


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
    if a.package_ambiguous or b.package_ambiguous:
        return 0.25
    scores: list[float] = []
    if a.weight_g and b.weight_g:
        scores.append(safe_ratio(a.weight_g, b.weight_g))
    if a.volume_ml and b.volume_ml:
        scores.append(safe_ratio(a.volume_ml, b.volume_ml))
    if a.total_weight_g and b.total_weight_g:
        scores.append(safe_ratio(a.total_weight_g, b.total_weight_g))
    if a.total_volume_ml and b.total_volume_ml:
        scores.append(safe_ratio(a.total_volume_ml, b.total_volume_ml))
    if a.quantity and b.quantity:
        scores.append(safe_ratio(float(a.quantity), float(b.quantity)))
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
    pack_relation = package_relation(a, b)
    features = {
        "semantic": round(float(text_similarity), 6),
        "product_type": round(type_score(a, b), 6),
        "attributes": round(attribute_similarity(a, b), 6),
        "pack_size": round(pack_similarity(a, b), 6),
        "price": round(safe_ratio(a.price, b.price), 6),
        "brand_relation": "same" if a.brand_clean and a.brand_clean == b.brand_clean else "different_or_unknown",
        "package_relation": pack_relation,
        "source_package": {"unit_weight_g": a.weight_g, "total_weight_g": a.total_weight_g, "unit_volume_ml": a.volume_ml, "total_volume_ml": a.total_volume_ml, "quantity": a.quantity, "ambiguous": a.package_ambiguous},
        "target_package": {"unit_weight_g": b.weight_g, "total_weight_g": b.total_weight_g, "unit_volume_ml": b.volume_ml, "total_volume_ml": b.total_volume_ml, "quantity": b.quantity, "ambiguous": b.package_ambiguous},
        "source_variant": a.variant_signature or None,
        "target_variant": b.variant_signature or None,
        "source_family": a.family_signature or None,
        "target_family": b.family_signature or None,
        "gates": ["same_country", "same_category_or_product_type", "different_seller_entity"],
        "source_company": a.company_id,
        "target_company": b.company_id,
        "source_seller_entity": a.seller_entity_id,
        "target_seller_entity": b.seller_entity_id,
    }
    score = (
        0.40 * features["semantic"]
        + 0.25 * features["product_type"]
        + 0.20 * features["attributes"]
        + 0.10 * features["pack_size"]
        + 0.05 * brand_relation(a, b)
    )
    same_type = a.product_type != "unknown" and a.product_type == b.product_type
    specific_type = same_type and a.product_type not in GENERIC_TYPES
    if a.family_signature and b.family_signature:
        same_family = a.family_signature == b.family_signature
    elif not a.family_signature and not b.family_signature:
        same_family = True
    else:
        # One title may omit the line name, but only a very strong textual match
        # is allowed to bridge that missing attribute.
        same_family = features["semantic"] >= 0.85
    if a.variant_signature and b.variant_signature:
        same_variant = a.variant_signature == b.variant_signature
    elif not a.variant_signature and not b.variant_signature:
        same_variant = True
    else:
        same_variant = features["semantic"] >= 0.90
    identity_ready = (
        same_type
        and same_family
        and same_variant
        and a.brand_clean
        and a.brand_clean == b.brand_clean
        and features["attributes"] >= 0.65
        and features["semantic"] >= 0.70
        and score >= 0.70
    )
    if identity_ready:
        match_type = "same_product" if pack_relation == "exact" else "same_product_variant"
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
            if source.shop_id == target.shop_id:
                continue
            if source.seller_entity_id and source.seller_entity_id == target.seller_entity_id:
                continue
            same_category = source.catid is not None and source.catid == target.catid
            same_type = source.product_type != "unknown" and source.product_type == target.product_type
            if not (same_category or same_type):
                continue
            if (source.product_type not in GENERIC_TYPES and target.product_type not in GENERIC_TYPES
                    and source.product_type != target.product_type):
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
            total_weight_g DOUBLE, total_volume_ml DOUBLE, package_ambiguous BOOLEAN NOT NULL,
            variant_signature VARCHAR,
            company_id VARCHAR NOT NULL, company_name VARCHAR NOT NULL,
            seller_entity_id VARCHAR NOT NULL, seller_entity_name VARCHAR NOT NULL,
            family_signature VARCHAR,
            variation_count INTEGER NOT NULL,
            price_variant_ambiguous BOOLEAN NOT NULL,
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
        p.embedding_text, p.total_weight_g, p.total_volume_ml, p.package_ambiguous,
        p.variant_signature or None, p.company_id, p.company_name,
        p.seller_entity_id, p.seller_entity_name,
        p.family_signature or None, p.variation_count, p.price_variant_ambiguous,
        PARSER_VERSION,
    ) for p in products]
    conn.executemany("INSERT INTO product_attributes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)


def rank_matches(products: list[Product], matrix: np.ndarray, model_version: str, top_k: int, min_score: float) -> list[dict[str, Any]]:
    by_source: dict[int, list[dict[str, Any]]] = {}
    for i, j in candidate_pairs(products):
        row = match_row(products[i], products[j], float(matrix[i, j]), model_version)
        by_source.setdefault(i, []).append(row)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    output: list[dict[str, Any]] = []
    for i, source in enumerate(products):
        rows = sorted(by_source.get(i, []), key=lambda x: x["match_score"], reverse=True)[:top_k]
        accepted = [r for r in rows if r["match_type"] in {"same_product", "same_product_variant", "substitute"} and r["match_score"] >= min_score]
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
    """Create a deterministic, stratified review sample.

    The sample deliberately includes identity predictions, abstentions and
    other matchable sources.  It is a QA sample, not a population estimate.
    """
    by_key = {(p.country_code, p.shop_id, p.item_id): p for p in products}
    by_source: dict[tuple[str, int, int], list[dict[str, Any]]] = {}
    for row in ranked_rows:
        key = (row["country_code"], row["source_shop_id"], row["source_item_id"])
        by_source.setdefault(key, []).append(row)
    source_keys = list(by_source)
    randomizer = random.Random(42)
    source_count = max(1, size // 5)
    identity_keys = [
        key for key in source_keys
        if any(row["match_type"] in {"same_product", "same_product_variant"} for row in by_source[key])
    ]
    abstained_keys = [key for key in source_keys if by_source[key][0]["source_status"] != "matchable"]
    other_matchable_keys = [
        key for key in source_keys if key not in identity_keys and key not in abstained_keys
    ]
    for pool in (identity_keys, abstained_keys, other_matchable_keys):
        randomizer.shuffle(pool)

    identity_quota = max(1, source_count // 4)
    abstention_quota = max(1, source_count // 4)
    selected_sources = identity_keys[:identity_quota] + abstained_keys[:abstention_quota]
    remaining_quota = max(0, source_count - len(selected_sources))
    selected_sources.extend(other_matchable_keys[:remaining_quota])
    # Fill a short stratum from every remaining pool. Keep the rest as overflow
    # because abstained sources contribute one row rather than five candidates.
    remaining = [key for key in source_keys if key not in selected_sources]
    randomizer.shuffle(remaining)
    selected_sources.extend(remaining)

    selected: list[dict[str, Any]] = []
    for source_key in selected_sources:
        source = by_key[source_key]
        rows = sorted(by_source[source_key], key=lambda r: r["rank"])
        if source_key in identity_keys:
            review_stratum = "identity_prediction"
        elif source_key in abstained_keys:
            review_stratum = "abstention"
        else:
            review_stratum = "other_matchable"
        for row in rows[:5]:
            target = by_key.get((row["country_code"], row["target_shop_id"], row["target_item_id"]))
            enriched = dict(row)
            enriched.update({
                "review_id": len(selected) + 1,
                "review_stratum": review_stratum,
                "pair_key": f'{row["country_code"]}:{row["source_shop_id"]}:{row["source_item_id"]}:{row["target_shop_id"]}:{row["target_item_id"]}',
                "source_product_name": source.product_name,
                "target_product_name": target.product_name if target else "",
                "source_company": source.company_name,
                "target_company": target.company_name if target else "",
                "source_seller_entity": source.seller_entity_name,
                "target_seller_entity": target.seller_entity_name if target else "",
                "source_family": source.family_signature,
                "target_family": target.family_signature if target else "",
                "source_variant": source.variant_signature,
                "target_variant": target.variant_signature if target else "",
                "source_quantity": source.quantity,
                "target_quantity": target.quantity if target else None,
                "source_total_weight_g": source.total_weight_g,
                "target_total_weight_g": target.total_weight_g if target else None,
                "package_relation": package_relation(source, target) if target else "unknown",
                "source_is_bundle": source.is_bundle,
                "target_is_bundle": target.is_bundle if target else False,
                "source_variation_count": source.variation_count,
                "target_variation_count": target.variation_count if target else 0,
                "source_price_variant_ambiguous": source.price_variant_ambiguous,
                "target_price_variant_ambiguous": target.price_variant_ambiguous if target else False,
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
        "review_id", "review_stratum", "pair_key", "country_code", "source_shop_id", "source_item_id", "source_product_name",
        "target_shop_id", "target_item_id", "target_product_name", "rank", "match_score", "match_type",
        "source_product_type", "target_product_type", "source_brand", "target_brand", "source_status",
        "source_company", "target_company", "source_seller_entity", "target_seller_entity",
        "source_family", "target_family", "source_variant", "target_variant",
        "source_quantity", "target_quantity", "source_total_weight_g", "target_total_weight_g", "package_relation",
        "source_is_bundle", "target_is_bundle", "source_variation_count", "target_variation_count",
        "source_price_variant_ambiguous", "target_price_variant_ambiguous",
        "matching_features", "review_label", "review_notes",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader()
        writer.writerows({field: row.get(field) for field in fields} for row in rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", default=os.environ.get("DB_PATH", "./warehouse/market.duckdb"), type=Path)
    parser.add_argument("--backend", choices=["tfidf", "sentence-transformers"], default="tfidf")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument(
        "--min-score", type=float, default=0.60,
        help="Ngưỡng phát hiện benchmark thay thế; không phải ngưỡng tự động đổi giá.",
    )
    parser.add_argument("--review-size", type=int, default=100)
    parser.add_argument("--review-file", default=None, type=Path)
    parser.add_argument("--company-registry", default=Path("./config/company_registry.csv"), type=Path)
    args = parser.parse_args()
    conn = duckdb.connect(str(args.db_path))
    run_id = start_run(conn, "product_matching", {
        "backend": args.backend,
        "top_k": args.top_k,
        "min_score": args.min_score,
        "db_path": str(args.db_path),
        "company_registry": str(args.company_registry),
    })
    try:
        products = load_latest_products(conn)
        assign_companies(products, load_company_registry(args.company_registry))
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
