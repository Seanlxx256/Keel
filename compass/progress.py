"""Durable batch progress with a heartbeat during blocking CPU and file work."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import threading
import time


class ProgressLog:
    def __init__(self, path: Path, *, console=False, interval=10):
        self.path, self.console, self.interval = path, console, interval
        self.started = time.monotonic()
        self.state = {}
        self.lock = threading.Lock()
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self._heartbeat, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *error):
        self.stopped.set()
        self.thread.join(timeout=1)

    def emit(self, event, **fields):
        with self.lock:
            if event != "heartbeat":
                self.state = {"stage": event, **fields}
            record = {"time": datetime.now(timezone.utc).isoformat(),
                      "elapsed_seconds": round(time.monotonic() - self.started, 3),
                      **self.state, "event": event}
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            if self.console:
                detail = " ".join(f"{key}={value}" for key, value in record.items()
                                  if key not in {"time", "event", "elapsed_seconds"})
                print(f"[Compass +{record['elapsed_seconds']:.1f}s] {event} {detail}", file=sys.stderr, flush=True)

    def _heartbeat(self):
        while not self.stopped.wait(self.interval):
            self.emit("heartbeat")
