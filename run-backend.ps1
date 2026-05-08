param(
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 8000,
    [switch]$NoReload,
    [switch]$ForceInstall,
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = Join-Path $RepoRoot "backend"
$VenvDir = Join-Path $BackendDir ".venv"
$PythonExe = Join-Path $VenvDir "Scripts\python.exe"
$RequirementsFile = Join-Path $BackendDir "requirements.txt"
$InstallMarker = Join-Path $VenvDir ".requirements.sha256"

function Invoke-CheckedCommand {
    param(
        [string]$FilePath,
        [string[]]$Arguments
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE`: $FilePath $($Arguments -join ' ')"
    }
}

function New-BackendVenv {
    Write-Host "Creating backend virtual environment..."

    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        Invoke-CheckedCommand $pyLauncher.Source @("-3", "-m", "venv", $VenvDir)
        return
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        Invoke-CheckedCommand $python.Source @("-m", "venv", $VenvDir)
        return
    }

    throw "Python was not found. Install Python 3, then run this script again."
}

function Test-BackendImports {
    & $PythonExe -c "import fastapi, uvicorn" *> $null
    return $LASTEXITCODE -eq 0
}

if (!(Test-Path $BackendDir)) {
    throw "Backend directory was not found at $BackendDir"
}

if (!(Test-Path $PythonExe)) {
    New-BackendVenv
}

if (!(Test-Path $PythonExe)) {
    throw "Virtual environment Python was not found at $PythonExe"
}

if (!$SkipInstall) {
    $requirementsHash = (Get-FileHash $RequirementsFile -Algorithm SHA256).Hash
    $installedHash = if (Test-Path $InstallMarker) { Get-Content $InstallMarker -Raw } else { "" }
    $importsReady = Test-BackendImports

    if ($ForceInstall -or !$importsReady -or $requirementsHash -ne $installedHash.Trim()) {
        Write-Host "Installing backend requirements..."
        Invoke-CheckedCommand $PythonExe @("-m", "pip", "install", "--upgrade", "pip")
        Invoke-CheckedCommand $PythonExe @("-m", "pip", "install", "-r", $RequirementsFile)
        Set-Content -Path $InstallMarker -Value $requirementsHash
    }
}

$uvicornArgs = @("app.main:app", "--host", $BindHost, "--port", "$Port")
if (!$NoReload) {
    $uvicornArgs += "--reload"
}

Write-Host "Starting backend at http://${BindHost}:${Port}"
Set-Location $BackendDir
& $PythonExe -m uvicorn @uvicornArgs
exit $LASTEXITCODE
