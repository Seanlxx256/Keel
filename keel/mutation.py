"""Opt-in, bounded mutation probes of changed Python functions."""
from __future__ import annotations

import ast
import copy

from .audit import audit_metadata
from .core import AuditFailed


def _functions(tree):
    result = {}

    def visit(node, prefix=""):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = prefix + child.name
                if not isinstance(child, ast.ClassDef):
                    result[name] = child
                visit(child, name + ".")
            else:
                visit(child, prefix)
    visit(tree)
    return result


def _mutate(function):
    # Avoid nested functions: one probe is attributed to exactly one changed function.
    def body_nodes(node):
        yield node
        for child in ast.iter_child_nodes(node):
            if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                yield from body_nodes(child)

    nodes = [node for statement in function.body for node in body_nodes(statement)]
    for node in nodes:
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Constant):
            value = node.value.value
            if type(value) is bool:
                node.value.value = not value
                return "flip_boolean_return"
            if type(value) in {int, float}:
                node.value.value = value + 1
                return "increment_numeric_return"
    inverse = {ast.Eq: ast.NotEq, ast.NotEq: ast.Eq, ast.Lt: ast.GtE, ast.GtE: ast.Lt,
               ast.Gt: ast.LtE, ast.LtE: ast.Gt, ast.Is: ast.IsNot, ast.IsNot: ast.Is,
               ast.In: ast.NotIn, ast.NotIn: ast.In}
    for node in nodes:
        if isinstance(node, ast.Compare) and type(node.ops[0]) in inverse:
            node.ops[0] = inverse[type(node.ops[0])]()
            return "invert_comparison"
    return None


def candidates(originals, workspace, limit):
    probes = []
    for name, before in originals.items():
        if not name.endswith(".py"):
            continue
        after = workspace.path(name).read_bytes()
        if before == after:
            continue
        old_functions = _functions(ast.parse(before.decode("utf-8")))
        tree = ast.parse(after.decode("utf-8"))
        for function_name, function in _functions(tree).items():
            old = old_functions.get(function_name)
            if old is not None and ast.dump(old) == ast.dump(function):
                continue
            mutated = copy.deepcopy(tree)
            operator = _mutate(_functions(mutated)[function_name])
            if operator is not None:
                probes.append({"path": name, "function": function_name, "operator": operator,
                               "content": (ast.unparse(mutated) + "\n").encode("utf-8")})
            if len(probes) >= limit:
                return probes
    return probes


def run_probes(workspace, originals, acceptance, final_verification, limit, report):
    probes = candidates(originals, workspace, limit)
    report.update(requested=limit, sampled=len(probes), probes=[], status="running")
    for index, probe in enumerate(probes):
        workspace.budget.check()
        path = workspace.path(probe["path"], write=True)
        actual = path.read_bytes()
        record = {key: value for key, value in probe.items() if key != "content"}
        report["probes"].append(record)
        workspace.trace.emit("auditor", "mutation_started", **record)
        try:
            workspace.budget.charge_tool()
            path.write_bytes(probe["content"])
            checks = workspace.verify(acceptance, phase=f"mutation-{index}")
            record["verification"] = checks
            if any(check["timeout"] for check in checks):
                record["outcome"] = "inconclusive"
            else:
                # For JUnit, require actual assertion failures and intact collection.
                metadata_findings = audit_metadata(final_verification, checks)
                collection_errors = {f["rule"] for f in metadata_findings} - {"test_failures_in_report"}
                if collection_errors or any(check.get("metadata", {}).get("errors", 0) for check in checks):
                    record["outcome"] = "inconclusive"
                else:
                    killed = any(check["returncode"] not in {0, None} and
                                 (not check["junit_required"] or check.get("metadata", {}).get("failures", 0) > 0)
                                 for check in checks)
                    record["outcome"] = "killed" if killed else "survived"
        except Exception:
            record["outcome"] = "interrupted"
            report["status"] = "interrupted"
            raise
        finally:
            # Restoration deliberately does not consume budget: it must run after exhaustion.
            path.write_bytes(actual)
            workspace.trace.emit("auditor", "mutation_restored", path=probe["path"], probe_index=index)
        workspace.trace.emit("auditor", "mutation_finished", **{key: record[key] for key in
                             ("path", "function", "operator", "outcome")})
        if record["outcome"] != "killed":
            report["status"] = record["outcome"]
            raise AuditFailed([{"rule": "mutation_" + record["outcome"], "path": record["path"],
                                "function": record["function"]}])
    report["status"] = "passed" if probes else "no_candidates"
