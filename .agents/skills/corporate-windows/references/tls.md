# TLS and system trust stores

First identify which process owns the failing TLS connection. A fix for one layer does not
automatically fix another.

## uv owns the connection

Use uv's system-certificate support when the enterprise root is already trusted by Windows:

```powershell
uv --system-certs sync
$env:UV_SYSTEM_CERTS = 'true'
uv sync
```

For persistent user-level configuration, prefer `system-certs = true` in `uv.toml`. Do not add
`truststore` merely to repair uv's own downloader: uv performs its own TLS verification.

## Python owns the connection

Inspect locally with `scripts/inspect-python-tls.py`. If an application or diagnostic helper must
use the native certificate store, use `truststore.SSLContext` explicitly. Only application entry
points or one-off scripts may use `truststore.inject_into_ssl()`. A reusable library must never
inject into global SSL state at import time.

Installing `truststore` as a project dependency requires a real runtime requirement. For a
diagnostic-only use, prefer an isolated tool environment or dev-only context instead of adding it
to production dependencies.

## Node owns the connection

Use the operating-system store through:

```powershell
node --use-system-ca <script>
$env:NODE_USE_SYSTEM_CA = '1'
```

## Custom CA or mTLS

Use only an IT-approved PEM bundle or client certificate. Keep private keys and tokens outside the
repository. Record the certificate source and scope without copying secret material into logs.

Never use insecure-host flags, disable TLS verification, disable certificate revocation checks, or
install an unverified certificate as a workaround.
