import json
from pathlib import Path
import tempfile
import threading
import unittest

from compass.progress import ProgressLog


class ProgressTests(unittest.TestCase):
    def test_heartbeat_retains_active_stage_and_stops_on_error(self):
        seen = threading.Event()
        class Observed(ProgressLog):
            def emit(self, event, **fields):
                super().emit(event, **fields)
                if event == "heartbeat":
                    seen.set()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "progress.jsonl"
            reporter = Observed(path, interval=0.01)
            with self.assertRaisesRegex(ValueError, "fixture"):
                with reporter:
                    reporter.emit("bm25_build_started", dataset="fixture", documents=1000)
                    self.assertTrue(seen.wait(timeout=2))
                    raise ValueError("fixture")
            self.assertFalse(reporter.thread.is_alive())
            records = [json.loads(line) for line in path.read_text().splitlines()]
            heartbeat = next(row for row in records if row["event"] == "heartbeat")
            self.assertEqual(heartbeat["stage"], "bm25_build_started")
            self.assertEqual(heartbeat["dataset"], "fixture")
            self.assertEqual(heartbeat["documents"], 1000)
