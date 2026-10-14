import argparse
import json
from pathlib import Path
import sqlite3

from .index import RepositoryIndex, build_index
from .vectors import HashEmbedder, OllamaEmbedder
from .retrieval import Retriever, routing_from_dict
from keel.core import Budget, BudgetExceeded, Limits, ModelError
from keel.models import OllamaModel


def main(argv=None):
    parser = argparse.ArgumentParser(prog="compass", description="Repository-local Python symbol, graph and vector index")
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("index", help="Build and atomically publish a full index generation")
    build.add_argument("--repo", type=Path, required=True)
    build.add_argument("--parser", choices=["tree-sitter", "python-ast"], default="tree-sitter")
    build.add_argument("--vectors", choices=["none", "sqlite", "lancedb"], default="none")
    build.add_argument("--embedding", choices=["hash", "ollama"])
    build.add_argument("--embedding-model")
    build.add_argument("--embedding-url", default="http://localhost:11434")
    build.add_argument("--dimensions", type=int, default=128, help="Hash embedding dimensions")
    for name in ("symbol", "context", "search", "status"):
        command = sub.add_parser(name)
        command.add_argument("--repo", type=Path, required=True)
        if name in {"symbol", "search"}:
            command.add_argument("query")
        if name == "context":
            command.add_argument("file")
            command.add_argument("line", type=int)
        if name != "status":
            command.add_argument("--limit", type=int, default=10)
    for name in ("retrieve", "evaluate"):
        command = sub.add_parser(name, help="Adaptive retrieval" if name == "retrieve" else "Evaluate normalized JSONL queries")
        command.add_argument("--repo", type=Path, required=True)
        command.add_argument("--limit", type=int, default=10)
        command.add_argument("--routing", type=Path, help="Optional JSON routing settings")
        command.add_argument("--model", help="Ollama chat model for opt-in T2 exploration")
        command.add_argument("--model-url", default="http://localhost:11434")
        command.add_argument("--max-tokens", type=int, default=20000)
        command.add_argument("--max-model-calls", type=int, default=8)
        command.add_argument("--max-tool-calls", type=int, default=100)
        command.add_argument("--max-wallclock", type=float, default=120)
        if name == "retrieve":
            command.add_argument("query")
            command.add_argument("--mode", choices=["adaptive", "t0", "t1", "t2"], default="adaptive")
        else:
            command.add_argument("--dataset", type=Path, required=True)
            command.add_argument("--modes", nargs="+", choices=["adaptive", "t0", "t1", "t2"], default=["t0", "t1", "adaptive"])
            command.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "index":
            embedder = None
            if args.embedding and args.vectors == "none":
                raise ValueError("--embedding requires --vectors sqlite or lancedb")
            if args.embedding == "hash":
                embedder = HashEmbedder(args.dimensions)
            elif args.embedding == "ollama":
                embedder = OllamaEmbedder(args.embedding_model, args.embedding_url)
            result = build_index(args.repo, parser=args.parser, vector_store=args.vectors, embedder=embedder)
        else:
            with RepositoryIndex(args.repo) as index:
                if args.command in {"retrieve", "evaluate"}:
                    routing = routing_from_dict(json.loads(args.routing.read_text(encoding="utf-8")) if args.routing else None)
                    model = OllamaModel(args.model, args.model_url) if args.model else None
                    limits = Limits(max_tokens=args.max_tokens, max_model_calls=args.max_model_calls,
                                    max_tool_calls=args.max_tool_calls, max_wallclock=args.max_wallclock)
                    if args.command == "retrieve":
                        result = Retriever(index, routing=routing, model=model, budget=Budget(limits)).retrieve(args.query, args.limit, args.mode)
                    else:
                        from .evaluation import evaluate, load_queries
                        result = evaluate(index, load_queries(args.dataset), modes=args.modes, k=args.limit,
                                          model=model, routing=routing, limits=limits)
                        if args.output:
                            if args.output.exists():
                                raise ValueError("Evaluation output already exists; choose a new path")
                            args.output.parent.mkdir(parents=True, exist_ok=True)
                            with args.output.open("x", encoding="utf-8") as output:
                                json.dump(result, output, ensure_ascii=False, indent=2)
                elif args.command == "symbol":
                    result = index.find_symbol(args.query, args.limit)
                elif args.command == "search":
                    result = index.search_vector(args.query, args.limit)
                elif args.command == "context":
                    result = index.context(args.file, args.line, args.limit)
                else:
                    result = {**index.metadata, "stale": index.stale}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, KeyError, sqlite3.Error, BudgetExceeded, ModelError) as error:
        parser.exit(2, f"compass: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
