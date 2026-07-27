$null = [Console]::In.ReadToEnd()

[ordered]@{
    continue = $true
    systemMessage = 'Before compaction, checkpoint the active ExecPlan and .agent/runs state with progress, decisions, validation evidence, failures, and the next restartable action.'
} | ConvertTo-Json -Compress
