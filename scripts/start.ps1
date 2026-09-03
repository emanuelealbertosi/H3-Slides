param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'process-control.ps1')
New-Item -ItemType Directory -Path (Join-Path $projectRoot 'logs') -Force | Out-Null
$startLock=$null
try {
try { $startLock=[IO.File]::Open((Join-Path $projectRoot 'logs\start.lock'), 'OpenOrCreate', 'ReadWrite', 'None') }
catch { throw 'Un avvio e gia in corso in questa cartella. Attendi che termini.' }
$config = Get-Content -LiteralPath (Join-Path $projectRoot 'config.example.json') -Raw | ConvertFrom-Json
$localConfig = Join-Path $projectRoot 'config.local.json'
if (Test-Path -LiteralPath $localConfig) {
    $override = Get-Content -LiteralPath $localConfig -Raw | ConvertFrom-Json
    if ($override.port) { $config.port = $override.port }
}
$url = "http://127.0.0.1:$($config.port)"
try { $health = Invoke-RestMethod "$url/api/health" -TimeoutSec 2 } catch { $health = $null }
if ($health -and $health.app -eq 'H3-slides') {
    if (-not (Get-OwnedAppListener $projectRoot $config.port)) {
        throw 'Questa porta appartiene a un altra copia di H3-Slides. Non la apro o modifico: cambia porta in config.local.json.'
    }
    Write-Host "H3-slides e' gia' attivo: $url"
    if (-not $NoBrowser) { Start-Process $url }
    exit 0
}
if (Get-NetTCPConnection -LocalPort $config.port -State Listen -ErrorAction SilentlyContinue) {
    throw "La porta $($config.port) e' occupata. Non avvio altre copie."
}
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$entry = Join-Path $projectRoot 'run_h3_slides.py'
if (-not (Test-Path -LiteralPath $python) -or
    -not (Test-Path -LiteralPath (Join-Path $projectRoot 'runtime\installed.json'))) {
    Write-Host 'Prima installazione: preparo i componenti nella cartella dell app. Serve Internet.'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'setup.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'Installazione non completata: controlla logs\setup-*.log e rilancia Installa-H3-slides.bat.' }
}
New-Item -ItemType Directory -Path (Join-Path $projectRoot 'logs') -Force | Out-Null
Push-Location -LiteralPath $projectRoot
try {
    & $python -m h3_slides.preflight --core-only
    if ($LASTEXITCODE -ne 0) { throw 'Verifica avvio fallita. Correggi gli errori indicati sopra; nessuna copia avviata.' }
} finally { Pop-Location }
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
} finally { if ($startLock) { $startLock.Dispose() } }
