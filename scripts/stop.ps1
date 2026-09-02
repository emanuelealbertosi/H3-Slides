$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$config = Get-Content -LiteralPath (Join-Path $projectRoot 'config.example.json') -Raw | ConvertFrom-Json
if (Test-Path -LiteralPath (Join-Path $projectRoot 'config.local.json')) {
    $override = Get-Content -LiteralPath (Join-Path $projectRoot 'config.local.json') -Raw | ConvertFrom-Json
    if ($override.port) { $config.port = $override.port }
}
$url = "http://127.0.0.1:$($config.port)"
try {
    $health = Invoke-RestMethod "$url/api/health" -TimeoutSec 2
    if ($health.app -ne 'H3-slides') { throw "La porta non appartiene a H3-slides" }
    Invoke-RestMethod "$url/api/shutdown" -Method Post -Headers @{'X-H3-Slides'='1'} -ContentType 'application/json' -Body '{}' | Out-Null
} catch { Write-Host "Arresto HTTP non disponibile. Verifico solo i processi di questa cartella." }
Start-Sleep -Seconds 2
$entry = [IO.Path]::GetFullPath((Join-Path $projectRoot 'run_h3_slides.py'))
$python = [IO.Path]::GetFullPath((Join-Path $projectRoot '.venv\Scripts\python.exe'))
$allProcesses = @(Get-CimInstance Win32_Process)
$targets = [System.Collections.Generic.List[object]]::new()
$allProcesses | Where-Object {
    $_.ExecutablePath -eq $python -and
    ($_.CommandLine -like ('*"' + $entry + '"*') -or $_.CommandLine -like ('* ' + $entry))
} | ForEach-Object { $targets.Add($_) }
for ($index = 0; $index -lt $targets.Count; $index++) {
    $parentId = $targets[$index].ProcessId
    $allProcesses | Where-Object ParentProcessId -eq $parentId | ForEach-Object {
        if (-not ($targets | Where-Object ProcessId -eq $_.ProcessId)) { $targets.Add($_) }
    }
}
for ($index = $targets.Count - 1; $index -ge 0; $index--) {
    $target = $targets[$index]
    $live = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $target.ProcessId)
    if ($live -and $live.CreationDate -eq $target.CreationDate) {
        Stop-Process -Id $target.ProcessId -Force -ErrorAction SilentlyContinue
    }
}
Write-Host "H3-slides fermato. Gli altri programmi non sono stati toccati."
