[CmdletBinding(DefaultParameterSetName = 'Update')]
param(
    [Parameter(Mandatory)]
    [string]$Path,

    [Parameter(Mandatory, ParameterSetName = 'Update')]
    [string]$OldText,

    [Parameter(Mandatory)]
    [string]$NewText,

    [Parameter(Mandatory, ParameterSetName = 'Create')]
    [switch]$Create,

    [string]$WorkspaceRoot = (Get-Location).Path
)

$ErrorActionPreference = 'Stop'

function Test-Ascii {
    param([AllowNull()][string]$Value)

    if ($null -eq $Value) {
        return $true
    }
    foreach ($character in $Value.ToCharArray()) {
        if ([int]$character -gt 127) {
            return $false
        }
    }
    return $true
}

function Test-PathInside {
    param(
        [Parameter(Mandatory)][string]$Candidate,
        [Parameter(Mandatory)][string]$Root
    )

    $separator = [IO.Path]::DirectorySeparatorChar
    $normalizedRoot = $Root.TrimEnd($separator) + $separator
    return $Candidate.StartsWith($normalizedRoot, [StringComparison]::OrdinalIgnoreCase)
}

if ($env:OS -ne 'Windows_NT') {
    throw 'The corporate non-ASCII text editor is Windows-only.'
}

$userProfile = [Environment]::GetFolderPath('UserProfile')
if (Test-Ascii $userProfile) {
    throw (
        'This helper is forbidden on an ASCII user profile. Use built-in apply_patch and do not ' +
        'activate the company non-ASCII workaround.'
    )
}

$resolvedWorkspace = (Resolve-Path -LiteralPath $WorkspaceRoot).Path
$candidate = if ([IO.Path]::IsPathRooted($Path)) {
    [IO.Path]::GetFullPath($Path)
}
else {
    [IO.Path]::GetFullPath((Join-Path $resolvedWorkspace $Path))
}
if (-not (Test-PathInside -Candidate $candidate -Root $resolvedWorkspace)) {
    throw "Target must stay inside WorkspaceRoot: $candidate"
}

$target = [IO.FileInfo]$candidate
$parent = $target.Directory.FullName
if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
    throw "Target parent directory does not exist: $parent"
}

$utf8NoBom = [Text.UTF8Encoding]::new($false, $true)
$utf8Bom = [Text.UTF8Encoding]::new($true, $true)
$staging = Join-Path $parent ".$(($target.Name)).$([guid]::NewGuid().ToString('N')).tmp"

try {
    if ($Create) {
        if (Test-Path -LiteralPath $candidate) {
            throw "Create refuses to overwrite an existing file: $candidate"
        }
        [IO.File]::WriteAllText($staging, $NewText, $utf8NoBom)
        [IO.File]::Move($staging, $candidate)
        return
    }

    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
        throw "Update target does not exist: $candidate"
    }
    if ($OldText.Length -eq 0) {
        throw 'OldText must not be empty for an update.'
    }

    $originalBytes = [IO.File]::ReadAllBytes($candidate)
    $hasBom = (
        $originalBytes.Length -ge 3 -and
        $originalBytes[0] -eq 0xEF -and
        $originalBytes[1] -eq 0xBB -and
        $originalBytes[2] -eq 0xBF
    )
    $content = if ($hasBom) {
        $utf8Bom.GetString($originalBytes, 3, $originalBytes.Length - 3)
    }
    else {
        $utf8NoBom.GetString($originalBytes)
    }

    $first = $content.IndexOf($OldText, [StringComparison]::Ordinal)
    if ($first -lt 0) {
        throw 'OldText was not found; re-read the file before editing.'
    }
    $second = $content.IndexOf(
        $OldText,
        $first + $OldText.Length,
        [StringComparison]::Ordinal
    )
    if ($second -ge 0) {
        throw 'OldText is not unique; use a larger exact context block.'
    }

    $updated = $content.Substring(0, $first) + $NewText + $content.Substring($first + $OldText.Length)
    $encoding = if ($hasBom) { $utf8Bom } else { $utf8NoBom }
    [IO.File]::WriteAllText($staging, $updated, $encoding)

    $currentBytes = [IO.File]::ReadAllBytes($candidate)
    if (-not [Linq.Enumerable]::SequenceEqual[byte]($originalBytes, $currentBytes)) {
        throw 'Target changed after it was read; refusing to overwrite concurrent work.'
    }
    [IO.File]::Move($staging, $candidate, $true)
}
finally {
    if (Test-Path -LiteralPath $staging) {
        Remove-Item -LiteralPath $staging
    }
}
