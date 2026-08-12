$ErrorActionPreference = "Stop"
$showcaseRoot = $PSScriptRoot
$projectRoot = Join-Path $showcaseRoot "outputs/project"
$outputRoot = Join-Path $showcaseRoot "outputs"

uv run qlibx project init $projectRoot --apply
uv run qlibx project sample $projectRoot --apply
uv run python (Join-Path $projectRoot "examples/qlibx_owned/basic/run.py") $projectRoot |
    Set-Content -LiteralPath (Join-Path $outputRoot "result.json") -Encoding utf8
uv run qlibx artifact list $projectRoot |
    Set-Content -LiteralPath (Join-Path $outputRoot "catalog.json") -Encoding utf8
