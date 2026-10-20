"""Explicit real-dependency probes. Missing libraries are never counted as passes."""
from __future__ import annotations

import asyncio
from importlib import metadata, util
import json
from pathlib import Path
import platform
import sys
import tempfile
import time

from .index import RepositoryIndex, build_index, update_index
from .parsing import PythonParser
from .vectors import HashEmbedder


DEPENDENCIES = {"tree_sitter": [("tree_sitter", "tree-sitter"), ("tree_sitter_python", "tree-sitter-python")],
                "lancedb": [("lancedb", "lancedb")], "mcp_sdk": [("mcp", "mcp")]}


def probe_tree_sitter(root):
    raw = '# 🧭\n@decorate\nasync def fetch(value):\n    """Read values."""\n    return value\n'.encode()
    expected = PythonParser("python-ast").parse("api.py", raw)
    actual = PythonParser("tree-sitter").parse("api.py", raw)
    if actual != expected:
        raise ValueError("Tree-sitter and AST range/metadata probes disagree")
    (root / "api.py").write_bytes(raw)
    built = build_index(root, parser="tree-sitter")
    (root / "api.py").write_bytes(raw.replace(b"fetch(value)", b"fetch(value, retries=1)"))
    updated = update_index(root)
    if updated["update"]["parsed_files"] != 1:
        raise ValueError("Tree-sitter incremental extraction failed")
    return {"symbols": built["symbols"], "incremental_parsed_files": updated["update"]["parsed_files"]}


def probe_lancedb(root):
    (root / "api.py").write_bytes(b'def invoice_total(value):\n    """Calculate invoice totals."""\n    return value\n')
    (root / "caller.py").write_bytes(b"from api import invoice_total\ndef run(value):\n    return invoice_total(value)\n")
    (root / "other.py").write_bytes(b"def unrelated():\n    return None\n")
    build_index(root, parser="python-ast", vector_store="lancedb", embedder=HashEmbedder())
    with RepositoryIndex(root) as index:
        hits = index.search_vector("calculate invoice totals", 3)["results"]
        if not any(row["name"] == "invoice_total" for row in hits):
            raise ValueError("LanceDB search did not recover the indexed function")
    path = root / "api.py"
    path.write_bytes(path.read_bytes().replace(b"invoice_total(value)", b"invoice_total(value, tax=0)"))
    updated = update_index(root)
    if updated["update"]["embedded_symbols"] != 2 or updated["update"]["reused_vectors"] != 1:
        raise ValueError("LanceDB incremental vector reuse or dependency invalidation failed")
    with RepositoryIndex(root) as index:
        hits = index.search_vector("invoice totals", 3)["results"]
        if not any("tax=0" in row["signature"] for row in hits):
            raise ValueError("LanceDB search returned an outdated generation")
    return {"vector_hits": len(hits), "embedded_symbols": 2, "reused_vectors": 1,
            "embedding": "lexical hash; storage validation only"}


async def _sdk_session(root):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    command = StdioServerParameters(command=sys.executable,
                                     args=["-m", "compass", "serve", "--repo", str(root), "--auto-update"],
                                     cwd=str(Path(__file__).resolve().parents[1]))
    async with stdio_client(command) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            initialized = await session.initialize()
            tools = await session.list_tools()
            names = {tool.name for tool in tools.tools}
            expected = {"find_symbol", "search_code", "get_context", "impact_analysis", "get_symbols_overview"}
            if names != expected:
                raise ValueError(f"SDK tool discovery differs: missing={sorted(expected-names)}, unexpected={sorted(names-expected)}")
            overview = await session.call_tool("get_symbols_overview", {"file": "api.py"})
            outline = overview.structuredContent
            if overview.isError or not outline or not any(row.get('qualname') == 'fetch' for row in outline.get('results', [])):
                raise ValueError("SDK overview did not return the indexed fetch symbol")
            result = await session.call_tool("find_symbol", {"name": "fetch"})
            data = result.structuredContent
            if result.isError or not data or not data["results"]:
                raise ValueError("SDK could not decode the structured symbol result")
            old_generation = data["generation"]
            (root / "api.py").write_bytes(b"def fetch(value, retries=1):\n    return value\n")
            result = await session.call_tool("find_symbol", {"name": "fetch"})
            data = result.structuredContent
            if result.isError or data["generation"] == old_generation or "retries=1" not in data["results"][0]["signature"]:
                raise ValueError("SDK auto-update roundtrip returned stale code")
            error = await session.call_tool("impact_analysis", {"change": "upgrade api"})
            if not error.isError:
                raise ValueError("Missing chat model should produce a tool error")
            await session.send_ping()
            return {"protocol_version": initialized.protocolVersion, "tools": sorted(names),
                    "structured_results": True, "auto_update": True, "tool_errors": True, "symbol_overview": True}


def probe_mcp_sdk(root):
    (root / "api.py").write_bytes(b"def fetch(value):\n    return value\n")
    build_index(root, parser="python-ast")
    return asyncio.run(asyncio.wait_for(_sdk_session(root), timeout=30))


PROBES = {"tree_sitter": probe_tree_sitter, "lancedb": probe_lancedb, "mcp_sdk": probe_mcp_sdk}


def exception_causes(error):
    """Expose bounded leaf causes instead of losing them behind TaskGroup wrappers."""
    causes = []
    pending = [error]
    while pending and len(causes) < 8:
        current = pending.pop()
        children = getattr(current, 'exceptions', None)
        if children:
            pending.extend(reversed(children))
        else:
            causes.append(f'{type(current).__name__}: {str(current)[:1000]}')
    return causes


def validate_components(components=None):
    components = list(DEPENDENCIES if components is None else components)
    if not components or len(set(components)) != len(components) or any(name not in DEPENDENCIES for name in components):
        raise ValueError("Choose unique tree_sitter, lancedb and/or mcp_sdk components")
    checks = []
    for name in components:
        versions, missing = {}, []
        for module, package in DEPENDENCIES[name]:
            if util.find_spec(module) is None:
                missing.append(package)
            else:
                try:
                    versions[package] = metadata.version(package)
                except metadata.PackageNotFoundError:
                    versions[package] = "unknown"
        record = {"component": name, "versions": versions, "missing": missing}
        started = time.perf_counter()
        if missing:
            record.update(status="unavailable", detail="Install the project's optional validation dependencies")
        else:
            try:
                with tempfile.TemporaryDirectory(prefix=f"compass-{name}-") as directory:
                    record.update(status="passed", evidence=PROBES[name](Path(directory)))
            except Exception as error:
                record.update(status="failed", error=f"{type(error).__name__}: {error}", causes=exception_causes(error))
        record["seconds"] = time.perf_counter() - started
        checks.append(record)
    return {"python": platform.python_version(), "platform": platform.platform(), "checks": checks,
            "all_passed": all(record["status"] == "passed" for record in checks),
            "public_benchmark_verified": False}
