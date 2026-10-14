"""Synthetic W5 smoke: incremental refresh, actual MCP stdio, and cost-quality exports."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from compass.evaluation import evaluate
from compass.index import RepositoryIndex, build_index, update_index
from compass.reporting import write_report
from compass.retrieval import Routing
from compass.vectors import HashEmbedder


def main():
    with tempfile.TemporaryDirectory(prefix="compass-w5-") as directory:
        repo = Path(directory)
        (repo / "api.py").write_bytes(b"def fetch(value):\n    return value\n")
        (repo / "worker.py").write_bytes(b"from api import fetch\ndef run(value):\n    return fetch(value)\n")
        build_index(repo, parser="python-ast", vector_store="sqlite", embedder=HashEmbedder())
        (repo / "api.py").write_bytes(b"def fetch(value, retries=1):\n    return value\n")
        updated = update_index(repo)
        requests = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "compass-demo", "version": "1"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "find_symbol", "arguments": {"name": "fetch"}}}]
        completed = subprocess.run([sys.executable, "-m", "compass", "serve", "--repo", str(repo)],
                                   input="\n".join(json.dumps(request) for request in requests) + "\n",
                                   text=True, encoding="utf-8", stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   cwd=PROJECT, timeout=20, check=True)
        responses = [json.loads(line) for line in completed.stdout.splitlines()]
        with RepositoryIndex(repo) as index:
            evaluation = evaluate(index, [{"id": "fetch", "query": "fetch", "relevant_files": ["api.py"], "source": "synthetic-w5-demo"}],
                                  routing=Routing(min_relevance=0, min_overlap=0, max_entropy=1))
        output = PROJECT / ".keel" / "compass-reports" / uuid.uuid4().hex
        artifacts = write_report(evaluation, output)
        (output / "evaluation.json").write_text(json.dumps(evaluation, indent=2), encoding="utf-8")
        print(json.dumps({"synthetic": True, "update": updated["update"],
                          "mcp_tools": [tool["name"] for tool in responses[1]["result"]["tools"]],
                          "mcp_symbol": responses[2]["result"]["structuredContent"]["results"][0]["name"],
                          "report": artifacts}, indent=2))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
