import csv
import tempfile
import unittest
from pathlib import Path

from src.evaluate_matching import evaluate


class MatchingEvaluationTest(unittest.TestCase):
    def test_stable_pair_key_join_and_class_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            review_path = Path(directory) / "review.csv"
            labels_path = Path(directory) / "labels.csv"
            fields = ["review_id", "pair_key", "country_code", "source_shop_id", "source_item_id", "rank", "source_status", "match_type", "review_label", "review_notes"]
            rows = []
            predictions = ["same_product", "same_product_variant", "substitute", "near_match", "not_comparable"]
            actual = ["same_product", "same_product_variant", "near_match", "near_match", "not_comparable"]
            for index, prediction in enumerate(predictions, 1):
                rows.append({"review_id": str(index), "pair_key": f"vn:1:10:2:{index}", "country_code": "vn", "source_shop_id": "1", "source_item_id": "10", "rank": str(index), "source_status": "matchable", "match_type": prediction, "review_label": "", "review_notes": ""})
            with review_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader(); writer.writerows(rows)
            with labels_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["pair_key", "review_label", "review_notes"]); writer.writeheader()
                for row, label in zip(rows, actual):
                    writer.writerow({"pair_key": row["pair_key"], "review_label": label, "review_notes": ""})
            result = evaluate(review_path, labels_path)
            self.assertEqual(result["label_join"], "pair_key")
            self.assertEqual(result["labeled_pairs"], 5)
            self.assertEqual(result["class_metrics"]["same_product"]["f1"], 1.0)
            self.assertEqual(result["confusion_matrix"]["near_match"]["substitute"], 1)
            self.assertEqual(result["sampling_design"], "stratified_qa_not_population_weighted")
            self.assertEqual(result["review_stratum_sources"]["legacy_unstratified"], 1)


if __name__ == "__main__":
    unittest.main()
