$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Project virtual environment not found at $python"
}

$pythonWorks = $true
try {
    & $python --version *> $null
    $pythonWorks = $LASTEXITCODE -eq 0
}
catch {
    $pythonWorks = $false
}
if (-not $pythonWorks) {
    throw "Project virtual environment is not runnable. Recreate .venv using the README setup steps."
}

Push-Location $projectRoot
$previousAdminFlag = $env:TABULA_LOCAL_PROFILE_ADMIN
try {
    $env:TABULA_LOCAL_PROFILE_ADMIN = "1"
    & $python -m streamlit run app.py --server.address 127.0.0.1
}
finally {
    if ($null -eq $previousAdminFlag) {
        Remove-Item Env:TABULA_LOCAL_PROFILE_ADMIN -ErrorAction SilentlyContinue
    }
    else {
        $env:TABULA_LOCAL_PROFILE_ADMIN = $previousAdminFlag
    }
    Pop-Location
}
