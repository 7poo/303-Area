import unittest

import duckdb

from src.pipeline import ensure_manifest, finish_run, latest_successful_run, start_run


class PipelineManifestTest(unittest.TestCase):
    def test_running_stage_is_not_published_until_success(self):
        conn = duckdb.connect(":memory:")
        ensure_manifest(conn)
        run_id = start_run(conn, "market_signals")
        self.assertIsNone(latest_successful_run(conn, "market_signals"))
        finish_run(conn, run_id, "success", {"rows": 1})
        published = latest_successful_run(conn, "market_signals")
        self.assertEqual(published["run_id"], run_id)
        conn.close()


if __name__ == "__main__":
    unittest.main()
