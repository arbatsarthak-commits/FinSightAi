$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
Start-Process powershell -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-File", ".\start_backend.ps1"
Start-Sleep -Seconds 2
& ".\start_frontend.ps1"
