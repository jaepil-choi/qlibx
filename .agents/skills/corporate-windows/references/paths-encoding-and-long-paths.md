# Paths, encoding, and long paths

1. Inspect the username, user profile, repository, `TEMP`, `TMP`, uv cache, Python installation,
   and tool installation paths for non-ASCII characters and excessive length.
2. Record console encoding, Python filesystem encoding, and the exact process that rejects the path.
3. Prefer a task-scoped ASCII temporary directory or a verified junction over moving the repository
   or changing user-wide settings.
4. Quote literal Windows paths and use `-LiteralPath` for PowerShell filesystem operations.
5. Keep one shell end-to-end for file operations; do not enumerate paths in PowerShell and pass
   reconstructed strings to another shell.
6. Treat Windows long-path support as two conditions: operating-system policy and application
   long-path awareness. Detect both before asking for an administrator change.
7. Do not enable registry or group-policy settings automatically. Report the required policy and
   let the user or administrator decide.
8. When a workaround succeeds, record which path was redirected and keep generated output
   ownership unambiguous.

Do not assume every invalid-filename or encoding failure comes from a non-ASCII username. Reproduce
the failure with the smallest literal path before selecting a workaround.
