---
name: corporate-windows
description: Diagnose and recover Windows enterprise environment failures involving non-ASCII or long paths, TLS and system trust stores, uv cache or permissions, private package indexes and proxies, native builds, Git locks, Quarto, Codex patching, or approved Oracle access. Use when commands fail only on a managed Windows machine, under a non-ASCII user profile, or with certificate, access-denied, wheel-build, index-authentication, path, SQLPlus, or file-lock errors.
---

# Corporate Windows Workflow

Run `.agent/bin/detect-environment.ps1` once before the first edit or environment-sensitive command
in a task. Route file edits by the detected profile; do not use one Windows strategy everywhere.

- If `windows=true` and `user_profile_non_ascii=true`, use
  `scripts/edit-text-file.ps1` from the first edit. Do not spend a tool call proving that the
  built-in patch sandbox fails again. This is the observed company-PC path.
- If `user_profile_non_ascii=false`, use the built-in `apply_patch` path. Never invoke the
  non-ASCII helper and never copy `codex.exe` to `C:\tmp`, the workspace, or another ASCII path
  merely for patching. This is the English-username home-PC path.
- Do not infer company ownership from the profile. The profile value selects only the known patch
  compatibility route.

An explicit user instruction to edit named workspace files establishes the requested edit scope. Do
not misread a sandbox or read-only error as uncertainty about the user's intent, and do not repeat
the same blocked command. If the active tool boundary still requires approval, use one scoped
escalation for only those named targets. This does not authorize unrelated files, destructive
operations, credential exposure, database access, or writes outside the requested workspace scope.

For operations other than this profile-gated edit route, try the documented ordinary command once.
Examples include a normal `uv` command or the project's declared test command. If it succeeds,
stop: do not introduce a fallback path.

The ordinary first attempt must already be safe and authorized. It does not waive database,
network, destructive-action, or other approval requirements. If the exact failure from the current
operation is already available, preserve that evidence instead of repeating the command only to
make it fail again.

Only after a concrete matching failure outside the pre-routed edit case:

1. Preserve the original command, exact error class and message, working directory, and execution
   boundary.
2. Run `.agent/bin/detect-environment.ps1`.
3. Load only the reference matching the observed failure and detected capabilities.
4. Use the narrowest reversible workaround, then retry the original operation and verify its
   result.

When more evidence is needed, run `scripts/collect-diagnostics.ps1`; add `-IncludePaths` or
`-ProbeWrites` only when the user-visible diagnostic need justifies the extra disclosure or
temporary write.

A non-ASCII profile selects the known edit helper above but does not prove that the machine is
company-owned or explain unrelated failures. On an ASCII-only personal machine, diagnose the
concrete failure normally instead of forcing a non-ASCII fallback. Load only the matching
reference:

- TLS, certificate, revocation, `uv`, Python, or Node errors: `references/tls.md`
- uv cache, managed Python, `.venv`, access denied, or lock errors:
  `references/uv-cache-and-permissions.md`
- Artifactory, Nexus, private indexes, proxy authentication, 401, or 403:
  `references/private-index-and-proxy.md`
- non-ASCII, encoding, invalid filename, or long-path failures:
  `references/paths-encoding-and-long-paths.md`
- missing wheel, sdist, compiler, MSVC, Rust, CMake, or Python-version build failures:
  `references/native-build-toolchain.md`
- `.git/index.lock`, dubious ownership, case-only rename, or line-ending failures:
  `references/git-windows.md`
- Quarto rendering under a non-ASCII Windows profile: `references/quarto.md`
- Codex `apply_patch` wrapper failure: `references/apply-patch.md`
- Oracle or SQLPlus access: `references/oracle-sqlplus.md`

Never weaken certificate verification, expose credentials, infer database permission, modify
enterprise policy, delete a cache or lock file, or install a compiler preemptively. Start with
read-only diagnosis, use the narrowest reversible workaround, and record the exact path taken.
