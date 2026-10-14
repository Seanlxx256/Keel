from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import time
import uuid

from .graph import link_files
from .parsing import PythonParser
from .vectors import LanceVectors, checked_vectors, embedder_from_spec


SCHEMA_VERSION = 1
IGNORED = {".git", ".keel", ".compass", ".venv", ".venv-deps", "venv", "node_modules",
           "__pycache__", ".pytest_cache", "tmp", "build", "dist"}


def source_files(root):
    for directory, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(name for name in dirs if name not in IGNORED and not (Path(directory) / name).is_symlink())
        for name in sorted(names):
            path = Path(directory) / name
            if path.suffix == ".py" and not path.is_symlink():
                yield path.relative_to(root).as_posix(), path


def fingerprint(root):
    entries = []
    for name, path in source_files(root):
        hashed = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(65536), b""):
                hashed.update(block)
        entries.append((name, hashed.hexdigest()))
    return _fingerprint_entries(entries)


def _fingerprint_entries(entries):
    return hashlib.sha256(json.dumps(sorted(entries), ensure_ascii=False).encode()).hexdigest()


def git_ref(root):
    try:
        result = subprocess.run(["git", "-c", f"safe.directory={root.as_posix()}", "-C", str(root), "rev-parse", "HEAD"],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5, shell=False)
        return result.stdout.decode().strip() if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _schema(db):
    db.executescript("""
        CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE files(path TEXT PRIMARY KEY, module TEXT NOT NULL, content_hash TEXT NOT NULL, status TEXT NOT NULL);
        CREATE TABLE symbols(id TEXT PRIMARY KEY, path TEXT NOT NULL, module TEXT NOT NULL,
            name TEXT NOT NULL, qualname TEXT NOT NULL, kind TEXT NOT NULL, parent_id TEXT,
            start_line INTEGER NOT NULL, end_line INTEGER NOT NULL,
            signature TEXT NOT NULL, docstring TEXT NOT NULL, code TEXT NOT NULL, embed_text TEXT NOT NULL);
        CREATE INDEX symbols_name ON symbols(name);
        CREATE INDEX symbols_qualified ON symbols(qualname);
        CREATE INDEX symbols_path ON symbols(path, start_line);
        CREATE TABLE calls(id INTEGER PRIMARY KEY, path TEXT NOT NULL, source_id TEXT,
            target_id TEXT, target_text TEXT NOT NULL, line INTEGER NOT NULL, resolution TEXT NOT NULL);
        CREATE INDEX calls_source ON calls(source_id);
        CREATE INDEX calls_target ON calls(target_id);
        CREATE TABLE imports(id INTEGER PRIMARY KEY, path TEXT NOT NULL, scope TEXT NOT NULL,
            alias TEXT NOT NULL, target TEXT NOT NULL, imported_module TEXT NOT NULL,
            line INTEGER NOT NULL, resolved_module TEXT);
        CREATE TABLE vectors(id TEXT PRIMARY KEY, vector TEXT NOT NULL);
    """)


def build_index(repo: Path, *, parser="tree-sitter", vector_store="none", embedder=None):
    root = repo.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Repository must be a directory")
    if vector_store not in {"none", "sqlite", "lancedb"}:
        raise ValueError("Vector store must be none, sqlite or lancedb")
    if vector_store != "none" and embedder is None:
        raise ValueError("Vector indexing requires an explicit embedding provider")
    parser_impl = PythonParser(parser)
    started = time.monotonic()
    initial_git_ref = git_ref(root)
    snapshot = fingerprint(root)
    generation = uuid.uuid4().hex
    store = root / ".compass"
    if store.is_symlink():
        raise ValueError("Index directory cannot be a symlink")
    directory = store / "generations" / generation
    if not directory.resolve().is_relative_to(root):
        raise ValueError("Index path escapes repository")
    directory.mkdir(parents=True, exist_ok=False)
    vector_backend = LanceVectors(directory / "lance") if vector_store == "lancedb" else None
    parsed, file_rows, diagnostics = [], [], []
    for name, path in source_files(root):
        if path.stat().st_size > 1_000_000:
            diagnostics.append({"path": name, "error": "File exceeds 1 MB indexing limit"})
            hashed = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(65536), b""):
                    hashed.update(block)
            file_rows.append((name, "", hashed.hexdigest(), "skipped"))
            continue
        raw = path.read_bytes()
        hashed = hashlib.sha256(raw).hexdigest()
        try:
            file = parser_impl.parse(name, raw)
            parsed.append(file)
            file_rows.append((name, file.module, hashed, "indexed"))
        except (SyntaxError, UnicodeError, ValueError, RecursionError) as error:
            diagnostics.append({"path": name, "error": str(error)[:1000]})
            file_rows.append((name, "", hashed, "parse_error"))
    symbols = [symbol for file in parsed for symbol in file.symbols]
    edges, imports = link_files(parsed)
    metadata = {"schema_version": SCHEMA_VERSION, "generation": generation, "repo": str(root),
                "parser": parser, "vector_store": vector_store, "embedding": embedder.spec if vector_store != "none" else None,
                "index_ref": snapshot, "git_ref": initial_git_ref, "diagnostics": diagnostics,
                "complete": not diagnostics, "files": len(file_rows), "symbols": len(symbols),
                "calls": len(edges), "resolved_calls": sum(edge["target_id"] is not None for edge in edges),
                "imports": len(imports), "dimensions": None, "created_at": time.time()}
    db = sqlite3.connect(directory / "symbols.sqlite")
    try:
        _schema(db)
        db.executemany("INSERT INTO files VALUES(?,?,?,?)", file_rows)
        db.executemany("INSERT INTO symbols VALUES(" + ",".join("?" for _ in range(13)) + ")",
                       [tuple(asdict(symbol).values()) for symbol in symbols])
        db.executemany("INSERT INTO calls(path,source_id,target_id,target_text,line,resolution) VALUES(?,?,?,?,?,?)",
                       [tuple(edge.values()) for edge in edges])
        db.executemany("INSERT INTO imports(path,scope,alias,target,imported_module,line,resolved_module) VALUES(?,?,?,?,?,?,?)",
                       [tuple(entry.values()) for entry in imports])
        if vector_store != "none":
            records = []
            for offset in range(0, len(symbols), 32):
                batch = symbols[offset:offset + 32]
                vectors = embedder.embed([symbol.embed_text for symbol in batch])
                metadata["dimensions"] = checked_vectors(vectors, len(batch), metadata["dimensions"])
                for symbol, vector in zip(batch, vectors):
                    if vector_store == "sqlite":
                        db.execute("INSERT INTO vectors VALUES(?,?)", (symbol.id, json.dumps(vector)))
                    else:
                        records.append({"id": symbol.id, "vector": vector})
            if vector_backend is not None:
                vector_backend.write(records)
        # Reject mixed snapshots rather than publishing stale or internally inconsistent data.
        parsed_snapshot = _fingerprint_entries([(row[0], row[2]) for row in file_rows])
        if parsed_snapshot != snapshot or fingerprint(root) != snapshot or git_ref(root) != initial_git_ref:
            raise ValueError("Repository changed during indexing; generation was not published")
        metadata["build_seconds"] = round(time.monotonic() - started, 3)
        db.executemany("INSERT INTO metadata VALUES(?,?)", [(key, json.dumps(value)) for key, value in metadata.items()])
        db.commit()
    finally:
        db.close()
    temporary = store / (generation + ".json")
    temporary.write_text(json.dumps({"generation": generation, "schema_version": SCHEMA_VERSION}), encoding="utf-8")
    os.replace(temporary, store / "current.json")
    return metadata


class RepositoryIndex:
    def __init__(self, repo: Path):
        self.root = repo.resolve(strict=True)
        manifest = self.root / ".compass" / "current.json"
        if not manifest.is_file():
            raise ValueError("No Compass index; run compass index first")
        manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
        generation = manifest_data.get("generation", "")
        if not isinstance(generation, str) or not re.fullmatch(r"[0-9a-f]{32}", generation):
            raise ValueError("Invalid index generation")
        self.directory = (manifest.parent / "generations" / generation).resolve(strict=True)
        if not self.directory.is_relative_to(self.root) or manifest_data.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("Unsupported or invalid Compass index")
        self.db = sqlite3.connect((self.directory / "symbols.sqlite").as_uri() + "?mode=ro", uri=True)
        self.db.row_factory = sqlite3.Row
        self.metadata = {row[0]: json.loads(row[1]) for row in self.db.execute("SELECT key,value FROM metadata")}
        if self.metadata.get("schema_version") != SCHEMA_VERSION or self.metadata.get("repo") != str(self.root):
            self.db.close()
            raise ValueError("Index schema or repository identity does not match")
        # One scan per query session. Reopen for a new freshness observation.
        self.stale = (fingerprint(self.root) != self.metadata["index_ref"] or
                      (self.metadata["git_ref"] is not None and git_ref(self.root) != self.metadata["git_ref"]))

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def envelope(self, results, tier="T0", **extra):
        return {"tier": tier, "confidence": None, "index_ref": self.metadata["index_ref"],
                "git_ref": self.metadata["git_ref"], "generation": self.metadata["generation"],
                "stale": self.stale, "complete": self.metadata["complete"], "results": results, **extra}

    def require_fresh(self):
        if self.stale:
            raise ValueError("Compass index is stale; rebuild before reading code or graph results")

    def find_symbol(self, name, limit=20):
        self.require_fresh()
        self._limit(limit)
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Symbol name must be nonempty")
        rows = self.db.execute("SELECT * FROM symbols WHERE name=? OR qualname=? OR module||'.'||qualname=? ORDER BY path,start_line LIMIT ?",
                               (name, name, name, limit + 1)).fetchall()
        return self.envelope([dict(row) for row in rows[:limit]], truncated=len(rows) > limit)

    def context(self, path, line, limit=30):
        self.require_fresh()
        self._limit(limit)
        if type(line) is not int or line <= 0:
            raise ValueError("line must be a positive integer")
        row = self.db.execute("SELECT * FROM symbols WHERE path=? AND start_line<=? AND end_line>=? "
                              "ORDER BY end_line-start_line ASC LIMIT 1", (path.replace("\\", "/"), line, line)).fetchone()
        if row is None:
            return self.envelope([])
        outgoing = self.db.execute("SELECT * FROM calls WHERE source_id=? ORDER BY line LIMIT ?", (row["id"], limit + 1)).fetchall()
        incoming = self.db.execute("SELECT * FROM calls WHERE target_id=? ORDER BY path,line LIMIT ?", (row["id"], limit + 1)).fetchall()
        neighbors = {edge["target_id"] for edge in outgoing[:limit] if edge["target_id"]} | {
            edge["source_id"] for edge in incoming[:limit] if edge["source_id"]}
        return self.envelope([dict(row)], outgoing=[dict(edge) for edge in outgoing[:limit]],
                             incoming=[dict(edge) for edge in incoming[:limit]],
                             neighbors=[dict(self.db.execute("SELECT * FROM symbols WHERE id=?", (identifier,)).fetchone())
                                        for identifier in sorted(neighbors)],
                             truncated=len(outgoing) > limit or len(incoming) > limit)

    def search_vector(self, query, limit=10):
        self.require_fresh()
        self._limit(limit)
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Query must be nonempty")
        if self.metadata["vector_store"] == "none":
            raise ValueError("Index has no vectors; rebuild with an explicit vector store and embedding provider")
        if not self.metadata["symbols"]:
            return self.envelope([], tier="vector", embedding=self.metadata["embedding"])
        vector = embedder_from_spec(self.metadata["embedding"]).embed([query])[0]
        checked_vectors([vector], 1, self.metadata["dimensions"])
        if self.metadata["vector_store"] == "lancedb":
            hits = LanceVectors(self.directory / "lance").search(vector, limit)
        else:
            norm = math.sqrt(sum(value * value for value in vector))
            hits = []
            for row in self.db.execute("SELECT id,vector FROM vectors"):
                other = json.loads(row["vector"])
                similarity = sum(a * b for a, b in zip(vector, other)) / (norm * math.sqrt(sum(v * v for v in other)))
                hits.append({"id": row["id"], "distance": 1 - similarity})
            hits.sort(key=lambda row: (row["distance"], row["id"]))
        results = []
        for hit in hits[:limit]:
            row = self.db.execute("SELECT * FROM symbols WHERE id=?", (hit["id"],)).fetchone()
            results.append({**dict(row), "distance": hit["distance"]})
        return self.envelope(results, tier="vector", embedding=self.metadata["embedding"])

    @staticmethod
    def _limit(limit):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit must be an integer from 1 to 100")
