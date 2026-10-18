# Native first stage: Windows PowerShell 5.1, no Python required.
# Remaining arguments are passed as an array, never evaluated as shell code.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$pythonArgs = @($args)
$stage = $null
$lockStream = $null

function Read-Lock {
    $values = @{}
    foreach ($line in Get-Content -LiteralPath (Join-Path $PSScriptRoot 'python.lock')) {
        if ($line -match '^\s*(#|$)') { continue }
        if ($line -notmatch '^([a-z0-9_]+)=(\S+)$' -or $values.ContainsKey($Matches[1])) {
            throw 'Invalid Python runtime manifest.'
        }
        $values[$Matches[1]] = $Matches[2]
    }
    if ($values.version -notmatch '^3\.\d+\.\d+$' -or $values.Count -ne 7) {
        throw 'Invalid Python runtime version.'
    }
    foreach ($platform in @('windows_x64', 'windows_arm64', 'linux_source')) {
        if ($values["${platform}_sha256"] -notmatch '^[a-f0-9]{64}$' -or
            $values["${platform}_url"] -notmatch ('^https://www\.python\.org/ftp/python/' + [regex]::Escape($values.version) + '/[A-Za-z0-9.\-]+$')) {
            throw 'Invalid Python artifact URL or checksum.'
        }
    }
    return $values
}

function Test-Python([string]$path, [string]$version) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return $false }
    $probe = "import sys,ssl,sqlite3,tkinter,venv,ensurepip; assert sys.version.split()[0] == '$version'; assert tkinter.Tcl().eval('info patchlevel')"
    try {
        & $path -I -c $probe 2>$null | Out-Null
        return $LASTEXITCODE -eq 0
    } catch { return $false }
}

function Quote-Argument([string]$value) {
    # CommandLineToArgvW rules, including embedded quotes and trailing backslashes.
    $quoted = [regex]::Replace($value, '(\\*)"', '$1$1\"')
    $quoted = [regex]::Replace($quoted, '(\\+)$', '$1$1')
    return '"' + $quoted + '"'
}

try {
    # Foreign Tcl/Python environment variables can bind this Python to another runtime.
    foreach ($name in @('PYTHONHOME','PYTHONPATH','TCL_LIBRARY','TK_LIBRARY')) {
        Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
    }
    $env:PYTHONIOENCODING = 'utf-8'
    [Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
    $manifest = Read-Lock
    $version = $manifest.version
    $architecture = $env:PROCESSOR_ARCHITECTURE
    if ($env:PROCESSOR_ARCHITEW6432) { $architecture = $env:PROCESSOR_ARCHITEW6432 }
    $platform = switch ($architecture.ToUpperInvariant()) {
        'AMD64' { 'windows_x64' }
        'ARM64' { 'windows_arm64' }
        default { throw 'Pi Kit supports Windows x64 and ARM64.' }
    }
    $cache = if ($env:PI_KIT_RUNTIME_HOME) { $env:PI_KIT_RUNTIME_HOME } elseif ($env:OPENCODE_KIT_RUNTIME_HOME) { $env:OPENCODE_KIT_RUNTIME_HOME } else {
        Join-Path $env:LOCALAPPDATA 'OpenCodeKit\runtimes'
    }
    if (-not [IO.Path]::IsPathRooted($cache)) { throw 'Runtime cache must be an absolute path.' }
    $cache = [IO.Path]::GetFullPath($cache)
    [IO.Directory]::CreateDirectory($cache) | Out-Null
    # Reject junctions before any staging cleanup; never traverse user-provided links.
    for ($item = Get-Item -LiteralPath $cache; $null -ne $item; $item = $item.Parent) {
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Runtime cache cannot use junctions or symbolic links.' }
    }
    $target = Join-Path $cache "cpython-$version-$platform"
    if ((Test-Path -LiteralPath $target) -and ((Get-Item -LiteralPath $target).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'Runtime folder cannot be a junction or symbolic link.'
    }
    $python = Join-Path $target 'python.exe'
    $deadline = [DateTime]::UtcNow.AddMinutes(15)
    while ($null -eq $lockStream) {
        try { $lockStream = [IO.File]::Open((Join-Path $cache "$version-$platform.lock"), 'OpenOrCreate', 'ReadWrite', 'None') }
        catch [IO.IOException] {
            if ([DateTime]::UtcNow -gt $deadline) { throw 'Another Python setup is still running. Try again later.' }
            Start-Sleep -Seconds 1
        }
    }
    if (-not (Test-Python $python $version)) {
        if (Test-Path -LiteralPath $target) {
            throw "The private Python runtime is damaged: $target. Rename that folder and try again."
        }
        Write-Host "Pi Kit: preparing Python $version (first launch only)..."
        $stage = Join-Path $cache ('.setup-' + [guid]::NewGuid().ToString('N'))
        [IO.Directory]::CreateDirectory($stage) | Out-Null
        $archive = Join-Path $stage 'python.zip'
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -UseBasicParsing -Uri $manifest["${platform}_url"] -OutFile $archive -TimeoutSec 300
        $hash = [Security.Cryptography.SHA256]::Create()
        $stream = [IO.File]::OpenRead($archive)
        try { $actual = [BitConverter]::ToString($hash.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() }
        finally { $stream.Dispose(); $hash.Dispose() }
        if ($actual -ne $manifest["${platform}_sha256"]) {
            throw 'Python download checksum mismatch. Nothing was installed. Try downloading again.'
        }
        $unpacked = Join-Path $stage 'runtime'
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $zip = [IO.Compression.ZipFile]::OpenRead($archive)
        try {
            foreach ($entry in $zip.Entries) {
                $destination = [IO.Path]::GetFullPath((Join-Path $unpacked $entry.FullName))
                if (-not $destination.StartsWith($unpacked + '\', [StringComparison]::OrdinalIgnoreCase) -or
                    (($entry.ExternalAttributes -shr 16) -band 0xF000) -eq 0xA000) {
                    throw 'Unsafe path in Python archive.'
                }
            }
        } finally { $zip.Dispose() }
        [IO.Compression.ZipFile]::ExtractToDirectory($archive, $unpacked)
        if (-not (Test-Python (Join-Path $unpacked 'python.exe') $version)) { throw 'Downloaded Python failed its version / Tk / SSL / SQLite check.' }
        Move-Item -LiteralPath $unpacked -Destination $target
    }
    $lockStream.Dispose()
    $lockStream = $null
    $env:OPENCODE_KIT_PYTHON = $python
    $env:PATH = "$target;$target\Scripts;$env:PATH"
    if ($pythonArgs.Count -eq 1 -and $pythonArgs[0] -eq '--kit-runtime-path') {
        Write-Output $python
        exit 0
    }
    # Windows PowerShell 5.1 native invocation drops embedded quotes in -c strings.
    $start = New-Object Diagnostics.ProcessStartInfo
    $start.FileName = $python
    $start.UseShellExecute = $false
    $start.Arguments = (($pythonArgs | ForEach-Object { Quote-Argument $_ }) -join ' ')
    $child = [Diagnostics.Process]::Start($start)
    $child.WaitForExit()
    $result = $child.ExitCode
    $child.Dispose()
} catch {
    [Console]::Error.WriteLine('Pi Kit: ' + $_.Exception.Message)
    $result = 1
} finally {
    if ($null -ne $lockStream) { $lockStream.Dispose() }
    if ($null -ne $stage -and (Test-Path -LiteralPath $stage)) {
        # Only this invocation's fresh GUID directory, verified under the cache.
        $resolved = [IO.Path]::GetFullPath($stage)
        if ([IO.Path]::GetDirectoryName($resolved) -eq $cache -and
            [IO.Path]::GetFileName($resolved) -match '^\.setup-[a-f0-9]{32}$') {
            Remove-Item -LiteralPath $resolved -Recurse -Force
        }
    }
}
exit $result
