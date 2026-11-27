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

$startupScript = @'
import asyncio
import os
import uvicorn

class FinSightServer(uvicorn.Server):
    async def startup(self, sockets=None):
        await super().startup(sockets)
        if self.started:
            print("Backend started successfully.", flush=True)
            print("Backend URL: http://127.0.0.1:8000", flush=True)
            print(
                "Copy the pairing token below and paste it into the Pairing Token field "
                "in the FinSightAI Connect Backend window.",
                flush=True,
            )
            print("Pairing token:", flush=True)
            print(os.environ["LOCAL_API_TOKEN"], flush=True)

config = uvicorn.Config("backend.main:app", host="127.0.0.1", port=8000)
asyncio.run(FinSightServer(config).serve())
'@

$startupScriptEncoded = [Convert]::ToBase64String(
    [System.Text.Encoding]::UTF8.GetBytes($startupScript)
)
& ".\.venv\Scripts\python.exe" -c "import base64, sys; exec(base64.b64decode(sys.argv[1]))" $startupScriptEncoded
