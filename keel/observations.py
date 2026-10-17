"""Bounded paths and positions from observed tracebacks, without source lines."""
import re


def workspace_frames(traceback, limit=8):
    frames = []
    omitted = False
    for name, line in re.findall(r'File "/workspace/([^"\n]+)", line (\d+)', str(traceback)):
        parts = name.split('/')
        if (len(name) > 180 or not name.endswith('.py') or any(p in ('', '.', '..') for p in parts)
                or ':' in name or '\\' in name or int(line) <= 0 or int(line) > 10_000_000):
            continue
        item = {'path': name, 'line': int(line)}
        if item not in frames:
            frames.append(item)
    if len(frames) > limit:
        omitted = True
    return frames[-limit:], omitted
