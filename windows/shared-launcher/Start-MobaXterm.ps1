[CmdletBinding()]
param([switch]$ValidateOnly,[switch]$PrepareOnly,[switch]$NoDialogs)
$ErrorActionPreference='Stop'
trap {
    if($ValidateOnly -or $PrepareOnly -or $NoDialogs){[Console]::Error.WriteLine($_.Exception.Message)}
    else {Add-Type -AssemblyName System.Windows.Forms;[Windows.Forms.MessageBox]::Show($_.Exception.Message,'MobaXterm launcher')|Out-Null}
    exit 1
}
Import-Module (Join-Path $PSScriptRoot 'Portable-SessionPaths.psm1') -Force
Import-Module (Join-Path $PSScriptRoot 'Session-Lifecycle.psm1') -Force
$appDir=$PSScriptRoot
$convenient=[IO.Directory]::GetParent($appDir).FullName
$syncRoot=[IO.Directory]::GetParent($convenient).FullName
$source=Join-Path $convenient 'mobaxterm-sessions.mxtsessions'
$manifestPath=Join-Path $convenient 'portable-keys.json'
$template=Join-Path $appDir 'MobaXterm.ini'
$namespace=(Get-ByteHash ([Text.Encoding]::UTF8.GetBytes($syncRoot.ToLowerInvariant()))).Substring(0,16)
$localDir=Join-Path $env:LOCALAPPDATA ('MobaXtermPortable\'+$namespace)
$iniPath=Join-Path $localDir 'MobaXterm.ini'
$viewPath=Join-Path $localDir 'sessions-local.mxtsessions'
$pendingPath=Join-Path $localDir 'pending-edit.json'
$manifest=[IO.File]::ReadAllText($manifestPath)|ConvertFrom-Json
if($manifest.schema -ne 1){throw 'Unsupported key manifest.'}
$aliases=@{}
foreach($p in $manifest.aliases.PSObject.Properties){$aliases[$p.Name]=[string]$p.Value}
if($ValidateOnly){
    $initial=[IO.File]::ReadAllBytes($source)
    $view=Convert-MobaKeyPaths -Data $initial -Aliases $aliases -Root $syncRoot
    @{SourceSHA256=(Get-ByteHash $initial);DeviceDirectory=$localDir;ResolvedKeyFields=$view.Resolved;PendingKeyFields=$view.Pending;SharedINI=$template;LocalINI=$iniPath}|ConvertTo-Json
    return
}
$runLock=Enter-MobaRunLock $localDir
try {
    $owners=Get-MobaOwners $PSCommandPath
    if($owners.Apps -or $owners.Publishers){throw 'MobaXterm or its shared-session publisher is active. No files were replaced.'}
    if($PrepareOnly -and [IO.File]::Exists($pendingPath)){throw 'An unfinished edit must be preserved during preparation.'}
    if(-not $PrepareOnly){$null=Recover-MobaUnchangedPending -Directory $localDir -Source $source -LauncherPath $PSCommandPath}
    # Re-read the latest canonical source AFTER recovery and acquiring the lease.
    $initial=[IO.File]::ReadAllBytes($source);$initialHash=Get-ByteHash $initial
    $cacheMap=@{}
    $view=Convert-MobaKeyPaths -Data $initial -Aliases $aliases -Root $syncRoot -CacheMap $cacheMap
    $byteCodec=[Text.Encoding]::GetEncoding(28591)
    $iniSource=if([IO.File]::Exists($iniPath)){$iniPath}else{$template}
    $text=$byteCodec.GetString([IO.File]::ReadAllBytes($iniSource))
    $pathValue=ConvertTo-ByteText $viewPath
    $text=[regex]::Replace($text,'(?ms)(^\[SharedSessions0\][^\[]*?^FilePath=)[^\r\n]*',[Text.RegularExpressions.MatchEvaluator]{param($m)$m.Groups[1].Value+$pathValue})
    if($text -notmatch [regex]::Escape($pathValue)){throw 'Shared sessions section could not be redirected.'}
    $homePathValue=ConvertTo-ByteText (Join-Path $localDir 'home')
    $text=[regex]::Replace($text,'(?m)^HomeDir=[^\r\n]*',[Text.RegularExpressions.MatchEvaluator]{param($m)'HomeDir='+$homePathValue})
    $text=[regex]::Replace($text,'(?m)^AutoRefreshSharedSessions=[^\r\n]*','AutoRefreshSharedSessions=1')
    [IO.File]::WriteAllBytes($iniPath,$byteCodec.GetBytes($text))
    [IO.File]::WriteAllBytes($viewPath,$view.Data)
    if($PrepareOnly){@{SourceSHA256=$initialHash;DeviceDirectory=$localDir;LocalINI=$iniPath}|ConvertTo-Json;return}
    $exes=@(Get-ChildItem -LiteralPath $appDir -Filter 'MobaXterm*.exe' -File)
    if($exes.Count -ne 1){throw 'Expected one MobaXterm executable.'}
    $runId=[Guid]::NewGuid().ToString('N')
    $record=@{Schema=2;RunId=$runId;SourceHash=$initialHash;InitialViewHash=(Get-ByteHash $view.Data);CreatedUtc=[DateTime]::UtcNow.ToString('o');PublisherPid=$PID;PublisherStartedUtc=[Diagnostics.Process]::GetCurrentProcess().StartTime.ToUniversalTime().ToString('o')}
    [IO.File]::WriteAllText($pendingPath,($record|ConvertTo-Json),[Text.UTF8Encoding]::new($false))
    Write-MobaLifecycle $localDir 'run-started' @{runId=$runId}
    try {
        $process=Start-Process -FilePath $exes[0].FullName -ArgumentList ('-i "'+$iniPath+'"') -WorkingDirectory $appDir -PassThru
        $record.AppPid=$process.Id
        [IO.File]::WriteAllText($pendingPath,($record|ConvertTo-Json),[Text.UTF8Encoding]::new($false))
        Write-MobaLifecycle $localDir 'application-started' @{runId=$runId;appPid=$process.Id}
        $process.WaitForExit()
        Write-MobaLifecycle $localDir 'application-exited' @{runId=$runId;appPid=$process.Id;exitCode=$process.ExitCode}
        $edited=[IO.File]::ReadAllBytes($viewPath)
        if((Get-ByteHash $edited) -cne (Get-ByteHash $view.Data)){
            $normalized=Convert-MobaKeyPaths -Data $edited -Aliases $aliases -Root $syncRoot -Canonical -CacheMap $cacheMap
            $result=Publish-MobaSource -Source $source -InitialHash $initialHash -Data $normalized.Data -ConflictDirectory (Join-Path $localDir 'conflicts')
            if(-not $result.Published){
                Write-MobaLifecycle $localDir 'conflict-preserved' @{runId=$runId}
                Add-Type -AssemblyName System.Windows.Forms
                [Windows.Forms.MessageBox]::Show('Shared sessions changed on another device. Your edits were preserved at: '+$result.Conflict,'MobaXterm session conflict')|Out-Null
            }else{Write-MobaLifecycle $localDir 'edits-published' @{runId=$runId}}
        }
        if((([IO.File]::ReadAllText($pendingPath)|ConvertFrom-Json).RunId) -cne $runId){throw 'Pending ownership changed; record was preserved.'}
        [IO.File]::Delete($pendingPath)
        Write-MobaLifecycle $localDir 'run-completed' @{runId=$runId}
    }catch{
        Write-MobaLifecycle $localDir 'run-failed' @{runId=$runId;errorType=$_.Exception.GetType().FullName}
        $_|Out-String|Set-Content -LiteralPath (Join-Path $localDir 'last-error.txt') -Encoding UTF8
        throw
    }
}finally{$runLock.Dispose()}
