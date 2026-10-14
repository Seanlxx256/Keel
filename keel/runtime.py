from __future__ import annotations

import difflib
import json
import uuid
from pathlib import Path

from .core import Budget, BudgetExceeded, Ledger, Limits, ModelError, PolicyDenied, Trace
from .workspace import Workspace


def validate(config: dict):
    if not isinstance(config.get("goal"), str) or not config["goal"].strip():
        raise ValueError("goal must be a nonempty string")
    commands = config.get("acceptance", [])
    if not isinstance(commands, list) or not commands or any(not isinstance(c, list) or not c or
                           any(not isinstance(a, str) or not a for a in c) for c in commands):
        raise ValueError("acceptance must contain nonempty command argument lists")
    items = config.get("work_items", [])
    if not isinstance(items, list) or any(not isinstance(item, dict) or "id" not in item for item in items):
        raise ValueError("work_items must be an array of objects with IDs")
    identifiers = [item["id"] for item in items]
    if any(not isinstance(i, str) or not i for i in identifiers) or len(set(identifiers)) != len(identifiers):
        raise ValueError("Work item IDs must be unique nonempty strings")
    known, ordered, pending = set(), [], list(items)
    for item in items:
        edits = item.get("edits", [])
        if not isinstance(edits, list) or any(not isinstance(edit, dict) for edit in edits):
            raise ValueError("edits must be an array of objects")
        dependencies = item.get("depends_on", [])
        if not isinstance(dependencies, list) or any(not isinstance(d, str) for d in dependencies):
            raise ValueError("depends_on must be an array of IDs")
    while pending:
        ready = [item for item in pending if set(item.get("depends_on", [])) <= known]
        if not ready:
            raise ValueError("Work item graph contains a cycle or unknown dependency")
        for item in ready:
            for edit in item.get("edits", []):
                if any(not isinstance(edit.get(k), str) for k in ("path", "old", "new")):
                    raise ValueError("Edits require string path, old and new fields")
            ordered.append(item)
            known.add(item["id"])
            pending.remove(item)
    return ordered


def run(config: dict, repo: Path, output: Path, *, model=None) -> dict:
    ordered = validate(config)
    agent_mode = config.get("mode", "explicit") == "agent"
    if config.get("mode", "explicit") not in {"explicit", "agent"}:
        raise ValueError("mode must be explicit or agent")
    if agent_mode and ordered:
        raise ValueError("Agent mode generates its own plan; omit work_items")
    settings = config.get("agent", {})
    if not isinstance(settings, dict) or set(settings) - {"max_steps", "max_output"} or any(
            type(v) is not int or v <= 0 for v in settings.values()):
        raise ValueError("agent accepts positive integer max_steps and max_output")
    budget = Budget(Limits(**config.get("budget", {})))
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    ledger = Ledger(output / "ledger.sqlite")
    trace = Trace(output / "trace.jsonl")
    workspace = Workspace(repo, budget, ledger, trace)
    result = {"run_id": output.name, "goal": config["goal"], "status": "running",
              "work_items": [], "verification": [], "failure": None}
    originals = {}
    stage = "scout"
    try:
        trace.emit("runtime", "run_started", goal=config["goal"])
        initial = workspace.snapshot()
        if agent_mode:
            from .agents import generate_plan
            from .models import from_config
            model = model if model is not None else from_config(config.get("model", {}))
            def enter_role(role):
                nonlocal stage
                stage = role
            generated = generate_plan(config, model, workspace, on_role=enter_role)
            ordered = validate({**config, "work_items": generated})
        for query in config.get("queries", []):
            evidence = workspace.search(query)
            fact = ledger.add("symbol", "scout", f"Search: {query}", evidence)
            trace.emit("scout", "evidence", fact_id=fact)
        stage = "planner"
        plan_id = ledger.add("decision", "planner", "Validated task DAG", ordered)
        trace.emit("planner", "plan_ready", fact_id=plan_id, items=len(ordered))
        # Validate every target before making the first mutation.
        for item in ordered:
            if agent_mode:
                for name in item["files"]:
                    raw = workspace.path(name, write=True).read_bytes()
                    raw.decode("utf-8")
                    originals.setdefault(name, raw)
            for edit in item.get("edits", []):
                path = workspace.path(edit["path"], write=True)
                raw = path.read_bytes()
                raw.decode("utf-8")  # Only UTF-8 text edits are supported.
                originals.setdefault(edit["path"], raw)
        stage = "implementer"
        for item in ordered:
            budget.check()
            report = {"id": item["id"], "status": "running"}
            result["work_items"].append(report)
            trace.emit(stage, "item_started", item_id=item["id"])
            if agent_mode:
                from .agents import AgentSession
                session = AgentSession("implementer", model, workspace,
                                       allowed_files=item["files"], **settings)
                report["summary"] = session.execute(
                    {"goal": config["goal"], "work_item": item,
                     "completed_items": [{"id": entry["id"], "summary": entry.get("summary")}
                                         for entry in result["work_items"] if entry["status"] == "completed"]},
                    "a string summarizing the actual modifications you made")
                if not isinstance(report["summary"], str):
                    raise ModelError("Implementer final summary must be a string")
            for edit in item.get("edits", []):
                workspace.replace(edit["path"], edit["old"], edit["new"])
            report["status"] = "completed"
            trace.emit(stage, "item_completed", item_id=item["id"])
        stage = "verifier"
        result["verification"] = workspace.verify(config["acceptance"])
        stage = "auditor"
        final = workspace.snapshot()
        changed = sorted(name for name in initial.keys() | final.keys() if initial.get(name) != final.get(name))
        unexpected = [name for name in changed if name not in originals]
        result["audit"] = {"changed_files": changed, "unexpected_changes": unexpected,
                           "scope": "workspace diff allowlist; no semantic or test-metadata audit yet"}
        if unexpected:
            raise PolicyDenied(f"Changes outside declared edit targets: {unexpected}")
        if len(result["verification"]) != len(config["acceptance"]) or any(
                v["returncode"] != 0 for v in result["verification"]):
            result["status"] = "failed"
            result["failure"] = {"category": "verification_failed", "stage": "verifier",
                                 "message": "Acceptance commands did not all pass"}
        else:
            budget.check()
            result["status"] = "passed"
    except (BudgetExceeded, PolicyDenied, ModelError, ValueError, OSError, SyntaxError) as error:
        result["status"] = "failed"
        category = "budget_exhausted" if isinstance(error, BudgetExceeded) else (
            "policy_denied" if isinstance(error, PolicyDenied) else
            "model_error" if isinstance(error, ModelError) else "execution_error")
        result["failure"] = {"category": category, "stage": stage, "message": str(error)}
        for item in result["work_items"]:
            if item["status"] == "running":
                item["status"] = "failed"
    finally:
        recorded = {item["id"] for item in result["work_items"]}
        result["work_items"].extend({"id": item["id"], "status": "not_started"}
                                    for item in ordered if item["id"] not in recorded)
        if result["failure"]:
            fact = ledger.add("failed_attempt", "critic", result["failure"]["message"], result["failure"])
            trace.emit("critic", "failure_recorded", fact_id=fact, decision="return_to_operator")
        patch = []
        for name, before in originals.items():
            path = workspace.path(name)
            after = path.read_bytes() if path.exists() else b""
            lines = difflib.unified_diff(before.decode("utf-8").splitlines(keepends=True),
                                        after.decode("utf-8", errors="replace").splitlines(keepends=True),
                                        fromfile=f"a/{name}", tofile=f"b/{name}")
            for line in lines:
                patch.append(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n")
        (output / "changes.patch").write_text("".join(patch), encoding="utf-8")
        result["budget"] = budget.report()
        result["facts"] = ledger.summaries()
        result["artifacts"] = {name: str(output / name) for name in
                               ("changes.patch", "trace.jsonl", "ledger.sqlite")}
        trace.emit("runtime", "run_finished", status=result["status"])
        (output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        ledger.close()
    return result


def new_run_directory(repo: Path) -> Path:
    return repo / ".keel" / "runs" / uuid.uuid4().hex
