"""Build a single CMD entry point and an integrity-pinned release payload."""
import base64
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

from core import VERSION

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "dist" / "installer" / VERSION


def wrap_cmd(script, title):
    boot = "$ErrorActionPreference='Stop';try{$s=[IO.File]::ReadAllText($env:CLOUDRAGON_SETUP_SELF);$m='::CLOUDRAGON_SCRIPT';$i=$s.LastIndexOf($m,[StringComparison]::Ordinal);$b=[Convert]::FromBase64String($s.Substring($i+$m.Length));&([scriptblock]::Create([Text.Encoding]::UTF8.GetString($b)))}catch{Write-Host ('INSTALL FAILED: '+$_.Exception.Message);exit 1}"
    encoded = base64.b64encode(script.encode()).decode()
    lines = ["@echo off", "setlocal EnableExtensions DisableDelayedExpansion", 'set "CLOUDRAGON_SETUP_SELF=%~f0"',
             "echo " + title, '"%SystemRoot%\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" -NoLogo -NoProfile -Command "' + boot + '"',
             'set "SETUP_RESULT=%ERRORLEVEL%"', 'if not defined CLOUDRAGON_SETUP_NO_PAUSE pause',
             "exit /b %SETUP_RESULT%", "::CLOUDRAGON_SCRIPT"]
    return ("\r\n".join(lines) + "\r\n" + "\r\n".join(encoded[i:i+76] for i in range(0, len(encoded), 76)) + "\r\n").encode("ascii")


def main():
    support = OUT / "_support"
    optional = OUT / "Optional"
    support.mkdir(parents=True, exist_ok=True)
    optional.mkdir(exist_ok=True)
    payload = support / f"moba-quick-connect-v{VERSION}-payload.zip"
    exe = ROOT / "dist" / VERSION / "MobaQuickConnect.exe"
    licenses = ROOT / "release-resources" / "THIRD-PARTY-LICENSES.zip"
    entries = {"app/MobaQuickConnect.exe": exe.read_bytes(), "app/AutoStart.ps1": (ROOT / "windows/AutoStart.ps1").read_bytes(),
        "app/version.txt": VERSION.encode(), "app/README.md": (ROOT / "README.md").read_bytes(),
        "app/THIRD_PARTY.txt": (ROOT / "THIRD_PARTY.txt").read_bytes(),
        "app/THIRD-PARTY-LICENSES.zip": licenses.read_bytes(),
        "app/SOURCE.txt": b"https://github.com/jja6312/moba-quick-connect\n"}
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in sorted(entries.items()):
            info = zipfile.ZipInfo(name, (2026, 11, 22, 0, 0, 0)); info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, data)
    digest = hashlib.sha256(payload.read_bytes()).hexdigest()
    url = f"https://github.com/jja6312/moba-quick-connect/releases/download/v{VERSION}/{payload.name}"
    core = (ROOT / "windows/Install.Core.ps1").read_text(encoding="utf-8-sig")
    script = core + "\n" + f"""
if($env:CLOUDRAGON_SETUP_PAYLOAD_FILE){{$bytes=[IO.File]::ReadAllBytes($env:CLOUDRAGON_SETUP_PAYLOAD_FILE)}}else{{
 [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
 $client=New-Object Net.WebClient
 try{{$bytes=$client.DownloadData('{url}')}}finally{{$client.Dispose()}}
}}
$args=@{{Payload=$bytes;ExpectedHash='{digest}'}}
if($env:CLOUDRAGON_SETUP_LOCAL_DATA){{$args.LocalData=$env:CLOUDRAGON_SETUP_LOCAL_DATA}}
if($env:CLOUDRAGON_SETUP_MENU){{$args.MenuDirectory=$env:CLOUDRAGON_SETUP_MENU}}
if($env:CLOUDRAGON_SETUP_STARTUP){{$args.StartupDirectory=$env:CLOUDRAGON_SETUP_STARTUP}}
if($env:CLOUDRAGON_SETUP_NO_LAUNCH){{$args.NoLaunch=$true}}
Install-MobaQuickConnect @args | Format-List
"""
    (OUT / "Install.cmd").write_bytes(wrap_cmd(script, f"Moba Quick Connect {VERSION} Setup"))
    for action in ("Enable", "Disable"):
        script = f"""$ErrorActionPreference='Stop'
$root=Join-Path $env:LOCALAPPDATA 'Cloudragon\\MobaQuickConnect'
$receipt=Get-Content -LiteralPath (Join-Path $root 'installation.json') -Raw | ConvertFrom-Json
if($receipt.owner -cne 'moba-quick-connect' -or $receipt.version -notmatch '^\\d+\\.\\d+\\.\\d+$'){{throw 'Install Moba Quick Connect first.'}}
& (Join-Path $root ('versions\\'+$receipt.version+'\\AutoStart.ps1')) -Action {action}
"""
        (optional / f"{action}-Windows-Startup.cmd").write_bytes(wrap_cmd(script, f"Moba Quick Connect: {action} Windows startup"))
    (optional / "README.txt").write_text("Enable-Windows-Startup.cmd: Windows 로그인 시 트레이에서 자동 실행\nDisable-Windows-Startup.cmd: 자동 실행 해제\n설치만 하면 자동시작은 켜지지 않습니다.\n", encoding="utf-8-sig")
    shutil.copy2(ROOT / "README.md", support / "README.md")
    report = {"version": VERSION, "payloadSha256": digest, "exeSha256": hashlib.sha256(exe.read_bytes()).hexdigest(),
              "autostartDefault": False, "explorerLaunchRequested": False, "publicSource": "https://github.com/jja6312/moba-quick-connect"}
    (support / "manifest.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
