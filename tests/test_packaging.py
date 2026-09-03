"""Bootstrap safety tests: no downloads, models or real process termination."""
import json
import os
from pathlib import Path
import re
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def ps(script):
    # Do not leak the hosting PowerShell 7 module path into Windows PowerShell 5.
    env = {key: value for key, value in os.environ.items() if key.upper() != "PSMODULEPATH"}
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command",
         "$ErrorActionPreference='Stop'; " + script],
        cwd=ROOT, capture_output=True, text=True, timeout=35, env=env,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def literal(path):
    return "'" + str(path).replace("'", "''") + "'"


def test_manifest_pins_runtime_archives():
    manifest = json.loads((ROOT / "scripts/runtime-manifest.json").read_text())
    assert re.fullmatch(r"3\.12\.\d+", manifest["python"])
    for spec in [manifest["uv"], *[manifest["llama"][k] for k in ("cpu", "cuda", "cudart")]]:
        assert spec["url"].startswith("https://github.com/")
        assert "/releases/download/" in spec["url"]
        assert re.fullmatch("[a-f0-9]{64}", spec["sha256"])
    config = json.loads((ROOT / "config.example.json").read_text())
    assert config["host"] == "127.0.0.1"
    assert config["model_roots"] == ["models"]
    assert config["llama_executable"] == "runtime/llama/llama-server.exe"


@pytest.mark.skipif(os.name != "nt", reason="Windows installer")
def test_all_powershell_scripts_parse():
    ps("""
    Get-ChildItem scripts -Filter *.ps1 | ForEach-Object {
        $tokens=$null; $errors=$null
        [System.Management.Automation.Language.Parser]::ParseFile($_.FullName,[ref]$tokens,[ref]$errors) | Out-Null
        if ($errors.Count) { throw ($errors | Out-String) }
    }
    """)


@pytest.mark.skipif(os.name != "nt", reason="Windows installer")
def test_runtime_moves_cannot_escape_app(tmp_path):
    ps("$projectRoot=" + literal(tmp_path) + """
    . ./scripts/bootstrap.ps1
    Assert-RuntimePath (Join-Path $projectRoot 'runtime/llama/bin')
    foreach ($relative in @('runtime','runtime-other/llama','runtime/../../outside')) {
        $rejected=$false
        try { Assert-RuntimePath (Join-Path $projectRoot $relative) } catch { $rejected=$true }
        if (-not $rejected) { throw "Unsafe path accepted: $relative" }
    }
    """)


@pytest.mark.skipif(os.name != "nt", reason="Windows installer")
def test_bad_archive_hash_never_publishes_download(tmp_path):
    ps("$projectRoot=" + literal(tmp_path) + """
    . ./scripts/bootstrap.ps1
    function Start-Sleep {}
    function Invoke-WebRequest { param($OutFile)
        [IO.File]::WriteAllText($OutFile,'tampered download')
    }
    $spec=@{ url='https://github.com/test/test/releases/download/v1/test.zip'; sha256=('0'*64) }
    $rejected=$false
    try { Get-PinnedArchive $spec } catch { $rejected=$true }
    if (-not $rejected) { throw 'Bad checksum accepted' }
    if (Get-ChildItem -LiteralPath (Join-Path $projectRoot 'runtime/downloads') -Filter '*.zip') {
        throw 'Corrupt archive was published'
    }
    """)


@pytest.mark.skipif(os.name != "nt", reason="Windows installer")
def test_verified_cached_download_is_reused(tmp_path):
    ps("$projectRoot=" + literal(tmp_path) + """
    . ./scripts/bootstrap.ps1
    $cache=Join-Path $projectRoot 'runtime/downloads'
    New-Item -ItemType Directory -Path $cache -Force | Out-Null
    $original=Join-Path $cache 'fixture'
    [IO.File]::WriteAllText($original,'verified test bytes')
    $hash=(Get-FileHash -LiteralPath $original -Algorithm SHA256).Hash.ToLowerInvariant()
    $archive=Join-Path $cache ($hash.Substring(0,12)+'-test.zip')
    Copy-Item -LiteralPath $original -Destination $archive
    function Invoke-WebRequest { throw 'Unexpected network access' }
    $found=Get-PinnedArchive @{url='https://github.com/test/test/releases/download/v1/test.zip';sha256=$hash}
    if ($found -ne $archive) { throw 'Verified cache was not reused' }
    """)


@pytest.mark.skipif(os.name != "nt", reason="Windows installer")
def test_listener_ownership_rejects_other_installation(tmp_path):
    ps("$projectRoot=" + literal(tmp_path) + """
    . ./scripts/process-control.ps1
    function Get-NetTCPConnection { [pscustomobject]@{OwningProcess=999} }
    function Get-CimInstance { param($ClassName,$Filter)
        if ($Filter -eq 'ProcessId=999') { return $script:listener }
        return $null
    }
    $script:listener=[pscustomobject]@{
        ExecutablePath=(Join-Path $projectRoot '.venv/Scripts/python.exe')
        CommandLine=('python "'+(Join-Path $projectRoot 'run_h3_slides.py')+'"')
        ParentProcessId=998; ProcessId=999
    }
    if (-not (Get-OwnedAppListener $projectRoot 8766)) { throw 'Owned process not recognized' }
    if (Get-OwnedAppListener (Join-Path $projectRoot 'another copy') 8766) { throw 'Foreign copy accepted' }
    $script:listener.CommandLine='python -m unrelated_application'
    if (Get-OwnedAppListener $projectRoot 8766) { throw 'Unrelated Python accepted' }
    """)
