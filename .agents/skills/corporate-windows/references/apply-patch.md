# Codex editing on Windows

## Mandatory environment split

Run `.agent/bin/detect-environment.ps1` once before the first edit in a task. Use its result exactly:

| Detection | First edit method | Executable-copy policy |
|---|---|---|
| `windows=true` and `user_profile_non_ascii=true` | Use `scripts/edit-text-file.ps1` directly. Do not probe the known-broken built-in patch sandbox first. | A task-specific `C:\tmp` Codex executable is allowed only for a complex patch the direct editor cannot express. |
| `user_profile_non_ascii=false` | Use built-in `apply_patch`. | Never copy `codex.exe` to `C:\tmp`, the workspace, or another ASCII path merely for editing. Never use `edit-text-file.ps1`. |

This split reflects the two actual machines. Do not generalize the company workaround to an
English-username home PC. A non-ASCII profile selects the compatibility route; it is not a general
claim about Windows or proof of company ownership.

## Company non-ASCII PC: direct text editing

Use the bundled editor for ordinary source and document edits. It accepts exact text, requires a
unique match, detects concurrent changes, stays inside the workspace, and replaces atomically.

Update one exact section:

```powershell
$old = @"
exact current text
"@
$new = @"
replacement text
"@

& '.agents\skills\corporate-windows\scripts\edit-text-file.ps1' `
    -Path 'relative\path\file.py' `
    -OldText $old `
    -NewText $new

git diff --check -- 'relative/path/file.py'
```

Create a new text file without overwriting anything:

```powershell
$content = @"
new file content
"@

& '.agents\skills\corporate-windows\scripts\edit-text-file.ps1' `
    -Path 'relative\path\new-file.md' `
    -NewText $content `
    -Create

git diff --check -- 'relative/path/new-file.md'
```

Rules:

- Re-read the target immediately before constructing `$old`.
- Use a larger exact context block when the intended text is not unique.
- Split multi-section work into bounded edits and inspect the diff after each one.
- Never use ad-hoc `Set-Content`, Python rewriting, or blind search-and-replace.
- If the helper reports an ASCII profile, stop and use built-in `apply_patch`; do not bypass its
  hard guard.

## Company non-ASCII PC: complex apply_patch fallback

Use this only when an edit requires Codex patch grammar across multiple files or add/update/delete
operations that the direct text editor cannot express. Do not first retry the known-broken built-in
sandbox on this profile.

Resolve the current Codex executable from `apply_patch.bat`, copy it to a unique task-specific
ASCII path, preserve `--codex-run-as-apply-patch`, and remove the exact copy in `finally`.

```powershell
$detected = .\.agent\bin\detect-environment.ps1 | ConvertFrom-Json
if (-not $detected.windows -or -not $detected.user_profile_non_ascii) {
    throw 'Company non-ASCII patch fallback is forbidden on this profile.'
}
if ($patch.Length -gt 24000) {
    throw 'Split the patch by file or section.'
}
if (-not $patch.StartsWith('*** Begin Patch') -or
    -not $patch.TrimEnd().EndsWith('*** End Patch')) {
    throw 'Invalid apply_patch envelope.'
}
if ($patch -match '(?m)^\*\*\* Update File:' -and $patch -notmatch '(?m)^@@') {
    throw 'Every update patch requires an @@ hunk marker.'
}

$wrapper = (Get-Command apply_patch -ErrorAction Stop).Source
$wrapperText = Get-Content -LiteralPath $wrapper -Raw
$match = [regex]::Match(
    $wrapperText,
    '"(?<exe>[^"\r\n]+codex\.exe)"\s+--codex-run-as-apply-patch'
)
if (-not $match.Success) {
    throw "Cannot resolve codex.exe from $wrapper"
}

$sourceExe = $match.Groups['exe'].Value
$taskPatchExe = "C:\tmp\codex-apply-patch-$PID-$([guid]::NewGuid().ToString('N')).exe"
if (Test-Path -LiteralPath $taskPatchExe) {
    throw "Refusing to overwrite an existing executable: $taskPatchExe"
}

try {
    Copy-Item -LiteralPath $sourceExe -Destination $taskPatchExe
    & $taskPatchExe --codex-run-as-apply-patch $patch
    if ($LASTEXITCODE -ne 0) {
        throw "Codex apply-patch exited with code $LASTEXITCODE"
    }
}
finally {
    if (Test-Path -LiteralPath $taskPatchExe) {
        Remove-Item -LiteralPath $taskPatchExe
    }
}

git diff --check
```

Use one scoped elevated shell call if the company sandbox blocks the copy or a protected target
write. Do not use `-Force`, do not reuse a shared executable name, do not leave the executable
behind, and do not print a patch that may contain sensitive material.

## English-username home PC

Use built-in `apply_patch` normally. Do not run the company direct editor. Do not inspect the
wrapper, copy the Codex executable, create a `C:\tmp` fallback, or request elevation solely because
the company PC needed those steps.

If built-in `apply_patch` fails on this ASCII-profile PC, diagnose the concrete local error. The
failure is not evidence that the company non-ASCII workaround applies.

## Patch grammar checks

For Codex patch format:

1. Preserve `--codex-run-as-apply-patch` when invoking the resolved executable.
2. Put `@@` before each update hunk; every hunk line starts with `-`, `+`, or a context space.
3. Keep the single patch argument below 24,000 characters and split large patches.
4. Run `git diff --check` and inspect the affected diff after every edit.

```text
*** Begin Patch
*** Update File: path/to/file
@@
-old text
+new text
*** End Patch
```
