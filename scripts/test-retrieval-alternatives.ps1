param(
    [string]$Python = 'python',
    [string]$Source = '.keel/swe-public/bdb1b28a48574f5fa371d7f53271854e/result.json',
    [string]$Output = ('.keel/retrieval-alternatives/' + (Get-Date -Format 'yyyyMMdd-HHmmss')),
    [string]$SerenaPython = '.keel/tools/serena-venv/Scripts/python.exe',
    [string]$PyrightCommand,
    [switch]$SkipInstall
)
$ErrorActionPreference = 'Stop'
$packageDirectory = Join-Path (Get-Location) '.keel/tools/retrieval-baselines'
if (-not $SkipInstall) {
    # Isolated import directory; never change the caller's environment packages.
    & $Python -m pip install --disable-pip-version-check --target $packageDirectory rank_bm25 bm25s
    if ($LASTEXITCODE -ne 0) { throw 'Optional baseline installation failed; no scores were produced. Inspect pip output.' }
}
$comparisonArgs = @('examples/compare_retrieval_alternatives.py', '--source', $Source,
    '--output', $Output, '--packages-dir', $packageDirectory, '--serena-python', $SerenaPython)
if ($PyrightCommand) { $comparisonArgs += @('--pyright-command', $PyrightCommand) }
& $Python @comparisonArgs
if ($LASTEXITCODE -ne 0) { throw 'Retrieval comparison failed; inspect its saved artifacts.' }
