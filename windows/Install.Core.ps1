function Get-MobaInstalledHash([string]$Path) {
    $sha=[Security.Cryptography.SHA256]::Create()
    try{return [BitConverter]::ToString($sha.ComputeHash([IO.File]::ReadAllBytes($Path))).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose()}
}
function Install-MobaQuickConnect {
    param([byte[]]$Payload,[string]$ExpectedHash,[string]$LocalData=$env:LOCALAPPDATA,
          [string]$MenuDirectory=[Environment]::GetFolderPath('Programs'),
          [string]$StartupDirectory=[Environment]::GetFolderPath('Startup'),[switch]$NoLaunch)
    $ErrorActionPreference='Stop'
    $sha=[Security.Cryptography.SHA256]::Create()
    try{$actual=[BitConverter]::ToString($sha.ComputeHash($Payload)).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose()}
    if($actual -cne $ExpectedHash){throw 'Package checksum mismatch.'}
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $memory=[IO.MemoryStream]::new($Payload,$false)
    $zip=[IO.Compression.ZipArchive]::new($memory,[IO.Compression.ZipArchiveMode]::Read)
    $names=@{};$size=0
    try{
        foreach($entry in $zip.Entries){
            $name=$entry.FullName
            if(-not $name.StartsWith('app/') -or $name.Contains('\') -or $name.Contains(':') -or ($name.Split('/') -contains '..') -or ($name.Split('/') -contains '.') -or (($entry.ExternalAttributes -shr 16) -band 0xF000) -eq 0xA000){throw 'Unsafe package entry.'}
            $size+=$entry.Length
            if($size -gt 104857600 -or $names.Count -gt 100 -or $names.ContainsKey($name)){throw 'Invalid package size or duplicate entry.'}
            $names[$name]=$true
        }
    }finally{$zip.Dispose();$memory.Dispose()}
    foreach($required in @('app/MobaQuickConnect.exe','app/AutoStart.ps1')){if(-not $names.ContainsKey($required)){throw 'Incomplete package.'}}
    $parent=Join-Path ([IO.Path]::GetFullPath($LocalData)) 'Cloudragon'
    $root=Join-Path $parent 'MobaQuickConnect'
    foreach($dir in @($parent,$root)){
        if(Test-Path -LiteralPath $dir){
            $item=Get-Item -LiteralPath $dir -Force
            if(-not $item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)){throw 'Linked installation folder preserved.'}
        }
    }
    $receiptPath=Join-Path $root 'installation.json'
    if(Test-Path -LiteralPath $root){
        if(-not [IO.File]::Exists($receiptPath) -or (Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json).owner -cne 'moba-quick-connect'){throw 'Unowned installation folder preserved.'}
    }
    [IO.Directory]::CreateDirectory($parent)|Out-Null
    $stage=Join-Path $parent ('.moba-setup-'+[Guid]::NewGuid().ToString('N'))
    [IO.Directory]::CreateDirectory($stage)|Out-Null
    try{
        $archive=Join-Path $stage 'payload.zip'
        [IO.File]::WriteAllBytes($archive,$Payload)
        [IO.Compression.ZipFile]::ExtractToDirectory($archive,(Join-Path $stage 'unpack'))
        $app=Join-Path $stage 'unpack\app'
        $version=([IO.File]::ReadAllText((Join-Path $app 'version.txt'))).Trim()
        if($version -notmatch '^\d+\.\d+\.\d+$'){throw 'Invalid application version.'}
        $versions=Join-Path $root 'versions'
        if((Test-Path -LiteralPath $versions) -and ((Get-Item -LiteralPath $versions -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)){throw 'Linked versions folder preserved.'}
        [IO.Directory]::CreateDirectory($versions)|Out-Null
        $destination=Join-Path $versions $version
        if(Test-Path -LiteralPath $destination){
            foreach($file in Get-ChildItem -LiteralPath $app -File){
                $current=Join-Path $destination $file.Name
                if(-not [IO.File]::Exists($current) -or (Get-MobaInstalledHash $current) -cne (Get-MobaInstalledHash $file.FullName)){throw 'Modified installed version preserved.'}
            }
        }else{[IO.Directory]::Move($app,$destination)}
        $exe=Join-Path $destination 'MobaQuickConnect.exe'
        $next=@{owner='moba-quick-connect';version=$version;payloadSha256=$ExpectedHash;executable=('versions\'+$version+'\MobaQuickConnect.exe');exeSha256=(Get-MobaInstalledHash $exe)}
        $temporary=Join-Path $root ('installation-'+[Guid]::NewGuid().ToString('N')+'.tmp')
        [IO.File]::WriteAllText($temporary,($next|ConvertTo-Json),[Text.UTF8Encoding]::new($false))
        if([IO.File]::Exists($receiptPath)){[IO.File]::Replace($temporary,$receiptPath,(Join-Path $root ('installation-previous-'+[Guid]::NewGuid().ToString('N')+'.json')))}else{[IO.File]::Move($temporary,$receiptPath)}
        $menuLink=Join-Path $MenuDirectory 'Moba Quick Connect.lnk'
        $shell=New-Object -ComObject WScript.Shell
        if(Test-Path -LiteralPath $menuLink){if(-not $shell.CreateShortcut($menuLink).TargetPath.StartsWith($root+'\',[StringComparison]::OrdinalIgnoreCase)){throw 'Unrelated Start Menu shortcut preserved.'}}
        [IO.Directory]::CreateDirectory($MenuDirectory)|Out-Null
        $shortcut=$shell.CreateShortcut($menuLink)
        $shortcut.TargetPath=$exe
        $shortcut.WorkingDirectory=$destination
        $shortcut.Description='Moba Quick Connect'
        $shortcut.Save()
        if(Test-Path -LiteralPath (Join-Path $StartupDirectory 'Moba Quick Connect.lnk')){
            & (Join-Path $destination 'AutoStart.ps1') -Action Enable -LocalData $LocalData -StartupDirectory $StartupDirectory
        }
        $started=$false
        $running=@(Get-Process -Name 'MobaQuickConnect*' -ErrorAction SilentlyContinue)
        if(-not $NoLaunch -and $running.Count -eq 0){Start-Process -FilePath $exe|Out-Null;$started=$true}
        Write-Host 'Installed. Ctrl+Shift+Space opens the window while MobaXterm is focused.'
        if($running.Count){Write-Host 'An earlier instance is running. Exit it from the tray, then open Moba Quick Connect from Start.'}
        return [pscustomobject]@{version=$version;executable=$exe;started=$started;autostartRequested=$false;explorerLaunchRequested=$false}
    }finally{
        if([IO.Directory]::Exists($stage)){
            $checked=[IO.Path]::GetFullPath($stage)
            if($checked.StartsWith($parent+'\.moba-setup-',[StringComparison]::OrdinalIgnoreCase)){Remove-Item -LiteralPath $checked -Recurse -Force}
        }
    }
}
