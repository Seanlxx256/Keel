# Windows terminal environment setup

Run the script in the PowerShell terminal that will run Keel, not through a separate
`powershell -File` process: child processes cannot set their parent's environment.

```powershell
& .\scripts\setup-env.ps1
```

The script selects an active virtual environment, the repository `.venv`, or Python
on PATH, in that order. Override with `-PythonPath`. It checks Python >=3.11,
optional packages, model configuration, Docker, and an existing SWE-bench harness.
It never calls the model API and does not prove credentials are valid.

The configured model's `api_key_env` (currently `KEEL_MODEL_API_KEY`) is required
for OpenAI-compatible model calls. `GITHUB_TOKEN` is optional for GitHub collection;
request it with `-WithGitHub`. `OPENAI_API_KEY` is not required by the current config.
Ollama does not require this API key. Values are entered with masked prompts and
set only for this terminal and child processes. They are not saved to disk or user
environment settings. Rerun after restarting or opening a new terminal.

```powershell
# This workstation's existing main environment; launch Docker if requested.
& .\scripts\setup-env.ps1 -PythonPath D:\code\monocular_depth_estimation\.venv\Scripts\python.exe -WithGitHub -StartDocker

# Read-only diagnostic: no prompts, activation, install, config writes or Docker launch.
& .\scripts\setup-env.ps1 -CheckOnly -WithGitHub

# Fresh checkout: opt in to creating .venv and installing optional integrations.
& .\scripts\setup-env.ps1 -CreateVenv -InstallDependencies
```

If model config is missing, setup asks for endpoint/model and writes a credential-free
config. Existing configs are preserved. Providers may require different response or
token parameter settings; setup does not negotiate endpoint capabilities.
Docker launch is asynchronous; rerun `-CheckOnly` once it is ready. Engine checks
have a 15-second wait bound. Docker absence does not prevent non-container tasks.

SWE-bench uses a separate harness environment. For the current classic dataset:

```powershell
python -m venv .keel/harness-v3
& .keel/harness-v3/Scripts/python.exe -m pip install -r requirements/swebench-eval.txt
```

Do not recreate an existing harness just because the computer restarted. Images,
virtual environments and archived results normally persist on disk. Process-only
credentials and virtual environment selection must be restored in a new terminal.
