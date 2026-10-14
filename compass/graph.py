"""Conservative lexical linking. Dynamic targets remain explicit unresolved edges."""


def link_files(parsed_files):
    symbols = [symbol for file in parsed_files for symbol in file.symbols]
    absolute = {}
    for symbol in symbols:
        key = symbol.module + "." + symbol.qualname
        absolute.setdefault(key, []).append(symbol.id)
    modules = {file.module for file in parsed_files}
    edges = []
    imports = []
    for file in parsed_files:
        for entry in file.imports:
            imports.append({"path": file.path, **entry,
                            "resolved_module": entry["imported_module"] if entry["imported_module"] in modules else None})
        for call in file.calls:
            target = call["target"]
            pieces = target.split(".")
            candidates = []
            reason = "dynamic_or_unresolved"
            if call["simple"]:
                scope = call["scope"]
                scopes = [".".join(scope.split(".")[:i]) for i in range(len(scope.split(".")), 0, -1)] if scope else []
                scopes.append("")
                for lexical in scopes:
                    # Class-local imports are not visible as bare names inside methods.
                    parents = [symbol for symbol in file.symbols if symbol.qualname == lexical]
                    if lexical != call["scope"] and lexical and any(symbol.kind == "class" for symbol in parents):
                        continue
                    if pieces[0] in call["blocked"] and pieces[0] not in {"self", "cls"}:
                        reason = "shadowed_binding"
                        break
                    imported = [entry for entry in file.imports if entry["scope"] == lexical and entry["alias"] == pieces[0]]
                    if imported:
                        keys = {entry["target"] + ("." + ".".join(pieces[1:]) if len(pieces) > 1 else "") for entry in imported}
                        candidates = [identifier for key in keys for identifier in absolute.get(key, [])]
                        reason = "import"
                        break
                    # Bound local variables/parameters are not inferred as callable symbols.
                    if pieces[0] in {"self", "cls"} and len(pieces) > 1 and call["owner_class"]:
                        key = file.module + "." + call["owner_class"] + "." + ".".join(pieces[1:])
                        candidates = absolute.get(key, [])
                        reason = "receiver_candidate"
                        break
                    # A class namespace is not a function's enclosing lexical namespace.
                    if lexical != call["scope"] and lexical and any(symbol.kind == "class" for symbol in parents):
                        continue
                    key = file.module + "." + (lexical + "." if lexical else "") + target
                    if key in absolute:
                        candidates = absolute[key]
                        reason = "lexical"
                        break
            target_id = candidates[0] if len(candidates) == 1 else None
            edges.append({"path": file.path, "source_id": call["source_id"], "target_id": target_id,
                          "target_text": target, "line": call["line"],
                          "resolution": reason if target_id else "ambiguous" if len(candidates) > 1 else reason + ":unresolved"})
    return edges, imports
