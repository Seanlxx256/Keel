import argparse
import json
from pathlib import Path
import sqlite3
import subprocess

from .index import RepositoryIndex, build_index, update_index
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
    update = sub.add_parser("update", help="Incrementally refresh the selected index settings")
    update.add_argument("--repo", type=Path, required=True)
    report = sub.add_parser("report", help="Export measured cost-quality tables and Pareto frontiers")
    report.add_argument("--input", type=Path, required=True)
    report.add_argument("--output-dir", type=Path, required=True)
    validation = sub.add_parser("validate", help="Run real tree-sitter, LanceDB and official MCP SDK probes")
    validation.add_argument("--components", nargs="+", choices=["tree_sitter", "lancedb", "mcp_sdk"])
    validation.add_argument("--require-all", action="store_true", help="Fail if any selected integration is unavailable")
    validation.add_argument("--output", type=Path)
    benchmark = sub.add_parser("benchmark", help="Evaluate local canonical CORE or SWE-Explore exports")
    formats = benchmark.add_subparsers(dest="benchmark_format", required=True)
    batch = formats.add_parser("core-batch", help="Run a manifest of local CORE exports with repeated timing")
    batch.add_argument("--manifest", type=Path, required=True)
    batch.add_argument("--output-dir", type=Path, required=True)
    batch.add_argument("--repeats", type=int, default=3)
    batch.add_argument("--seed", type=int, default=0)
    batch.add_argument("--max-queries", type=int)
    batch.add_argument("--max-documents", type=int, default=200000)
    batch.add_argument("--progress", action="store_true", help="Print live progress and heartbeats to stderr; progress.jsonl is always written")
    core = formats.add_parser("core")
    core.add_argument("--data-dir", type=Path, required=True)
    core.add_argument("--revision", required=True)
    core.add_argument("--level", type=int, choices=[2, 3], required=True)
    core.add_argument("--max-documents", type=int, default=200000)
    core.add_argument("--max-queries", type=int)
    core.add_argument("--output", type=Path)
    swe = formats.add_parser("swe")
    swe.add_argument("--dataset", type=Path, required=True)
    swe.add_argument("--instance", required=True)
    swe.add_argument("--repo", type=Path, required=True)
    swe.add_argument("--issue-map", type=Path)
    swe.add_argument("--commit-map", type=Path)
    swe.add_argument("--line-budget", type=int, default=300)
    swe.add_argument("--mode", choices=["t0", "t1", "t2", "adaptive"], default="adaptive")
    swe.add_argument("--model")
    swe.add_argument("--model-url", default="http://localhost:11434")
    swe.add_argument("--output", type=Path)
    sweep = formats.add_parser("swe-sweep", help="Compare cascade modes and line budgets on one clean SWE snapshot")
    sweep.add_argument("--dataset", type=Path, required=True)
    sweep.add_argument("--instance", required=True)
    sweep.add_argument("--repo", type=Path, required=True)
    sweep.add_argument("--issue-map", type=Path)
    sweep.add_argument("--commit-map", type=Path)
    sweep.add_argument("--output-dir", type=Path, required=True)
    sweep.add_argument("--modes", nargs="+", choices=["t0", "t1", "t2", "adaptive"], default=["t0", "t1", "adaptive"])
    sweep.add_argument("--line-budgets", nargs="+", type=int, default=[100, 300])
    sweep.add_argument("--repeats", type=int, default=3)
    sweep.add_argument("--seed", type=int, default=0)
    sweep.add_argument("--routing", type=Path)
    sweep.add_argument("--model")
    sweep.add_argument("--model-url", default="http://localhost:11434")
    sweep.add_argument("--max-tokens", type=int, default=20000)
    sweep.add_argument("--max-model-calls", type=int, default=8)
    sweep.add_argument("--max-tool-calls", type=int, default=100)
    sweep.add_argument("--max-wallclock", type=float, default=120)
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
    for name in ("retrieve", "evaluate", "serve"):
        command = sub.add_parser(name, help={"retrieve": "Adaptive retrieval", "evaluate": "Evaluate normalized JSONL queries",
                                             "serve": "Run the repository-bound MCP stdio server"}[name])
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
        elif name == "evaluate":
            command.add_argument("--dataset", type=Path, required=True)
            command.add_argument("--modes", nargs="+", choices=["adaptive", "t0", "t1", "t2"], default=["t0", "t1", "adaptive"])
            command.add_argument("--output", type=Path)
        else:
            command.add_argument("--auto-update", action="store_true", help="Refresh stale indexes between MCP calls")
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            from .validation import validate_components
            if args.output and args.output.exists():
                raise ValueError("Validation output already exists; choose a new path")
            result = validate_components(args.components)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                with args.output.open("x", encoding="utf-8") as output:
                    json.dump(result, output, ensure_ascii=False, indent=2)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 1 if any(check["status"] == "failed" for check in result["checks"]) or (args.require_all and not result["all_passed"]) else 0
        elif args.command == "benchmark":
            if args.benchmark_format == "swe-sweep":
                from .benchmarks import load_swe_instance
                from .sweep import run_swe_sweep
                issue_map = json.loads(args.issue_map.read_text(encoding="utf-8")) if args.issue_map else None
                commit_map = json.loads(args.commit_map.read_text(encoding="utf-8")) if args.commit_map else None
                instance = load_swe_instance(args.dataset, args.instance, args.repo, issue_map=issue_map, commit_map=commit_map)
                model = OllamaModel(args.model, args.model_url) if args.model else None
                routing = routing_from_dict(json.loads(args.routing.read_text(encoding="utf-8")) if args.routing else None)
                limits = Limits(max_tokens=args.max_tokens, max_model_calls=args.max_model_calls,
                                max_tool_calls=args.max_tool_calls, max_wallclock=args.max_wallclock)
                with RepositoryIndex(args.repo) as index:
                    result = run_swe_sweep(index, instance, args.output_dir, modes=args.modes, line_budgets=args.line_budgets,
                                           repeats=args.repeats, seed=args.seed, model=model, routing=routing, limits=limits)
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return 0 if result["all_passed"] else 1
            if args.benchmark_format == "core-batch":
                from .experiments import run_core_batch
                result = run_core_batch(args.manifest, args.output_dir, repeats=args.repeats,
                                        max_queries=args.max_queries, seed=args.seed, max_documents=args.max_documents,
                                        progress=args.progress)
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return 0 if result["all_passed"] else 1
            from .benchmarks import evaluate_core, evaluate_swe, load_core, load_swe_instance
            if args.output and args.output.exists():
                raise ValueError("Benchmark output already exists; choose a new path")
            if args.benchmark_format == "core":
                dataset = load_core(args.data_dir, revision=args.revision, level=args.level, max_documents=args.max_documents)
                result = evaluate_core(dataset, max_queries=args.max_queries)
            else:
                issue_map = json.loads(args.issue_map.read_text(encoding="utf-8")) if args.issue_map else None
                commit_map = json.loads(args.commit_map.read_text(encoding="utf-8")) if args.commit_map else None
                instance = load_swe_instance(args.dataset, args.instance, args.repo, issue_map=issue_map, commit_map=commit_map)
                model = OllamaModel(args.model, args.model_url) if args.model else None
                with RepositoryIndex(args.repo) as index:
                    result = evaluate_swe(index, instance, line_budget=args.line_budget, mode=args.mode, model=model)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                with args.output.open("x", encoding="utf-8") as output:
                    json.dump(result, output, ensure_ascii=False, indent=2)
        elif args.command == "serve":
            from .mcp import StdioServer
            from .service import CompassService
            routing = routing_from_dict(json.loads(args.routing.read_text(encoding="utf-8")) if args.routing else None)
            model = OllamaModel(args.model, args.model_url) if args.model else None
            limits = Limits(max_tokens=args.max_tokens, max_model_calls=args.max_model_calls,
                            max_tool_calls=args.max_tool_calls, max_wallclock=args.max_wallclock)
            StdioServer(CompassService(args.repo, auto_update=args.auto_update, routing=routing, model=model, limits=limits)).serve()
            return 0
        elif args.command == "update":
            result = update_index(args.repo)
        elif args.command == "report":
            from .reporting import write_report
            result = write_report(json.loads(args.input.read_text(encoding="utf-8")), args.output_dir)
        elif args.command == "index":
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
    except (ValueError, OSError, KeyError, sqlite3.Error, BudgetExceeded, ModelError, subprocess.SubprocessError) as error:
        parser.exit(2, f"compass: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
