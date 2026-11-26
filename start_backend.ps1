$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not $env:LOCAL_API_TOKEN) {
    $tokenPath = Join-Path $PSScriptRoot ".local-api-token"
    if (Test-Path $tokenPath) {
        $env:LOCAL_API_TOKEN = (Get-Content $tokenPath -Raw).Trim()
    }
    else {
        $bytes = New-Object byte[] 32
        $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
        $rng.GetBytes($bytes)
        $env:LOCAL_API_TOKEN = [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
        [System.IO.File]::WriteAllText($tokenPath, $env:LOCAL_API_TOKEN)
    }
}

Write-Host "Local pairing token (enter this in the app's Connect backend prompt):" -ForegroundColor Yellow
Write-Host $env:LOCAL_API_TOKEN -ForegroundColor Yellow
& ".\.venv\Scripts\python.exe" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
