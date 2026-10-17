"""Preserve Linux artifact bytes when the official harness runs on Windows."""
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def linux_artifact_writes():
    original = Path.write_text
    def write_text(path, data, encoding=None, errors=None, newline=None):
        if path.suffix in {'.sh', '.diff', '.patch'}:
            # Disable host newline translation; do not edit the supplied text.
            return original(path, data, encoding=encoding or 'utf-8', errors=errors, newline='\n')
        return original(path, data, encoding=encoding, errors=errors, newline=newline)
    Path.write_text = write_text
    try:
        yield
    finally:
        Path.write_text = original
