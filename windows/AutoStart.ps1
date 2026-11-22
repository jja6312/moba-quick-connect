[CmdletBinding()]
param([ValidateSet('Enable','Disable')][string]$Action, [string]$LocalData=$env:LOCALAPPDATA,
      [string]$StartupDirectory=[Environment]::GetFolderPath('Startup'))
$ErrorActionPreference='Stop'
$root=Join-Path ([IO.Path]::GetFullPath($LocalData)) 'Cloudragon\MobaQuickConnect'
$link=Join-Path $StartupDirectory 'Moba Quick Connect.lnk'
. (Join-Path $PSScriptRoot 'Shortcuts.ps1')
if(Test-Path -LiteralPath $link){
    $existing=[Cloudragon.Moba.Shortcuts]::Read($link)
    if(-not $existing[0].StartsWith($root+'\',[StringComparison]::OrdinalIgnoreCase) -or $existing[1] -cne '--hidden'){
        throw 'An unrelated startup shortcut was preserved.'
    }
}
if($Action -eq 'Disable'){
    if(Test-Path -LiteralPath $link){Remove-Item -LiteralPath $link}
    Write-Host 'Windows automatic startup is OFF. Saved connections are unchanged.'
    return
}
$receipt=Get-Content -LiteralPath (Join-Path $root 'installation.json') -Raw | ConvertFrom-Json
if($receipt.owner -cne 'moba-quick-connect'){throw 'Install Moba Quick Connect first.'}
$exe=[IO.Path]::GetFullPath((Join-Path $root $receipt.executable))
if(-not $exe.StartsWith($root+'\',[StringComparison]::OrdinalIgnoreCase) -or -not [IO.File]::Exists($exe)){
    throw 'Installed application is missing.'
}
$sha=[Security.Cryptography.SHA256]::Create()
try{$actual=[BitConverter]::ToString($sha.ComputeHash([IO.File]::ReadAllBytes($exe))).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose()}
if($actual -cne $receipt.exeSha256){throw 'Installed application checksum changed.'}
foreach($dir in @($root,[IO.Path]::GetDirectoryName($exe),$StartupDirectory)){
    if((Get-Item -LiteralPath $dir -Force).Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Linked folder preserved.'}
}
[Cloudragon.Moba.Shortcuts]::Save($link,$exe,'--hidden',[IO.Path]::GetDirectoryName($exe),'Moba Quick Connect automatic startup',7)
Write-Host 'Windows automatic startup is ON. The application will stay in the tray after sign-in.'
