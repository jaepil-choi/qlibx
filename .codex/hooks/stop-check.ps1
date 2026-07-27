$null = [Console]::In.ReadToEnd()
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$activePlanDirectory = Join-Path $repositoryRoot '.agent\plans\active'

$unfinished = @()
foreach ($plan in Get-ChildItem -LiteralPath $activePlanDirectory -Filter '*.md' -File -ErrorAction SilentlyContinue) {
    $content = Get-Content -Raw -LiteralPath $plan.FullName
    if ($content -notmatch '(?im)^Status:\s*(complete|blocked)\s*$') {
        $unfinished += $plan.Name
    }
}

if ($unfinished.Count -gt 0) {
    [ordered]@{
        continue = $true
        systemMessage = "Completion check: unfinished active ExecPlan(s): $($unfinished -join ', '). Verify acceptance criteria, validation evidence, approvals, and durable state before claiming completion."
    } | ConvertTo-Json -Compress
}
