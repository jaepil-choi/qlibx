# TLS and system trust stores

1. Preserve the exact certificate or revocation error.
2. Prefer the operating system trust store when enterprise root certificates are installed there.
3. For `uv`, prefer its supported system-certificate mode, such as `--system-certs` or
   `UV_SYSTEM_CERTS=true`, when available in the installed version.
4. For Python application tooling that does not use the system store, use `truststore` locally in
   the application or helper environment. A reusable library must not inject trust globally on import.
5. For Node-based helpers, retry with `node --use-system-ca`.
6. Record the successful command and scope of the workaround.

Never use insecure flags, disable TLS verification, disable revocation checking, or install
unverified certificates as a workaround.
