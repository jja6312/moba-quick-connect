Set-StrictMode -Version Latest
$script:BytesCodec = [Text.Encoding]::GetEncoding(28591)
$script:AnsiCodec = [Text.Encoding]::Default
$script:Utf8Strict = New-Object Text.UTF8Encoding($false, $true)

function Get-PortableReference([string]$byteText) {
    $bytes = $script:BytesCodec.GetBytes($byteText)
    try { return $script:Utf8Strict.GetString($bytes) }
    catch { return [Text.Encoding]::GetEncoding(949).GetString($bytes) }
}

function ConvertTo-ByteText([string]$text) {
    return $script:BytesCodec.GetString($script:AnsiCodec.GetBytes($text))
}

function Get-RelativeKey([string]$reference, [hashtable]$aliases) {
    if ($aliases.ContainsKey($reference)) { return [string]$aliases[$reference] }
    $normalized = $reference.Replace('\', '/')
    if ($normalized.StartsWith('1keys/')) { return $normalized }
    $match = [regex]::Match($normalized, '(?i)^[a-z]:/NextCloud/EagerSync/(1keys/.+)$')
    if ($match.Success) { return $match.Groups[1].Value }
    $match = [regex]::Match($normalized, '(?i)(?:^|/)(1keys/.+)$')
    if ($match.Success) {
        foreach ($relative in $aliases.Values) {
            if ([string]::Equals($relative, $match.Groups[1].Value, [StringComparison]::OrdinalIgnoreCase)) { return [string]$relative }
        }
    }
    return $null
}

function Get-SafeKeyPath([string]$root, [string]$relative) {
    if ($relative -notmatch '^1keys/' -or $relative -match '(^|/)\.\.?(/|$)|[\r\n:%?#]') { throw 'Unsafe key reference.' }
    $path = [IO.Path]::GetFullPath((Join-Path $root $relative.Replace('/', '\')))
    $allowed = [IO.Path]::GetFullPath((Join-Path $root '1keys')) + '\'
    if (-not $path.StartsWith($allowed, [StringComparison]::OrdinalIgnoreCase)) { throw 'Key escapes EagerSync/1keys.' }
    return $path
}

function Convert-MobaKeyPaths {
    param([byte[]]$Data, [hashtable]$Aliases, [string]$Root, [switch]$Canonical, [string]$KeyCacheDirectory, [hashtable]$CacheMap=@{})
    $text = $script:BytesCodec.GetString($Data)
    $counts = @{ Resolved=0; Pending=0 }
    $changed = [regex]::Replace($text, '(?m)^(?<name>[^=\r\n]+=)#109#(?<fields>0%[^#\r\n]*)', [Text.RegularExpressions.MatchEvaluator]{
        param($match)
        $fields = $match.Groups['fields'].Value.Split([char]'%')
        if ($fields.Length -lt 16) { throw 'Unexpected SSH record.' }
        foreach ($index in @(14, 15)) {
            if (-not $fields[$index]) { continue }
            $reference = Get-PortableReference $fields[$index]
            if ($Canonical) {
                if ($CacheMap.ContainsKey($reference)) {
                    $relative = [string]$CacheMap[$reference]
                    $fields[$index] = ConvertTo-ByteText ('C:\NextCloud\EagerSync\' + $relative.Replace('/', '\'))
                    continue
                }
                $prefix = [IO.Path]::GetFullPath($Root).TrimEnd('\') + '\'
                if ($reference.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
                    $relative = $reference.Substring($prefix.Length).Replace('\', '/')
                    $null = Get-SafeKeyPath $Root $relative
                    $fields[$index] = ConvertTo-ByteText ('C:\NextCloud\EagerSync\' + $relative.Replace('/', '\'))
                }
            } else {
                $relative = Get-RelativeKey $reference $Aliases
                if ($relative) {
                    $path = Get-SafeKeyPath $Root $relative
                    if (Test-Path -LiteralPath $path -PathType Leaf) {
                        $viewPath = $path
                        # The synchronized original is authoritative and already
                        # has a meaningful name/folder. Keep a reverse mapping
                        # for publishing the device view back to the shared file.
                        $CacheMap[$viewPath] = $relative
                        if ($viewPath.StartsWith($env:USERPROFILE + '\', [StringComparison]::OrdinalIgnoreCase)) {
                            $CacheMap[('_ProfileDir_\' + $viewPath.Substring($env:USERPROFILE.Length + 1))] = $relative
                        }
                        $fields[$index] = ConvertTo-ByteText $viewPath
                        $counts.Resolved++
                    } else { $counts.Pending++ }
                } else { $counts.Pending++ }
            }
        }
        return $match.Groups['name'].Value + '#109#' + ($fields -join '%')
    })
    return [pscustomobject]@{ Data=$script:BytesCodec.GetBytes($changed); Resolved=$counts.Resolved; Pending=$counts.Pending }
}

function Get-ByteHash([byte[]]$Data) {
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash($Data))).Replace('-', '').ToLowerInvariant() }
    finally { $sha.Dispose() }
}

function Publish-MobaSource {
    param([string]$Source, [string]$InitialHash, [byte[]]$Data, [string]$ConflictDirectory)
    $actual = Get-ByteHash ([IO.File]::ReadAllBytes($Source))
    if ($actual -ne $InitialHash) {
        $null = New-Item -ItemType Directory -Force -Path $ConflictDirectory
        $conflict = Join-Path $ConflictDirectory ('sessions-conflict-' + [guid]::NewGuid().ToString('N') + '.mxtsessions')
        [IO.File]::WriteAllBytes($conflict, $Data)
        return [pscustomobject]@{ Published=$false; Conflict=$conflict }
    }
    $backupDirectory = Join-Path ([IO.Path]::GetDirectoryName($Source)) 'MobaXterm\backups'
    $null = New-Item -ItemType Directory -Force -Path $backupDirectory
    $backup = Join-Path $backupDirectory ('shared-before-publish-' + [guid]::NewGuid().ToString('N') + '.bak')
    $temporary = $Source + '.' + [guid]::NewGuid().ToString('N') + '.tmp'
    [IO.File]::WriteAllBytes($temporary, $Data)
    if ((Get-ByteHash ([IO.File]::ReadAllBytes($Source))) -ne $InitialHash) {
        Remove-Item -LiteralPath $temporary
        return Publish-MobaSource $Source $InitialHash $Data $ConflictDirectory
    }
    [IO.File]::Replace($temporary, $Source, $backup)
    return [pscustomobject]@{ Published=$true; Conflict=$null }
}

Export-ModuleMember -Function Get-PortableReference, ConvertTo-ByteText, Get-RelativeKey, Get-SafeKeyPath, Convert-MobaKeyPaths, Get-ByteHash, Publish-MobaSource
