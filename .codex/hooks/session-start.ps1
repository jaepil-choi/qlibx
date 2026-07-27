$ErrorActionPreference = 'Stop'
$null = [Console]::In.ReadToEnd()

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$detector = Join-Path $repositoryRoot '.agent\bin\detect-environment.ps1'
$environment = & $detector | ConvertFrom-Json
$activePlanDirectory = Join-Path $repositoryRoot '.agent\plans\active'
$activePlanCount = @(
    Get-ChildItem -LiteralPath $activePlanDirectory -Filter '*.md' -File -ErrorAction SilentlyContinue
).Count

$message = @(
    'Agent harness loaded.'
    "Active ExecPlans: $activePlanCount."
    "Non-ASCII profile workaround: $($environment.guidance.use_non_ascii_path_workarounds)."
    "Corporate workflow candidate: $($environment.guidance.load_corporate_windows_skill)."
    'Read .agent/project.yaml before planning; load only the skills required for the task.'
) -join ' '

[ordered]@{
    continue = $true
    systemMessage = $message
} | ConvertTo-Json -Compress
