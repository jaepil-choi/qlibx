[CmdletBinding()]
param(
    [switch]$IncludePaths,
    [switch]$ProbeWrites
)

$ErrorActionPreference = 'Stop'

function Test-Ascii {
    param([AllowNull()][string]$Value)
    if ($null -eq $Value) { return $true }
    foreach ($character in $Value.ToCharArray()) {
        if ([int]$character -gt 127) { return $false }
    }
    return $true
}

function Get-PathObservation {
    param([AllowNull()][string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) {
        return [ordered]@{ configured = $false }
    }

    $observation = [ordered]@{
        configured = $true
        exists = Test-Path -LiteralPath $Value
        ascii = Test-Ascii $Value
        length = $Value.Length
    }
    if ($IncludePaths) {
        $observation.path = $Value
    }
    return $observation
}

function Get-CommandVersion {
    param(
        [Parameter(Mandatory)][string]$Name,
        [string[]]$Arguments = @('--version')
    )

    if ($null -eq (Get-Command $Name -ErrorAction SilentlyContinue)) {
        return [ordered]@{ available = $false }
    }

    try {
        $line = (& $Name @Arguments 2>&1 | Select-Object -First 1).ToString().Trim()
        return [ordered]@{ available = $true; version = $line }
    }
    catch {
        return [ordered]@{ available = $true; error = $_.Exception.Message }
    }
}

function Get-UvDirectory {
    param([Parameter(Mandatory)][ValidateSet('cache', 'python')][string]$Kind)
    if ($null -eq (Get-Command uv -ErrorAction SilentlyContinue)) {
        return [ordered]@{ available = $false }
    }

    try {
        $value = if ($Kind -eq 'cache') {
            (& uv cache dir 2>&1 | Select-Object -First 1).ToString().Trim()
        }
        else {
            (& uv python dir 2>&1 | Select-Object -First 1).ToString().Trim()
        }
        return Get-PathObservation $value
    }
    catch {
        return [ordered]@{ available = $true; error = $_.Exception.Message }
    }
}

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..\..')).Path
$baseDetector = Join-Path $repositoryRoot '.agent\bin\detect-environment.ps1'
$baseEnvironment = & $baseDetector | ConvertFrom-Json
$temporaryPath = [System.IO.Path]::GetTempPath()
$writeProbe = [ordered]@{ requested = [bool]$ProbeWrites; succeeded = $null }

if ($ProbeWrites) {
    $probePath = Join-Path $temporaryPath ("agent-path-probe-{0}.tmp" -f [guid]::NewGuid())
    try {
        [System.IO.File]::WriteAllText($probePath, 'probe')
        $writeProbe.succeeded = $true
    }
    catch {
        $writeProbe.succeeded = $false
        $writeProbe.error = $_.Exception.Message
    }
    finally {
        if (Test-Path -LiteralPath $probePath) {
            Remove-Item -LiteralPath $probePath -Force
        }
    }
}

$longPathsEnabled = $null
try {
    $longPathsEnabled = (
        Get-ItemProperty -LiteralPath 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem' `
            -Name LongPathsEnabled -ErrorAction Stop
    ).LongPathsEnabled -eq 1
}
catch {
    $longPathsEnabled = $null
}

$proxyVariables = @(
    'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY',
    'http_proxy', 'https_proxy', 'all_proxy', 'no_proxy'
)
$proxyPresence = [ordered]@{}
foreach ($name in $proxyVariables) {
    $proxyPresence[$name] = -not [string]::IsNullOrWhiteSpace(
        [Environment]::GetEnvironmentVariable($name)
    )
}

[ordered]@{
    schema_version = 1
    base_environment = $baseEnvironment
    paths = [ordered]@{
        repository = Get-PathObservation $repositoryRoot
        user_profile = Get-PathObservation ([Environment]::GetFolderPath('UserProfile'))
        temp = Get-PathObservation $temporaryPath
        uv_cache = Get-UvDirectory 'cache'
        uv_python = Get-UvDirectory 'python'
    }
    tools = [ordered]@{
        uv = Get-CommandVersion 'uv'
        python = Get-CommandVersion 'python'
        node = Get-CommandVersion 'node'
        git = Get-CommandVersion 'git'
        quarto = Get-CommandVersion 'quarto'
        sqlplus = Get-CommandVersion 'sqlplus' @('-V')
    }
    policy = [ordered]@{
        long_paths_enabled = $longPathsEnabled
        corporate_profile_explicit = $baseEnvironment.explicit_corporate_profile
    }
    proxy_variable_present = $proxyPresence
    temp_write_probe = $writeProbe
} | ConvertTo-Json -Depth 8
