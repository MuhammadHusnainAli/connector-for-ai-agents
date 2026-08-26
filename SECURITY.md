# Security Policy

## Supported versions

Fixes land on the latest release. Older versions are not patched.

| Version | Supported |
| ------- | --------- |
| 0.1.x   | ✅        |

## Reporting a vulnerability

Report privately — please don't open a public issue for a security problem.

- **Preferred:** [open a private advisory](https://github.com/MuhammadHusnainAli/connector-for-ai-agents/security/advisories/new)
- **Email:** muhammad.husnain.ali.738@gmail.com

Tell us what you can reproduce: affected version, what an attacker gains, and
the steps or a proof of concept. You'll get an acknowledgement within 72 hours
and an assessment within 7 days. If we agree it's a vulnerability, we'll agree a
disclosure date with you and credit you in the advisory unless you'd rather stay
anonymous.

## What this package does and does not protect

Read this before filing — the boundary is deliberate and documented.

**In scope:** the connector definitions, the auth flows (token exchange,
refresh, request signing), request building and interpolation, the proxy client,
and the CLI.

**Out of scope by design:** this package does **not** store, encrypt, or manage
secrets. `connect()` returns a plain `Connection` object and hands it to you;
where it lives, how it is encrypted, and who may read it are your
application's decisions. Reports that amount to "credentials are readable in the
`Connection` object" describe the intended contract, not a flaw.

Also out of scope: vulnerabilities in the third-party APIs the catalogue points
at, and the correctness of a provider's own TLS or auth implementation.

## Handling credentials safely

- **Never commit connection files.** They hold live credentials. `connectors
  connect -o FILE` writes them `0600` (owner read/write only), but a `0600` file
  in a repository is still a leaked credential.
- **The CLI hides secrets by default.** `connect`, `verify`, `refresh` and
  `request --dry-run` redact credentials, authorization headers, and
  key-bearing query parameters when printing to the terminal. `--show-secrets`
  prints them; use it only when you mean to, and remember your shell history and
  terminal scrollback keep whatever it prints.
- **Prefer `-o FILE` to piping.** Writing the connection to a file keeps it out
  of logs and scrollback.
- **Credentials passed as CLI arguments are visible to other processes** on the
  same host (via `/proc` and `ps`) and are recorded in shell history. For
  anything but local experimentation, drive the library from your own code
  rather than passing `-c apiKey=...` on a command line.
- **Rotate anything you have echoed**, pasted into an issue, or committed.

## Known cryptographic notes

`SIGNATURE` auth (WS-Security UsernameToken, used by Emarsys) computes
`base64(sha1_hex(nonce + created + password))`. SHA-1 is mandated by the
WS-Security UsernameToken profile and by the providers that accept these tokens;
substituting a stronger hash would simply fail to authenticate. The call is
marked `usedforsecurity=False`, which both documents that the algorithm is the
protocol's choice rather than ours and keeps it working on FIPS-restricted
builds. The password itself is never transmitted, the nonce comes from
`secrets`, and the resulting token is short-lived.

Static analysis flags this call as weak hashing. That finding is accurate about
SHA-1 and inapplicable as a fix: the algorithm is fixed by the remote protocol.

## Dependencies

Runtime dependencies are `httpx`, `PyYAML`, `PyJWT` and `cryptography`.
Dependabot watches them weekly, and CI runs the test suite on every push and
pull request against Python 3.10 through 3.13.
