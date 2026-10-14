[CmdletBinding()]
param(
    [ValidateRange(1, 1000000)]
    [int]$MaxQueries = 20,
    [ValidateRange(1, 3600)]
    [int]$DownloadTimeoutSeconds = 300,
    [string]$PythonCommand = "python"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$revision = "23da5d97a8a4495d4bd6d5616aa86d5a12a60699"
$remoteDirectory = "data/LEVEL-2/SWE-bench_Verified"
$projectRoot = Split-Path -Parent $PSScriptRoot
$runName = "$(Get-Date -Format 'yyyyMMdd-HHmmss')-$([guid]::NewGuid().ToString('N').Substring(0, 8))"
$runDirectory = Join-Path $projectRoot ".keel/core-public/$runName"
$utf8 = New-Object System.Text.UTF8Encoding($false)

function Receive-CoreFile {
    param([string]$Url, [string]$Destination)
    $partial = "$Destination.partial"
    & curl.exe --fail --location --show-error --connect-timeout 10 `
        --max-time $DownloadTimeoutSeconds --retry 2 --retry-delay 2 `
        --output $partial $Url
    if ($LASTEXITCODE -ne 0) {
        throw "Download failed. URL: $Url. Partial file retained: $partial"
    }
    if (-not (Test-Path -LiteralPath $partial) -or (Get-Item -LiteralPath $partial).Length -eq 0) {
        throw "Download returned an empty file: $Url"
    }
    Move-Item -LiteralPath $partial -Destination $Destination -Force
}

Push-Location $projectRoot
try {
    Get-Command curl.exe -ErrorAction Stop | Out-Null
    Get-Command $PythonCommand -ErrorAction Stop | Out-Null
    & $PythonCommand -c "import sys, compass; print('Python:', sys.executable); print('Compass:', compass.__file__)"
    if ($LASTEXITCODE -ne 0) { throw "Cannot import Compass with the selected Python interpreter" }

    New-Item -ItemType Directory -Path $runDirectory -Force | Out-Null
    Write-Host "Artifacts: $runDirectory"
    Write-Host "[1/3] Listing the pinned Verified Level-2 export..."
    $listingPath = Join-Path $runDirectory "directory.json"
    $treeUrl = "https://huggingface.co/api/datasets/zhangfw123/CORE-Bench/tree/${revision}/${remoteDirectory}?recursive=true&limit=1000"
    Receive-CoreFile -Url $treeUrl -Destination $listingPath
    $files = ConvertFrom-Json -InputObject ([IO.File]::ReadAllText($listingPath, $utf8))
    if ($null -eq $files -or $files -isnot [array]) { throw "Expected a nonempty API directory array" }
    # This subset should fit one page. Fail instead of silently choosing from a truncated listing.
    if ($files.Count -ge 1000) { throw "Directory listing may be paginated; refusing an incomplete selection" }
    $candidates = @($files | Where-Object { $_.type -eq "file" -and $_.path.EndsWith("/corpus.jsonl") } | Sort-Object size, path)
    if ($candidates.Count -eq 0) { throw "No corpus.jsonl found in the pinned directory" }
    $selected = $null
    foreach ($candidate in $candidates) {
        $parent = $candidate.path -replace '/corpus\.jsonl$', ''
        $names = @($files | Where-Object { $_.type -eq "file" } | ForEach-Object { $_.path })
        if ($names -contains "$parent/queries.jsonl" -and $names -contains "$parent/qrels.jsonl") {
            $selected = $candidate
            break
        }
    }
    if ($null -eq $selected) { throw "No complete corpus/queries/qrels export found" }
    $repositoryPath = $selected.path -replace '/corpus\.jsonl$', ''
    if (-not $repositoryPath.StartsWith("$remoteDirectory/") -or $repositoryPath.Contains("..")) {
        throw "Unexpected repository path in API response"
    }
    $dataDirectory = Join-Path $runDirectory "data"
    New-Item -ItemType Directory -Path $dataDirectory | Out-Null
    Write-Host "Selected: $repositoryPath"
    Write-Host "Corpus size: $([math]::Round($selected.size / 1MB, 2)) MB"
    Write-Host "[2/3] Downloading three files..."
    $hashes = @{}
    foreach ($name in @("corpus.jsonl", "queries.jsonl", "qrels.jsonl")) {
        Write-Host "Downloading $name"
        $remotePath = "$repositoryPath/$name"
        $destination = Join-Path $dataDirectory $name
        Receive-CoreFile -Url "https://huggingface.co/datasets/zhangfw123/CORE-Bench/resolve/$revision/$remotePath" -Destination $destination
        $metadata = @($files | Where-Object { $_.path -eq $remotePath })
        if ($metadata.Count -ne 1 -or (Get-Item -LiteralPath $destination).Length -ne $metadata[0].size) {
            throw "Downloaded size differs from the pinned API listing: $name"
        }
        $hashes[$name] = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    $selection = @{
        source = "https://huggingface.co/datasets/zhangfw123/CORE-Bench"
        revision = $revision
        repository = $repositoryPath
        selection = "Smallest complete corpus in the pinned Verified Level-2 listing; not a representative sample"
        max_queries = $MaxQueries
        sha256 = $hashes
        public_benchmark_verified = $false
    }
    [IO.File]::WriteAllText((Join-Path $runDirectory "selection.json"), ($selection | ConvertTo-Json -Depth 10), $utf8)
    $outputPath = Join-Path $runDirectory "evaluation.json"
    Write-Host "[3/3] Running the Compass BM25 document reference..."
    & $PythonCommand -m compass benchmark core --data-dir $dataDirectory `
        --revision $revision --level 2 --max-queries $MaxQueries --output $outputPath
    if ($LASTEXITCODE -ne 0) { throw "Evaluation failed; downloaded files retained at $dataDirectory" }
    Write-Host ""
    Write-Host "Result: $outputPath"
    Write-Host "Scope: one selected public-data repository, at most $MaxQueries queries; BM25 reference only."
    Write-Host "This is not a full-cascade, official-evaluator, or leaderboard result."
}
catch {
    Write-Host "FAILED: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Artifacts (if created): $runDirectory"
    exit 1
}
finally {
    Pop-Location
}
