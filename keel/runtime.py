from __future__ import annotations

import difflib
import json
import sys
import uuid
from pathlib import Path

from .audit import audit_metadata, audit_text
from .core import AuditFailed, Budget, BudgetExceeded, Ledger, Limits, ModelError, PolicyDenied, RecoveryStopped, Trace, digest
from .execution import CommandRunner, normalize_acceptance, validate_execution
from .workspace import Workspace
from .state import RoleStateMachine
from .verification_infrastructure import EnvironmentBlocked, verify_available


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
    infrastructure_retries = config.get('verification_infrastructure_retries', 0)
    if type(infrastructure_retries) is not int or not 0 <= infrastructure_retries <= 2:
        raise ValueError('verification_infrastructure_retries must be an integer from 0 to 2')
    mutation_samples = config.get("mutation_samples", 0)
    if type(mutation_samples) is not int or not 0 <= mutation_samples <= 20:
        raise ValueError("mutation_samples must be an integer from 0 to 20")
    agent_mode = config.get("mode", "explicit") == "agent"
    localized_mode = config.get('mode') == 'localized-proposal'
    scout_steps = config.get('localization_tool_steps', 0)
    require_external = config.get('localization_require_external', False)
    if type(require_external) is not bool or (require_external and not scout_steps):
        raise ValueError('localization_require_external requires enabled localization_tool_steps')
    if require_external and not any('scout' in policy['roles']
            for spec in config.get('mcp_servers', {}).values() for policy in spec['tools'].values()):
        raise ValueError('External-tool validation requires authorized Scout MCP tools')
    if type(scout_steps) is not int or not 0 <= scout_steps <= 12 or (scout_steps and not localized_mode):
        raise ValueError('localization_tool_steps requires localized-proposal mode and integer 0..12')
    if scout_steps:
        for spec in config.get('mcp_servers', {}).values():
            for policy in spec.get('tools', {}).values():
                if 'scout' in policy['roles'] and policy.get('read_only') is not True:
                    raise ValueError('Localization MCP tools must be explicitly declared read_only')
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
    from .recovery import RecoveryController, validate_recovery
    recovery_config = validate_recovery(config.get('recovery', {}))
    adaptive = recovery_config.get('strategy') == 'adaptive'
    from .diagnostic_execution import validate_probe_config
    probe_config = config.get('diagnostic_execution')
    validate_probe_config(probe_config)
    if probe_config is not None and not (adaptive and localized_mode):
        raise ValueError('diagnostic_execution requires adaptive localized-proposal mode')
    continuation = config.get('continuation_context')
    if continuation is not None:
        if (not adaptive or not isinstance(continuation,dict)
                or set(continuation)!={'verification','changes','provenance'}
                or not isinstance(continuation['verification'],list) or not continuation['verification']
                or not isinstance(continuation['changes'],dict) or not isinstance(continuation['provenance'],dict)
                or len(json.dumps(continuation).encode())>24000):
            raise ValueError('Continuation requires adaptive recovery and bounded verification/change evidence')
    require_inspection = config.get('require_diagnostic_inspection', False)
    if type(require_inspection) is not bool or (require_inspection and not (adaptive and localized_mode)):
        raise ValueError('require_diagnostic_inspection requires adaptive localized-proposal mode')
    preserve_candidates = config.get('preserve_repair_candidates', False)
    if type(preserve_candidates) is not bool or (preserve_candidates and not (adaptive and localized_mode)):
        raise ValueError('preserve_repair_candidates requires adaptive localized-proposal mode')
    if adaptive and not (agent_mode or localized_mode):
        raise ValueError('adaptive recovery requires agent or localized-proposal mode')
    if adaptive:
        root = Path(repo).resolve(strict=True)
        for name in recovery_config['write_roots']:
            directory = (root / name).resolve()
            if not directory.is_relative_to(root) or not directory.is_dir():
                raise ValueError('Recovery write_roots must be existing directories within the repository')
    if recovery_config.get('max_actions', 0) and not (proposal_mode or agent_mode):
        raise ValueError('recovery requires a model-driven mode')
    repair_attempts = config.get('verification_repair_attempts', 3 if recovery_config.get('max_actions', 0) else 0)
    if type(repair_attempts) is not int or not 0 <= repair_attempts <= (8 if adaptive else 3) or (repair_attempts and not (proposal_mode or agent_mode)):
        raise ValueError('verification_repair_attempts requires a model-driven mode and integer 0..3 (adaptive: 0..8)')
    settings = config.get("agent", {})
    if not isinstance(settings, dict) or set(settings) - {"max_steps", "max_output", "critic_max_output", "require_evidence", "max_work_items", "max_context_bytes", "proposal_context_hard_bytes", "proposal_context_policy", "require_change", "require_python_ast_change"} or any(
            type(v) is not int or v <= 0 for key, v in settings.items() if key not in {"require_evidence", "require_change", "require_python_ast_change", "proposal_context_policy"}) or any(
            type(settings[key]) is not bool for key in ("require_evidence", "require_change", "require_python_ast_change") if key in settings):
        raise ValueError("agent accepts positive integer max_steps/max_output/max_work_items/max_context_bytes and boolean require_evidence/require_change/require_python_ast_change")
    if settings.get('critic_max_output',1024)>4096:
        raise ValueError('critic_max_output must be 1..4096')
    from .proposals import proposal_context_limits
    proposal_context_limits(settings)
    if ('proposal_context_hard_bytes' in settings or 'proposal_context_policy' in settings) and not proposal_mode:
        raise ValueError('Proposal context policies are supported only in proposal modes')
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
    if model is not None and callable(getattr(type(model), 'bind_budget', None)):
        model.bind_budget(budget)
    if recovery_config.get('budget_driven'):
        # Each further repair requires a model call. This derived ceiling adds
        # no stage-specific cutoff before the existing global call budget.
        repair_attempts = budget.limits.max_model_calls
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    ledger = Ledger(output / "ledger.sqlite", check_same_thread=engine != "langgraph")
    from .telemetry import LocalTelemetry
    telemetry = LocalTelemetry(output / "spans.otlp.json")
    trace = Trace(output / "trace.jsonl", telemetry=telemetry)
    lifecycle = RoleStateMachine(trace, allow_recovery=adaptive)
    workspace = Workspace(repo, budget, ledger, trace, runner=CommandRunner(config.get("execution")),
                          retrieval=config.get("retrieval"), retrieval_model=model, memoization=config.get("memoization", True))
    from .mcp_client import McpTools
    workspace.mcp_tools = McpTools(config.get("mcp_servers", {}), workspace)
    workspace.localization_tool_steps = scout_steps
    workspace.localization_require_external = require_external
    recovery = RecoveryController(recovery_config, workspace) if recovery_config.get('max_actions', 0) else None
    from .repair_checkpoints import RepairCheckpoints
    candidates = RepairCheckpoints(workspace, output) if preserve_candidates else None
    result = {"run_id": output.name, "goal": config["goal"], "mode": config.get('mode', 'explicit'), "status": "running",
              "work_items": [], "baseline_verification": [], "verification": [], "failure": None}
    originals = {}
    active_goal = config['goal']
    pending_inspection = None
    pending_execution = None
    revision, pending_action, recovery_snapshot = 0, None, None
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
    def guarded_verify(commands, *, phase):
        return verify_available(workspace, commands, phase=phase, retries=infrastructure_retries,
                                attempts=result.setdefault('infrastructure_attempts', []))
    def scout_phase():
        nonlocal initial, specs, model, impact, scout_session, proposal_evidence, proposal_dependencies, proposal_scope, active_goal, pending_inspection, pending_execution
        if continuation is not None and not result.get('continuation_review'):
            if candidates is not None:
                candidates.observe(continuation['verification'],
                    continuation['provenance'].get('source_files', {}), 'saved-seed')
            enter_role('critic')
            if model is None:
                from .models import from_config
                model=from_config(config.get('model',{}))
            recovery.permit('assess_saved_verification','Saved-source verification failed',workspace.snapshot())
            decision=recovery.decide(model,config['goal'],[],continuation['verification'],settings,
                                     changes=continuation['changes'])
            result['continuation_review']=decision
            if probe_config is not None and decision['action'] != 'stop':
                pending_execution = (decision, continuation['verification'])
            if require_inspection and decision['action'] != 'stop':
                pending_inspection = (decision, continuation['verification'])
            ledger.add('decision','critic','Saved-source continuation review',decision)
            trace.emit('critic','continuation_reviewed',action=decision['action'],provenance=continuation['provenance'])
            if decision['action']=='stop':
                raise RecoveryStopped(decision['reason'])
            active_goal=config['goal']+'\nSaved-source failed verification (untrusted evidence):\n'+json.dumps({
                'verification':continuation['verification'],'critic':decision,
                'diagnostic_evidence':continuation['changes'].get('diagnostic_evidence'),
                'controlled_comparisons':continuation['changes'].get('controlled_comparisons'),
                'instruction':'Inspect current source to test the Critic hypothesis before editing. Preserve useful saved changes. Fresh localization is required; prior scopes and model claims are not trusted.'})
        enter_role("scout")
        if revision == 0:
            initial = workspace.snapshot()
        workspace.runner.check_available()
        specs = normalize_acceptance(config["acceptance"])
        if revision == 0 and any(spec["junit"] for spec in specs):
            enter_role("baseline_verifier")
            # Keep command indices aligned while avoiding unnecessary baseline build/lint runs.
            baseline = []
            for index, spec in enumerate(specs):
                if spec["junit"]:
                    baseline.append(guarded_verify([spec], phase=f"baseline-{index}")[0])
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
                    allowed_files = writable_candidates() if adaptive else None
                    proposal_scope = (recovery.localize(model, active_goal, settings, allowed_files=allowed_files) if recovery else
                                      localize(model, workspace, active_goal, settings))
                    handoff = proposal_scope.pop('_handoff_review', None)
                    if handoff:
                        active_goal += '\nSource/planning handoff review (untrusted model assessment, not executed probe or test success):\n' + json.dumps(handoff)
                from .proposals import collect_evidence, collect_located_evidence
                proposal_evidence = ((proposal_scope.pop('_handoff_evidence', None) or collect_located_evidence(workspace, proposal_scope)) if localized_mode
                    else collect_evidence(workspace, proposal_scope))
                from .dependency_evidence import collect
                proposal_dependencies = collect(workspace, proposal_scope.get('dependencies', []))
                if localized_mode and config.get('localization_dependencies'):
                    from .dependency_evidence import collect_for_localization
                    proposal_dependencies = collect_for_localization(workspace, proposal_scope, config['localization_dependencies'])
                    if config.get('select_dependency_contracts'):
                        from .dependency_evidence import select_contracts
                        proposal_dependencies = select_contracts(model, workspace, active_goal, proposal_dependencies, settings)
            else:
                impact, scout_session = inspect_repository({**config, 'goal': active_goal}, model, workspace)
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
            generated = plan_repository({**config, 'goal': active_goal}, model, workspace, impact, scout_session)
            ordered = validate({**config, "work_items": generated})
        elif proposal_mode:
            ordered = [{'id': 'localized-repair', 'description': active_goal,
                        'files': proposal_scope['files']}]
        if adaptive:
            from .recovery import within_write_roots
            for item in ordered:
                for name in item['files']:
                    if not within_write_roots(name, recovery_config['write_roots']):
                        raise PolicyDenied('Plan target outside operator recovery write_roots: ' + name)
                    path = workspace.path(name, write=True)
                    if not name.endswith('.py') or not path.is_file():
                        raise PolicyDenied('Adaptive plans may target existing Python source files only')
            if revision and workspace.snapshot() != recovery_snapshot:
                raise PolicyDenied('Workspace changed during recovery localization/planning')
        plan_id = ledger.add("decision", "planner", "Validated task DAG", ordered)
        trace.emit("planner", "plan_ready", fact_id=plan_id, items=len(ordered))
        if adaptive:
            result.setdefault('plans', []).append({'revision': revision, 'plan_sha256': digest(ordered), 'items': ordered})
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
        nonlocal pending_inspection, active_goal, pending_execution
        enter_role("implementer")
        if pending_execution is not None:
            from .diagnostic_execution import execute_check
            from .proposals import collect_located_evidence, collect_evidence
            import hashlib
            decision, observed_verification = pending_execution
            # A repair route may reuse localization after a previous edit; always
            # reacquire current bytes rather than passing stale proposal windows.
            anchors_current = all(hashlib.sha256(workspace.read(name, role='scout')['value'].encode()).hexdigest()
                                  == proposal_scope['source_sha256'][name] for name in proposal_scope['files'])
            current_probe_evidence = (collect_located_evidence(workspace, proposal_scope) if anchors_current
                else collect_evidence(workspace, {'files':proposal_scope['files'], 'queries':[]}))
            handoff = execute_check(model, workspace, config['goal'], decision,
                observed_verification, current_probe_evidence, settings, probe_config,
                controlled_comparisons=(continuation or {}).get('changes',{}).get('controlled_comparisons'))
            result.setdefault('diagnostic_executions', []).append(handoff)
            pending_execution = None
            if handoff['closure']['state'] == 'blocked_verified':
                raise EnvironmentBlocked('Diagnostic executor failed; see diagnostic_executions evidence')
            if not any(row.get('outcome') == 'completed' for row in handoff['executions']):
                raise RecoveryStopped('Diagnostic experiment did not complete; no patch authorized')
            if handoff['assessment_unverified']['conclusion'] == 'unknown':
                raise RecoveryStopped('Diagnostic question remains unresolved after execution; no patch authorized')
            active_goal += '\nExecuted current diagnostic check (untrusted evidence):\n'+json.dumps(handoff)
        if require_inspection and pending_inspection is not None:
            from .diagnostic_inspection import inspect_diagnosis
            decision, observed_verification = pending_inspection
            inspection = inspect_diagnosis(model, workspace, config['goal'], decision,
                observed_verification, proposal_scope['files'], settings)
            result.setdefault('diagnostic_inspections', []).append(inspection)
            pending_inspection = None
            if inspection['assessment']['outcome'] == 'insufficient':
                raise RecoveryStopped('Diagnostic inspection found insufficient evidence: '+inspection['assessment']['next_step'])
            active_goal += '\nFresh diagnostic inspection (untrusted source and model assessment):\n'+json.dumps(inspection)
        if adaptive and pending_action == 'repair':
            repair_implementation(result['verification'], len(result['verification_attempts']))
            return
        for item in ordered:
            budget.check()
            report = {"id": item["id"] if revision == 0 else f"revision-{revision}:{item['id']}", "status": "running"}
            if adaptive:
                report.update(revision=revision, plan_item_id=item['id'])
            result["work_items"].append(report)
            trace.emit(stage, "item_started", item_id=item["id"])
            if agent_mode:
                from .agents import AgentSession
                session = AgentSession("implementer", model, workspace,
                                       allowed_files=item["files"], **settings)
                task = {"goal": active_goal, "work_item": item,
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
                report['summary'] = propose(model, workspace, active_goal, item['files'], proposal_evidence, settings,
                                            dependencies=proposal_dependencies, validation_retries=min(repair_attempts, 1), recovery=recovery)
            for edit in item.get("edits", []):
                workspace.replace(edit["path"], edit["old"], edit["new"])
            report["status"] = "completed"
            trace.emit(stage, "item_completed", item_id=item["id"])
    def verifier_phase():
        nonlocal stage
        if adaptive:
            adaptive_verifier_phase()
            return
        enter_role("verifier")
        result["verification_attempts"] = []
        for attempt in range(repair_attempts + 1):
            stage = 'verifier'
            verification = guarded_verify(config["acceptance"], phase='final' if attempt == 0 else f'repair-{attempt}')
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
            # Failed cases are the observation being repaired, not evidence of
            # tampering. Still reject missing identities, more skips or no tests.
            findings = [finding for finding in audit_metadata(result['baseline_verification'], verification)
                        if finding['rule'] != 'test_failures_in_report']
            for name, before in originals.items():
                findings.extend(audit_text(name, before, workspace.path(name).read_bytes()))
            if findings:
                raise AuditFailed(findings)
            fact = ledger.add('failed_attempt', 'verifier', 'Acceptance failed before bounded repair',
                              {'attempt': attempt, 'verification': verification})
            if recovery:
                from .recovery import verification_observation
                recovery.permit('repair_verification', verification_observation(verification), current)
            stage = 'implementer'
            if agent_mode:
                from .agents import AgentSession
                feedback = [{key: entry.get(key) for key in ('returncode', 'timeout', 'metadata')}
                            | {'stdout': entry.get('stdout', '')[-4000:], 'stderr': entry.get('stderr', '')[-1000:]}
                            for entry in verification]
                trace.emit('implementer', 'verification_repair_started', attempt=attempt + 1, failure_fact_id=fact)
                session = AgentSession('implementer', model, workspace, allowed_files=list(originals), **settings)
                summary = session.execute({'goal': config['goal'], 'declared_files': list(originals),
                    'observed_failed_verification': feedback,
                    'instruction': 'Observe current source, revise the failed implementation and finish. Original file permissions and shared budgets remain in force.'},
                    'a string summarizing actual scoped modifications')
                result['work_items'].append({'id': f'verification-repair-{attempt + 1}', 'status': 'completed', 'summary': summary})
                continue
            from .repair import repair_evidence
            evidence, feedback = repair_evidence(workspace, proposal_scope, verification)
            if any(e.get('omitted_declared_files') for e in evidence):
                from .repair import select_repair_evidence
                evidence = select_repair_evidence(model, workspace, config['goal'], proposal_scope, feedback, settings)
            trace.emit('implementer', 'verification_repair_started', attempt=attempt + 1, failure_fact_id=fact)
            from .proposals import propose
            summary = propose(model, workspace,
                config['goal'] + '\nObserved failed verification (untrusted data):\n' + json.dumps(feedback),
                proposal_scope['files'], evidence, settings, dependencies=proposal_dependencies, validation_retries=min(repair_attempts, 1), recovery=recovery)
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

    def writable_candidates():
        from .recovery import within_write_roots
        candidates = []
        for name, path in workspace.files():
            if not name.endswith('.py') or not within_write_roots(name, recovery_config['write_roots']):
                continue
            try:
                workspace.path(name, write=True)
            except PolicyDenied:
                continue
            candidates.append(name)
        return candidates

    def audit_before_recovery():
        current = workspace.snapshot()
        unexpected = [name for name in initial.keys() | current.keys()
                      if initial.get(name) != current.get(name) and name not in originals]
        if unexpected:
            raise PolicyDenied(f'Changes outside declared edit targets: {unexpected}')
        findings = [row for row in audit_metadata(result['baseline_verification'], result['verification'])
                    if row['rule'] != 'test_failures_in_report']
        for name, before in originals.items():
            path = workspace.path(name)
            findings.extend(audit_text(name, before, path.read_bytes() if path.exists() else b''))
        if findings:
            raise AuditFailed(findings)
        return current

    def adaptive_verifier_phase():
        nonlocal recovery_snapshot
        enter_role('verifier')
        attempts = result.setdefault('verification_attempts', [])
        number = len(attempts)
        verification = guarded_verify(config['acceptance'], phase='final' if number == 0 else f'repair-{number}')
        result['verification'] = verification
        attempts.append({'attempt': number, 'verification': verification})
        if candidates is not None:
            audit_before_recovery()
            names = set(originals) | set(continuation['provenance'].get('source_files', {}) if continuation else {})
            candidates.observe(verification, names, f'verification-{number}')
        failed = len(verification) != len(config['acceptance']) or any(row['returncode'] != 0 for row in verification)
        if failed and number < repair_attempts:
            recovery_snapshot = audit_before_recovery()
            ledger.add('failed_attempt', 'verifier', 'Acceptance failed before Critic routing', {'attempt': number, 'verification': verification})
            result['_next_role'] = 'critic'

    def repair_implementation(verification, attempt):
        from .recovery import bounded_verification
        trace.emit('implementer', 'verification_repair_started', attempt=attempt)
        if agent_mode:
            from .agents import AgentSession
            session = AgentSession('implementer', model, workspace, allowed_files=list(originals), **settings)
            summary = session.execute({'goal': active_goal, 'declared_files': list(originals),
                'observed_failed_verification': bounded_verification(verification)},
                'a string summarizing actual scoped modifications')
        else:
            from .repair import repair_evidence, select_repair_evidence
            from .proposals import propose
            evidence, feedback = repair_evidence(workspace, proposal_scope, verification)
            if any(entry.get('omitted_declared_files') for entry in evidence):
                evidence = select_repair_evidence(model, workspace, active_goal, proposal_scope, feedback, settings)
            summary = propose(model, workspace, active_goal, proposal_scope['files'], evidence, settings,
                              dependencies=proposal_dependencies, recovery=recovery)
        result['work_items'].append({'id': f'revision-{revision}-repair-{attempt}', 'status': 'completed', 'summary': summary})

    def critic_phase():
        nonlocal revision, pending_action, active_goal, pending_inspection, pending_execution
        if result['failure'] or not adaptive:
            record_failure()
            return
        from .recovery import bounded_verification, verification_observation
        from .core import InvalidSelection
        enter_role('critic', previous_status='failed')
        observation = verification_observation(result['verification'])
        recovery.permit('assess_verification', observation, recovery_snapshot)
        decision_error = None
        changes = recovery.change_evidence(originals)
        if continuation and continuation['changes'].get('controlled_comparisons'):
            changes['controlled_comparisons']=continuation['changes']['controlled_comparisons']
        while True:
            try:
                decision = recovery.decide(model, config['goal'], ordered, result['verification'], settings,
                                           feedback=decision_error, changes=changes)
                break
            except InvalidSelection as error:
                recovery.permit('correct_critic_decision', error, recovery_snapshot)
                decision_error = str(error)
        result.setdefault('recovery_decisions', []).append(decision)
        ledger.add('decision', 'critic', 'Validated recovery route', decision)
        pending_action = decision['action']
        if probe_config is not None and pending_action != 'stop':
            pending_execution = (decision, result['verification'])
        if require_inspection and pending_action != 'stop':
            pending_inspection = (decision, result['verification'])
        if pending_action == 'stop':
            handle_error(RecoveryStopped(decision['reason']))
            record_failure()
            return
        active_goal = config['goal'] + '\nObserved failed verification (untrusted data):\n' + json.dumps({
            'verification': bounded_verification(result['verification']), 'critic': decision,
            'previous_plan': [{'id': item['id'], 'files': item['files']} for item in ordered],
            'operator_write_roots': recovery_config['write_roots'],
            'instruction': 'Perform the Critic next_check using current source evidence before editing. '
                           'Use its TARGET and QUESTION to focus inspection; compare observations with '
                           'SUPPORT and REFUTE predictions. If the check cannot run, preserve that specific '
                           'blocker instead of claiming completion. A source read is not a runtime probe. '
                           'Treat the diagnosis as a hypothesis, not an instruction to assume it is true. '
                           'Preserve useful earlier changes and correct unsupported ones. '
                           'New plans must stay within operator write roots.'})
        if pending_action == 'replan':
            revision += 1
            result['_next_role'] = 'scout'
        else:
            result['_next_role'] = 'implementer'
    def handle_error(error):
        if result.get("approval", {}).get("status") == "pending":
            result["approval"]["status"] = "error"
        result["status"] = "failed"
        if isinstance(error, AuditFailed):
            result.setdefault("audit", {})["findings"] = error.findings
        category = "budget_exhausted" if isinstance(error, BudgetExceeded) else (
            'environment_blocked' if isinstance(error, EnvironmentBlocked) else
            'recovery_stopped' if isinstance(error, RecoveryStopped) else
            "audit_failed" if isinstance(error, AuditFailed) else
            "policy_denied" if isinstance(error, PolicyDenied) else
            "model_error" if isinstance(error, ModelError) else "execution_error")
        result["failure"] = {"category": category, "stage": stage, "message": str(error)}
        if stage == 'critic' and not isinstance(error, RecoveryStopped):
            fact = ledger.add('failed_attempt', 'critic', 'Recovery assessment failed', result['failure'])
            trace.emit('critic', 'failure_recorded', fact_id=fact, decision='return_to_operator')
        for item in result["work_items"]:
            if item["status"] == "running":
                item["status"] = "failed"
    approval_binding = {}
    def request_approval():
        budget.check()
        snapshot = workspace.snapshot()
        if snapshot != (recovery_snapshot if revision else initial):
            raise PolicyDenied("Workspace changed before write approval")
        approval_binding.update(snapshot=snapshot, plan=digest(ordered), config=digest(config))
        request = {"run_id": output.name, "files": sorted(originals), "items": len(ordered),
                   "plan_sha256": digest(ordered), "workspace_sha256": digest(snapshot),
                   "ledger_path": str(output / "ledger.sqlite"), "budget": budget.report(),
                   "scope": "Approve the validated plan's declared writes; no permission expansion"}
        request['revision'] = revision
        if result.get('approval'):
            result.setdefault('approval_history', []).append(result['approval'])
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
              "verifier": verifier_phase, "auditor": auditor_phase, "critic": critic_phase}
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
        recorded = {item.get('plan_item_id', item['id']) for item in result['work_items']
                    if item.get('revision', 0) == revision}
        result["work_items"].extend({"id": item["id"], "status": "not_started"}
                                    for item in ordered if item["id"] not in recorded)
        if result["failure"] and lifecycle.state != "critic":
            record_failure()
        lifecycle.finish(result["status"])
        result["state_machine"] = lifecycle.report()
        if recovery and recovery.progress:
            recovery.progress.review(result['verification'], terminal_status=result['status'])
        if candidates is not None and result['status']=='failed' and result.get('failure',{}).get('category') in {
                'budget_exhausted','recovery_stopped','verification_failed'}:
            try:
                audit_before_recovery()
                selected = candidates.restore_on_failure(originals)
                if selected is not None:
                    result['selected_repair_candidate'] = selected
                    trace.emit('runtime','repair_candidate_selected',
                               label=selected['selected_label'],restored_files=selected['restored_files'])
            except (ValueError, OSError, PolicyDenied, AuditFailed) as error:
                result['repair_candidate_selection_error'] = type(error).__name__+': '+str(error)
        patch = []
        for name, before in originals.items():
            path = workspace.path(name)
            after = path.read_bytes() if path.exists() else b""
            lines = difflib.unified_diff(before.decode("utf-8").splitlines(keepends=True),
                                        after.decode("utf-8", errors="replace").splitlines(keepends=True),
                                        fromfile=f"a/{name}", tofile=f"b/{name}")
            for line in lines:
                patch.append(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n")
        # Diff payload lines may already contain CRLF. Windows text translation
        # would turn them into CRCRLF and corrupt hunk lengths on export.
        (output / "changes.patch").write_bytes("".join(patch).encode("utf-8"))
        result["budget"] = budget.report()
        result['external_tool_calls'] = getattr(workspace, 'external_tool_metrics', {})
        result['external_tool_validation'] = {'required': require_external,
            'attempted': getattr(workspace, 'localization_external_attempted', False),
            'successful_requests': sum(row['completed'] for row in result['external_tool_calls'].values())}
        if recovery:
            result['recovery'] = recovery.report()
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
