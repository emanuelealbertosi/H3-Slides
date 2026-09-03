# Bootstrap stays inside the chosen application folder. No registry/PATH/user Python changes.
function Assert-RuntimePath([string]$Target) {
    $prefix=[IO.Path]::GetFullPath((Join-Path $projectRoot 'runtime'))+[IO.Path]::DirectorySeparatorChar
    if (-not [IO.Path]::GetFullPath($Target).StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)) {
        throw 'Percorso runtime fuori dalla cartella applicativa.'
    }
}
function Get-PinnedArchive($Spec) {
    $uri=[Uri]$Spec.url
    if ($uri.Scheme -ne 'https' -or $uri.Host -ne 'github.com' -or $Spec.sha256 -notmatch '^[a-f0-9]{64}$') {
        throw 'Manifest download non valido.'
    }
    $name=[IO.Path]::GetFileName($uri.AbsolutePath)
    if ($name -notmatch '^[a-zA-Z0-9._-]+\.zip$') { throw 'Nome archivio non valido.' }
    $cache=Join-Path $projectRoot 'runtime\downloads'
    New-Item -ItemType Directory -Path $cache -Force | Out-Null
    $archive=Join-Path $cache ($Spec.sha256.Substring(0,12)+'-'+$name)
    if ((Test-Path -LiteralPath $archive) -and
        (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -eq $Spec.sha256) { return $archive }
    $partial=$archive+'.part'
    Write-Host "Download verificato: $name"
    for ($attempt=1;$attempt -le 3;$attempt++) {
        try {
            Invoke-WebRequest $uri.AbsoluteUri -OutFile $partial -UseBasicParsing -TimeoutSec 600
            if ((Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash -ne $Spec.sha256) { throw 'SHA256 non corrispondente.' }
            Assert-RuntimePath $partial
            Assert-RuntimePath $archive
            Move-Item -LiteralPath $partial -Destination $archive -Force
            return $archive
        } catch {
            if ($attempt -eq 3) { throw }
            Write-Host "Download interrotto: riprovo ($attempt/3)..."
            Start-Sleep -Seconds 2
        }
    }
}
function Install-PrivatePython($Manifest) {
    $uvDir=Join-Path $projectRoot 'runtime\uv'
    $uvExe=Join-Path $uvDir 'uv.exe'
    if (-not (Test-Path -LiteralPath $uvExe)) {
        Expand-Archive -LiteralPath (Get-PinnedArchive $Manifest.uv) -DestinationPath $uvDir -Force
    }
    $env:UV_PYTHON_INSTALL_DIR=Join-Path $projectRoot 'runtime\python'
    $env:UV_CACHE_DIR=Join-Path $projectRoot 'runtime\uv-cache'
    $env:UV_PYTHON_INSTALL_REGISTRY='0'
    $env:UV_PYTHON_INSTALL_BIN='0'
    $env:UV_NO_CONFIG='1'
    $env:UV_NO_PROGRESS='1'
    & $uvExe python install $Manifest.python --no-registry --no-bin | Out-Host
    if ($LASTEXITCODE -ne 0) { throw 'Download Python privato fallito. Controlla rete/proxy e riprova.' }
    $found=& $uvExe python find --managed-python --no-python-downloads $Manifest.python
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $found -PathType Leaf)) { throw 'Python privato non trovato.' }
    Assert-RuntimePath $found
    return $found
}
function Install-LlamaRuntime($Manifest,[string]$Backend) {
    if ($Backend -eq 'skip') {
        Write-Host 'Motore locale non richiesto: puoi usare API remote.'
        return
    }
    $llamaDir=Join-Path $projectRoot 'runtime\llama'
    $server=Join-Path $llamaDir 'llama-server.exe'
    if (Test-Path -LiteralPath $server) {
        # Windows PowerShell 5.1 can turn redirected native stderr into a
        # terminating error even when llama-server exits successfully.
        & $server --version
        if ($LASTEXITCODE -eq 0) {
            Write-Host 'Motore llama.cpp esistente conservato.'
            return
        }
        Write-Host 'Il motore esistente non parte: verra conservato in backup.'
    }
    $selected=$Backend
    if ($selected -eq 'auto') {
        $nvidia=@(Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue | Where-Object Name -Match 'NVIDIA')
        $selected=if ($nvidia.Count) { 'cuda' } else { 'cpu' }
    }
    $stage=Join-Path $projectRoot ('runtime\llama-setup-'+[guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $stage -Force | Out-Null
    Write-Host "Installazione llama.cpp $($Manifest.llama.version) ($selected)..."
    Expand-Archive -LiteralPath (Get-PinnedArchive $Manifest.llama.$selected) -DestinationPath $stage
    if ($selected -eq 'cuda') {
        Expand-Archive -LiteralPath (Get-PinnedArchive $Manifest.llama.cudart) -DestinationPath $stage -Force
    }
    $executables=@(Get-ChildItem -LiteralPath $stage -Filter llama-server.exe -Recurse -File)
    if ($executables.Count -ne 1) { throw 'Archivio llama.cpp senza un server univoco.' }
    $candidate=$executables[0]
    # Release archives can have a bin/ prefix. Keep DLLs beside the executable.
    if ($selected -eq 'cuda') {
        Get-ChildItem -LiteralPath $stage -Filter '*.dll' -Recurse -File | ForEach-Object {
            $destination=Join-Path $candidate.DirectoryName $_.Name
            if ($_.FullName -ne $destination -and -not (Test-Path -LiteralPath $destination)) {
                Copy-Item -LiteralPath $_.FullName -Destination $destination
            }
        }
    }
    & $candidate.FullName --version
    if ($LASTEXITCODE -ne 0) {
        if ($selected -eq 'cuda' -and $Backend -eq 'auto') {
            Write-Warning 'CUDA non si avvia con i driver presenti: installo il motore CPU. I driver non vengono modificati.'
            Install-LlamaRuntime $Manifest 'cpu'
            return
        }
        throw 'llama.cpp non si avvia. Controlla driver/Visual C++ Redistributable x64 o usa -LlamaBackend skip per API remote.'
    }
    $backup=Join-Path $projectRoot ('runtime\llama-backup-'+[guid]::NewGuid().ToString('N'))
    foreach ($target in @($candidate.DirectoryName,$llamaDir,$backup)) { Assert-RuntimePath $target }
    if (Test-Path -LiteralPath $llamaDir) { Move-Item -LiteralPath $llamaDir -Destination $backup }
    Move-Item -LiteralPath $candidate.DirectoryName -Destination $llamaDir
    Write-Host "Motore $selected pronto. Nessun GGUF scaricato."
}
