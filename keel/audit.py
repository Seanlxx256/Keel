"""Deterministic diff and test-execution checks; deliberately no LLM judgments."""
from __future__ import annotations

import ast
from collections import Counter
import configparser
import json
from pathlib import Path, PurePosixPath
import tomllib
import xml.etree.ElementTree as ET


PROTECTED_PARTS = {"test", "tests", "testing", "__tests__", ".github", ".git", ".keel", ".compass"}
PROTECTED_NAMES = {"conftest.py", "pytest.ini", "tox.ini", ".gitlab-ci.yml", "jenkinsfile",
                   "azure-pipelines.yml", ".circleci", "noxfile.py"}
TEST_SUFFIXES = ("_test.py", ".test.js", ".test.jsx", ".test.ts", ".test.tsx",
                 ".spec.js", ".spec.jsx", ".spec.ts", ".spec.tsx")


def protected_path(name: str) -> bool:
    path = PurePosixPath(name.replace("\\", "/").lower())
    return bool(set(path.parts) & (PROTECTED_PARTS | {".circleci"}) or
                path.name in PROTECTED_NAMES or path.name.startswith("test_") or
                path.name.endswith(TEST_SUFFIXES))


def _truth(node):
    """Recognize only side-effect-free, literal true assertions."""
    try:
        return bool(ast.literal_eval(node))
    except (ValueError, TypeError, SyntaxError):
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            value = _truth(node.operand)
            return None if value is None else not value
        if isinstance(node, ast.Compare) and len(node.ops) == 1 and isinstance(node.ops[0], ast.Eq):
            try:
                return ast.literal_eval(node.left) == ast.literal_eval(node.comparators[0])
            except (ValueError, TypeError):
                return None
        return None


def _python_facts(text: str):
    tree = ast.parse(text)
    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for entry in node.names:
                aliases[entry.asname or entry.name.split(".")[0]] = entry.name if entry.asname else entry.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom) and node.module:
            for entry in node.names:
                aliases[entry.asname or entry.name] = node.module + "." + entry.name

    def qualified(node):
        if isinstance(node, ast.Name):
            return aliases.get(node.id, node.id)
        if isinstance(node, ast.Attribute):
            return qualified(node.value) + "." + node.attr
        return ""

    assertions = Counter()
    true_assertions = Counter()
    skips = Counter()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert):
            signature = ast.dump(node.test)
            assertions[signature] += 1
            if _truth(node.test) is True:
                true_assertions[signature] += 1
        # Standard unittest assertion methods, including assertRaises contexts.
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr.startswith("assert"):
            assertions[ast.dump(node)] += 1
        target = node.func if isinstance(node, ast.Call) else node
        if isinstance(target, (ast.Name, ast.Attribute)):
            name = qualified(target)
            if name in {"pytest.skip", "pytest.xfail", "pytest.mark.skip", "pytest.mark.skipif", "pytest.mark.xfail",
                        "unittest.skip", "unittest.skipIf", "unittest.skipUnless", "unittest.expectedFailure"} or name.endswith(".skipTest"):
                # Count canonical names rather than import spelling; walking Call and Attribute
                # yields two occurrences for calls, consistently before and after an edit.
                skips[name] += 1
    return assertions, true_assertions, skips


def audit_text(name: str, before: bytes, after: bytes) -> list[dict]:
    if before == after:
        return []
    findings = []
    if protected_path(name):
        findings.append({"rule": "protected_file_changed", "path": name})
    try:
        filename = PurePosixPath(name).name.lower()
        old_config = new_config = None
        if filename == "pyproject.toml":
            old_tool = tomllib.loads(before.decode("utf-8")).get("tool", {})
            new_tool = tomllib.loads(after.decode("utf-8")).get("tool", {})
            old_config = {key: old_tool.get(key) for key in ("pytest", "coverage")}
            new_config = {key: new_tool.get(key) for key in ("pytest", "coverage")}
        elif filename == "package.json":
            old, new = json.loads(before), json.loads(after)
            old_config = {key: old.get(key) for key in ("scripts", "jest", "nyc")}
            new_config = {key: new.get(key) for key in ("scripts", "jest", "nyc")}
        elif filename == "setup.cfg":
            def test_sections(raw):
                parser = configparser.ConfigParser(interpolation=None)
                parser.read_string(raw.decode("utf-8"))
                return {section: dict(parser[section]) for section in parser.sections()
                        if section == "tool:pytest" or section.startswith("coverage:")}
            old_config, new_config = test_sections(before), test_sections(after)
        if old_config != new_config:
            findings.append({"rule": "test_configuration_changed", "path": name})
    except (ValueError, UnicodeError, configparser.Error, AttributeError):
        findings.append({"rule": "configuration_audit_parse_failed", "path": name})
    if Path(name).suffix.lower() == ".py":
        try:
            old_asserts, old_true, old_skips = _python_facts(before.decode("utf-8"))
            new_asserts, new_true, new_skips = _python_facts(after.decode("utf-8"))
            if old_asserts - new_asserts:
                findings.append({"rule": "assertion_removed_or_rewritten", "path": name})
            if new_true - old_true:
                findings.append({"rule": "constant_true_assertion_added", "path": name})
            if new_skips - old_skips:
                findings.append({"rule": "skip_or_xfail_added", "path": name})
        except (SyntaxError, UnicodeError, RecursionError, ValueError):
            findings.append({"rule": "python_audit_parse_failed", "path": name})
    return findings


def read_junit(path: Path) -> dict:
    """Read leaf test cases, never trust user-controlled aggregate counts."""
    if not path.is_file() or path.is_symlink():
        raise ValueError("A fresh, regular JUnit XML report is required")
    if path.stat().st_size > 10_000_000:
        raise ValueError("JUnit XML report exceeds 10 MB")
    raw = path.read_bytes()
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("JUnit XML declarations with DTDs/entities are unsupported")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as error:
        raise ValueError("Malformed JUnit XML report") from error
    if root.tag not in {"testsuite", "testsuites"}:
        raise ValueError("Expected JUnit testsuite or testsuites root")
    cases = list(root.iter("testcase"))
    identities = Counter()
    skipped = failed = errors = 0
    for case in cases:
        if not case.get("name"):
            raise ValueError("JUnit test cases require names")
        identities[case.get("classname", "") + "::" + case.get("name")] += 1
        skipped += case.find("skipped") is not None
        failed += case.find("failure") is not None
        errors += case.find("error") is not None
    return {"collected": len(cases), "skipped": skipped, "failures": failed, "errors": errors,
            "test_ids": dict(identities)}


def audit_metadata(baseline: list[dict], final: list[dict]) -> list[dict]:
    findings = []
    for index, result in enumerate(final):
        if not result.get("junit_required"):
            continue
        prefix = {"command_index": index}
        old = baseline[index].get("metadata") if index < len(baseline) else None
        new = result.get("metadata")
        if old is None or new is None:
            findings.append({**prefix, "rule": "missing_test_metadata"})
            continue
        if new["collected"] == 0 or new["collected"] <= new["skipped"]:
            findings.append({**prefix, "rule": "no_tests_executed"})
        if Counter(old["test_ids"]) - Counter(new["test_ids"]):
            findings.append({**prefix, "rule": "test_cases_removed"})
        if new["skipped"] > old["skipped"]:
            findings.append({**prefix, "rule": "skipped_tests_increased"})
        if new["failures"] or new["errors"]:
            findings.append({**prefix, "rule": "test_failures_in_report"})
    return findings
