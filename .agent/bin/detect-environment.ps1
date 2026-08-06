[CmdletBinding()]
param()

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

function Test-CommandAvailable {
    param([Parameter(Mandatory)][string]$Name)
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

$profileValue = [Environment]::GetEnvironmentVariable('AGENT_CORPORATE_PROFILE')
$explicitCorporateProfile = $profileValue -match '^(?i:1|true|yes|on)$'
$userName = [Environment]::UserName
$userProfile = [Environment]::GetFolderPath('UserProfile')

$result = [ordered]@{
    schema_version = 1
    platform = [Environment]::OSVersion.Platform.ToString()
    windows = $IsWindows -or $env:OS -eq 'Windows_NT'
    user_name_non_ascii = -not (Test-Ascii $userName)
    user_profile_non_ascii = -not (Test-Ascii $userProfile)
    explicit_corporate_profile = $explicitCorporateProfile
    capabilities = [ordered]@{
        uv = Test-CommandAvailable 'uv'
        python = (Test-CommandAvailable 'python') -or (Test-CommandAvailable 'py')
        node = Test-CommandAvailable 'node'
        quarto = Test-CommandAvailable 'quarto'
        sqlplus = Test-CommandAvailable 'sqlplus'
        git = Test-CommandAvailable 'git'
    }
    guidance = [ordered]@{
        use_non_ascii_path_workarounds = (-not (Test-Ascii $userProfile))
        load_corporate_windows_skill = $explicitCorporateProfile -or (-not (Test-Ascii $userProfile))
        edit_strategy = if (-not (Test-Ascii $userProfile)) {
            'corporate_non_ascii_direct_editor'
        } else {
            'builtin_apply_patch'
        }
        allow_task_scoped_codex_copy = (-not (Test-Ascii $userProfile))
        forbid_non_ascii_profile_edit_workarounds = (Test-Ascii $userProfile)
        company_ownership_inferred = $false
    }
}

$result | ConvertTo-Json -Depth 5 -Compress
