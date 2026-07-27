---
name: corporate-windows
description: Diagnose and recover Windows enterprise environment failures involving non-ASCII or long paths, TLS and system trust stores, uv cache or permissions, private package indexes and proxies, native builds, Git locks, Quarto, Codex patching, or approved Oracle access. Use when commands fail only on a managed Windows machine, under a non-ASCII user profile, or with certificate, access-denied, wheel-build, index-authentication, path, SQLPlus, or file-lock errors.
---

# Corporate Windows Workflow

Run `.agent/bin/detect-environment.ps1` first. When more evidence is needed, run
`scripts/collect-diagnostics.ps1`; add `-IncludePaths` or `-ProbeWrites` only when the user-visible
diagnostic need justifies the extra disclosure or temporary write.

A non-ASCII username or profile path activates path-related workarounds but does not prove that the
machine is company-owned. Preserve the original command, error class, and execution boundary before
trying a workaround. Load only the matching reference:

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
