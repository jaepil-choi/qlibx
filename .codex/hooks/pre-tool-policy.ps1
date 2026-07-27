$ErrorActionPreference = 'Stop'
$rawInput = [Console]::In.ReadToEnd()

try {
    $payload = $rawInput | ConvertFrom-Json
}
catch {
    exit 0
}

$serializedInput = ''
if ($null -ne $payload.tool_input) {
    $serializedInput = $payload.tool_input | ConvertTo-Json -Depth 20 -Compress
}
elseif ($null -ne $payload.toolInput) {
    $serializedInput = $payload.toolInput | ConvertTo-Json -Depth 20 -Compress
}

$warnings = [System.Collections.Generic.List[string]]::new()

if ($serializedInput -match '(?i)(--insecure|--no-verify-ssl|verify\s*=\s*false|ssl[_-]?verify\s*=\s*false|disable.{0,20}revocation)') {
    $warnings.Add('TLS verification or certificate revocation must not be disabled. Use the corporate-windows TLS workflow.')
}

if ($serializedInput -match '(?i)\b(sqlplus|kwam-sqlplus)\b') {
    $warnings.Add('Database access requires exact SQL disclosure, load assessment, and explicit approval for this query.')
}

if ($serializedInput -match '(?i)\bgit\s+(add|commit|push|merge|rebase|tag)\b') {
    $warnings.Add('Git mutation requires explicit task or user authorization and must exclude unrelated changes.')
}

$mentionsExperimentOrShowcase = $serializedInput -match '(?i)(experiments?[\\/]|showcases?[\\/])'
$mentionsTests = $serializedInput -match '(?i)tests?[\\/]'
if ($mentionsExperimentOrShowcase -and $mentionsTests) {
    $warnings.Add('Do not add or modify tests solely for experiment or showcase work.')
}

if ($warnings.Count -gt 0) {
    [ordered]@{
        systemMessage = 'HARNESS POLICY: ' + ($warnings -join ' ')
    } | ConvertTo-Json -Compress
}
