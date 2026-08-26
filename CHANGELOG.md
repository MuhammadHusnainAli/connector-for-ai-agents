# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.3] — 2026-08-26

### Security

- **The CLI no longer prints credentials by default.** `connect`, `verify`,
  `refresh` and `request --dry-run` redact credential values, authorization
  headers, and key-bearing query parameters when writing to the terminal, so
  secrets stop landing in scrollback, CI logs, and pasted output. Pass
  `--show-secrets` for the previous behaviour.
- **Connection files are written `0600`.** `-o FILE` now creates the file
  owner-read/write only and tightens an existing file's mode before writing, so
  a stored connection is no longer world-readable. The file still contains live
  credentials by necessity — the note printed alongside it says so.
- **WS-Security signing documented and marked.** The SHA-1 digest in
  `SIGNATURE` auth is mandated by the WS-Security UsernameToken profile the
  providers implement, so it is unchanged on the wire; it is now marked
  `usedforsecurity=False`, which records that the algorithm is the protocol's
  choice and lets it run on FIPS-restricted builds.
- **CI runs with least privilege.** The workflow now declares
  `permissions: contents: read`, dropping every other scope from its token.

### Added

- `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, and this changelog.
- `--show-secrets` on `connect`, `verify`, `refresh` and `request`.
- `scripts/split_connectors.py`, which regroups the catalogue into one file per
  auth mode and, with `--check`, fails CI when an entry sits in the wrong file.
- `registry.CONNECTORS_DIR` and `ConnectorRegistry.connectors_path`.
- Python 3.14 in the CI matrix, alongside the classifier that already claimed it.

### Changed

- **The connector catalogue is split by auth mode.** The single 840 KB
  `data/connectors.yaml` is now `data/connectors/api-key.yaml`,
  `oauth2.yaml`, `basic.yaml` and 14 more — one file per auth mode, largest
  404 KB. Adding a connector no longer means a diff against a 35,000-line file,
  and two connectors in different modes stop colliding. The registry loads and
  merges every `*.yaml` under the directory, so this is layout, not API: all
  1,586 connectors resolve byte-for-byte identically to 0.1.2.
- Alias resolution follows chains and no longer depends on the order entries
  appear on disk, which it had to once a target could live in another file.
- Duplicate connector ids across files are rejected rather than resolved by
  filename order.
- `auth_mode` is never redacted — it describes the scheme, not a secret.

### Deprecated

- `ConnectorRegistry.connectors_file` is now a read-only alias of
  `connectors_path`, which may be a directory. Passing `connectors_file=` a
  single YAML file still works, so a custom catalogue needs no change.

## [0.1.2] — 2026-08-25

### Added

- **629 connectors, taking the catalogue from 957 to 1586.** Each definition was
  transcribed from a maintained open-source implementation of that provider's
  API — [Pipedream](https://github.com/PipedreamHQ/pipedream) (347),
  [ActivePieces](https://github.com/activepieces/activepieces) (234),
  [n8n](https://github.com/n8n-io/n8n) (27) and new upstream
  [Nango](https://github.com/NangoHQ/nango) providers (21) — so the base url,
  credential placement and verification endpoint come from working code.
- Every base url was then called unauthenticated: 367 answered `401`/`403`, 51
  answered as an API, 50 are per-tenant urls that cannot be called without a
  tenant, 147 resolved without a confirmable unauthenticated endpoint, and 14
  are copied verbatim from the upstream Nango catalogue. A further 431
  candidates were dropped rather than shipped unverified, including 55 whose
  base url turned out to be a documentation page and 12 duplicates of existing
  connectors.
- 629 logos in the existing 62×62 SVG format, so all 1586 connectors ship one
  (1591 icon files).
- `docs/added-connectors.md`, recording the base url, credential placement,
  verification endpoint and check result behind every addition.

### Changed

- No existing connector definition was modified or removed. No API changes:
  `ConnectorManager`, `AsyncConnectorManager` and the `connectors` CLI behave
  exactly as in 0.1.1, with more connectors in the registry.

## [0.1.1] — 2026-08-25

### Added

- CI workflow across Python 3.10–3.13, and a PyPI publish workflow using trusted
  publishing, triggered by publishing a GitHub Release.
- Weekly Dependabot checks for GitHub Actions and Python dependencies.

## [0.1.0]

### Added

- Initial release: 957 connectors with their logos, the auth fields each one
  needs, and the logic to turn filled-in fields into a verified connection.
- Sync and async managers over one implementation, auth strategies for
  `API_KEY`, `BASIC`, `OAUTH2`, `OAUTH2_CC`, `TWO_STEP`, `JWT`, `SIGNATURE`,
  `TBA` and `OAUTH1`, request proxying with interpolation, pagination and retry
  metadata, and a `connectors` CLI.

[0.1.3]: https://github.com/MuhammadHusnainAli/connector-for-ai-agents/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/MuhammadHusnainAli/connector-for-ai-agents/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/MuhammadHusnainAli/connector-for-ai-agents/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/MuhammadHusnainAli/connector-for-ai-agents/releases/tag/v0.1.0
