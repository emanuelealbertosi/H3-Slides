param([string]$NodeVersion='24.19.0', [string]$PythonExecutable='',
      [ValidateSet('auto','cpu','cuda','skip')][string]$LlamaBackend='auto', [switch]$VerifyOnly)
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
$projectRoot=Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
if ($NodeVersion -notmatch '^\d+\.\d+\.\d+$') { throw 'Versione Node non valida' }
if ($VerifyOnly) {
    if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) { throw 'Ambiente Python mancante: esegui l installazione senza -VerifyOnly.' }
    & '.\.venv\Scripts\python.exe' -m h3_slides.preflight
    exit $LASTEXITCODE
}
New-Item -ItemType Directory -Path 'logs','data','outputs','models' -Force | Out-Null
$setupLock=$null
$transcriptStarted=$false
try {
try { $setupLock=[IO.File]::Open((Join-Path $projectRoot 'logs\setup.lock'), 'OpenOrCreate', 'ReadWrite', 'None') }
catch { throw 'Un altra installazione e gia in corso in questa cartella. Attendi che termini.' }
Start-Transcript -Path (Join-Path $projectRoot ('logs\setup-'+(Get-Date -Format 'yyyyMMdd-HHmmss')+'.log')) | Out-Null
$transcriptStarted=$true
if (-not [Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -eq 'ARM64') {
    throw 'Questo pacchetto richiede Windows x64 (Intel/AMD). ARM e altri sistemi non sono supportati.'
}
[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
. (Join-Path $PSScriptRoot 'bootstrap.ps1')
$manifest=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'runtime-manifest.json') -Raw | ConvertFrom-Json
$appPython=[IO.Path]::GetFullPath((Join-Path $projectRoot '.venv\Scripts\python.exe'))
$appEntry=[IO.Path]::GetFullPath((Join-Path $projectRoot 'run_h3_slides.py'))
$running=@(Get-CimInstance Win32_Process | Where-Object {
    $_.ExecutablePath -eq $appPython -and $_.CommandLine -match [regex]::Escape($appEntry)
})
if ($running.Count) {
    throw 'Chiudi prima H3-Slides con Ferma-H3-slides.bat. Non modifico dipendenze mentre l app e attiva.'
}
$completionMarker=Join-Path $projectRoot 'runtime\installed.json'
if (Test-Path -LiteralPath $completionMarker) {
    $previousMarker=Join-Path $projectRoot ('runtime\installed-previous-'+[guid]::NewGuid().ToString('N')+'.json')
    Assert-RuntimePath $completionMarker
    Assert-RuntimePath $previousMarker
    Move-Item -LiteralPath $completionMarker -Destination $previousMarker
}
Write-Host '[1/6] Ambiente Python 3.12 privato e dipendenze...'
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    if ($PythonExecutable) {
        if (-not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf)) { throw 'PythonExecutable non trovato.' }
        $pythonCommand=$PythonExecutable
        $pythonArgs=@()
    } else {
        $pythonCommand=Install-PrivatePython $manifest
        $pythonArgs=@()
    }
    & $pythonCommand @pythonArgs -c "import sys,struct; sys.exit(0 if sys.version_info[:2]==(3,12) and struct.calcsize('P')==8 else 1)"
    if ($LASTEXITCODE -ne 0) { throw 'Serve Python 3.12 a 64 bit. Nessun ambiente creato.' }
    & $pythonCommand @pythonArgs -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Creazione ambiente Python non riuscita' }
}
& '.\.venv\Scripts\python.exe' -c "import sys,struct; sys.exit(0 if sys.version_info[:2]==(3,12) and struct.calcsize('P')==8 else 1)"
if ($LASTEXITCODE -ne 0) { throw 'Ambiente .venv incompatibile o danneggiato: spostalo in una cartella di backup e rilancia l installazione.' }
# A pip-less existing venv is supported. Do not redirect native stderr here:
# Windows PowerShell 5.1 would throw before ensurepip gets a chance to repair it.
& '.\.venv\Scripts\python.exe' -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('pip') else 1)"
if ($LASTEXITCODE -ne 0) {
    & '.\.venv\Scripts\python.exe' -m ensurepip --upgrade
    if ($LASTEXITCODE -ne 0) { throw 'pip non disponibile in questo ambiente Python' }
}
& '.\.venv\Scripts\python.exe' -m pip --disable-pip-version-check install -r requirements.lock
if ($LASTEXITCODE -ne 0) { throw 'Installazione dipendenze Python non riuscita' }
& '.\.venv\Scripts\python.exe' -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Dipendenze Python in conflitto. Controlla il log sopra.' }
$nodeDir=Join-Path $projectRoot 'runtime\node'
Write-Host '[2/6] Verifica Node e npm dedicati...'
$nodeExe=Join-Path $nodeDir 'node.exe'
$nodeReady=(Test-Path -LiteralPath $nodeExe) -and
    (Test-Path -LiteralPath (Join-Path $nodeDir 'npm.cmd')) -and
    (Test-Path -LiteralPath (Join-Path $nodeDir 'node_modules\npm\bin\npm-cli.js'))
if ($nodeReady) {
    $installedVersion=& $nodeExe --version
    $nodeReady=($LASTEXITCODE -eq 0 -and $installedVersion -eq "v$NodeVersion")
}
if (-not $nodeReady) {
    $staging=Join-Path $projectRoot ('runtime\setup-'+[guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $staging -Force | Out-Null
    $filename="node-v$NodeVersion-win-x64.zip"
    $base="https://nodejs.org/dist/v$NodeVersion"
    $archive=Join-Path $staging $filename
    [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest "$base/$filename" -OutFile $archive -UseBasicParsing -TimeoutSec 300
    $checksums=(Invoke-WebRequest "$base/SHASUMS256.txt" -UseBasicParsing -TimeoutSec 60).Content
    if ($checksums -is [byte[]]) { $checksums=[Text.Encoding]::UTF8.GetString($checksums) }
    $entry=($checksums -split "\n" | Where-Object { $_.Trim().EndsWith("  $filename") })
    if (@($entry).Count -ne 1) { throw 'Checksum Node non trovato' }
    $expected=($entry.Trim() -split '\s+')[0]
    if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne $expected) { throw 'Checksum Node non valido' }
    Expand-Archive -LiteralPath $archive -DestinationPath $staging
    $unpacked=Join-Path $staging "node-v$NodeVersion-win-x64"
    # Resolve every directory before a move, constrained to this project's runtime.
    $runtimeRoot=[IO.Path]::GetFullPath((Join-Path $projectRoot 'runtime'))+[IO.Path]::DirectorySeparatorChar
    $backup=Join-Path $projectRoot ('runtime\node-backup-'+[guid]::NewGuid().ToString('N'))
    foreach ($target in @($nodeDir,$unpacked,$backup)) {
        if (-not [IO.Path]::GetFullPath($target).StartsWith($runtimeRoot,[StringComparison]::OrdinalIgnoreCase)) {
            throw 'Percorso runtime non valido: nessun file spostato.'
        }
    }
    $checkVersion=& (Join-Path $unpacked 'node.exe') --version
    if ($LASTEXITCODE -ne 0 -or $checkVersion -ne "v$NodeVersion") { throw 'Runtime Node scaricato non funzionante.' }
    if (Test-Path -LiteralPath $nodeDir) {
        Move-Item -LiteralPath $nodeDir -Destination $backup
        Write-Host "Vecchio runtime conservato in: $backup"
    }
    Move-Item -LiteralPath $unpacked -Destination $nodeDir
}
$env:PATH="$nodeDir;$env:PATH"
$npm=Join-Path $nodeDir 'npm.cmd'
if (-not (Test-Path -LiteralPath $npm)) { throw 'Usa una distribuzione Node completa con npm in runtime\node.' }
$env:PLAYWRIGHT_BROWSERS_PATH=Join-Path $projectRoot 'runtime\browsers'
Write-Host '[3/6] Installazione Slidev e componenti web...'
& $npm ci --foreground-scripts
if ($LASTEXITCODE -ne 0) { throw 'Installazione dipendenze Node non riuscita' }
& $nodeExe 'scripts\dependency-check.mjs'
if ($LASTEXITCODE -ne 0) { throw 'Controllo dipendenze corrette fallito: installazione non completata.' }
Write-Host '[4/6] Installazione browser per anteprima ed export...'
& (Join-Path $nodeDir 'node.exe') 'node_modules\playwright-chromium\cli.js' install chromium
if ($LASTEXITCODE -ne 0) { throw 'Installazione Chromium non riuscita' }
Write-Host '[5/6] Motore LLM locale...'
Install-LlamaRuntime $manifest $LlamaBackend
Write-Host '[6/6] Verifica effettiva dei componenti installati...'
& '.\.venv\Scripts\python.exe' -m h3_slides.preflight
if ($LASTEXITCODE -ne 0) { throw 'Installazione incompleta: correggi gli errori indicati e rilancia questo BAT.' }
Write-Host 'Componenti verificati. Avvia-H3-slides.bat: se manca un modello, l app chiede di sceglierlo dal disco.'
Write-Host 'I modelli e SearXNG non sono scaricati o avviati automaticamente.'
@{ installed_at=(Get-Date).ToString('o'); platform='windows-x64'; llama_backend=$LlamaBackend } |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $projectRoot 'runtime\installed.json') -Encoding UTF8
} finally {
    if ($transcriptStarted) { Stop-Transcript | Out-Null }
    if ($setupLock) { $setupLock.Dispose() }
}
