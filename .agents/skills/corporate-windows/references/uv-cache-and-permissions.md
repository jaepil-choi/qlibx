# uv cache and permission recovery

1. Preserve the failing command and exact `WinError`, access-denied, or lock message.
2. Inspect `uv --version`, `uv cache dir`, `uv python dir`, the selected interpreter, `.venv`, and
   running uv or Python processes.
3. Distinguish a Codex sandbox denial from an operating-system ACL, antivirus lock, stale process,
   cache corruption, and an unwritable user profile.
4. Retry the same command with scoped sandbox escalation when the failure names a protected uv
   cache or managed-Python path.
5. Prefer `--refresh` or `--refresh-package <name>` before cleaning cache data.
6. Use `uv cache clean <name>` before considering a full `uv cache clean`.
7. Never delete files inside the uv cache manually. Never remove `.venv` while a Python, editor,
   notebook, or uv process may still be using it.
8. If the default cache path is unusable, use a task-scoped ASCII `UV_CACHE_DIR` on the same
   filesystem as the environment when possible.
9. Recreate `.venv` only after confirming the exact path and obtaining approval when it may contain
   user state.

Use `--no-cache` only as a bounded diagnostic. uv still needs a temporary cache for that invocation,
and routinely bypassing cache hides the root cause and degrades performance.
