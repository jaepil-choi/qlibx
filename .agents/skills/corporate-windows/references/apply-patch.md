# Codex apply_patch on Windows

Use `apply_patch` for manual file edits.

If an elevated Windows shell cannot execute the `apply_patch.bat` wrapper:

1. Inspect the wrapper and resolve the actual Codex patch executable it invokes.
2. Invoke that executable in apply-patch mode with the patch on standard input.
3. If a copied fallback executable is unavoidable, place it under an ASCII task-specific path such
   as `C:\tmp`.
4. Give every concurrent agent a unique fallback filename to prevent races.
5. Verify the resulting diff immediately.

Do not substitute `git apply` merely to bypass a broken Codex wrapper. Do not overwrite a shared
fallback executable used by another agent.
