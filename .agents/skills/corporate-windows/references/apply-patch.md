# Codex apply_patch on Windows

Use the built-in `apply_patch` path for manual file edits. Always try it normally first, regardless
of username, profile path, machine ownership, or a previous failure seen on another computer. If it
succeeds, stop and do not inspect wrappers, copy executables, or create an ASCII fallback.

If the built-in patch failure from the current operation is already captured, use that evidence;
do not repeat the same failing patch solely to activate this workflow.

Only after the normal path fails:

1. Preserve the exact error, command boundary, working directory, and whether the failure came from
   the built-in tool, a shell wrapper, or the underlying executable.
2. Run `.agent/bin/detect-environment.ps1`. A non-ASCII username or profile enables a path
   workaround but does not establish causality. If the profile is ASCII-only, continue diagnosing
   the observed wrapper, ACL, sandbox, or packaging failure without assuming a path-encoding cause.
3. Inspect `apply_patch.bat` and resolve the actual Codex patch executable and argument contract it
   invokes.
4. Invoke the actual executable in apply-patch mode using the contract required by that build. Do
   not assume that every build accepts standard input. For example, if the executable reports that
   `--codex-run-as-apply-patch` requires a UTF-8 `PATCH` argument, pass the entire patch as one
   argument.
5. If the actual executable is inaccessible from its installed location and a copied fallback is
   unavoidable, place it under an ASCII task-specific path such as `C:\tmp`. Give every concurrent
   agent a unique fallback filename to prevent races, and do not overwrite a shared executable.
6. Apply the patch, verify the resulting diff immediately, and remove only the task-specific
   temporary executable after the final patch succeeds.

## Preflight for `--codex-run-as-apply-patch PATCH`

Treat executable mode, patch grammar, and Windows argument length as separate preconditions. Check
all three before retrying a real edit.

### 1. Preserve the wrapper's mode flag

If `apply_patch.bat` invokes:

```bat
"...\codex.exe" --codex-run-as-apply-patch %*
```

invoke the resolved or task-specific copied executable with both the mode flag and the complete
patch argument:

```powershell
& $taskPatchExe --codex-run-as-apply-patch $patch
```

Do not invoke that executable as `& $taskPatchExe $patch`. That starts normal Codex CLI behavior
instead of apply-patch mode and can produce unrelated TTY or local-state-database errors. Diagnose
those errors as an invocation-contract failure before blaming the document, sandbox, or database.
A no-op patch may return nonzero because no file changed; establish the contract from the wrapper
and actual error text rather than treating a no-op exit code as the primary proof.

### 2. Validate update-hunk grammar before launching

An update patch needs an `@@` marker before changed lines. Every line inside the hunk must begin
with `-`, `+`, or a context space:

```text
*** Begin Patch
*** Update File: path/to/file
@@
-old text
+new text
*** End Patch
```

Before invoking the executable, inspect a bounded numbered preview of the generated payload. Check
that `*** Begin Patch`, the file directive, `@@`, prefixed hunk lines, and `*** End Patch` appear in
that order. Do not retry an invalid payload through a different privilege boundary.

When PowerShell generates a full-section hunk, parenthesize the split before piping so every line
gets its prefix:

```powershell
$oldLines = (($oldSection -split "`n") | ForEach-Object { '-' + $_ }) -join "`n"
$newLines = (($newSection -split "`n") | ForEach-Object { '+' + $_ }) -join "`n"
```

Do not write `($oldSection -split "`n", -1 | ForEach-Object { ... })`; PowerShell operator
precedence can leave all but the first line unprefixed.

### 3. Keep the single PATCH argument bounded

When the build requires `PATCH` as one argument, Windows command-line limits still apply. Split a
large edit into deterministic file- or section-sized patches before invocation. If process launch
fails with `The filename or extension is too long`, reduce the patch argument; do not switch to
standard input when the inspected executable contract requires an argument.

After each smaller patch, run `git diff --check` and inspect the affected headings or lines before
continuing. Do not reapply a section that already succeeded.

Do not substitute `git apply`, a search-and-replace script, or direct file rewriting merely to
bypass a broken Codex wrapper. Do not copy an executable or switch to an ASCII path before the
ordinary method has actually failed on the current machine.
