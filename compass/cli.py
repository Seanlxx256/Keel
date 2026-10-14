import argparse
import json
from pathlib import Path
import sqlite3

from .index import RepositoryIndex, build_index
from .vectors import HashEmbedder, OllamaEmbedder


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
                if args.command == "symbol":
                    result = index.find_symbol(args.query, args.limit)
                elif args.command == "search":
                    result = index.search_vector(args.query, args.limit)
                elif args.command == "context":
                    result = index.context(args.file, args.line, args.limit)
                else:
                    result = {**index.metadata, "stale": index.stale}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, KeyError, sqlite3.Error) as error:
        parser.exit(2, f"compass: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
