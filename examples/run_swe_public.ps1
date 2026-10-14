[CmdletBinding()]
param(
    [ValidateRange(1, 12)][int]$Repositories = 1,
    [ValidateRange(1, 100000)][int]$LineBudget = 100,
    [ValidateRange(1, 100)][int]$Repeats = 1,
    [int]$Seed = 42,
    [string]$PythonCommand = "python",
    [switch]$Offline,
    [switch]$PrepareOnly
)
$runnerArguments = @("-u", (Join-Path $PSScriptRoot "run_swe_public.py"), "--repositories", $Repositories,
    "--line-budget", $LineBudget, "--repeats", $Repeats, "--seed", $Seed)
if ($Offline) { $runnerArguments += "--offline" }
if ($PrepareOnly) { $runnerArguments += "--prepare-only" }
# Stderr carries live progress. Python persists a separate progress JSONL and final result.
& $PythonCommand @runnerArguments
exit $LASTEXITCODE
