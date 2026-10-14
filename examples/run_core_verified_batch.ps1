[CmdletBinding()]
param(
    [ValidateRange(1, 1000000)][int]$MaxQueries = 20,
    [ValidateRange(1, 100)][int]$Repeats = 3,
    [int]$Seed = 42,
    [ValidateRange(1, 3600)][int]$DownloadTimeoutSeconds = 300,
    [string]$PythonCommand = "python",
    [switch]$Offline
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$revision = "23da5d97a8a4495d4bd6d5616aa86d5a12a60699"
$remoteDirectory = "data/LEVEL-2/SWE-bench_Verified"
$projectRoot = Split-Path -Parent $PSScriptRoot
$cacheRoot = Join-Path $projectRoot ".keel/datasets/core/$revision"
$runName = "$(Get-Date -Format 'yyyyMMdd-HHmmss')-$([guid]::NewGuid().ToString('N').Substring(0, 8))"
$runDirectory = Join-Path $projectRoot ".keel/core-verified-batch/$runName"
$utf8 = New-Object System.Text.UTF8Encoding($false)

function Write-JsonFile {
    param([string]$Destination, $Value)
    [IO.File]::WriteAllText($Destination, ($Value | ConvertTo-Json -Depth 20), $utf8)
}

function Receive-CoreFile {
    param([string]$Url, [string]$Destination)
    if ($Offline) { throw "Offline cache is missing or invalid: $Destination" }
    $partial = "$Destination.partial"
    & curl.exe --fail --location --show-error --connect-timeout 10 `
        --max-time $DownloadTimeoutSeconds --retry 2 --retry-delay 2 `
        --output $partial $Url
    if ($LASTEXITCODE -ne 0) { throw "Download failed: $Url. Completed cache files are retained; rerun to retry." }
    if (-not (Test-Path -LiteralPath $partial) -or (Get-Item -LiteralPath $partial).Length -eq 0) {
        throw "Empty download: $Url"
    }
    Move-Item -LiteralPath $partial -Destination $Destination -Force
}

Push-Location $projectRoot
try {
    if (-not $Offline) { Get-Command curl.exe -ErrorAction Stop | Out-Null }
    Get-Command $PythonCommand -ErrorAction Stop | Out-Null
    & $PythonCommand -c "import sys, compass; print('Python:', sys.executable); print('Compass:', compass.__file__)"
    if ($LASTEXITCODE -ne 0) { throw "Cannot import Compass using the selected Python" }
    New-Item -ItemType Directory -Path $cacheRoot -Force | Out-Null
    New-Item -ItemType Directory -Path $runDirectory -Force | Out-Null
    Write-Host "Artifacts: $runDirectory"
    Write-Host "Cache: $cacheRoot"
    Write-Host "[1/3] Loading the fixed Verified Level-2 repository list..."
    $listingPath = Join-Path $cacheRoot "verified-directory.json"
    if (-not $Offline) {
        $treeUrl = "https://huggingface.co/api/datasets/zhangfw123/CORE-Bench/tree/${revision}/${remoteDirectory}?recursive=true&limit=1000"
        Receive-CoreFile -Url $treeUrl -Destination $listingPath
    }
    $files = ConvertFrom-Json -InputObject ([IO.File]::ReadAllText($listingPath, $utf8))
    if ($null -eq $files -or $files -isnot [array] -or $files.Count -ge 1000) {
        throw "Missing, invalid or possibly paginated directory listing"
    }
    $corpora = @($files | Where-Object { $_.type -eq "file" -and $_.path.EndsWith("/corpus.jsonl") } | Sort-Object path)
    if ($corpora.Count -ne 12) { throw "Expected exactly 12 pinned Verified repositories; found $($corpora.Count). Refusing a partial batch." }
    $seen = @{}
    $datasets = @()
    $position = 0
    foreach ($corpus in $corpora) {
        $remotePath = $corpus.path -replace '/corpus\.jsonl$', ''
        $prefix = "$remoteDirectory/"
        if (-not $remotePath.StartsWith($prefix)) { throw "Unexpected repository path: $remotePath" }
        $repository = $remotePath.Substring($prefix.Length)
        if ($repository -notmatch '^[A-Za-z0-9_.-]+$' -or $repository -eq '.' -or $repository -eq '..' -or $seen.ContainsKey($repository)) {
            throw "Unsafe or duplicate repository name: $repository"
        }
        $seen[$repository] = $true
        $position++
        Write-Host "[2/3] Repository $position/12 : $repository"
        $localDirectory = Join-Path $cacheRoot $repository
        New-Item -ItemType Directory -Path $localDirectory -Force | Out-Null
        $hashes = @{}
        foreach ($name in @("corpus.jsonl", "queries.jsonl", "qrels.jsonl")) {
            $path = "$remotePath/$name"
            $metadata = @($files | Where-Object { $_.type -eq "file" -and $_.path -eq $path })
            if ($metadata.Count -ne 1) { throw "Missing or duplicated input: $path" }
            $destination = Join-Path $localDirectory $name
            $receiptPath = "$destination.receipt.json"
            $cached = $false
            if ((Test-Path -LiteralPath $destination) -and (Test-Path -LiteralPath $receiptPath)) {
                try {
                    $receipt = ConvertFrom-Json -InputObject ([IO.File]::ReadAllText($receiptPath, $utf8))
                    $actual = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant()
                    $cached = $receipt.revision -eq $revision -and $receipt.path -eq $path -and `
                        $receipt.sha256 -eq $actual -and (Get-Item -LiteralPath $destination).Length -eq $metadata[0].size
                }
                catch { $cached = $false }
            }
            if ($cached) {
                Write-Host "  Cached: $name"
            }
            else {
                Write-Host "  Downloading: $name"
                Receive-CoreFile -Url "https://huggingface.co/datasets/zhangfw123/CORE-Bench/resolve/$revision/$path" -Destination $destination
                if ((Get-Item -LiteralPath $destination).Length -ne $metadata[0].size) { throw "Downloaded size mismatch: $path" }
                $actual = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant()
                Write-JsonFile -Destination $receiptPath -Value @{ revision = $revision; path = $path; sha256 = $actual }
            }
            $hashes[$name] = $actual
        }
        $datasets += @{ name = $repository; data_dir = $localDirectory; revision = $revision; level = 2; sha256 = $hashes }
    }
    $manifestPath = Join-Path $runDirectory "manifest.json"
    Write-JsonFile -Destination $manifestPath -Value @{ version = 1; benchmark = "core"; datasets = $datasets }
    Copy-Item -LiteralPath $listingPath -Destination (Join-Path $runDirectory "directory.json")
    Write-JsonFile -Destination (Join-Path $runDirectory "selection.json") -Value @{
        revision = $revision; source_directory = $remoteDirectory; repositories = @($datasets | ForEach-Object { $_.name })
        selection = "All 12 repositories in the pinned Verified Level-2 export; corpus is not sampled"
        max_queries_per_repository = $MaxQueries; seed = $Seed; repeats = $Repeats; offline = [bool]$Offline
        script_sha256 = (Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant()
        public_benchmark_verified = $false
    }
    Write-Host "[3/3] Evaluating 12 repositories, at most $MaxQueries queries each, $Repeats repetitions..."
    $resultsDirectory = Join-Path $runDirectory "results"
    $logPath = Join-Path $runDirectory "evaluation.log"
    Write-Host "Live progress: $(Join-Path $resultsDirectory 'progress.jsonl')"
    Write-Host "Final JSON stdout log: $logPath"
    # Native stderr carries ordinary progress, not PowerShell errors. Check the exit code explicitly.
    $savedErrorAction = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $PythonCommand -u -m compass benchmark core-batch --manifest $manifestPath --output-dir $resultsDirectory `
            --max-queries $MaxQueries --repeats $Repeats --seed $Seed --progress > $logPath
        $evaluationExit = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $savedErrorAction }
    $reportPath = Join-Path $resultsDirectory "batch.json"
    if (Test-Path -LiteralPath $reportPath) {
        $report = ConvertFrom-Json -InputObject ([IO.File]::ReadAllText($reportPath, $utf8))
        Write-Host ($report.summary | ConvertTo-Json -Depth 10)
    }
    if ($evaluationExit -ne 0) { throw "Evaluation failed or partially failed. Inspect $reportPath and $logPath" }
    Write-Host ""
    Write-Host "Batch result: $reportPath"
    Write-Host "Per-repository CSV: $(Join-Path $resultsDirectory 'datasets.csv')"
    Write-Host "Scope: fixed 12-repository BM25 reference; not full-cascade or official leaderboard scores."
}
catch {
    Write-Host "FAILED: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Artifacts (if created): $runDirectory"
    exit 1
}
finally { Pop-Location }
