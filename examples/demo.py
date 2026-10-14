"""Run with python examples/demo.py from the project directory."""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from keel.runtime import run


with tempfile.TemporaryDirectory(prefix="keel-demo-") as directory:
    repo = Path(directory)
    (repo / "app.py").write_text("API_VERSION = 1\n", encoding="utf-8")
    config = {
        "goal": "Migrate API_VERSION from 1 to 2",
        "queries": ["API_VERSION"],
        "budget": {"max_wallclock": 30, "max_tool_calls": 20},
        "work_items": [{"id": "migrate-api", "depends_on": [], "edits": [
            {"path": "app.py", "old": "API_VERSION = 1", "new": "API_VERSION = 2"}]}],
        "acceptance": [[sys.executable, "-c", "import app; assert app.API_VERSION == 2"]],
    }
    output = Path(__file__).resolve().parents[1] / ".keel" / "demo-runs"
    import uuid
    result = run(config, repo, output / uuid.uuid4().hex)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] == "passed" else 1)
