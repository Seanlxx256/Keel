[CmdletBinding()]
param(
    [string]$PythonCommand = "python",
    [ValidateRange(1, 100)][int]$Repeats = 1,
    [switch]$Offline,
    [switch]$PlanOnly,
    [switch]$PrepareOnly
)
$runnerArguments = @("-u", "-X", "faulthandler", (Join-Path $PSScriptRoot "run_swe_independent.py"), "--repeats", $Repeats)
if ($Offline) { $runnerArguments += "--offline" }
if ($PlanOnly) { $runnerArguments += "--plan-only" }
if ($PrepareOnly) { $runnerArguments += "--prepare-only" }
& $PythonCommand @runnerArguments
exit $LASTEXITCODE
