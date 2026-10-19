"""Durable batch progress with a heartbeat during blocking CPU and file work."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import threading
import time
import uuid


def atomic_json(path, value, *, attempts=8, delay=.01, recovery=None):
    """Publish JSON with bounded retry for transient Windows sharing violations."""
    path = Path(path)
    temporary = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        encoded = json.dumps(value, indent=2).encode('utf-8')
        temporary.write_bytes(encoded)
        from keel.experience import RecoverySession, environment
        session = recovery or RecoverySession(task='atomic_json', max_actions=attempts-1)
        def probe(error):
            sibling = path.with_name(path.name+'.'+uuid.uuid4().hex+'.probe')
            try:
                sibling.write_bytes(b'probe')
                moved = sibling.with_suffix('.moved')
                import os
                os.replace(sibling, moved)
                moved.unlink()
                return {'applicable': True, 'check': 'sibling_create_replace_delete_passed',
                        'root_cause': 'undetermined_target_lock_or_target_acl'}
            except OSError:
                return {'applicable': False, 'check': 'parent_write_probe_failed'}
            finally:
                sibling.unlink(missing_ok=True)
        def verify(_):
            return path.read_bytes() == encoded
        session.run(lambda: temporary.replace(path), stage='atomic_publish',
            facts=environment(parent=str(path.parent.resolve())),
            classify=lambda error: 'permission' if isinstance(error, PermissionError) else type(error).__name__,
            actions={'retry_replace_v1': {'categories': ['permission'], 'probe': probe,
                'apply': lambda remaining: time.sleep(min(delay*2**max(0, session.used_actions-1), .2, remaining))}},
            verify=verify)
    finally:
        temporary.unlink(missing_ok=True)


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
