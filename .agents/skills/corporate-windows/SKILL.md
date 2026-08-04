---
name: corporate-windows
description: Diagnose and recover Windows enterprise environment failures involving non-ASCII or long paths, TLS and system trust stores, uv cache or permissions, private package indexes and proxies, native builds, Git locks, Quarto, Codex patching, or approved Oracle access. Use when commands fail only on a managed Windows machine, under a non-ASCII user profile, or with certificate, access-denied, wheel-build, index-authentication, path, SQLPlus, or file-lock errors.
---

# Corporate Windows Workflow

Do not activate a corporate or non-ASCII workaround preemptively. Always try the documented,
ordinary command once in the current environment first. Examples include the built-in
`apply_patch` path, a normal `uv` command, or the project's declared test command. If it succeeds,
stop: do not run environment detection and do not introduce a fallback path.

The ordinary first attempt must already be safe and authorized. It does not waive database,
network, destructive-action, or other approval requirements. If the exact failure from the current
operation is already available, preserve that evidence instead of repeating the command only to
make it fail again.

Only after a concrete matching failure:

1. Preserve the original command, exact error class and message, working directory, and execution
   boundary.
2. Run `.agent/bin/detect-environment.ps1`.
3. Load only the reference matching the observed failure and detected capabilities.
4. Use the narrowest reversible workaround, then retry the original operation and verify its
   result.

When more evidence is needed, run `scripts/collect-diagnostics.ps1`; add `-IncludePaths` or
`-ProbeWrites` only when the user-visible diagnostic need justifies the extra disclosure or
temporary write.

A non-ASCII username or profile path permits path-related workarounds only after a relevant failure
has occurred. It does not prove that the machine is company-owned, and it is not by itself evidence
that non-ASCII text caused the failure. On an ASCII-only personal machine, diagnose the concrete
failure normally instead of forcing a non-ASCII fallback. Load only the matching reference:

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
