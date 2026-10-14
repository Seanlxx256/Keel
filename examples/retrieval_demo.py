"""Synthetic adaptive-retrieval smoke demo with a scripted T2 model, never a benchmark."""
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compass.evaluation import evaluate
from compass.index import RepositoryIndex, build_index
from compass.retrieval import Retriever, Routing
from compass.vectors import HashEmbedder
from keel.models import Reply


class Exploration:
    def __init__(self, seed, target):
        self.actions = iter([{"expand": [seed]}, {"read": target}, {"final": [target]}])

    def complete(self, messages, **kwargs):
        return Reply(json.dumps(next(self.actions)), 20)


def main():
    with tempfile.TemporaryDirectory(prefix="compass-retrieval-") as directory:
        root = Path(directory)
        (root / "storage.py").write_bytes(b'def save_order(payload):\n    """Persist purchase record."""\n    return payload\n')
        (root / "service.py").write_bytes(b'from storage import save_order\ndef submit_order(payload):\n    return save_order(payload)\n')
        build_index(root, parser="python-ast", vector_store="sqlite", embedder=HashEmbedder())
        with RepositoryIndex(root) as index:
            seed = index.find_symbol("save_order")["results"][0]["id"]
            target = index.find_symbol("submit_order")["results"][0]["id"]
            retriever = Retriever(index, routing=Routing(min_relevance=0, min_overlap=0, max_entropy=1))
            exact = retriever.retrieve("save_order")
            hybrid = retriever.retrieve("persist purchase record")
            explored = Retriever(index, model=Exploration(seed, target), routing=Routing(candidates=1)).retrieve(
                "persist purchase record", mode="t2")
            queries = [{"id": "purchase", "query": "persist purchase record", "relevant_files": ["storage.py"], "source": "synthetic-demo"}]
            evaluation = evaluate(index, queries)
            print(json.dumps({"synthetic": True, "t0": {"tier": exact["tier"], "usage": exact["usage"]},
                              "t1": {"tier": hybrid["tier"], "signals": hybrid["signals"]},
                              "t2": {"tier": explored["tier"], "selected": explored["results"][0]["qualname"],
                                     "status": explored["routing"]["mode_status"], "usage": explored["usage"]},
                              "evaluation": evaluation["summary"]}, indent=2))
            return 0 if exact["tier"] == "T0" and hybrid["tier"] == "T1" and explored["tier"] == "T2" else 1


if __name__ == "__main__":
    raise SystemExit(main())
