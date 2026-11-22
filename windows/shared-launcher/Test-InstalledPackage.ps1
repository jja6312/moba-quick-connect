[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$PackageDirectory,[string]$MobaXtermExe,[string]$ScratchDirectory='C:\MobaXtermSetupTests')
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$stage=$PackageDirectory
$fixture=Join-Path $ScratchDirectory ('deployment-test-'+[guid]::NewGuid().ToString('N'))
$app=Join-Path $fixture '동기화 폴더\EagerSync\convinient\MobaXterm'
$convenient=[IO.Directory]::GetParent($app).FullName
$syncRoot=[IO.Directory]::GetParent($convenient).FullName
$device=Join-Path $fixture 'Device Profile'
$null=New-Item -ItemType Directory -Path $app -Force
$null=New-Item -ItemType Directory -Path (Join-Path $syncRoot '1keys') -Force
[IO.File]::WriteAllText((Join-Path $syncRoot '1keys\test.key'),'NOT-A-REAL-PRIVATE-KEY')
Copy-Item -LiteralPath (Join-Path ([IO.Directory]::GetParent($stage).FullName) 'Portable-SessionPaths.psm1') -Destination (Join-Path $app 'Portable-SessionPaths.psm1')
'{"schema":1,"aliases":{}}' | Set-Content -LiteralPath (Join-Path $convenient 'portable-keys.json') -Encoding UTF8
$session='Demo=#109#0%192.0.2.10%22%test%%-1%-1%%%%%0%0%0%C:\NextCloud\EagerSync\1keys\test.key%%-1%0%0%0%%1080%%0%0%1%%0%%%%0%-1%-1%0#MobaFont%10%0%0%-1%15%236,236,236%30,30,30%180,180,192%0%-1%0%%xterm%-1%0%_Std_Colors_0_%80%24%0%1%-1%<none>%%0%0%-1%0%#0# #-1'
$sourceText="[SharedSettings]`r`nAllowedEditors=`r`n`r`n[Bookmarks]`r`nSubRep=`r`nImgNum=43`r`n"+$session+"`r`n"
[IO.File]::WriteAllBytes((Join-Path $convenient 'mobaxterm-sessions.mxtsessions'),[Text.Encoding]::ASCII.GetBytes($sourceText))
$template="[Misc]`r`nHomeDir=unused`r`nSlashDir=unused`r`n`r`n[SharedSessions0]`r`nFolderName=cloudragon`r`nFilePath=unused`r`n`r`n[Bookmarks]`r`nSubRep=`r`n"
[IO.File]::WriteAllBytes((Join-Path $app 'MobaXterm.ini'),[Text.Encoding]::ASCII.GetBytes($template))
$seed=Join-Path $fixture 'seed.ini'
$personalText="[Misc]`r`nHomeDir=unused`r`nSlashDir=unused`r`n`r`n[SharedSessions0]`r`nFolderName=ExistingOtherShare`r`nFilePath=C:\other-share.mxtsessions`r`n`r`n[Bookmarks]`r`nSubRep=private`r`n"+$session.Replace('Demo=','Personal=')+"`r`n"
[IO.File]::WriteAllBytes($seed,[Text.Encoding]::ASCII.GetBytes($personalText))
$sourceHash=(Get-FileHash -LiteralPath (Join-Path $convenient 'mobaxterm-sessions.mxtsessions')).Hash
$desktop=Join-Path ([Environment]::GetFolderPath('Desktop')) 'MobaXterm - Shared Sessions.lnk'
$shortcutHash=if(Test-Path -LiteralPath $desktop){(Get-FileHash -LiteralPath $desktop).Hash}else{$null}
if(!$MobaXtermExe){
    $MobaXtermExe=@((([Environment]::GetFolderPath('ProgramFilesX86'))+'\Mobatek\MobaXterm\MobaXterm.exe'),(([Environment]::GetFolderPath('ProgramFiles'))+'\Mobatek\MobaXterm\MobaXterm.exe')) | Where-Object {Test-Path -LiteralPath $_} | Select-Object -First 1
}
if(!$MobaXtermExe){throw 'Specify the installed MobaXterm executable with -MobaXtermExe.'}
$installed=$MobaXtermExe
& (Join-Path $stage 'Install-SharedSessions.ps1') -DeviceDirectory $device -MobaXtermExe $installed -ExistingIni $seed -SharedAppDirectory $app -NoShortcuts | Out-Null
$configuration=Get-Content -LiteralPath (Join-Path $device 'deployment.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if($configuration.SharedSessionIndex -ne 1){throw 'The unrelated shared-session section was overwritten.'}
$codec=[Text.Encoding]::GetEncoding(28591)
$ini=$codec.GetString([IO.File]::ReadAllBytes((Join-Path $device 'MobaXterm.ini')))
if($ini -notmatch 'FolderName=ExistingOtherShare' -or $ini -notmatch '\[SharedSessions1\]'){throw 'Shared-session sections were not preserved.'}
$view=$codec.GetString([IO.File]::ReadAllBytes((Join-Path $device 'sessions-local.mxtsessions')))
if($view -match [regex]::Escape('C:\NextCloud\EagerSync\1keys\test.key')){throw 'The canonical key reference was not resolved.'}
Import-Module (Join-Path $app 'Portable-SessionPaths.psm1') -Force
$fixtureView=[Text.Encoding]::GetEncoding(28591).GetString([IO.File]::ReadAllBytes((Join-Path $device 'sessions-local.mxtsessions')))
$fixtureMatch=[regex]::Match($fixtureView,'(?m)^Demo=#109#(?<fields>0%[^#\r\n]*)')
$preparedKey=Get-PortableReference ($fixtureMatch.Groups['fields'].Value.Split('%')[14])
if(-not [IO.File]::Exists($preparedKey) -or [IO.Path]::GetFullPath($preparedKey) -cne [IO.Path]::GetFullPath((Join-Path $syncRoot '1keys\test.key'))){throw 'The synthetic original-key reference was not prepared.'}
if((Get-FileHash -LiteralPath (Join-Path $convenient 'mobaxterm-sessions.mxtsessions')).Hash -ne $sourceHash){throw 'Setup changed the shared source.'}
$shortcutAfter=if(Test-Path -LiteralPath $desktop){(Get-FileHash -LiteralPath $desktop).Hash}else{$null}
if($shortcutAfter -ne $shortcutHash){throw 'The NoShortcuts test changed the real desktop shortcut.'}
if(!(Get-Acl -LiteralPath (Join-Path $device 'keys')).AreAccessRulesProtected){throw 'The key cache ACL is not protected.'}
# Reinstall should preserve the device's private sessions and the unrelated share.
& (Join-Path $stage 'Install-SharedSessions.ps1') -DeviceDirectory $device -MobaXtermExe $installed -SharedAppDirectory $app -NoShortcuts | Out-Null
# Simulated abnormal termination must block replacement of an unfinished edit.
'{}' | Set-Content -LiteralPath (Join-Path $device 'pending-edit.json') -Encoding UTF8
$blocked=$false
try{& (Join-Path $stage 'Install-SharedSessions.ps1') -DeviceDirectory $device -MobaXtermExe $installed -SharedAppDirectory $app -NoShortcuts | Out-Null}catch{if($_.Exception.Message -like '*unfinished shared edit*'){$blocked=$true}else{throw}}
if(!$blocked){throw 'Unfinished-edit protection did not block reinstall.'}
# Verify publication with synthetic records only, without launching MobaXterm.
Import-Module (Join-Path $app 'Portable-SessionPaths.psm1') -Force
$preparedBytes=[IO.File]::ReadAllBytes((Join-Path $device 'sessions-local.mxtsessions'))
$preparedText=$codec.GetString($preparedBytes)
$sshMatch=[regex]::Match($preparedText,'(?m)^Demo=#109#(?<fields>0%[^#\r\n]*)')
$keyReference=Get-PortableReference ($sshMatch.Groups['fields'].Value.Split('%')[14])
$cacheMap=@{}
$cacheMap[$keyReference]='1keys/test.key'
$canonical=Convert-MobaKeyPaths -Data $preparedBytes -Aliases @{} -Root $syncRoot -Canonical -CacheMap $cacheMap
if($codec.GetString($canonical.Data) -notmatch [regex]::Escape('C:\NextCloud\EagerSync\1keys\test.key')){throw 'Canonical key round trip failed.'}
$extraRecord=$session.Replace('Demo=','AddedSynthetic=').Replace('192.0.2.10','192.0.2.11')
$newBytes=$codec.GetBytes($codec.GetString($canonical.Data).TrimEnd([char[]]"`r`n")+"`r`n"+$extraRecord+"`r`n")
$syntheticSource=Join-Path $convenient 'mobaxterm-sessions.mxtsessions'
$published=Publish-MobaSource -Source $syntheticSource -InitialHash $sourceHash.ToLowerInvariant() -Data $newBytes -ConflictDirectory (Join-Path $device 'conflicts')
if(!$published.Published){throw 'Synthetic normal-exit publication failed.'}
$publishedHash=(Get-FileHash -LiteralPath $syntheticSource).Hash
$conflict=Publish-MobaSource -Source $syntheticSource -InitialHash $sourceHash.ToLowerInvariant() -Data $preparedBytes -ConflictDirectory (Join-Path $device 'conflicts')
if($conflict.Published -or !(Test-Path -LiteralPath $conflict.Conflict)){throw 'Synthetic concurrent-edit conflict was not preserved.'}
if((Get-FileHash -LiteralPath $syntheticSource).Hash -ne $publishedHash){throw 'Concurrent publication overwrote the newer synthetic source.'}
Write-Output 'PASS: new installation, Unicode/space paths, native preparation, original-key reference, private/unrelated-share preservation, reinstall, pending-edit protection, source unchanged by installer, canonical key round trip, synthetic publication/conflict preservation, and no real desktop changes.'
Write-Output ('Fixture: '+$fixture)
