"""Evaluate manually labeled Product Matching review pairs."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


STRICT_RELEVANT = {"same_product"}
PEER_RELEVANT = {"same_product", "same_product_variant", "substitute", "near_match"}


def evaluate(path: Path, labels_path: Path | None = None) -> dict:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    label_join = "none"
    if labels_path and labels_path.exists():
        with labels_path.open("r", encoding="utf-8", newline="") as handle:
            label_rows = list(csv.DictReader(handle))
        if label_rows and label_rows[0].get("pair_key") and rows and rows[0].get("pair_key"):
            labels = {row["pair_key"]: row for row in label_rows}
            label_join = "pair_key"
            for row in rows:
                label = labels.get(row["pair_key"])
                if label:
                    row["review_label"] = label.get("review_label", "")
                    row["review_notes"] = label.get("review_notes", "")
        elif not rows or not rows[0].get("pair_key"):
            labels = {row["review_id"]: row for row in label_rows}
            label_join = "legacy_review_id"
            for row in rows:
                label = labels.get(row["review_id"])
                if label:
                    row["review_label"] = label.get("review_label", "")
                    row["review_notes"] = label.get("review_notes", "")
    labeled = [row for row in rows if row.get("review_label", "").strip()]
    pending = len(rows) - len(labeled)
    review_stratum_counts: dict[str, int] = {}
    review_stratum_sources: dict[str, set[tuple[str, str, str]]] = {}
    for row in rows:
        stratum = row.get("review_stratum", "legacy_unstratified") or "legacy_unstratified"
        review_stratum_counts[stratum] = review_stratum_counts.get(stratum, 0) + 1
        review_stratum_sources.setdefault(stratum, set()).add(
            (row["country_code"], row["source_shop_id"], row["source_item_id"])
        )
    groups: dict[tuple[str, str, str], list[dict]] = {}
    for row in labeled:
        key = (row["country_code"], row["source_shop_id"], row["source_item_id"])
        groups.setdefault(key, []).append(row)
    complete = [sorted(group, key=lambda row: int(row["rank"])) for group in groups.values() if len(group) == 5]
    matchable = [group for group in complete if group[0].get("source_status") == "matchable"]
    abstained = [group for group in complete if group[0].get("source_status") == "not_enough_evidence"]
    peer_p_at_1 = sum(group[0]["review_label"].strip() in PEER_RELEVANT for group in matchable) / len(matchable) if matchable else None
    peer_p_at_5 = sum(sum(row["review_label"].strip() in PEER_RELEVANT for row in group) / 5 for group in matchable) / len(matchable) if matchable else None
    strict_p_at_1 = sum(group[0]["review_label"].strip() in STRICT_RELEVANT for group in matchable) / len(matchable) if matchable else None
    strict_p_at_5 = sum(sum(row["review_label"].strip() in STRICT_RELEVANT for row in group) / 5 for group in matchable) / len(matchable) if matchable else None
    labels = sorted({row["review_label"].strip() for row in labeled})
    class_metrics: dict[str, dict[str, float | int | None]] = {}
    confusion: dict[str, dict[str, int]] = {}
    for row in labeled:
        actual, predicted = row["review_label"].strip(), row.get("match_type", "").strip()
        confusion.setdefault(actual, {})[predicted] = confusion.setdefault(actual, {}).get(predicted, 0) + 1
    for label in labels:
        tp = sum(row["review_label"].strip() == label and row.get("match_type", "").strip() == label for row in labeled)
        fp = sum(row["review_label"].strip() != label and row.get("match_type", "").strip() == label for row in labeled)
        fn = sum(row["review_label"].strip() == label and row.get("match_type", "").strip() != label for row in labeled)
        precision = tp / (tp + fp) if tp + fp else None
        recall = tp / (tp + fn) if tp + fn else None
        f1 = 2 * precision * recall / (precision + recall) if precision is not None and recall is not None and precision + recall else None
        class_metrics[label] = {"support": tp + fn, "precision": precision, "recall": recall, "f1": f1}
    return {
        "review_file": str(path), "total_pairs": len(rows), "labeled_pairs": len(labeled),
        "sampling_design": "stratified_qa_not_population_weighted",
        "review_stratum_pairs": review_stratum_counts,
        "review_stratum_sources": {key: len(value) for key, value in review_stratum_sources.items()},
        "label_join": label_join,
        "pending_pairs": pending, "complete_sources": len(complete), "matchable_sources": len(matchable),
        "abstained_sources": len(abstained),
        "peer_precision_at_1": peer_p_at_1, "peer_precision_at_5": peer_p_at_5,
        "strict_precision_at_1": strict_p_at_1, "strict_precision_at_5": strict_p_at_5,
        "coverage_on_review_sources": len(matchable) / len(complete) if complete else None,
        "class_metrics": class_metrics, "confusion_matrix": confusion,
        "targets": {"peer_precision_at_1": 0.80, "peer_precision_at_5": 0.70},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-file", default="./warehouse/matching_review.csv", type=Path)
    parser.add_argument("--labels-file", default="./validation/matching_review_labels.csv", type=Path)
    args = parser.parse_args()
    print(json.dumps(evaluate(args.review_file, args.labels_file), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
