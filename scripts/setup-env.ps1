<# Run in the terminal that will run Keel: & .\scripts\setup-env.ps1
   Credentials remain in this PowerShell process and its child processes only. #>
[CmdletBinding()]
param(
    [string]$PythonPath,
    [string]$ModelConfig = '.keel/model-openai.json',
    [switch]$WithGitHub,
    [switch]$CheckOnly,
    [switch]$CreateVenv,
    [switch]$InstallDependencies,
    [switch]$StartDocker
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path $PSScriptRoot -Parent
$configPath = if ([IO.Path]::IsPathRooted($ModelConfig)) { $ModelConfig } else { Join-Path $repoRoot $ModelConfig }

function Read-ProcessSecret([string]$Name) {
    if ([Environment]::GetEnvironmentVariable($Name, 'Process')) {
        Write-Host "$Name is already available (value hidden)."
        return
    }
    if ($CheckOnly) { Write-Warning "$Name is missing."; return }
    $secret = Read-Host "Enter $Name (hidden; Enter skips)" -AsSecureString
    if ($secret.Length -eq 0) { Write-Warning "$Name was not configured."; return }
    $credential = New-Object System.Net.NetworkCredential('', $secret)
    [Environment]::SetEnvironmentVariable($Name, $credential.Password, 'Process')
    $credential = $null
    $secret.Dispose()
    Write-Host "$Name configured for this terminal only."
}

if (-not $PythonPath) {
    $candidates = @()
    if ($env:VIRTUAL_ENV) { $candidates += Join-Path $env:VIRTUAL_ENV 'Scripts/python.exe' }
    $candidates += Join-Path $repoRoot '.venv/Scripts/python.exe'
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) { $candidates += $pythonCommand.Source }
    $PythonPath = $candidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
}
if (-not $PythonPath) { throw 'Python not found. Install Python >=3.11, or pass -PythonPath.' }
$PythonPath = (Resolve-Path -LiteralPath $PythonPath).Path
$version = & $PythonPath -c 'import sys; print(sys.version.split()[0]); sys.exit(0 if sys.version_info >= (3,11) else 1)'
if ($LASTEXITCODE -ne 0) { throw 'Keel requires Python >=3.11.' }
Write-Host "Python $version : $PythonPath"

if ($CreateVenv -and -not $CheckOnly) {
    $target = Join-Path $repoRoot '.venv'
    if (Test-Path -LiteralPath $target) { throw '.venv already exists; select its interpreter instead of recreating it.' }
    & $PythonPath -m venv $target
    if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed.' }
    $PythonPath = Join-Path $target 'Scripts/python.exe'
}
if ($InstallDependencies -and -not $CheckOnly) {
    & $PythonPath -m pip install -e "${repoRoot}[mcp,langgraph,compass]"
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
}
if (-not $CheckOnly) {
    $prefix = & $PythonPath -c 'import sys; print(sys.prefix if sys.prefix != sys.base_prefix else str())'
    if ($prefix) { $env:VIRTUAL_ENV = $prefix }
    $pythonBin = Split-Path $PythonPath -Parent
    $env:PATH = $pythonBin + [IO.Path]::PathSeparator + $env:PATH
}
& $PythonPath -c "import importlib.util,json; print('Optional packages: ' + json.dumps({m:importlib.util.find_spec(m) is not None for m in ['langgraph','mcp','pyarrow']}))"
if ($LASTEXITCODE -ne 0) { throw 'Python dependency check failed.' }

if (-not (Test-Path -LiteralPath $configPath)) {
    if ($CheckOnly) { Write-Warning "Model config missing: $configPath" }
    else {
        $modelName = Read-Host 'Model name required by your endpoint'
        $endpoint = Read-Host 'API base URL, including /v1 (Enter: https://api.openai.com/v1)'
        if (-not $modelName.Trim()) { throw 'Model name must not be empty.' }
        if (-not $endpoint) { $endpoint = 'https://api.openai.com/v1' }
        $config = [ordered]@{provider='openai-compatible'; name=$modelName; base_url=$endpoint;
            api_key_env='KEEL_MODEL_API_KEY'; response_mode='json_object'; token_limit_field='max_completion_tokens'}
        [IO.Directory]::CreateDirectory((Split-Path $configPath -Parent)) | Out-Null
        [IO.File]::WriteAllText($configPath, ($config | ConvertTo-Json), (New-Object Text.UTF8Encoding($false)))
    }
}
if (Test-Path -LiteralPath $configPath) {
    $config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
    if ($config.provider -eq 'openai-compatible') {
        $keyName = if ($config.api_key_env) { $config.api_key_env } else { 'KEEL_MODEL_API_KEY' }
        if ($keyName -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') { throw 'Invalid api_key_env in model config.' }
        Read-ProcessSecret $keyName
    }
    Write-Host "Model config: $configPath (credentials not stored here)."
}
if ($WithGitHub) { Read-ProcessSecret 'GITHUB_TOKEN' }

$dockerCommand = Get-Command docker -ErrorAction SilentlyContinue
if (-not $dockerCommand -and $env:ProgramFiles) {
    $dockerBin = Join-Path $env:ProgramFiles 'Docker/Docker/resources/bin'
    if (Test-Path (Join-Path $dockerBin 'docker.exe')) {
        if (-not $CheckOnly) { $env:PATH = $dockerBin + ';' + $env:PATH }
        $dockerCommand = Get-Item (Join-Path $dockerBin 'docker.exe')
    }
}
if ($StartDocker -and -not $CheckOnly) {
    $desktop = if ($env:ProgramFiles) { Join-Path $env:ProgramFiles 'Docker/Docker/Docker Desktop.exe' }
    if ($dockerCommand) {
        $binPath = if ($dockerCommand.Source) { $dockerCommand.Source } else { $dockerCommand.FullName }
        $customDesktop = Join-Path (Split-Path (Split-Path (Split-Path $binPath -Parent) -Parent) -Parent) 'Docker Desktop.exe'
        if (Test-Path $customDesktop) { $desktop = $customDesktop }
    }
    if ($desktop -and (Test-Path $desktop)) { Start-Process -FilePath $desktop -WindowStyle Hidden; Write-Host 'Docker Desktop launch requested; engine startup may take a moment.' }
    else { Write-Warning 'Docker Desktop location unknown; start it manually.' }
}
if ($dockerCommand) {
    $dockerExe = if ($dockerCommand.Source) { $dockerCommand.Source } else { $dockerCommand.FullName }
    # A bounded child process prevents setup hanging on an unresponsive engine.
    $job = Start-Job -ArgumentList $dockerExe -ScriptBlock { param($exe) & $exe info --format '{{.ServerVersion}}' 2>$null }
    $done = Wait-Job $job -Timeout 15
    if ($done) { $server = Receive-Job $job -ErrorAction SilentlyContinue }
    if ($server) { Write-Host "Docker engine: $server" } else { Write-Warning 'Docker engine unavailable or not ready; start Docker Desktop and rerun -CheckOnly.' }
    Stop-Job $job -ErrorAction SilentlyContinue
    Remove-Job $job -Force
} else { Write-Warning 'Docker CLI not found. Docker is required for container acceptance and SWE-bench.' }

$harness = Join-Path $repoRoot '.keel/harness-v3/Scripts/python.exe'
if (Test-Path $harness) {
    & $harness -c "import importlib.metadata; print('SWE-bench harness: ' + importlib.metadata.version('swebench'))"
    if ($LASTEXITCODE -ne 0) { Write-Warning 'Harness interpreter exists but swebench package is unavailable.' }
} else { Write-Warning 'Optional SWE-bench harness environment not found; see requirements/swebench-eval.txt.' }
Write-Host 'Checks finished. Missing credentials/engine must be resolved before the corresponding task can run.'
Write-Host 'Run Keel in this same terminal. Closing it removes process-only credentials.'
