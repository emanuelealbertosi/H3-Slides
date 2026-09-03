param([ValidateSet('start','stop','status')][string]$Action='status',
      [ValidateSet('podman','docker')][string]$Engine='podman')
$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
$compose=Join-Path $projectRoot 'deploy\searxng\compose.yml'
$envFile=Join-Path $projectRoot 'deploy\searxng\.env'
if (-not (Get-Command $Engine -ErrorAction SilentlyContinue)) {
    throw "$Engine non disponibile. Configura un motore con supporto Compose oppure scegli DuckDuckGo nell'app. Nessun componente Windows viene installato automaticamente."
}
if (-not (Test-Path -LiteralPath $envFile)) {
    throw 'Prima copia deploy\searxng\.env.example in .env e imposta SEARXNG_SECRET. Vedi README.'
}
$composeArgs=@('compose','--project-name','h3-slides-search','-f',$compose,'--env-file',$envFile)
if ($Action -eq 'start') { $composeArgs+=@('up','-d') }
elseif ($Action -eq 'stop') { $composeArgs+=@('stop') }
else { $composeArgs+=@('ps') }
& $Engine @composeArgs
if ($LASTEXITCODE -ne 0) { throw "Operazione $Action non riuscita. Verifica il motore container e il supporto Compose." }
