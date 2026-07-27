# Quarto under non-ASCII Windows paths

Use this only when Quarto or revealjs Sass compilation fails because its installation, temporary,
or cache path includes non-ASCII characters.

1. Confirm the failing path and error.
2. Create or reuse a verified ASCII-only junction for the Quarto installation.
3. Set `TEMP`, `TMP`, `LOCALAPPDATA`, and `APPDATA` to task-scoped ASCII directories under
   `C:\tmp`.
4. Invoke `quarto.exe` through the ASCII junction.
5. Keep the source document and generated report behavior unchanged.

Example installation junction:

```powershell
if (-not (Test-Path -LiteralPath 'C:\tmp\quarto-ascii')) {
    New-Item -ItemType Junction `
        -Path 'C:\tmp\quarto-ascii' `
        -Target "$env:LOCALAPPDATA\Programs\Quarto" | Out-Null
}
```

Do not assume that every Quarto failure is caused by the username; preserve and inspect the
original error first.
