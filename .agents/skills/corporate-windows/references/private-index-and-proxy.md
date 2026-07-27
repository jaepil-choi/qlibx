# Private indexes and proxies

1. Separate DNS, proxy, certificate, authentication, authorization, and package-not-found failures.
2. Keep index URLs free of embedded credentials in committed files.
3. Supply named-index credentials through `UV_INDEX_<NAME>_USERNAME` and
   `UV_INDEX_<NAME>_PASSWORD`, an approved credential store, or the configured keyring provider.
4. Record only whether proxy and credential inputs are present; never log their values.
5. Preserve uv's default `first-index` strategy unless the repository explicitly documents another
   policy. Do not use `unsafe-best-match` as a generic authentication workaround.
6. Use `authenticate = "always"` only when the index's unauthenticated behavior prevents uv from
   discovering credentials and the index policy is known.
7. Treat 401, 403, and 404 separately. Do not add broad ignored error codes until the index's
   documented behavior is verified.
8. Never use `allow-insecure-host` to bypass a corporate certificate error.
9. Prevent dependency confusion: pin internal packages to an explicit named index when repository
   policy requires that provenance.

If the private index is unreachable, report the host, status class, certificate mode, and attempted
credential source without exposing usernames, passwords, tokens, or proxy URLs containing secrets.
