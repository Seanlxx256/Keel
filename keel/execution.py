"""Operator-configured verifier execution. Docker is optional and never falls back."""
from __future__ import annotations

import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid

from .core import PolicyDenied


def normalize_acceptance(entries):
    if not isinstance(entries, list) or not entries:
        raise ValueError("acceptance must contain at least one command")
    normalized = []
    for entry in entries:
        if isinstance(entry, dict):
            if set(entry) - {"command", "junit"} or type(entry.get("junit", False)) is not bool:
                raise ValueError("Acceptance objects allow only command and boolean junit")
            command, junit = entry.get("command"), entry.get("junit", False)
        else:
            command, junit = entry, False
        if not isinstance(command, list) or not command or any(not isinstance(a, str) or not a or "\x00" in a for a in command):
            raise ValueError("Acceptance command must be a nonempty argument array")
        if junit and not any("{junit}" in part for part in command):
            raise ValueError("JUnit-enabled commands require a {junit} output placeholder")
        if not junit and any("{junit}" in part for part in command):
            raise ValueError("{junit} requires junit: true")
        normalized.append({"command": list(command), "junit": junit})
    return normalized


def validate_execution(config):
    if not isinstance(config, dict) or set(config) - {"backend", "image", "cpus", "memory_mb", "pids_limit"}:
        raise ValueError("Unknown execution settings")
    backend = config.get("backend", "local")
    if backend not in {"local", "docker"}:
        raise ValueError("execution.backend must be local or docker")
    if backend == "local" and set(config) - {"backend"}:
        raise ValueError("Resource settings require the docker backend")
    if backend == "docker":
        image = config.get("image")
        if not isinstance(image, str) or not image or image.startswith("-") or any(c.isspace() for c in image):
            raise ValueError("Docker execution requires a valid operator-supplied image name")
        cpus = config.get("cpus", 1)
        if type(cpus) not in {int, float} or not math.isfinite(cpus) or cpus <= 0:
            raise ValueError("cpus must be finite and positive")
        for key, default in (("memory_mb", 512), ("pids_limit", 128)):
            if type(config.get(key, default)) is not int or config.get(key, default) <= 0:
                raise ValueError(f"{key} must be a positive integer")


class CommandRunner:
    def __init__(self, config=None):
        self.config = config or {}
        validate_execution(self.config)
        self.backend = self.config.get("backend", "local")

    def check_available(self):
        if self.backend == "docker" and shutil.which("docker") is None:
            raise PolicyDenied("Docker backend requested but docker is unavailable; no local fallback")

    def docker_command(self, command, root: Path, reports: Path | None, name: str):
        if "," in str(root) or (reports is not None and "," in str(reports)):
            raise ValueError("Docker bind-mount paths cannot contain commas")
        args = ["docker", "run", "--rm", "--pull=never", "--name", name, "--init",
                "--network=none", "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges",
                "--user=65534:65534", "--cpus", str(self.config.get("cpus", 1)),
                "--memory", f"{self.config.get('memory_mb', 512)}m",
                "--memory-swap", f"{self.config.get('memory_mb', 512)}m",
                "--pids-limit", str(self.config.get("pids_limit", 128)),
                "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m", "--shm-size=16m",
                "--env", "PYTHONDONTWRITEBYTECODE=1", "--env", "PYTHONPYCACHEPREFIX=/tmp/keel-pycache",
                "--env", "HOME=/tmp",
                "--mount", f"type=bind,source={root},target=/workspace,readonly", "--workdir", "/workspace"]
        if reports is not None:
            args += ["--mount", f"type=bind,source={reports},target=/keel-reports"]
        return args + [self.config["image"], *command]

    def run(self, command, root: Path, timeout: float, reports: Path | None = None):
        # Docker resolves bind sources independently of the subprocess cwd.
        # Resolve once on the host so relative callers mount the same directory
        # that local execution and source validation use.
        root = Path(root).resolve(strict=True)
        if not root.is_dir():
            raise ValueError("Execution workspace must be a directory")
        if reports is not None:
            reports = Path(reports).resolve(strict=True)
            if not reports.is_dir():
                raise ValueError("Execution reports path must be a directory")
        self.check_available()
        name = "keel-" + uuid.uuid4().hex
        launched = self.docker_command(command, root, reports, name) if self.backend == "docker" else command
        try:
            with tempfile.TemporaryDirectory(prefix="keel-pycache-") as pycache:
                environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPYCACHEPREFIX": pycache}
                completed = subprocess.run(launched, cwd=root, shell=False, stdin=subprocess.DEVNULL,
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                           timeout=timeout, env=environment)
            return {"returncode": completed.returncode, "timeout": False,
                    "stdout": completed.stdout.decode("utf-8", errors="replace"),
                    "stderr": completed.stderr.decode("utf-8", errors="replace"), "backend": self.backend}
        except subprocess.TimeoutExpired as error:
            if self.backend == "docker":
                try:
                    cleanup = subprocess.run(["docker", "rm", "--force", name], shell=False,
                                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
                    if cleanup.returncode != 0 and b"No such container" not in cleanup.stderr:
                        raise PolicyDenied(f"Timed out; failed to remove container {name}")
                except (OSError, subprocess.TimeoutExpired):
                    raise PolicyDenied(f"Timed out; could not confirm cleanup of container {name}") from None
            return {"returncode": None, "timeout": True,
                    "stdout": (error.stdout or b"").decode("utf-8", errors="replace"),
                    "stderr": (error.stderr or b"").decode("utf-8", errors="replace"), "backend": self.backend}
