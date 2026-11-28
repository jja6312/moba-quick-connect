Set-StrictMode -Version Latest

function Get-MobaFileHash([string]$Path) {
    $sha=[Security.Cryptography.SHA256]::Create()
    try {return [BitConverter]::ToString($sha.ComputeHash([IO.File]::ReadAllBytes($Path))).Replace('-','').ToLowerInvariant()}
    finally {$sha.Dispose()}
}

function Enter-MobaRunLock([string]$Directory) {
    [IO.Directory]::CreateDirectory($Directory)|Out-Null
    try {return [IO.File]::Open((Join-Path $Directory 'session-run.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)}
    catch [IO.IOException] {
        if(($_.Exception.GetBaseException().HResult -band 0xffff) -notin @(32,33)){throw}
        $busy=[InvalidOperationException]::new('The shared-session launcher is still saving or starting. Try again in a moment.')
        $busy.Data['MobaLauncherBusy']=$true
        throw $busy
    }
}

function Test-MobaPublisherCommand([string]$CommandLine,[string]$LauncherPath) {
    if(-not $CommandLine){return $false}
    $leaf=[IO.Path]::GetFileName($LauncherPath)
    $mentions=($CommandLine.IndexOf($leaf,[StringComparison]::OrdinalIgnoreCase) -ge 0 -or $CommandLine.IndexOf('Start-MobaXterm-Installed.ps1',[StringComparison]::OrdinalIgnoreCase) -ge 0)
    if(-not $mentions){return $false}
    $argument=[regex]::Match($CommandLine,'(?i)(?:^|\s)-(?:f|fi|fil|file)\s+(?:"(?<path>[^"]+)"|(?<path>[^\s]+))')
    if(-not $argument.Success){return $true} # Inline/wrapper invocation: ambiguous ownership blocks recovery.
    $path=$argument.Groups['path'].Value
    try {
        if([IO.Path]::IsPathRooted($path)){
            if([string]::Equals([IO.Path]::GetFullPath($path),[IO.Path]::GetFullPath($LauncherPath),[StringComparison]::OrdinalIgnoreCase)){return $true}
        }
    }catch{return $true}
    # CIM does not expose a process current directory. A relative invocation or
    # another shared-launcher wrapper mentioning this script is fail-closed.
    return $true
}

function Register-MobaAttempt([string]$Directory) {
    $attempts=Join-Path $Directory 'launch-attempts'
    [IO.Directory]::CreateDirectory($attempts)|Out-Null
    $path=Join-Path $attempts ($PID.ToString()+'.json')
    Import-MobaCim
    $process=Get-CimInstance Win32_Process -Filter ('ProcessId='+$PID) -ErrorAction Stop
    $record=@{schema=1;kind='moba-launch-attempt';pid=$PID;startedUtc=$process.CreationDate.ToUniversalTime().ToString('o');stage='contender'}
    [IO.File]::WriteAllText($path,($record|ConvertTo-Json),[Text.UTF8Encoding]::new($false))
    return $path
}

function Set-MobaAttemptPublishing([string]$Path) {
    $record=[IO.File]::ReadAllText($Path)|ConvertFrom-Json
    if($record.pid -ne $PID){throw 'Launch attempt ownership changed.'}
    $record.stage='publisher'
    [IO.File]::WriteAllText($Path,($record|ConvertTo-Json),[Text.UTF8Encoding]::new($false))
}

function Test-MobaContender($Process,[string]$Directory) {
    if(-not $Directory){return $false}
    try{
        $path=Join-Path $Directory (([int]$Process.ProcessId).ToString()+'.json')
        $record=[IO.File]::ReadAllText($path)|ConvertFrom-Json
        return $record.schema -eq 1 -and $record.kind -eq 'moba-launch-attempt' -and $record.stage -eq 'contender' -and
            $record.pid -eq $Process.ProcessId -and [DateTime]::Parse($record.startedUtc).ToUniversalTime().Ticks -eq $Process.CreationDate.ToUniversalTime().Ticks
    }catch{return $false}
}

function Import-MobaCim {
    # Import the Windows-native CIM module, avoiding inherited PowerShell 7 paths.
    if($PSVersionTable.PSVersion.Major -eq 5){
        $module=Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\Modules\CimCmdlets\CimCmdlets.psd1'
        Import-Module $module -ErrorAction Stop
    }
}

function Get-MobaOwners([string]$LauncherPath,[string]$IgnoreContendersIn='') {
    Import-MobaCim
    $all=@(Get-CimInstance Win32_Process -ErrorAction Stop)
    $ancestors=@{};$cursor=[int]$PID
    while($cursor -gt 0 -and -not $ancestors.ContainsKey($cursor)){
        $ancestors[$cursor]=$true
        $entry=@($all|Where-Object {[int]$_.ProcessId -eq $cursor})
        if(-not $entry.Count){break};$cursor=[int]$entry[0].ParentProcessId
    }
    $apps=@($all|Where-Object {$_.Name -like 'MobaXterm*'})
    $workers=@($all|Where-Object {
        -not $ancestors.ContainsKey([int]$_.ProcessId) -and $_.Name -match '^(powershell|pwsh)\.exe$' -and
        (Test-MobaPublisherCommand ([string]$_.CommandLine) $LauncherPath) -and -not (Test-MobaContender $_ $IgnoreContendersIn)
    })
    return [pscustomobject]@{Apps=$apps.Count;Publishers=$workers.Count}
}

function Write-MobaLifecycle([string]$Directory,[string]$Event,[hashtable]$Details=@{}) {
    $record=@{utc=[DateTime]::UtcNow.ToString('o');event=$Event;publisherPid=$PID}
    foreach($key in $Details.Keys){$record[$key]=$Details[$key]}
    [IO.File]::AppendAllText((Join-Path $Directory 'lifecycle.jsonl'),($record|ConvertTo-Json -Depth 4 -Compress)+[Environment]::NewLine,[Text.UTF8Encoding]::new($false))
}

function Write-MobaActivationEvent([string]$Directory,[string]$Event) {
    # A second click must not become an error if the publisher is appending its
    # own lifecycle event at exactly the same instant.
    try{if([IO.Directory]::Exists($Directory)){Write-MobaLifecycle $Directory $Event}}catch{}
}

function Invoke-MobaExistingInstance {
    param([string]$Directory,[string]$LauncherPath,[string]$IniPath,[scriptblock]$OwnerProbe,[scriptblock]$Activator)
    $owners=if($OwnerProbe){& $OwnerProbe}else{Get-MobaOwners $LauncherPath}
    if(-not ($owners.Apps -or $owners.Publishers)){return $false}
    if($owners.Apps){
        if($Activator){& $Activator|Out-Null}else{
            try{
                if(-not ('MobaQuickConnect.NativeActivation' -as [type])){
                    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
namespace MobaQuickConnect {
 public static class NativeActivation {
  [DllImport("user32.dll")] static extern bool IsIconic(IntPtr hWnd);
  [DllImport("user32.dll")] static extern bool ShowWindowAsync(IntPtr hWnd, int command);
  [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] static extern bool FlashWindow(IntPtr hWnd, bool invert);
  public static void Show(IntPtr handle) {
   ShowWindowAsync(handle, IsIconic(handle) ? 9 : 5);
   if (!SetForegroundWindow(handle)) FlashWindow(handle, true);
  }
 }
}
'@
                }
                $windows=@([Diagnostics.Process]::GetProcesses()|Where-Object {$_.ProcessName -like 'MobaXterm*' -and $_.MainWindowHandle -ne [IntPtr]::Zero})
                if($IniPath){
                    $matching=@(Get-CimInstance Win32_Process|Where-Object {
                        $m=[regex]::Match([string]$_.CommandLine,'(?i)(?:^|\s)-i\s+(?:"(?<ini>[^"]+)"|(?<ini>[^\s]+))')
                        $_.Name -like 'MobaXterm*' -and $m.Success -and [string]::Equals([IO.Path]::GetFullPath($m.Groups['ini'].Value),[IO.Path]::GetFullPath($IniPath),[StringComparison]::OrdinalIgnoreCase)
                    }|ForEach-Object {$_.ProcessId})
                    $windows=@($windows|Where-Object {$_.Id -in $matching})
                }
                # Prefer this portable install if several Moba installations run.
                $preferred=@($windows|Where-Object {try{[IO.Path]::GetDirectoryName($_.MainModule.FileName) -ieq [IO.Path]::GetDirectoryName($LauncherPath)}catch{$false}})
                if($preferred.Count){$windows=$preferred}
                if($windows.Count){[MobaQuickConnect.NativeActivation]::Show($windows[0].MainWindowHandle)}
            }catch{} # Startup/exit races are ordinary second-click conditions.
        }
        Write-MobaActivationEvent $Directory 'existing-application-requested'
    }else{Write-MobaActivationEvent $Directory 'activation-deferred-publisher-active'}
    return $true
}

function Test-MobaRecordedOwner($Record) {
    if(-not $Record.PSObject.Properties['PublisherPid']){return $false}
    if(-not $Record.PSObject.Properties['PublisherStartedUtc']){throw 'Incomplete publisher identity. Pending edit was preserved.'}
    if([string]$Record.PublisherPid -notmatch '^[1-9][0-9]*$'){throw 'Invalid publisher identity. Pending edit was preserved.'}
    try {$owner=[Diagnostics.Process]::GetProcessById([int]$Record.PublisherPid)}catch [ArgumentException]{return $false}
    try {
        $expected=[DateTime]::Parse([string]$Record.PublisherStartedUtc).ToUniversalTime()
        return [Math]::Abs(($owner.StartTime.ToUniversalTime()-$expected).TotalSeconds) -lt 1
    }finally {$owner.Dispose()}
}

function Assert-MobaPendingRecord($Record) {
    if($null -eq $Record -or $Record -isnot [pscustomobject]){throw 'Unknown pending edit was preserved for recovery.'}
    $fields=@($Record.PSObject.Properties.Name)
    if($fields -contains 'Schema'){
        if($Record.Schema -isnot [int] -or $Record.Schema -ne 2){throw 'Unsupported pending schema was preserved for recovery.'}
        foreach($name in @('RunId','PublisherPid','PublisherStartedUtc')){
            if(-not $Record.PSObject.Properties[$name]){throw 'Incomplete publisher identity was preserved.'}
        }
        if([string]$Record.RunId -cnotmatch '^[0-9a-f]{32}$' -or [string]$Record.PublisherPid -notmatch '^[1-9][0-9]*$'){throw 'Invalid publisher identity was preserved.'}
        try{$null=[DateTime]::Parse([string]$Record.PublisherStartedUtc)}catch{throw 'Invalid publisher timestamp was preserved.'}
    }else{
        if($fields.Count -ne 3 -or @($fields|Where-Object {$_ -notin @('SourceHash','InitialViewHash','CreatedUtc')}).Count){throw 'Unknown legacy pending edit was preserved for recovery.'}
    }
    foreach($name in @('SourceHash','InitialViewHash')){
        if(-not $Record.PSObject.Properties[$name] -or [string]$Record.$name -cnotmatch '^[0-9a-fA-F]{64}$'){throw 'Invalid pending edit was preserved for recovery.'}
    }
    if(-not $Record.PSObject.Properties['CreatedUtc']){throw 'Unknown pending edit was preserved for recovery.'}
    try{$null=[DateTime]::Parse([string]$Record.CreatedUtc)}catch{throw 'Invalid pending timestamp was preserved.'}
}

function Recover-MobaUnchangedPending {
    param([string]$Directory,[string]$Source,[string]$LauncherPath,[scriptblock]$OwnerProbe,
          [scriptblock]$BeforeRecheck)
    # Caller holds session-run.lock for this whole operation and the ensuing run.
    $pending=Join-Path $Directory 'pending-edit.json'
    if(-not [IO.File]::Exists($pending)){return $null}
    $view=Join-Path $Directory 'sessions-local.mxtsessions';$ini=Join-Path $Directory 'MobaXterm.ini'
    $probe={Get-MobaOwners $LauncherPath -IgnoreContendersIn (Join-Path $Directory 'launch-attempts')}
    if($OwnerProbe){$probe=$OwnerProbe}
    $owners=& $probe
    if($owners.Apps -or $owners.Publishers){throw 'A MobaXterm application or publisher is active. Pending edit was preserved.'}
    $before=@{}
    foreach($file in @($pending,$view,$ini,$Source)){$before[$file]=Get-MobaFileHash $file}
    try {$record=[IO.File]::ReadAllText($pending)|ConvertFrom-Json}catch{throw 'Unreadable pending edit was preserved for recovery.'}
    Assert-MobaPendingRecord $record
    if(Test-MobaRecordedOwner $record){throw 'The recorded publisher is still active. Pending edit was preserved.'}
    if($before[$view] -cne ([string]$record.InitialViewHash).ToLowerInvariant()){
        throw 'Unpublished session edits were preserved. Review the local view before recovery.'
    }
    $root=[IO.Path]::GetFullPath($Directory).TrimEnd('\')
    $archive=[IO.Path]::GetFullPath((Join-Path $root ('recovery\unchanged-'+[DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')+'-'+[Guid]::NewGuid().ToString('N'))))
    if(-not $archive.StartsWith($root+'\',[StringComparison]::OrdinalIgnoreCase)){throw 'Recovery path escaped its device directory.'}
    [IO.Directory]::CreateDirectory($archive)|Out-Null
    foreach($file in @($pending,$view,$ini)){
        $backup=Join-Path $archive ([IO.Path]::GetFileName($file)+'.before')
        [IO.File]::Copy($file,$backup,$false)
        if((Get-MobaFileHash $backup) -cne $before[$file]){throw 'Backup mismatch. Pending edit was preserved.'}
    }
    if($BeforeRecheck){& $BeforeRecheck}
    $owners=& $probe
    if($owners.Apps -or $owners.Publishers -or (Test-MobaRecordedOwner $record)){throw 'A writer became active. Pending edit was preserved.'}
    foreach($file in @($pending,$view,$ini,$Source)){
        if((Get-MobaFileHash $file) -cne $before[$file]){throw 'Files changed during recovery. Pending edit was preserved.'}
    }
    $destination=Join-Path $archive 'pending-edit.recovered.json'
    [IO.File]::Move($pending,$destination)
    if((Get-MobaFileHash $destination) -cne $before[$pending]){throw 'Archived pending checksum mismatch.'}
    Write-MobaLifecycle $Directory 'unchanged-pending-archived' @{archive=[IO.Path]::GetFileName($archive);sourceChanged=($before[$Source] -cne ([string]$record.SourceHash).ToLowerInvariant())}
    return $archive
}

Export-ModuleMember -Function Get-MobaFileHash,Enter-MobaRunLock,Get-MobaOwners,Write-MobaLifecycle,Recover-MobaUnchangedPending,Test-MobaPublisherCommand,Invoke-MobaExistingInstance,Write-MobaActivationEvent,Register-MobaAttempt,Set-MobaAttemptPublishing
