"""Prepare pinned SWE-Explore/Verified intersections and optionally run real Compass sweeps."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import urllib.request
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compass.benchmarks import load_swe_instance
from compass.index import RepositoryIndex, build_index
from compass.preparation import PublicData, SWE_DATASET, VERIFIED_DATASET, prepare_snapshot, select_instances
from compass.progress import ProgressLog
from compass.retrieval import Routing
from compass.sweep import run_swe_sweep
from compass.vectors import OllamaEmbedder
from keel.core import Limits, ModelError
from keel.models import OllamaModel


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repositories", type=int, default=1)
    parser.add_argument("--repository-id", nargs="+", help="Optional explicit owner/repository allowlist")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--prepare-only", action="store_true", help="Download and verify snapshots without model calls")
    parser.add_argument("--swe-files", nargs="+", help="Explicit Hub paths if automatic split discovery is ambiguous")
    parser.add_argument("--verified-files", nargs="+")
    parser.add_argument("--embedding-model", default="keel-embed")
    parser.add_argument("--embedding-num-batch", type=int, default=32, help="Ollama token compute batch for low-memory hardware")
    parser.add_argument("--chat-model", default="keel-chat")
    parser.add_argument("--model-url", default="http://localhost:11434")
    parser.add_argument("--line-budget", type=int, default=100)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args(argv)
    if not 1 <= args.repositories <= 12 or not 1 <= args.line_budget <= 100000 or not 1 <= args.repeats <= 100 or args.timeout <= 0:
        parser.error("Invalid repository count, line budget, repeats or timeout")
    project = Path(__file__).resolve().parents[1]
    output = project / ".keel/swe-public" / uuid.uuid4().hex
    output.mkdir(parents=True)
    print(f"Artifacts: {output}", flush=True)
    try:
        with ProgressLog(output / "progress.jsonl", console=True) as progress:
            data = PublicData(project / ".keel/datasets/swe", offline=args.offline, timeout=args.timeout, progress=progress.emit)
            progress.emit("swe_dataset_loading")
            swe, swe_source = data.dataset(SWE_DATASET, "train", filenames=args.swe_files)
            progress.emit("verified_metadata_loading")
            verified, verified_source = data.dataset(VERIFIED_DATASET, "test", filenames=args.verified_files)
            selected, selection = select_instances(swe, verified, count=args.repositories, seed=args.seed, repositories=args.repository_id)
            plan = {"sources": [swe_source, verified_source], "selection": selection, "seed": args.seed,
                    "instances": [{"id": item["record"]["instance_id"], "repository_id": item["repository_id"],
                                   "base_commit": item["record"]["base_commit"]} for item in selected],
                    "settings": vars(args), "public_benchmark_verified": False}
            # Freeze the sample before checking out code, calling models or measuring quality.
            (output / "plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
            model = None
            if not args.prepare_only:
                progress.emit("model_preflight")
                model = OllamaModel(args.chat_model, args.model_url)
                embedder = OllamaEmbedder(args.embedding_model, args.model_url, timeout=args.timeout, num_batch=args.embedding_num_batch)
                embedder.embed(["Prepare semantic code retrieval."])
                with urllib.request.urlopen(args.model_url.rstrip("/") + "/api/tags", timeout=15) as response:
                    inventory = json.load(response)
                (output / "models.json").write_text(json.dumps(inventory, indent=2), encoding="utf-8")
                names = {item["name"] for item in inventory["models"]}
                if not any(name in names for name in (args.chat_model, args.chat_model + ":latest")):
                    raise ValueError("Chat model missing from the configured Ollama inventory")
            completed = []
            for number, item in enumerate(selected, 1):
                repo_id, record = item["repository_id"], item["record"]
                progress.emit("snapshot_preparing", repository=repo_id, instance=record["instance_id"], number=number, total=len(selected))
                snapshot = project / ".keel/swe-snapshots" / repo_id.replace("/", "--") / record["base_commit"]
                repo = prepare_snapshot(repo_id, record["base_commit"], snapshot, offline=args.offline, timeout=args.timeout)
                instance_directory = output / f"instance-{number:03d}"
                instance_directory.mkdir()
                dataset_path = instance_directory / "instance.jsonl"
                dataset_path.write_text(json.dumps(record) + "\n", encoding="utf-8")
                instance = load_swe_instance(dataset_path, record["instance_id"], repo)
                progress.emit("snapshot_verified", repository=repo_id, instance=record["instance_id"])
                result = {"repository_id": repo_id, "instance_id": record["instance_id"], "snapshot": str(repo), "status": "prepared"}
                if not args.prepare_only:
                    progress.emit("semantic_index_building", repository=repo_id)
                    # SQLite is exact search; it avoids adding native-storage variables to the first model experiment.
                    build_index(repo, parser="tree-sitter", vector_store="sqlite", embedder=embedder)
                    progress.emit("cascade_sweep_running", repository=repo_id, line_budget=args.line_budget)
                    with RepositoryIndex(repo) as index:
                        measured = run_swe_sweep(index, instance, instance_directory / "sweep", repository_id=repo_id,
                                                 modes=("t0", "t1", "t2", "adaptive"), line_budgets=(args.line_budget,),
                                                 repeats=args.repeats, seed=args.seed, model=model, routing=Routing(max_steps=4),
                                                 limits=Limits(max_wallclock=300, max_tokens=30000, max_model_calls=4, max_tool_calls=100))
                    result.update(status="passed" if measured["all_passed"] else "incomplete", summary=measured["summary"],
                                  sweep=str(instance_directory / "sweep/sweep.json"))
                completed.append(result)
                with (output / "instances.jsonl").open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(result) + "\n")
                progress.emit("instance_finished", repository=repo_id, status=result["status"])
            result = {"prepared_only": args.prepare_only, "instances": completed,
                      "all_passed": all(row["status"] in {"passed", "prepared"} for row in completed), "public_benchmark_verified": False}
            (output / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
            print(json.dumps(result, indent=2), flush=True)
            return 0 if result["all_passed"] else 1
    except (ValueError, OSError, KeyError, subprocess.SubprocessError, ModelError) as error:
        (output / "failure.json").write_text(json.dumps({"type": type(error).__name__, "error": str(error)}, indent=2), encoding="utf-8")
        print(f"FAILED: {error}\nArtifacts retained: {output}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
