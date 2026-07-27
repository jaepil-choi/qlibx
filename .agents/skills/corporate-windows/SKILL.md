---
name: corporate-windows
description: Apply conditional Windows enterprise workarounds for non-ASCII paths, system trust stores, Quarto, patching, and approved Oracle access.
---

# Corporate Windows Workflow

Run `.agent/bin/detect-environment.ps1` first. A non-ASCII username or profile path activates
path-related workarounds but does not prove the machine is company-owned. Load only the reference
needed for the observed capability or error:

- TLS, certificate, revocation, `uv`, Python, or Node errors: `references/tls.md`
- Quarto rendering under a non-ASCII Windows profile: `references/quarto.md`
- Codex `apply_patch` wrapper failure: `references/apply-patch.md`
- Oracle or SQLPlus access: `references/oracle-sqlplus.md`

Never weaken certificate verification, infer database permission, or apply every workaround
preemptively. Preserve the original failure evidence and record which conditional path was used.
