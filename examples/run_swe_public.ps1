[CmdletBinding()]
param(
    [ValidateRange(1, 12)][int]$Repositories = 1,
    [ValidateRange(1, 20)][int]$InstancesPerRepository = 1,
    [ValidateRange(1, 100000)][int]$LineBudget = 100,
    [ValidateRange(1, 100)][int]$Repeats = 1,
    [ValidateRange(1, 2048)][int]$EmbeddingNumBatch = 32,
    [int]$Seed = 42,
    [ValidateSet("rrf", "code-aware")][string]$Ranking = "rrf",
    [ValidateSet("preview", "read")][string]$EvidencePolicy = "read",
    [ValidateRange(1024, 131072)][int]$ChatContext = 8192,
    [string]$PythonCommand = "python",
    [switch]$Offline,
    [switch]$CompareRankings,
    [switch]$PlanOnly,
    [switch]$PrepareOnly
)
$runnerArguments = @("-u", "-X", "faulthandler", (Join-Path $PSScriptRoot "run_swe_public.py"), "--repositories", $Repositories,
    "--line-budget", $LineBudget, "--repeats", $Repeats, "--seed", $Seed, "--embedding-num-batch", $EmbeddingNumBatch,
    "--ranking", $Ranking, "--evidence-policy", $EvidencePolicy, "--chat-context", $ChatContext)
$runnerArguments += @("--instances-per-repository", $InstancesPerRepository)
if ($Offline) { $runnerArguments += "--offline" }
if ($CompareRankings) { $runnerArguments += "--compare-rankings" }
if ($PlanOnly) { $runnerArguments += "--plan-only" }
if ($PrepareOnly) { $runnerArguments += "--prepare-only" }
# Stderr carries live progress. Python persists a separate progress JSONL and final result.
& $PythonCommand @runnerArguments
$runnerExit = $LASTEXITCODE
if ($runnerExit -ne 0) { Write-Host "SWE runner exited with code $runnerExit. Inspect the stderr traceback and the printed artifact directory." }
exit $runnerExit
