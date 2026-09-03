# A matching port/name alone does not prove ownership: another copy may be running.
function Get-OwnedAppListener([string]$Root, [int]$Port) {
    $entry=[IO.Path]::GetFullPath((Join-Path $Root 'run_h3_slides.py'))
    $pattern='(?i)(?:"'+[regex]::Escape($entry)+'"|(?<!\S)'+[regex]::Escape($entry)+'(?=\s|$))'
    foreach ($connection in @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)) {
        $process=Get-CimInstance Win32_Process -Filter ('ProcessId='+$connection.OwningProcess)
        if (-not $process -or $process.CommandLine -notmatch $pattern) { continue }
        $executable=$process.ExecutablePath
        foreach ($relative in @('.venv','runtime\python')) {
            $prefix=[IO.Path]::GetFullPath((Join-Path $Root $relative))+[IO.Path]::DirectorySeparatorChar
            if ($executable -and $executable.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)) {
                return $process
            }
        }
        # An explicitly supplied system Python may back the Windows venv redirector.
        $parent=Get-CimInstance Win32_Process -Filter ('ProcessId='+$process.ParentProcessId)
        if ($parent -and $parent.ExecutablePath -eq (Join-Path $Root '.venv\Scripts\python.exe') -and
            $parent.CommandLine -match $pattern) { return $process }
    }
    return $null
}
