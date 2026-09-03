param([ValidatePattern('^\d+\.\d+\.\d+(-[A-Za-z0-9.-]+)?$')][string]$Version='0.2.1')
$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'Git serve solo a creare la release, non agli utenti che installano lo ZIP.' }
$status=@(git status --porcelain)
if ($LASTEXITCODE -ne 0 -or $status.Count) { throw 'Prima della release: revisionare e committare tutti i sorgenti. Non impacchetto file non committati.' }
$files=@(git ls-tree -r --name-only HEAD)
foreach ($file in $files) {
    $vendorBundle=$file -in @('vendor/pptxgenjs/dist/pptxgen.cjs.js','vendor/pptxgenjs/dist/pptxgen.es.js')
    if ((-not $vendorBundle -and $file -match '(^|/)(runtime|data|outputs|logs|dist|node_modules|\.venv|__pycache__)/') -or
        $file -match '(^|/)config\.local\.json$' -or
        ($file -match '(^|/)\.env(\..*)?$' -and -not $file.EndsWith('/.env.example') -and $file -ne '.env.example') -or
        $file -match '\.(gguf|safetensors|sqlite3?|pem|key|pfx)$' -or
        ($file.StartsWith('models/') -and $file -ne 'models/.gitkeep')) {
        throw "File riservato nel commit: $file. Release annullata."
    }
}
foreach ($required in @('Avvia-H3-slides.bat','Installa-H3-slides.bat','Ferma-H3-slides.bat',
                        'scripts/setup.ps1','scripts/bootstrap.ps1','scripts/runtime-manifest.json','requirements.lock','package-lock.json',
                        'vendor/pptxgenjs/package.json','vendor/pptxgenjs/LICENSE','vendor/pptxgenjs/provenance.json',
                        'vendor/pptxgenjs/dist/pptxgen.cjs.js','vendor/pptxgenjs/dist/pptxgen.es.js','vendor/pptxgenjs/types/index.d.ts')) {
    if ($files -notcontains $required) { throw "Componente assente dal commit: $required" }
}
$dist=Join-Path $projectRoot 'dist'
New-Item -ItemType Directory -Path $dist -Force | Out-Null
$filename="H3-Slides-windows-x64-$Version.zip"
$archive=Join-Path $dist $filename
if (Test-Path -LiteralPath $archive) { throw "Release gia presente: $archive. Nessun file sovrascritto." }
& git archive --format=zip --prefix=H3-Slides/ "--output=$archive" HEAD
if ($LASTEXITCODE -ne 0) { throw 'git archive fallito' }
$hash=(Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
"$hash  $filename" | Set-Content -LiteralPath ($archive+'.sha256') -Encoding ASCII
Write-Host "ZIP: $archive"
Write-Host "SHA256: $hash"
Write-Host "Commit: $(git rev-parse HEAD)"
