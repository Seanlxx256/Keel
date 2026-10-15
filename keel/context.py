"""Bounded selection of file-read evidence at trusted role boundaries."""
import hashlib


def handoff_context(target, sources, files, limit=4):
    allowed = {target.ws.path(name).relative_to(target.ws.root).as_posix() for name in files}
    selected, seen = [], set()
    for source in reversed(sources):
        if source.ws is not target.ws:
            raise ValueError("Context sources must belong to the same workspace")
        for fact_id in sorted(source.read_evidence, reverse=True):
            metadata = source.read_evidence[fact_id]
            name = metadata["path"]
            if name not in allowed or name in seen:
                continue
            target.ws.budget.check()
            try:
                raw = target.ws.path(name).read_bytes()
            except OSError:
                continue
            if hashlib.sha256(raw).hexdigest() != metadata["sha256"]:
                continue
            selected.append((source, fact_id, metadata))
            seen.add(name)
            if len(selected) == limit:
                break
        if len(selected) == limit:
            break
    references = []
    for source, fact_id, metadata in selected:
        reference = target.accept_evidence(source, [fact_id])[0]
        references.append({**reference, **metadata, "freshness": "matched source bytes at selection"})
    target.ws.handed_off_facts = getattr(target.ws, "handed_off_facts", 0) + len(references)
    target.ws.trace.emit(target.role, "context_selected", files=len(allowed), facts=len(references), limit=limit)
    return references
