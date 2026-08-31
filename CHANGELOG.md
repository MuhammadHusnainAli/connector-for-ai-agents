# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] — 2026-08-27

The catalogue told you how to *connect* to 1,586 APIs. This release adds the
next layer: what each connector can actually **do**, and which of those things a
particular credential is allowed to do.

### Added

- **A tool layer.** 5,126 tools across 279 packs, covering 291 connectors. Each tool
  is a named capability — `send_email_with_file_attachments`, `create_deal`,
  `merge_pull_request` — with a description a model can act on, typed inputs, a
  described output, and the OAuth scopes the provider demands for it.
  `manager.list_tools()`, `get_tool()`, `describe_tools()`, `search_tools()` and
  `tool_specs(format="anthropic" | "openai" | "mcp")`.
- **Scope-aware enablement.** `manager.check_tools(connection)` compares each
  tool's required scopes against the grant recorded on the connection and
  returns a `ToolReport` splitting them into enabled, disabled — with the
  missing scopes named — and unknown. `report.missing_scopes()` lists every
  scope that would unlock at least one more tool. This is the answer to "my
  client id and secret only have these permissions, so which tools do I really
  have".
- **Live scope discovery.** `manager.discover_scopes(connection)` asks the
  provider itself: it reads the access token's own claims where the provider
  issues a JWT (Microsoft, Salesforce — no request at all), calls a token-info
  endpoint where there is one (HubSpot, Google, SendGrid), or reads a response
  header (GitHub, Slack). `check_tools_live()` judges the report on that real
  grant. Where a connector declares neither, it falls back to the connection's
  own record, so there is always an answer — `ScopeDiscovery.known` separates
  *no scopes* from *could not tell*.
- **Running tools.** `manager.call_tool(connection, name, arguments)` validates
  the arguments against the tool's input schema, binds them into the request,
  sends it authenticated, and returns a parsed `ToolResult`. A tool the recorded
  grant rules out raises `ToolPermissionError` before anything is sent; an
  unknown grant never blocks. `prepare_tool_request()` returns the resolved
  request without sending it.
- **Tool packs as data**, in `data/tools/<auth-mode>/<connector-id>.yaml` —
  the same one-file-per-auth-mode sharding the connector catalogue uses. Adding
  a connector's tools is one file, no code change. A pack declares its provider's
  scope-comparison rules (`case_insensitive`, `strip_prefixes`, `implies`), how
  to discover a live credential's scopes, and `applies_to` for connectors that
  share an API surface — which is how one Microsoft Graph pack serves both
  `microsoft` and `outlook`.
- **Grouped scope grants.** A pack can set `scope_rules.expand_groups`, for
  providers that name several objects in one scope: Accelo grants
  `read(companies,contacts)` as a single string, which a plain comparison reads
  as a scope nobody holds. Scope splitting is parenthesis-aware for the same
  reason, so the grant survives to be expanded rather than being cut in half.
- **Two template constructs** that cover the shapes providers want: `$map` turns
  a list of plain values into a list of provider-shaped objects (Graph's
  `toRecipients`, attachment arrays), and `$mime` assembles a base64url RFC 2822
  message from ordinary to/subject/body/attachments fields, so Gmail's send API
  takes the same arguments as everything else. `encoding: form` sends
  form-encoded bodies with bracket notation, for Stripe and Twilio. `$when`
  makes a nested object conditional on the argument that justifies it, so a
  partial update cannot send `{"contentType": "HTML"}` with no content and wipe
  the field it was only meant to leave alone; an object that wanted content and
  got none is dropped rather than sent as `{}`.
- **CLI:** `connectors tools <id>`, `connectors tool <id> <name>`,
  `connectors check-tools <conn.json> [--live]` and `connectors call <conn.json>
  <name> -a key=value -a key:=<json>`. `connectors stats` now reports tool
  counts. `call --dry-run` prints the prepared request with secrets redacted.
- **`scripts/scaffold_tools.py`**, which writes a tool pack skeleton in the right
  folder (`--new`), lints every pack (`--check`, run in CI) and reports coverage
  (`--list`).
- **Packs generated from providers' own OpenAPI specifications.**
  `scripts/generate_from_openapi.py` turns a published spec into a tool pack --
  real paths, methods, parameters and descriptions, all lifted from the spec and
  nothing inferred; operations the spec does not describe well enough to build a
  usable tool from are skipped. `scripts/discover_openapi.py` finds those specs,
  either in the apis.guru directory or at the conventional locations on a
  provider's own host, and writes a plan the generator consumes in bulk. Each
  generated file records the spec URL in `generated_from` and sets
  `generated: true`, and is held to exactly the same lint and test contract as a
  hand-authored one.
- **[TOOLS.md](TOOLS.md)** — every connector and the tools it exposes, generated
  by `scripts/scaffold_tools.py --catalogue` and checked by `--check` so it
  cannot go stale.
- **Model Context Protocol tools for MCP connectors** — `list_server_tools` and
  `call_server_tool`, which are `tools/list` and `tools/call` from the MCP
  specification. Unlike a REST provider's endpoints these are defined by the
  protocol, so they hold for any server that speaks it. Where the server's
  address is a connection-config value (a generic MCP server) or shares an
  origin with the connector's declared OAuth endpoints, it is resolved from
  that rather than guessed.
- **Raw authenticated request tools on every connector with a base url** —
  `get_from_api`, `post_to_api`, `put_to_api`, `patch_api`, `delete_from_api`.
  They take a path and an optional query or body, apply the connection's
  credentials, and make no claim about which endpoints exist, so no connector in
  the catalogue is undrivable while its pack is still unwritten. A named tool
  always wins where one exists; these never shadow a pack. A connector with no
  address of its own takes a full url instead, so every one of the 1,586
  connectors now exposes tools.
- **A generated `check_connection` tool** for every connector with no
  hand-authored pack but a verification endpoint in its catalogue entry — 595 of
  them, so 886 of the 1,586 connectors now have at least one tool that is known
  to be real. It is synthesised at runtime from in-repo data, marked
  `generated`, and never shadows a hand-authored pack. A connector whose entry
  declares no such endpoint gets no tool: nothing is inferred about a provider's
  API. `has_authored_tools()` is the stricter check, and `tool_stats()` reports
  the two tiers separately.
- **[docs/tools.md](docs/tools.md)**, the tool pack format field by field.

### Changed

- `ConnectorManager` and `AsyncConnectorManager` take an optional `tools=`
  registry alongside `registry=`. Both default as before, so existing code is
  unaffected.
- The test suite grows from 109 to 229 tests. Every bundled tool is checked: it
  must sit in the folder matching its connector's auth mode, build a request
  that resolves with no leftover `${…}`, read only arguments it declares, use
  every argument it declares, keep `read_only` and `destructive` consistent with
  its HTTP verb, and serialise to a valid tool definition in all three LLM
  formats.

### Notes

- The other 1,517 connectors are unchanged — they still connect, refresh and
  make authenticated requests. They simply have no tool pack yet; adding one is
  a single YAML file, and `scripts/scaffold_tools.py --new <id>` writes the
  skeleton in the right place.
- README's coverage table is generated from the bundled packs by
  `scripts/scaffold_tools.py --readme`, and `--check` fails CI when it is stale,
  so it cannot drift as packs are added.
- Where a provider configures permissions on the app rather than carrying them
  on the token (Notion, Asana, Intercom, ClickUp, Box, Calendly), the packs
  declare no scopes and every tool reports as enabled. That is the honest
  answer: a 403 from those providers means the app's configuration is too
  narrow, not that a scope is missing from the grant.

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
