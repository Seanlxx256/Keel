"""Python-first structural chunks and conservative static references.

Tree-sitter provides byte ranges; Python AST supplies language-specific metadata.
The stdlib range backend is explicit, never an invisible dependency fallback.
"""
from __future__ import annotations

import ast
from bisect import bisect_right
from dataclasses import dataclass, field
import hashlib
from pathlib import PurePosixPath


@dataclass
class Symbol:
    id: str
    path: str
    module: str
    name: str
    qualname: str
    kind: str
    parent_id: str | None
    start_line: int
    end_line: int
    signature: str
    docstring: str
    code: str
    embed_text: str


@dataclass
class ParsedFile:
    path: str
    module: str
    symbols: list[Symbol] = field(default_factory=list)
    imports: list[dict] = field(default_factory=list)
    calls: list[dict] = field(default_factory=list)


def module_name(path):
    parts = list(PurePosixPath(path).with_suffix("").parts)
    if parts and parts[0] == "src":
        parts.pop(0)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _assigned(statements):
    names = set()

    class Bindings(ast.NodeVisitor):
        def visit_Name(self, node):
            if isinstance(node.ctx, ast.Store):
                names.add(node.id)
        def visit_FunctionDef(self, node): pass
        def visit_AsyncFunctionDef(self, node): pass
        def visit_ClassDef(self, node): pass
        def visit_Lambda(self, node): pass
    visitor = Bindings()
    for statement in statements:
        visitor.visit(statement)
    return names


class PythonParser:
    def __init__(self, backend="tree-sitter"):
        if backend not in {"tree-sitter", "python-ast"}:
            raise ValueError("Parser must be tree-sitter or python-ast")
        self.backend = backend
        self.parser = None
        if backend == "tree-sitter":
            try:
                from tree_sitter import Language, Parser
                import tree_sitter_python
            except ImportError:
                raise ValueError("Tree-sitter dependencies unavailable; install .[compass] or explicitly use --parser python-ast") from None
            self.parser = Parser(Language(tree_sitter_python.language()))

    def parse(self, path: str, raw: bytes) -> ParsedFile:
        text = raw.decode("utf-8")
        tree = ast.parse(text, filename=path)
        lines = raw.splitlines(keepends=True)
        offsets = [0]
        for line in lines:
            offsets.append(offsets[-1] + len(line))
        ranges = {}
        if self.parser is not None:
            syntax_tree = self.parser.parse(raw)
            root = syntax_tree.root_node
            if root.has_error:
                raise ValueError(f"Tree-sitter found syntax errors: {path}")
            # Cursor traversal avoids cached parent/child Node graphs, whose GC can
            # crash the 0.26 bindings on large Python files on Windows.
            cursor = syntax_tree.walk()
            ancestors = []
            while True:
                node = cursor.node
                if node.type in {"function_definition", "class_definition"}:
                    name = node.child_by_field_name("name")
                    body = node.child_by_field_name("body")
                    parent = ancestors[-1] if ancestors else None
                    start, end = (parent[1], parent[2]) if parent and parent[0] == "decorated_definition" else (node.start_byte, node.end_byte)
                    # Derive rows from stable byte offsets instead of temporary Point
                    # wrappers (0.26 can return corrupted rows during long traversals).
                    ranges[(bisect_right(offsets, node.start_byte), raw[name.start_byte:name.end_byte].decode())] = (
                        start, end, node.start_byte, body.start_byte)
                if cursor.goto_first_child():
                    ancestors.append((node.type, node.start_byte, node.end_byte))
                    continue
                if cursor.goto_next_sibling():
                    continue
                while ancestors:
                    cursor.goto_parent()
                    ancestors.pop()
                    if cursor.goto_next_sibling():
                        break
                else:
                    break
        result = ParsedFile(path, module_name(path))
        def source_range(node):
            if ranges:
                return ranges[(node.lineno, node.name)]
            start = offsets[node.lineno - 1] + node.col_offset
            decorated = start
            if node.decorator_list:
                decorator = node.decorator_list[0]
                decorated = offsets[decorator.lineno - 1] + decorator.col_offset - 1
            end = offsets[node.end_lineno - 1] + node.end_col_offset
            first = node.body[0]
            body = offsets[first.lineno - 1] + first.col_offset
            return decorated, end, start, body

        class Extractor(ast.NodeVisitor):
            def __init__(self):
                self.scopes = []
                self.class_scope = None
                self.bound = [_assigned(tree.body)]

            @property
            def scope(self):
                return self.scopes[-1] if self.scopes else None

            def definition(self, node, kind):
                parent = self.scope
                qualname = (parent.qualname + "." if parent else "") + node.name
                identifier = hashlib.sha256(f"{path}:{qualname}:{node.lineno}".encode()).hexdigest()[:24]
                start, end, header, body = source_range(node)
                signature = raw[header:body].decode().strip()
                docstring = ast.get_docstring(node, clean=True) or ""
                symbol = Symbol(identifier, path, result.module, node.name, qualname, kind,
                                parent.id if parent else None, raw[:start].count(b"\n") + 1,
                                node.end_lineno, signature, docstring, raw[start:end].decode(),
                                f"{path}\n{result.module}.{qualname}\n{signature}\n{docstring}"[:12000])
                result.symbols.append(symbol)
                # Decorators/defaults execute in the enclosing scope.
                for decorator in node.decorator_list:
                    self.visit(decorator)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for default in node.args.defaults + [d for d in node.args.kw_defaults if d is not None]:
                        self.visit(default)
                previous_class = self.class_scope
                if kind == "class":
                    for base in node.bases:
                        self.visit(base)
                    self.class_scope = qualname
                self.scopes.append(symbol)
                assigned = set()
                if kind != "class":
                    assigned.update(a.arg for a in node.args.posonlyargs + node.args.args + node.args.kwonlyargs)
                    for arg in (node.args.vararg, node.args.kwarg):
                        if arg:
                            assigned.add(arg.arg)

                    assigned.update(_assigned(node.body))
                self.bound.append(assigned)
                for statement in node.body:
                    self.visit(statement)
                self.bound.pop()
                self.scopes.pop()
                self.class_scope = previous_class

            def visit_FunctionDef(self, node):
                self.definition(node, "method" if self.scope and self.scope.kind == "class" else "function")

            visit_AsyncFunctionDef = visit_FunctionDef

            def visit_ClassDef(self, node):
                self.definition(node, "class")

            def visit_Import(self, node):
                for entry in node.names:
                    result.imports.append({"scope": self.scope.qualname if self.scope else "",
                                           "alias": entry.asname or entry.name.split(".")[0],
                                           "target": entry.name if entry.asname else entry.name.split(".")[0],
                                           "imported_module": entry.name, "line": node.lineno})

            def visit_ImportFrom(self, node):
                base = node.module or ""
                if node.level:
                    package = result.module.split(".") if PurePosixPath(path).name == "__init__.py" else result.module.split(".")[:-1]
                    if node.level > len(package):
                        base = "<unresolved-relative>"
                    else:
                        base = ".".join(package[:len(package) - node.level + 1] + ([base] if base else []))
                for entry in node.names:
                    result.imports.append({"scope": self.scope.qualname if self.scope else "",
                                           "alias": entry.asname or entry.name,
                                           "target": base + "." + entry.name if base else entry.name,
                                           "imported_module": base, "line": node.lineno})

            def visit_Call(self, node):
                def dotted(value):
                    if isinstance(value, ast.Name):
                        return value.id
                    if isinstance(value, ast.Attribute):
                        prefix = dotted(value.value)
                        return prefix + "." + value.attr if prefix else ""
                    return ""
                target = dotted(node.func)
                result.calls.append({"source_id": self.scope.id if self.scope else None,
                                     "scope": self.scope.qualname if self.scope else "", "target": target or ast.unparse(node.func),
                                     "simple": bool(target), "owner_class": self.class_scope,
                                     "blocked": sorted(set().union(*self.bound)) if self.bound else [], "line": node.lineno})
                self.generic_visit(node)

        Extractor().visit(tree)
        return result
