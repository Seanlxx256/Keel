"""Verified operational experience. Stored records never supply executable code."""
from contextlib import contextmanager
import json
import platform
import sqlite3
import sys
import time
import subprocess
from pathlib import Path


def environment(**facts):
    return dict(system=platform.system(), python=platform.python_version(),
                interpreter=str(Path(sys.executable).resolve()), **facts)


def probe_interpreter(interpreter, modules, *, timeout=10):
    """Check the actual child interpreter, without installing into the host."""
    script = ('import importlib,importlib.metadata,json,sys; '
              'names=json.loads(sys.argv[1]); '
              'print(json.dumps({"interpreter":sys.executable,"version":sys.version,'
              '"modules":{name:importlib.import_module(name).__file__ for name in names}}))')
    result = subprocess.run([str(interpreter), '-c', script, json.dumps(modules)],
                            capture_output=True, text=True, timeout=timeout)
    return dict(passed=result.returncode == 0, interpreter=str(interpreter),
                facts=json.loads(result.stdout) if result.returncode == 0 else None,
                error=result.stderr[-1500:] if result.returncode else None)


class ExperienceStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS attempts '
                       '(task TEXT, signature TEXT, action TEXT, outcome TEXT, evidence TEXT)')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=2)
        try:
            with db:
                yield db
        finally:
            db.close()

    def record(self, task, signature, action, outcome, evidence):
        with self.connect() as db:
            db.execute('INSERT INTO attempts VALUES(?,?,?,?,?)',
                       (task, signature, action, outcome, json.dumps(evidence, sort_keys=True)))

    def verified(self, signature, action):
        with self.connect() as db:
            return db.execute('SELECT task FROM attempts WHERE signature=? AND action=? '
                              'AND outcome="verified" LIMIT 1', (signature, action)).fetchone()


class RecoverySession:
    """Bounded observe/probe/act/verify loop with exact applicability matching.

    Unknown failures may use a caller's diagnostic callback, which returns only
    registered action IDs. Callbacks must obey the supplied remaining deadline;
    blocking operations still require their parent process watchdog.
    """
    def __init__(self, *, task, store=None, max_actions=2, deadline=None, diagnose=None):
        if not 0 <= max_actions <= 12:
            raise ValueError('max_actions must be between 0 and 12')
        self.task, self.store = task, store
        self.max_actions, self.deadline, self.diagnose = max_actions, deadline, diagnose
        self.used_actions = 0
        self.events = []

    def remaining(self):
        return float('inf') if self.deadline is None else max(0, self.deadline-time.monotonic())

    def run(self, operation, *, stage, facts, classify, actions, verify):
        self.events.append(dict(event='preflight', stage=stage, facts=facts))
        pending = []
        seen = set()
        while True:
            if self.remaining() <= 0:
                raise TimeoutError('Recovery operation wall-clock budget exhausted')
            try:
                result = operation()
                if verify(result) is not True:
                    raise ValueError('Recovery result verification failed')
            except Exception as error:
                for signature, action, evidence in pending:
                    self._record(signature, action, 'failed', dict(evidence, next_error=type(error).__name__))
                pending.clear()
                category = classify(error)
                signature = json.dumps(dict(stage=stage, category=category, facts=facts), sort_keys=True)
                self.events.append(dict(event='observed', category=category, error_type=type(error).__name__))
                if self.used_actions >= self.max_actions or self.remaining() <= 0:
                    raise
                candidates = [key for key, value in actions.items() if category in value['categories']]
                known = [key for key in candidates if self.store and self.store.verified(signature, key)]
                self.events.append(dict(event='retrieved', actions=known))
                if not candidates and self.diagnose and category not in seen:
                    seen.add(category)
                    self.used_actions += 1
                    proposed = self.diagnose(dict(category=category, stage=stage, facts=facts,
                                                  error_type=type(error).__name__), self.remaining())
                    candidates = [proposed] if proposed in actions else []
                selected = None
                for key in known + [key for key in candidates if key not in known]:
                    evidence = actions[key]['probe'](error)
                    self.events.append(dict(event='applicability', action=key, evidence=evidence))
                    if evidence.get('applicable') is True:
                        selected = key
                        break
                    self._record(signature, key, 'inapplicable', evidence)
                if selected is None or self.used_actions >= self.max_actions:
                    self._record(signature, '', 'unresolved', dict(error_type=type(error).__name__))
                    raise
                self.used_actions += 1
                try:
                    actions[selected]['apply'](self.remaining())
                except Exception as action_error:
                    self._record(signature, selected, 'failed', dict(error_type=type(action_error).__name__))
                    raise
                pending.append((signature, selected, evidence))
                self.events.append(dict(event='executed', action=selected))
                continue
            for signature, action, evidence in pending:
                self._record(signature, action, 'verified', dict(evidence, validation='operation_and_validator_passed'))
            return result

    def _record(self, signature, action, outcome, evidence):
        self.events.append(dict(event=outcome, action=action, evidence=evidence))
        if self.store:
            self.store.record(self.task, signature, action, outcome, evidence)
