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

Do not substitute `git apply`, a search-and-replace script, or direct file rewriting merely to
bypass a broken Codex wrapper. Do not copy an executable or switch to an ASCII path before the
ordinary method has actually failed on the current machine.
