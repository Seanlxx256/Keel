"""Static import presence, never a claim about reachability or runtime failure."""
import ast


def imported_symbol(source, module, symbol):
    tree = ast.parse(source)
    return [{'line': node.lineno, 'local_name': alias.asname or alias.name}
            for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module == module
            for alias in node.names if alias.name == symbol]
