"""Generate and benchmark a deterministic synthetic commerce market.

Synthetic rows are stored separately from production data. The generator
exposes latent demand, canonical identity and event labels so algorithms can
be tested against known truth without claiming real-world causal validity.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .matching import Product, assign_companies, build_similarity_matrix, create_embeddings, parse_product, rank_matches


GENERATOR_VERSION = "synthetic-market-v1.0"
START_DATE = date(2026, 1, 1)

FAMILY_SPECS = [
    ("vn", "richy", "Richy", "Jinju", "banh_gao", "Bánh gạo", ["bò nướng tiêu", "muối hồng", "phô mai", "mật ong"], [100, 134.4, 145, 180]),
    ("vn", "richy", "Richy", "Kenju", "banh_quy", "Bánh quy", ["sô-cô-la", "dâu", "vani", "phô mai"], [120, 186, 220, 279]),
    ("vn", "richy", "Richy", "Karo", "banh_karo", "Bánh trứng Karo", ["chà bông", "phô mai", "sô-cô-la"], [26, 156, 260]),
    ("vn", "richy", "Richy", "Mini Bite", "banh_yen_mach", "Bánh yến mạch", ["phô mai", "sô-cô-la", "cốm sữa"], [150, 220, 300]),
    ("vn", "orion", "Orion", "ChocoPie", "banh_bong_lan", "Bánh bông lan ChocoPie", ["sô-cô-la", "dâu"], [198, 330, 396]),
    ("vn", "orion", "Orion", "Custas", "banh_bong_lan", "Bánh bông lan Custas", ["vani", "sô-cô-la"], [141, 282, 470]),
    ("vn", "mondelez", "Mondelez", "AFC", "banh_quy", "Bánh quy AFC", ["rau củ", "phô mai", "lúa mì"], [172, 200, 300]),
    ("vn", "mondelez", "Mondelez", "Oreo", "banh_quy", "Bánh quy Oreo", ["sô-cô-la", "dâu", "vani"], [133, 266, 399]),
    ("vn", "nestle", "Nestlé", "Nescafé", "ca_phe", "Cà phê Nescafé", ["sữa", "đen", "cốt dừa"], [170, 255, 340]),
    ("vn", "bibica", "Bibica", "Hura", "banh_bong_lan", "Bánh bông lan Hura", ["vani", "sô-cô-la", "dâu"], [180, 300, 360]),
    ("id", "glad2glow", "Glad2Glow", "Blueberry", "moisturizer", "Moisturizer", ["niacinamide", "ceramide", "centella"], [30, 50, 80]),
    ("id", "glad2glow", "Glad2Glow", "Pomegranate", "serum", "Serum wajah", ["niacinamide", "vitamin c", "salicylic acid"], [17, 30, 50]),
    ("id", "scora", "Scora", "Daily UV", "sunscreen", "Sunscreen SPF50", ["centella", "ceramide", "vitamin c"], [30, 50, 80]),
    ("id", "cyeecare", "Cyeecare", "Clear Skin", "facial_wash", "Facial wash", ["salicylic acid", "niacinamide", "centella"], [50, 80, 100]),
]

REGIMES = ("stable_market", "promotion_pulse", "price_war", "stockout", "seasonal_growth")
NOISE_PREFIXES = ("[OFFICIAL]", "[GIAO NHANH]", "[DATE MỚI]", "[PROMO]", "")
COMPANY_IDS = sorted({spec[1] for spec in FAMILY_SPECS})


@dataclass
class SyntheticConfig:
    canonical_count: int = 250
    sellers_per_product: int = 3
    days: int = 120
    seed: int = 303


def _round_price(value: float, currency: str) -> int:
    step = 100 if currency == "VND" else 100
    return max(step, int(round(value / step) * step))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    fields = list(rows[0])
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _relation(a: dict[str, Any], b: dict[str, Any]) -> str:
    if a["country_code"] != b["country_code"]:
        return "not_comparable"
    if a["canonical_product_id"] == b["canonical_product_id"]:
        return "same_product" if a["pack_count"] == b["pack_count"] else "same_product_variant"
    if a["product_type"] == b["product_type"]:
        return "substitute"
    return "near_match"


def generate_dataset(output_dir: Path, config: SyntheticConfig) -> dict[str, Any]:
    rng = random.Random(config.seed)
    canonical: list[dict[str, Any]] = []
    offers: list[dict[str, Any]] = []
    variation_prices: list[dict[str, Any]] = []
    economics: list[dict[str, Any]] = []
    promotions: list[dict[str, Any]] = []
    daily: list[dict[str, Any]] = []

    base_combinations = []
    for spec_index, spec in enumerate(FAMILY_SPECS):
        for flavor in spec[6]:
            for weight in spec[7]:
                base_combinations.append((spec_index, spec, flavor, weight))
    rng.shuffle(base_combinations)
    combinations = list(base_combinations)
    while len(combinations) < config.canonical_count:
        combinations.extend(base_combinations[: config.canonical_count - len(combinations)])

    seller_registry: dict[tuple[str, int], tuple[str, str, str, str]] = {}
    for canonical_index, (_, spec, flavor, weight) in enumerate(combinations[: config.canonical_count], 1):
        country, company_id, brand, family, product_type, phrase, _, _ = spec
        currency = "VND" if country == "vn" else "IDR"
        canonical_id = f"SYN-{country.upper()}-{canonical_index:04d}"
        edition = 1 + (canonical_index - 1) // len(base_combinations)
        regime = REGIMES[(canonical_index + config.seed) % len(REGIMES)]
        unit_base = (14000 + weight * 85 + canonical_index % 11 * 900) if currency == "VND" else (12000 + weight * 140)
        canonical_row = {
            "canonical_product_id": canonical_id,
            "country_code": country,
            "currency": currency,
            "company_id": company_id,
            "brand": brand,
            "family": family,
            "product_type": product_type,
            "flavor": flavor,
            "edition": edition,
            "unit_weight_g": weight,
            "regime": regime,
            "latent_base_demand": round(rng.uniform(12, 85), 2),
            "own_price_elasticity": round(rng.uniform(-2.4, -1.1), 3),
            "generator_version": GENERATOR_VERSION,
            "random_seed": config.seed,
            "is_synthetic": True,
        }
        canonical.append(canonical_row)

        pack_pattern = [1, 1, 2, 4]
        for seller_index in range(config.sellers_per_product):
            pack_count = pack_pattern[(canonical_index + seller_index) % len(pack_pattern)]
            seller_entity_id = f"{company_id}_distributor_{seller_index + 1}"
            seller_name = f"{brand} Distributor {seller_index + 1}"
            shop_id = (100_000 if country == "vn" else 900_000) + COMPANY_IDS.index(company_id) * 100 + seller_index + 1
            seller_registry[(country, shop_id)] = (company_id, brand, seller_entity_id, seller_name)
            item_id = canonical_index * 100 + seller_index + (1_000_000 if country == "vn" else 2_000_000)
            multi_option = (canonical_index + seller_index) % 5 == 0
            options = [f"Combo {pack_count}", f"Combo {pack_count * 2}", f"Combo {pack_count * 3}"] if multi_option else [f"Combo {pack_count}"]
            prefix = NOISE_PREFIXES[(canonical_index + seller_index) % len(NOISE_PREFIXES)]
            combo = f"Combo {pack_count} " if pack_count > 1 else ""
            title = f"{prefix} {combo}{phrase} {brand} {family} dòng S{edition} vị {flavor} {weight:g}g".strip()
            seller_factor = 0.96 + seller_index * 0.035
            base_price = _round_price(unit_base * pack_count * seller_factor, currency)
            listed_price = _round_price(base_price / rng.uniform(0.72, 0.92), currency)
            offer_id = f"{country}:{shop_id}:{item_id}"
            offer = {
                "offer_id": offer_id,
                "canonical_product_id": canonical_id,
                "variant_id": f"{canonical_id}-{flavor}-{weight:g}",
                "country_code": country,
                "currency": currency,
                "shop_id": shop_id,
                "seller_entity_id": seller_entity_id,
                "seller_entity_name": seller_name,
                "item_id": item_id,
                "product_name": title,
                "brand": brand,
                "family": family,
                "product_type": product_type,
                "flavor": flavor,
                "unit_weight_g": weight,
                "pack_count": pack_count,
                "total_weight_g": round(weight * pack_count, 2),
                "displayed_price": base_price,
                "listed_price": listed_price,
                "tier_variation_options": json.dumps(options, ensure_ascii=False),
                "selected_option": options[0],
                "multi_option": multi_option,
                "generator_version": GENERATOR_VERSION,
                "random_seed": config.seed,
                "is_synthetic": True,
            }
            offers.append(offer)
            for option_index, option in enumerate(options, 1):
                option_pack = pack_count * option_index
                variation_prices.append({
                    "offer_id": offer_id,
                    "variation_option": option,
                    "pack_count": option_pack,
                    "variation_price": _round_price(base_price * option_index * (0.98 ** (option_index - 1)), currency),
                    "is_default_option": option_index == 1,
                    "ground_truth_selected_option": options[0],
                    "is_synthetic": True,
                })

            cost_pct = rng.uniform(0.58, 0.73)
            cogs = _round_price(base_price * cost_pct, currency)
            platform_fee_pct = round(rng.uniform(4.0, 10.0), 2)
            fulfillment = _round_price(base_price * rng.uniform(0.025, 0.06), currency)
            return_rate = round(rng.uniform(0.01, 0.08), 4)
            platform_fee_value = base_price * platform_fee_pct / 100.0
            payment_fee_value = base_price * 0.02
            expected_return_cost = cogs * return_rate
            contribution = base_price - cogs - platform_fee_value - payment_fee_value - fulfillment - expected_return_cost
            economics.append({
                "offer_id": offer_id,
                "base_checkout_price": base_price,
                "cogs": cogs,
                "cogs_low": _round_price(cogs * 0.94, currency),
                "cogs_high": _round_price(cogs * 1.08, currency),
                "platform_fee_pct": platform_fee_pct,
                "payment_fee_pct": 2.0,
                "fulfillment_cost": fulfillment,
                "expected_return_rate": return_rate,
                "expected_return_cost": _round_price(expected_return_cost, currency),
                "contribution_margin_value": int(round(contribution / 100.0) * 100),
                "contribution_margin_pct": round(contribution / base_price * 100.0, 2),
                "minimum_gross_margin_pct": 15.0,
                "ground_truth_cost": True,
                "is_synthetic": True,
            })

            promo_start = 25 + (canonical_index * 7 + seller_index * 3) % max(30, config.days - 35)
            promo_length = 5 + canonical_index % 9
            promo_pct = 8 + (canonical_index + seller_index) % 18
            promo_id = f"PROMO-{canonical_index:04d}-{seller_index + 1}"
            promotions.append({
                "promotion_id": promo_id,
                "offer_id": offer_id,
                "start_day": promo_start,
                "end_day": min(config.days - 1, promo_start + promo_length),
                "minimum_spend": _round_price(base_price * 0.8, currency),
                "discount_pct": promo_pct,
                "discount_cap": _round_price(base_price * 0.2, currency),
                "seller_funded_pct": 60,
                "platform_funded_pct": 40,
                "stackable": False,
                "ground_truth_event": "promotion_pulse",
                "is_synthetic": True,
            })

            stock = int(rng.uniform(120, 420))
            latent_base = canonical_row["latent_base_demand"] * (0.9 + seller_index * 0.08)
            elasticity = canonical_row["own_price_elasticity"]
            cumulative_sold = 0
            for day_index in range(config.days):
                day = START_DATE + timedelta(days=day_index)
                weekly = 1.0 + 0.12 * math.sin(2 * math.pi * day.weekday() / 7)
                trend = 1.0 + (0.0025 * day_index if regime == "seasonal_growth" else 0.0)
                promo_active = promo_start <= day_index <= promo_start + promo_length
                discount_pct = promo_pct if promo_active else 0
                regime_price_factor = 1.0
                if regime == "price_war" and day_index >= 60:
                    regime_price_factor = 0.88 - 0.01 * seller_index
                checkout = _round_price(base_price * regime_price_factor * (1 - discount_pct / 100), currency)
                price_ratio = max(0.5, checkout / base_price)
                latent_demand = latent_base * weekly * trend * (price_ratio ** elasticity)
                if promo_active:
                    latent_demand *= 1.12
                if regime == "stockout" and 48 <= day_index <= 62:
                    stock = min(stock, 3)
                noise = max(0.2, rng.gauss(1.0, 0.16))
                demand_units = max(0, int(round(latent_demand * noise)))
                observed_units = min(stock, demand_units)
                stockout = observed_units < demand_units
                stock -= observed_units
                cumulative_sold += observed_units
                if day_index % 14 == 13:
                    stock += int(rng.uniform(180, 360))
                missing = rng.random() < 0.008
                outlier = rng.random() < 0.002
                observed_price = checkout * (10 if outlier else 1)
                event_label = "none"
                if day_index == promo_start:
                    event_label = "promotion_started"
                elif day_index == promo_start + promo_length + 1:
                    event_label = "promotion_ended"
                elif regime == "price_war" and day_index == 60:
                    event_label = "structural_price_drop"
                elif stockout:
                    event_label = "stockout_censoring"
                daily.append({
                    "snapshot_date": day.isoformat(),
                    "day_index": day_index,
                    "offer_id": offer_id,
                    "canonical_product_id": canonical_id,
                    "country_code": country,
                    "currency": currency,
                    "displayed_price": "" if missing else observed_price,
                    "checkout_price": "" if missing else checkout,
                    "discount_pct": "" if missing else discount_pct,
                    "promotion_active": promo_active,
                    "latent_demand_units": round(latent_demand, 2),
                    "demand_units_before_stock": demand_units,
                    "observed_units_sold": "" if missing else observed_units,
                    "cumulative_units_sold": cumulative_sold,
                    "stock_on_hand": "" if missing else stock,
                    "stockout_flag": stockout,
                    "ground_truth_event": event_label,
                    "regime": regime,
                    "data_quality_flag": "missing_snapshot" if missing else "price_outlier" if outlier else "valid",
                    "generator_version": GENERATOR_VERSION,
                    "random_seed": config.seed,
                    "is_synthetic": True,
                })

    by_canonical: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_country_type: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    by_country: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for offer in offers:
        by_canonical[offer["canonical_product_id"]].append(offer)
        by_country_type[(offer["country_code"], offer["product_type"])].append(offer)
        by_country[offer["country_code"]].append(offer)
    ground_pairs: list[dict[str, Any]] = []
    for source in offers:
        candidates: list[dict[str, Any]] = []
        same = [x for x in by_canonical[source["canonical_product_id"]] if x["seller_entity_id"] != source["seller_entity_id"]]
        candidates.extend(same[:2])
        substitutes = [x for x in by_country_type[(source["country_code"], source["product_type"])] if x["canonical_product_id"] != source["canonical_product_id"]]
        if substitutes:
            candidates.append(substitutes[(source["item_id"] + config.seed) % len(substitutes)])
        near = [x for x in by_country[source["country_code"]] if x["product_type"] != source["product_type"]]
        if near:
            candidates.append(near[(source["item_id"] + 3) % len(near)])
        other_country = "id" if source["country_code"] == "vn" else "vn"
        if by_country[other_country]:
            candidates.append(by_country[other_country][source["item_id"] % len(by_country[other_country])])
        for target in dict.fromkeys(x["offer_id"] for x in candidates):
            target_row = next(x for x in candidates if x["offer_id"] == target)
            ground_pairs.append({
                "pair_key": f'{source["offer_id"]}->{target_row["offer_id"]}',
                "source_offer_id": source["offer_id"],
                "target_offer_id": target_row["offer_id"],
                "ground_truth_label": _relation(source, target_row),
                "difference_driver": (
                    "seller_only" if source["canonical_product_id"] == target_row["canonical_product_id"] and source["pack_count"] == target_row["pack_count"]
                    else "pack_count" if source["canonical_product_id"] == target_row["canonical_product_id"]
                    else "product_identity" if source["product_type"] == target_row["product_type"]
                    else "category_or_country"
                ),
                "is_hard_negative": source["product_type"] == target_row["product_type"] and source["canonical_product_id"] != target_row["canonical_product_id"],
                "generator_version": GENERATOR_VERSION,
                "random_seed": config.seed,
                "is_synthetic": True,
            })

    files = {
        "canonical_products.csv": canonical,
        "offers.csv": offers,
        "variation_prices.csv": variation_prices,
        "unit_economics.csv": economics,
        "promotion_terms.csv": promotions,
        "daily_market.csv": daily,
        "matching_ground_truth.csv": ground_pairs,
    }
    for name, rows in files.items():
        _write_csv(output_dir / name, rows)

    report = validate_dataset(canonical, offers, variation_prices, economics, promotions, daily, ground_pairs)
    report["config"] = asdict(config)
    report["generator_version"] = GENERATOR_VERSION
    report["files"] = {
        name: {
            "rows": len(rows),
            "sha256": hashlib.sha256((output_dir / name).read_bytes()).hexdigest(),
        }
        for name, rows in files.items()
    }
    (output_dir / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"report": report, "offers": offers, "seller_registry": seller_registry}


def validate_dataset(
    canonical: list[dict[str, Any]],
    offers: list[dict[str, Any]],
    variation_prices: list[dict[str, Any]],
    economics: list[dict[str, Any]],
    promotions: list[dict[str, Any]],
    daily: list[dict[str, Any]],
    ground_pairs: list[dict[str, Any]],
) -> dict[str, Any]:
    offer_ids = {row["offer_id"] for row in offers}
    econ_ids = {row["offer_id"] for row in economics}
    default_counts = Counter(row["offer_id"] for row in variation_prices if row["is_default_option"])
    listed_by_offer = {row["offer_id"]: float(row["listed_price"]) for row in offers}
    violations = {
        "duplicate_offer_id": len(offers) - len(offer_ids),
        "missing_unit_economics": len(offer_ids - econ_ids),
        "invalid_default_variation_count": sum(default_counts[offer_id] != 1 for offer_id in offer_ids),
        "cogs_not_below_displayed_price": sum(
            econ["cogs"] >= offer["displayed_price"] for econ, offer in zip(economics, offers)
        ),
        "observed_sales_exceed_demand": sum(
            int(row["observed_units_sold"] or 0) > int(row["demand_units_before_stock"]) for row in daily
        ),
        "checkout_above_listed_price": sum(
            row["checkout_price"] != "" and float(row["checkout_price"]) > listed_by_offer[row["offer_id"]]
            for row in daily
        ),
    }
    return {
        "status": "valid" if not any(violations.values()) else "invalid",
        "row_counts": {
            "canonical_products": len(canonical),
            "offers": len(offers),
            "variation_prices": len(variation_prices),
            "unit_economics": len(economics),
            "promotion_terms": len(promotions),
            "daily_market": len(daily),
            "matching_ground_truth": len(ground_pairs),
        },
        "ground_truth_distribution": dict(Counter(row["ground_truth_label"] for row in ground_pairs)),
        "regime_distribution": dict(Counter(row["regime"] for row in canonical)),
        "data_quality_distribution": dict(Counter(row["data_quality_flag"] for row in daily)),
        "unit_economics_summary": {
            "negative_contribution_offers": sum(float(row["contribution_margin_value"]) < 0 for row in economics),
            "below_15pct_contribution_offers": sum(float(row["contribution_margin_pct"]) < 15 for row in economics),
            "median_contribution_margin_pct": round(
                sorted(float(row["contribution_margin_pct"]) for row in economics)[len(economics) // 2], 2
            ),
        },
        "violations": violations,
    }


def benchmark_matching(output_dir: Path, offers: list[dict[str, Any]], registry: dict[tuple[str, int], tuple[str, str, str, str]]) -> dict[str, Any]:
    products: list[Product] = []
    by_key: dict[tuple[str, int, int], dict[str, Any]] = {}
    for row in offers:
        product = Product(
            row["country_code"], row["currency"], (START_DATE + timedelta(days=119)).isoformat(),
            int(row["shop_id"]), row["seller_entity_name"], int(row["item_id"]),
            row["product_name"], row["brand"], float(row["displayed_price"]),
            100 + sum(ord(char) for char in row["product_type"]) % 100,
            None, None, None, None, False, False, "Phân loại", row["tier_variation_options"],
        )
        products.append(parse_product(product))
        by_key[(product.country_code, product.shop_id, product.item_id)] = row
    assign_companies(products, registry)
    embeddings, model_version = create_embeddings(products, "tfidf")
    ranked = rank_matches(products, build_similarity_matrix(embeddings), model_version, top_k=5, min_score=0.60)
    top_rows = [row for row in ranked if row["rank"] == 1 and row["target_item_id"] is not None]
    identity_sources = 0
    identity_hit = 0
    relation_correct = 0
    relation_confusion: dict[str, Counter[str]] = defaultdict(Counter)
    for row in top_rows:
        source = by_key[(row["country_code"], row["source_shop_id"], row["source_item_id"])]
        target = by_key[(row["country_code"], row["target_shop_id"], row["target_item_id"])]
        actual = _relation(source, target)
        predicted = row["match_type"]
        relation_confusion[actual][predicted] += 1
        relation_correct += actual == predicted
        has_identity = any(
            other["canonical_product_id"] == source["canonical_product_id"]
            and other["seller_entity_id"] != source["seller_entity_id"]
            for other in offers
        )
        if has_identity:
            identity_sources += 1
            identity_hit += actual in {"same_product", "same_product_variant"}
    multi = [p for p in products if by_key[(p.country_code, p.shop_id, p.item_id)]["multi_option"]]
    report = {
        "sources": len(products),
        "top1_rows": len(top_rows),
        "top1_relation_accuracy": round(relation_correct / len(top_rows), 4) if top_rows else None,
        "identity_retrieval_at_1": round(identity_hit / identity_sources, 4) if identity_sources else None,
        "multi_option_gate_recall": round(sum(p.price_variant_ambiguous for p in multi) / len(multi), 4) if multi else None,
        "confusion_matrix": {actual: dict(predicted) for actual, predicted in relation_confusion.items()},
        "model_version": model_version,
        "evaluation_scope": "synthetic_regression_only_not_real_world_accuracy",
    }
    (output_dir / "matching_benchmark.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("./synthetic/market_benchmark_v1"))
    parser.add_argument("--canonical-count", type=int, default=250)
    parser.add_argument("--sellers-per-product", type=int, default=3)
    parser.add_argument("--days", type=int, default=120)
    parser.add_argument("--seed", type=int, default=303)
    parser.add_argument("--skip-matching-benchmark", action="store_true")
    args = parser.parse_args()
    config = SyntheticConfig(args.canonical_count, args.sellers_per_product, args.days, args.seed)
    result = generate_dataset(args.output_dir, config)
    output = {"generation": result["report"]}
    if not args.skip_matching_benchmark:
        output["matching_benchmark"] = benchmark_matching(args.output_dir, result["offers"], result["seller_registry"])
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if result["report"]["status"] == "valid" else 1


if __name__ == "__main__":
    raise SystemExit(main())
