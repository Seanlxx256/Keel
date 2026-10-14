[CmdletBinding()]
param(
    [ValidateRange(1, 12)][int]$Repositories = 1,
    [ValidateRange(1, 100000)][int]$LineBudget = 100,
    [ValidateRange(1, 100)][int]$Repeats = 1,
    [ValidateRange(1, 2048)][int]$EmbeddingNumBatch = 32,
    [int]$Seed = 42,
    [ValidateSet("rrf", "code-aware")][string]$Ranking = "rrf",
    [string]$PythonCommand = "python",
    [switch]$Offline,
    [switch]$PrepareOnly
)
$runnerArguments = @("-u", "-X", "faulthandler", (Join-Path $PSScriptRoot "run_swe_public.py"), "--repositories", $Repositories,
    "--line-budget", $LineBudget, "--repeats", $Repeats, "--seed", $Seed, "--embedding-num-batch", $EmbeddingNumBatch,
    "--ranking", $Ranking)
if ($Offline) { $runnerArguments += "--offline" }
if ($PrepareOnly) { $runnerArguments += "--prepare-only" }
# Stderr carries live progress. Python persists a separate progress JSONL and final result.
& $PythonCommand @runnerArguments
$runnerExit = $LASTEXITCODE
if ($runnerExit -ne 0) { Write-Host "SWE runner exited with code $runnerExit. Inspect the stderr traceback and the printed artifact directory." }
exit $runnerExit
