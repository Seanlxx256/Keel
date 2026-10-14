"""Dependency-free Compass smoke demo; no semantic-quality claims."""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compass.index import RepositoryIndex, build_index
from compass.vectors import HashEmbedder


def main():
    with tempfile.TemporaryDirectory(prefix="compass-demo-") as directory:
        repo = Path(directory)
        (repo / "payments.py").write_bytes(
            b'def calculate_total(amount):\n    """Calculate invoice totals."""\n    return amount * 1.1\n')
        (repo / "checkout.py").write_bytes(
            b"from payments import calculate_total\n\ndef checkout(amount):\n    return calculate_total(amount)\n")
        stats = build_index(repo, parser="python-ast", vector_store="sqlite", embedder=HashEmbedder())
        with RepositoryIndex(repo) as index:
            symbol = index.find_symbol("calculate_total")["results"][0]
            graph = index.context("checkout.py", 4)
            hits = index.search_vector("calculate invoice totals", limit=1)["results"]
            output = {"parser": stats["parser"], "vector_store": stats["vector_store"],
                      "embedding": stats["embedding"], "files": stats["files"], "symbols": stats["symbols"],
                      "resolved_calls": stats["resolved_calls"],
                      "symbol": {key: symbol[key] for key in ("name", "path", "start_line", "signature")},
                      "outgoing": graph["outgoing"], "top_vector_hit": hits[0]["name"]}
        (repo / "payments.py").write_bytes(b"def calculate_total(amount):\n    return amount\n")
        with RepositoryIndex(repo) as index:
            output["stale_after_edit"] = index.stale
        print(json.dumps(output, indent=2))
        return 0 if output["resolved_calls"] == 1 and output["stale_after_edit"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
