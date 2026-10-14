"""Demonstrate a covered mutation and an uncovered mutation without a model or Docker."""
import json
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from keel.runtime import run


def demo():
    summaries = []
    for label, check in (("covered", "import app; assert app.version() == 2"),
                         ("uncovered", "import app; assert callable(app.version)")):
        with tempfile.TemporaryDirectory(prefix="keel-mutation-") as directory:
            repo = Path(directory)
            (repo / "app.py").write_bytes(b"def version():\n    return 1\n")
            output = Path(__file__).resolve().parents[1] / ".keel" / "mutation-demos" / uuid.uuid4().hex
            config = {"goal": "Upgrade version() to return 2", "mutation_samples": 1,
                      "work_items": [{"id": "upgrade", "edits": [
                          {"path": "app.py", "old": "return 1", "new": "return 2"}]}],
                      "acceptance": [[sys.executable, "-c", check]]}
            result = run(config, repo, output)
            restored = (repo / "app.py").read_bytes() == b"def version():\n    return 2\n"
            summaries.append({"scenario": label, "status": result["status"],
                              "mutation": result["mutation"]["status"], "restored": restored,
                              "result": str(output / "result.json")})
    print(json.dumps(summaries, indent=2))
    return 0 if (summaries[0]["status"] == "passed" and summaries[1]["status"] == "failed"
                 and all(item["restored"] for item in summaries)) else 1


if __name__ == "__main__":
    raise SystemExit(demo())
