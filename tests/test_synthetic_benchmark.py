import tempfile
import unittest
from pathlib import Path

from src.synthetic_benchmark import SyntheticConfig, benchmark_matching, generate_dataset


class SyntheticBenchmarkTest(unittest.TestCase):
    def test_generation_is_valid_deterministic_and_benchmarkable(self):
        config = SyntheticConfig(canonical_count=24, sellers_per_product=3, days=30, seed=303)
        with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
            first = generate_dataset(Path(first_dir), config)
            second = generate_dataset(Path(second_dir), config)

            report = first["report"]
            self.assertEqual(report["status"], "valid")
            self.assertEqual(report["row_counts"]["offers"], 72)
            self.assertEqual(report["row_counts"]["daily_market"], 2160)
            self.assertTrue(all(value == 0 for value in report["violations"].values()))
            self.assertEqual(
                report["files"]["daily_market.csv"]["sha256"],
                second["report"]["files"]["daily_market.csv"]["sha256"],
            )

            benchmark = benchmark_matching(Path(first_dir), first["offers"], first["seller_registry"])
            self.assertEqual(benchmark["sources"], 72)
            self.assertEqual(benchmark["multi_option_gate_recall"], 1.0)
            self.assertGreater(benchmark["identity_retrieval_at_1"], 0.5)


if __name__ == "__main__":
    unittest.main()
