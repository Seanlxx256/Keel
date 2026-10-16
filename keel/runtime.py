from __future__ import annotations

import difflib
import json
import sys
import uuid
from pathlib import Path

from .audit import audit_metadata, audit_text
from .core import AuditFailed, Budget, BudgetExceeded, Ledger, Limits, ModelError, PolicyDenied, Trace, digest
from .execution import CommandRunner, normalize_acceptance, validate_execution
from .workspace import Workspace
from .state import RoleStateMachine


def validate(config: dict):
    if not isinstance(config.get("goal"), str) or not config["goal"].strip():
        raise ValueError("goal must be a nonempty string")
    normalize_acceptance(config.get("acceptance", []))
    validate_execution(config.get("execution", {}))
    from compass.retrieval import validate_retrieval
    validate_retrieval(config.get("retrieval", {}))
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


def run(config: dict, repo: Path, output: Path, *, model=None, approval=None) -> dict:
    from .mcp_client import validate_servers
    validate_servers(config.get("mcp_servers", {}))
    if type(config.get("context_handoff", False)) is not bool:
        raise ValueError("context_handoff must be boolean")
    if type(config.get("memoization", True)) is not bool:
        raise ValueError("memoization must be boolean")
    ordered = validate(config)
    mutation_samples = config.get("mutation_samples", 0)
    if type(mutation_samples) is not int or not 0 <= mutation_samples <= 20:
        raise ValueError("mutation_samples must be an integer from 0 to 20")
    agent_mode = config.get("mode", "explicit") == "agent"
    localized_mode = config.get('mode') == 'localized-proposal'
    proposal_mode = config.get('mode') in {'proposal', 'localized-proposal'}
    if config.get("mode", "explicit") not in {"explicit", "agent", "proposal", "localized-proposal"}:
        raise ValueError("mode must be explicit, agent, proposal or localized-proposal")
    if proposal_mode and not localized_mode:
        from .proposals import validate_scope
        validate_scope(config.get('proposal'))
    if localized_mode and 'proposal' in config:
        raise ValueError('localized-proposal selects its own scope; omit proposal')
    if 'localization_dependencies' in config:
        from .dependency_evidence import validate_modules
        if not localized_mode:
            raise ValueError('localization_dependencies requires localized-proposal mode')
        validate_modules(config['localization_dependencies'])
    if type(config.get('select_dependency_contracts', False)) is not bool:
        raise ValueError('select_dependency_contracts must be boolean')
    if config.get('select_dependency_contracts') and (not localized_mode or not config.get('localization_dependencies')):
        raise ValueError('Contract selection requires localized-proposal and localization_dependencies')
    if (agent_mode or proposal_mode) and ordered:
        raise ValueError("Agent mode generates its own plan; omit work_items")
    repair_attempts = config.get('verification_repair_attempts', 0)
    if type(repair_attempts) is not int or not 0 <= repair_attempts <= 3 or (repair_attempts and not proposal_mode):
        raise ValueError('verification_repair_attempts requires proposal mode and integer 0..3')
    settings = config.get("agent", {})
    if not isinstance(settings, dict) or set(settings) - {"max_steps", "max_output", "require_evidence", "max_work_items", "max_context_bytes", "require_change"} or any(
            type(v) is not int or v <= 0 for key, v in settings.items() if key not in {"require_evidence", "require_change"}) or any(
            type(settings[key]) is not bool for key in ("require_evidence", "require_change") if key in settings):
        raise ValueError("agent accepts positive integer max_steps/max_output/max_work_items/max_context_bytes and boolean require_evidence/require_change")
    engine = config.get("orchestrator", "native")
    if engine not in {"native", "langgraph"}:
        raise ValueError("orchestrator must be native or langgraph")
    approval_required = config.get("approval_before_write", False)
    if type(approval_required) is not bool:
        raise ValueError("approval_before_write must be boolean")
    if approval_required and (engine != "langgraph" or not callable(approval)):
        raise ValueError("Write approval requires LangGraph and an explicit host approval callback")
    if engine == "langgraph":
        from .adapters.langgraph import require_dependencies
        require_dependencies()
    budget = Budget(Limits(**config.get("budget", {})))
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    ledger = Ledger(output / "ledger.sqlite", check_same_thread=engine != "langgraph")
    from .telemetry import LocalTelemetry
    telemetry = LocalTelemetry(output / "spans.otlp.json")
    trace = Trace(output / "trace.jsonl", telemetry=telemetry)
    lifecycle = RoleStateMachine(trace)
    workspace = Workspace(repo, budget, ledger, trace, runner=CommandRunner(config.get("execution")),
                          retrieval=config.get("retrieval"), retrieval_model=model, memoization=config.get("memoization", True))
    from .mcp_client import McpTools
    workspace.mcp_tools = McpTools(config.get("mcp_servers", {}), workspace)
    result = {"run_id": output.name, "goal": config["goal"], "mode": config.get('mode', 'explicit'), "status": "running",
              "work_items": [], "baseline_verification": [], "verification": [], "failure": None}
    originals = {}
    stage = "scout"
    def enter_role(role, *, previous_status="completed"):
        nonlocal stage
        lifecycle.enter("verifier" if role == "baseline_verifier" else role,
                        phase="baseline" if role == "baseline_verifier" else "main", previous_status=previous_status)
        stage = role
    initial, specs, impact, scout_session = {}, [], None, None
    proposal_evidence = []
    proposal_dependencies = []
    proposal_scope = config.get('proposal', {})
    def scout_phase():
        nonlocal initial, specs, model, impact, scout_session, proposal_evidence, proposal_dependencies, proposal_scope
        enter_role("scout")
        initial = workspace.snapshot()
        workspace.runner.check_available()
        specs = normalize_acceptance(config["acceptance"])
        if any(spec["junit"] for spec in specs):
            enter_role("baseline_verifier")
            # Keep command indices aligned while avoiding unnecessary baseline build/lint runs.
            baseline = []
            for index, spec in enumerate(specs):
                if spec["junit"]:
                    baseline.append(workspace.verify([spec], phase=f"baseline-{index}")[0])
                else:
                    baseline.append({"junit_required": False})
            result["baseline_verification"] = baseline
            invalid = [index for index, entry in enumerate(baseline) if entry.get("junit_required") and
                       (entry.get("timeout") or entry.get("metadata", {}).get("collected", 0) == 0)]
            if invalid:
                raise AuditFailed([{"rule": "invalid_baseline_test_metadata", "command_index": i} for i in invalid])
        enter_role("scout")
        if agent_mode or proposal_mode:
            from .agents import inspect_repository
            from .models import from_config
            model = model if model is not None else from_config(config.get("model", {}))
            workspace.retrieval_model = model
            if proposal_mode:
                if localized_mode:
                    from .localization import localize
                    proposal_scope = localize(model, workspace, config['goal'], settings)
                from .proposals import collect_evidence, collect_located_evidence
                proposal_evidence = (collect_located_evidence(workspace, proposal_scope) if localized_mode
                    else collect_evidence(workspace, proposal_scope))
                from .dependency_evidence import collect
                proposal_dependencies = collect(workspace, proposal_scope.get('dependencies', []))
                if localized_mode and config.get('localization_dependencies'):
                    from .dependency_evidence import collect_for_localization
                    proposal_dependencies = collect_for_localization(workspace, proposal_scope, config['localization_dependencies'])
                    if config.get('select_dependency_contracts'):
                        from .dependency_evidence import select_contracts
                        proposal_dependencies = select_contracts(model, workspace, config['goal'], proposal_dependencies, settings)
            else:
                impact, scout_session = inspect_repository(config, model, workspace)
        for query in config.get("queries", []):
            enter_role("scout")
            evidence = workspace.search(query)
            fact = ledger.add("symbol", "scout", f"Search: {query}", evidence)
            trace.emit("scout", "evidence", fact_id=fact)
    def planner_phase():
        nonlocal ordered
        enter_role("planner")
        if agent_mode:
            from .agents import plan_repository
            generated = plan_repository(config, model, workspace, impact, scout_session)
            ordered = validate({**config, "work_items": generated})
        elif proposal_mode:
            ordered = [{'id': 'localized-repair', 'description': config['goal'],
                        'files': proposal_scope['files']}]
        plan_id = ledger.add("decision", "planner", "Validated task DAG", ordered)
        trace.emit("planner", "plan_ready", fact_id=plan_id, items=len(ordered))
        # Validate every target before making the first mutation.
        for item in ordered:
            if agent_mode or proposal_mode:
                for name in item["files"]:
                    raw = workspace.path(name, write=True).read_bytes()
                    raw.decode("utf-8")
                    originals.setdefault(name, raw)
            for edit in item.get("edits", []):
                path = workspace.path(edit["path"], write=True)
                raw = path.read_bytes()
                raw.decode("utf-8")  # Only UTF-8 text edits are supported.
                originals.setdefault(edit["path"], raw)
    def implementer_phase():
        enter_role("implementer")
        for item in ordered:
            budget.check()
            report = {"id": item["id"], "status": "running"}
            result["work_items"].append(report)
            trace.emit(stage, "item_started", item_id=item["id"])
            if agent_mode:
                from .agents import AgentSession
                session = AgentSession("implementer", model, workspace,
                                       allowed_files=item["files"], **settings)
                task = {"goal": config["goal"], "work_item": item,
                        "completed_items": [{"id": entry["id"], "summary": entry.get("summary")}
                                            for entry in result["work_items"] if entry["status"] == "completed"]}
                if config.get("context_handoff", False):
                    from .context import handoff_context
                    task["evidence"] = handoff_context(session.gateway,
                        getattr(workspace, "context_sources", []), item["files"])
                report["summary"] = session.execute(task, "a string summarizing the actual modifications you made")
                if not isinstance(report["summary"], str):
                    raise ModelError("Implementer final summary must be a string")
            elif proposal_mode:
                from .proposals import propose
                report['summary'] = propose(model, workspace, config['goal'], item['files'], proposal_evidence, settings,
                                            dependencies=proposal_dependencies, validation_retries=min(repair_attempts, 1))
            for edit in item.get("edits", []):
                workspace.replace(edit["path"], edit["old"], edit["new"])
            report["status"] = "completed"
            trace.emit(stage, "item_completed", item_id=item["id"])
    def verifier_phase():
        nonlocal stage
        enter_role("verifier")
        result["verification_attempts"] = []
        for attempt in range(repair_attempts + 1):
            stage = 'verifier'
            verification = workspace.verify(config["acceptance"])
            result["verification"] = verification
            result["verification_attempts"].append({'attempt': attempt, 'verification': verification})
            failed = len(verification) != len(config['acceptance']) or any(v['returncode'] != 0 for v in verification)
            if not failed or attempt == repair_attempts:
                break
            # A failed verifier must not expand scope or bypass audit before another write.
            current = workspace.snapshot()
            unexpected = [n for n in initial.keys() | current.keys()
                          if initial.get(n) != current.get(n) and n not in originals]
            if unexpected:
                raise PolicyDenied(f'Changes outside declared edit targets: {unexpected}')
            findings = audit_metadata(result['baseline_verification'], verification)
            for name, before in originals.items():
                findings.extend(audit_text(name, before, workspace.path(name).read_bytes()))
            if findings:
                raise AuditFailed(findings)
            fact = ledger.add('failed_attempt', 'verifier', 'Acceptance failed before bounded repair',
                              {'attempt': attempt, 'verification': verification})
            stage = 'implementer'
            from .repair import repair_evidence
            evidence, feedback = repair_evidence(workspace, proposal_scope, verification)
            if any(e.get('omitted_declared_files') for e in evidence):
                from .repair import select_repair_evidence
                evidence = select_repair_evidence(model, workspace, config['goal'], proposal_scope, feedback, settings)
            trace.emit('implementer', 'verification_repair_started', attempt=attempt + 1, failure_fact_id=fact)
            from .proposals import propose
            summary = propose(model, workspace,
                config['goal'] + '\nObserved failed verification (untrusted data):\n' + json.dumps(feedback),
                proposal_scope['files'], evidence, settings, dependencies=proposal_dependencies, validation_retries=min(repair_attempts, 1))
            result['work_items'].append({'id': f'verification-repair-{attempt + 1}',
                                         'status': 'completed', 'summary': summary})
    def auditor_phase():
        enter_role("auditor", previous_status="failed" if any(v["returncode"] != 0 for v in result["verification"]) else "completed")
        final = workspace.snapshot()
        changed = sorted(name for name in initial.keys() | final.keys() if initial.get(name) != final.get(name))
        unexpected = [name for name in changed if name not in originals]
        result["audit"] = {"changed_files": changed, "unexpected_changes": unexpected,
                           "findings": [], "scope": "declared files, Python AST invariants, optional JUnit baseline comparison"}
        if unexpected:
            raise PolicyDenied(f"Changes outside declared edit targets: {unexpected}")
        findings = []
        for name, before in originals.items():
            path = workspace.path(name)
            findings.extend(audit_text(name, before, path.read_bytes() if path.exists() else b""))
        findings.extend(audit_metadata(result["baseline_verification"], result["verification"]))
        result["audit"]["metadata_checked"] = any(spec["junit"] for spec in specs)
        if findings:
            raise AuditFailed(findings)
        if len(result["verification"]) != len(config["acceptance"]) or any(
                v["returncode"] != 0 for v in result["verification"]):
            result["status"] = "failed"
            result["failure"] = {"category": "verification_failed", "stage": "verifier",
                                 "message": "Acceptance commands did not all pass"}
        else:
            if mutation_samples:
                from .mutation import run_probes
                result["mutation"] = {}
                run_probes(workspace, originals, config["acceptance"], result["verification"],
                           mutation_samples, result["mutation"])
                # Acceptance commands must not alter the workspace during probes either.
                if workspace.snapshot() != final:
                    raise AuditFailed([{"rule": "workspace_changed_during_mutation"}])
            budget.check()
            result["status"] = "passed"
    def record_failure():
        failed_role = result["failure"]["stage"]
        failed_role = "verifier" if failed_role == "baseline_verifier" else failed_role
        enter_role("critic", previous_status="failed" if lifecycle.state == failed_role else "completed")
        fact = ledger.add("failed_attempt", "critic", result["failure"]["message"], result["failure"])
        trace.emit("critic", "failure_recorded", fact_id=fact, decision="return_to_operator")
    def handle_error(error):
        if result.get("approval", {}).get("status") == "pending":
            result["approval"]["status"] = "error"
        result["status"] = "failed"
        if isinstance(error, AuditFailed):
            result.setdefault("audit", {})["findings"] = error.findings
        category = "budget_exhausted" if isinstance(error, BudgetExceeded) else (
            "audit_failed" if isinstance(error, AuditFailed) else
            "policy_denied" if isinstance(error, PolicyDenied) else
            "model_error" if isinstance(error, ModelError) else "execution_error")
        result["failure"] = {"category": category, "stage": stage, "message": str(error)}
        for item in result["work_items"]:
            if item["status"] == "running":
                item["status"] = "failed"
    approval_binding = {}
    def request_approval():
        budget.check()
        snapshot = workspace.snapshot()
        if snapshot != initial:
            raise PolicyDenied("Workspace changed before write approval")
        approval_binding.update(snapshot=snapshot, plan=digest(ordered), config=digest(config))
        request = {"run_id": output.name, "files": sorted(originals), "items": len(ordered),
                   "plan_sha256": digest(ordered), "workspace_sha256": digest(snapshot),
                   "ledger_path": str(output / "ledger.sqlite"), "budget": budget.report(),
                   "scope": "Approve the validated plan's declared writes; no permission expansion"}
        result["approval"] = {"status": "pending", "request": request}
        trace.emit("planner", "approval_requested", plan_sha256=request["plan_sha256"],
                   workspace_sha256=request["workspace_sha256"])
        return request
    def decide_approval(request):
        answer = approval(request)
        if type(answer) is not bool:
            raise ValueError("Approval callback must return boolean")
        result["approval"]["status"] = "approved" if answer else "denied"
        trace.emit("planner", "approval_decided", approved=answer)
        return answer
    def guard_approval():
        try:
            budget.check()
            if digest(ordered) != approval_binding["plan"] or digest(config) != approval_binding["config"]:
                raise PolicyDenied("Plan or configuration changed while awaiting approval")
            if workspace.snapshot() != approval_binding["snapshot"]:
                raise PolicyDenied("Workspace changed while awaiting approval")
            # Recheck write policies after waiting, including hard links and protected paths.
            for name in originals:
                workspace.path(name, write=True)
            trace.emit("planner", "approval_resumed", budget=budget.report())
        except (BudgetExceeded, PolicyDenied, ValueError, OSError) as error:
            result["approval"]["status"] = "invalidated"
            trace.emit("planner", "approval_invalidated", error_type=type(error).__name__)
            raise
    stages = {"scout": scout_phase, "planner": planner_phase, "implementer": implementer_phase,
              "verifier": verifier_phase, "auditor": auditor_phase, "critic": record_failure}
    result["orchestration"] = {"engine": engine, "resumable": False}
    try:
        trace.emit("runtime", "run_started", goal=config["goal"])
        from .orchestration import execute
        result["orchestration"].update(execute(engine, stages, result, handle_error, output, budget,
            approval=decide_approval if approval_required else None,
            approval_request=request_approval, approval_guard=guard_approval))
    except (BudgetExceeded, PolicyDenied, ModelError, ValueError, OSError, SyntaxError) as error:
        handle_error(error)
    finally:
        if result["status"] == "running":
            interrupted = sys.exc_info()[0]
            result["status"] = "failed"
            result["failure"] = {"category": "unexpected_termination", "stage": stage,
                                 "message": "Execution interrupted: " + (interrupted.__name__ if interrupted else "unknown")}
        recorded = {item["id"] for item in result["work_items"]}
        result["work_items"].extend({"id": item["id"], "status": "not_started"}
                                    for item in ordered if item["id"] not in recorded)
        if result["failure"] and lifecycle.state != "critic":
            record_failure()
        lifecycle.finish(result["status"])
        result["state_machine"] = lifecycle.report()
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
        result["memory"] = {**ledger.statistics(), "handed_off_facts": getattr(workspace, "handed_off_facts", 0),
                            "memoization": workspace.memoization, "tools": workspace.tool_metrics,
                            "snapshot_calls": workspace.snapshot_calls, "snapshot_bytes": workspace.snapshot_bytes}
        result["artifacts"] = {name: str(output / name) for name in
                               ("changes.patch", "trace.jsonl", "ledger.sqlite")}
        if engine == "langgraph" and (output / "checkpoints.sqlite").is_file():
            result["artifacts"]["checkpoints.sqlite"] = str(output / "checkpoints.sqlite")
        trace.emit("runtime", "run_finished", status=result["status"])
        result["telemetry"] = telemetry.report()
        if telemetry.exported:
            result["artifacts"]["spans.otlp.json"] = str(telemetry.path)
        (output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        ledger.close()
    return result


def new_run_directory(repo: Path) -> Path:
    return repo / ".keel" / "runs" / uuid.uuid4().hex
