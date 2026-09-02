param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$config = Get-Content -LiteralPath (Join-Path $projectRoot 'config.example.json') -Raw | ConvertFrom-Json
$localConfig = Join-Path $projectRoot 'config.local.json'
if (Test-Path -LiteralPath $localConfig) {
    $override = Get-Content -LiteralPath $localConfig -Raw | ConvertFrom-Json
    if ($override.port) { $config.port = $override.port }
}
$url = "http://127.0.0.1:$($config.port)"
try { $health = Invoke-RestMethod "$url/api/health" -TimeoutSec 2 } catch { $health = $null }
if ($health -and $health.app -eq 'H3-slides') {
    Write-Host "H3-slides e' gia' attivo: $url"
    if (-not $NoBrowser) { Start-Process $url }
    exit 0
}
if (Get-NetTCPConnection -LocalPort $config.port -State Listen -ErrorAction SilentlyContinue) {
    throw "La porta $($config.port) e' occupata. Non avvio altre copie."
}
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$entry = Join-Path $projectRoot 'run_h3_slides.py'
$process = Start-Process -FilePath $python -ArgumentList ('"' + $entry + '"') -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $projectRoot 'logs\console.log') -RedirectStandardError (Join-Path $projectRoot 'logs\console-error.log')
for ($attempt = 0; $attempt -lt 40; $attempt++) {
    Start-Sleep -Milliseconds 500
    if ($process.HasExited) { throw "Avvio fallito: controlla logs\console-error.log" }
    try {
        $health = Invoke-RestMethod "$url/api/health" -TimeoutSec 2
        if ($health.app -eq 'H3-slides') { Write-Host "H3-slides avviato: $url"; if (-not $NoBrowser) { Start-Process $url }; exit 0 }
    } catch {}
}
throw "Avvio lento: controlla logs\console-error.log prima di riprovare."
