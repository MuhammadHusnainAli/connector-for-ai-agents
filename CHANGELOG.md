# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **47 more connectors: Azure, and the vector, graph and cloud databases.** The
  catalogue goes from 1,586 to 1,633; 1,234 now connect end to end from
  user-supplied values alone. Every base url and verification endpoint was
  called for real, unauthenticated, and
  [docs/azure-and-vector-connectors.md](docs/azure-and-vector-connectors.md)
  records what each check returned.
  - **Azure data planes (17)** — `azure-ai-search`, `azure-cosmos-db`,
    `azure-key-vault`, `azure-app-configuration`, `azure-monitor-logs`,
    `azure-data-explorer`, `azure-service-bus`, `azure-ai-services`,
    `azure-ai-language`, `azure-document-intelligence`, `azure-content-safety`,
    `azure-ai-translator`, `azure-ai-speech`, `azure-maps`, and
    `azure-storage-queue`/`-table`/`-file` alongside the existing
    `azure-blob-storage`. Each carries the Entra scope its own service demands,
    which is the detail that most often breaks an Azure integration; Cosmos DB
    also gets the `type=aad&ver=1.0&sig=` authorization form and the
    `x-ms-version`/`x-ms-date` headers it requires instead of a plain bearer.
  - **Azure control plane (11)** — `azure-resource-manager` plus one entry per
    resource provider: `azure-virtual-machines`, `azure-postgresql`,
    `azure-mysql`, `azure-sql-database`, `azure-aks`, `azure-app-service`,
    `azure-container-registry`, `azure-cosmos-db-accounts`,
    `azure-ai-search-management` and `azure-storage-accounts`. They share
    `management.azure.com` and differ in the verification endpoint, so
    `connect()` proves access to *that* provider rather than to the
    subscription in general. api-versions come from the current `stable`
    folders of `Azure/azure-rest-api-specs`.
  - **Vector and search databases (12)** — `qdrant`, `qdrant-cloud`,
    `opensearch`, `elasticsearch`, `pinecone`, `chroma`, `milvus`,
    `zilliz-cloud`, `typesense`, `marqo`, `turbopuffer` and `upstash-vector`.
  - **Graph and operational databases (7)** — `neo4j` (the HTTP Query API),
    `neo4j-aura`, `mongodb-atlas`, `redis-cloud`, `upstash`,
    `couchbase-capella` and `singlestore`.

- **Tool packs for eight more connectors, 1,052 tools in all**, every one written
  against the provider's own reference. Seven of them had nothing but the raw
  `get_from_api`/`post_to_api` fallbacks; the eighth had a generated pack:
  - **`adp-workforce-now` (267), `adp-workforce-now-next-gen` (199),
    `adp-run` (84) and `adp-lyric` (65)** — one pack per ADP product, built from
    ADP's own API Explorer and the OpenAPI document behind each API there, so
    each carries the endpoints ADP publishes *for that product* rather than a
    shared guess. Reads are OData collections; writes are ADP events, with
    `post_event` and `get_event_metadata` reaching any event name and a typed
    tool for every event ADP documents.
  - **`adyen` (339)** — Management, Balance Platform Configuration, Legal Entity
    Management, Transfers, Disputes, Balance Control, Checkout, Recurring,
    Payout and Data Protection. Adyen serves each of those from a different
    host, so every tool pins its own with `base_url_override` and works whatever
    `resource` the connection was configured with. The API-credential roles
    Adyen documents per call are recorded in each tool's `notes`. Adyen has more
    APIs than those ten, and writing a pack replaces a connector's raw request
    tools, so the pack keeps five of its own (`get_from_adyen_api` and friends)
    that follow the connection's `resource` for the services it does not name.
  - **`affinity` (58)** — the whole Affinity v1 CRM: lists and list entries,
    fields, field values and their change history, persons, organizations,
    opportunities, interactions, relationship strengths, notes, entity files,
    reminders and webhooks.
  - **`adyntel` (32)** — replaces the generated pack with full coverage: Meta,
    Google, LinkedIn and TikTok ad scrapes, keyword search, domain keywords,
    traffic estimates, tracking pixels, recurring tracking jobs and reseller
    user administration.
  - **`adrapid` (8)** — banner rendering end to end, plus the template, media
    and font library the overrides draw on.

- **Tool packs for eleven Azure connectors, and Entra ID siblings for the five
  key-based ones: 468 tools in all.** Every one of these connectors previously
  shipped only the raw `get_from_api`/`post_to_api` fallbacks, which tell an
  agent nothing about what the service can do. Each pack is written against
  Microsoft's own REST reference, and every tool carries an optional
  `api_version` argument defaulting to the version this catalogue pins for that
  connector — Azure makes `api-version` mandatory on every call and versions
  each resource provider separately, so a service pinned elsewhere is a
  per-call override rather than a fork of the pack.
  - **`azure-ai-search` (41)** — the search service's own data plane: indexes,
    documents, indexers, data sources, skillsets, synonym maps and aliases.
    `search_documents` covers all four retrieval styles in one tool — keyword,
    OData filter, vector and semantic — because on this API a hybrid query is
    simply several of them in the same request.
  - **`azure-container-registry` (49)** — registries, admin and scoped
    credentials, geo-replication, webhooks, scope maps, tokens, cache rules and
    ACR Tasks with their runs and logs. Tasks version separately from the
    registry resource, so those tools default to their own api-version.
  - **`azure-app-service` (42)** — web apps, function apps, slots and swaps,
    App Service plans, app settings and connection strings, runtime and logging
    configuration, deployments, source control, publish profiles and function
    keys.
  - **`azure-ai-speech` (38)** — batch transcription, Custom Speech models,
    projects, datasets, endpoints and evaluations, plus batch and real-time
    synthesis. `list_voices` and `synthesize_speech` override the base url to
    the region's `*.tts.speech.microsoft.com` host, which is where Microsoft
    puts synthesis.
  - **`azure-aks` (37)** — clusters, node pools, upgrades, maintenance windows
    and snapshots, with `list_cluster_user_credentials` for the kubeconfig and
    `run_command` for reaching a private cluster's Kubernetes API from the
    management plane.
  - **`azure-ai-language` (31)** — sentiment, key phrases, entities, PII,
    entity linking and language detection as one tool each rather than one
    `kind` argument, plus the asynchronous job APIs, conversational language
    understanding, custom question answering, and the authoring APIs behind
    them. Four families, four api-versions.
  - **`azure-blob-storage` (26)** — containers, blobs, blocks, snapshots, tags,
    tiers and `get_user_delegation_key` for signing SAS tokens from the Entra
    identity rather than the account key.
  - **`azure-ai-search-management` (23)** — the Microsoft.Search control plane:
    services, scaling, admin and query keys, quota, and private link. Its
    `list_admin_keys` is what supplies the key the `azure-ai-search` data-plane
    connector authenticates with.
  - **`azure-ai-services` (21)** — the multi-service resource, so one pack
    across five path prefixes: image analysis and OCR, content safety with its
    blocklists, document intelligence, Language and Translator.
  - **`azure-app-configuration` (15)** — key-values with their labels, locks,
    revisions and snapshots, plus feature flags, which are key-values under a
    reserved prefix rather than a resource of their own.
  - **`azure-ai-translator` (7)** — the complete Translator Text v3.0 surface:
    translate, detect, transliterate, break sentence, dictionary lookup and
    examples, and the supported-language list.

- **Five Entra ID connectors for the Azure AI services (138 tools).**
  `azure-ai-language-entra`, `azure-ai-search-entra`, `azure-ai-services-entra`,
  `azure-ai-speech-entra` and `azure-ai-translator-entra` are the same
  endpoints, the same tools and the same base urls as their key-based
  namesakes (taking the catalogue to 1,638 connectors), authenticating as a
  service principal (client credentials against
  Microsoft Entra ID) instead of with `Ocp-Apim-Subscription-Key`. A connector
  carries one auth mode, so supporting both means two entries — the pattern the
  catalogue already used for `azure-ai-search` and `azure-ai-search-management`.
  Each carries the scope its own service demands (`search.azure.com/.default`
  for Search, `cognitiveservices.azure.com/.default` for the rest), and the
  Translator sibling additionally carries the resource's ARM id, which
  Translator requires as `Ocp-Apim-ResourceId` when the caller presents a token
  rather than a key. These are the only way in on a resource with local
  authentication disabled, and each pack's header records the Azure RBAC role
  the principal needs.

### Changed

- **`weaviate` is categorised `search`, not `other`**, so it lists alongside the
  vector databases added here. It is the only existing definition this release
  changes.

- **A tool path may now be a single whole-path placeholder.** `${path}` is the
  documented shape for a raw request tool — the slot holds a whole path, so its
  slashes are structural — but the pack lint rejected it for having no leading
  `/`, which is why no written pack could carry an escape hatch. The rule now
  accepts a path that is exactly one placeholder, and still rejects a typo like
  `v1/users`.

### Fixed

- **`MMM` in a date template rendered as garbage.** The moment-style token
  table rewrote `MM` before `MMM`, so `MMM` became `%mM` and a template asking
  for "Sep" produced "09M". Tokens are now ordered longest-first, `ddd` and
  `MMM` are supported, and both use fixed English abbreviations rather than
  strftime's locale-dependent `%a`/`%b` -- a provider that wants an RFC 1123
  date (Azure's `x-ms-date`) rejects "lun." from a French host. This is what
  lets `azure-cosmos-db` generate the date header Cosmos requires.

- **`proxy.body` is now applied.** Three connectors (Adyntel, Mandrill, Sage)
  authenticate from a field inside the JSON body rather than a header, and the
  catalogue has always recorded that as `proxy.body` — but nothing merged it
  into the outgoing request, so those credentials had to be passed as tool
  arguments. `RequestBuilder` now merges the resolved template under the
  caller's body, nested objects included. A request with no JSON body of its own
  is left alone, so this cannot turn a GET into a request with content, and a
  template the connection cannot fill in is dropped rather than sent as a
  literal `${…}`.

## [0.2.0] — 2026-09-01

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

[0.2.0]: https://github.com/MuhammadHusnainAli/connector-for-ai-agents/compare/v0.1.3...v0.2.0
[0.1.3]: https://github.com/MuhammadHusnainAli/connector-for-ai-agents/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/MuhammadHusnainAli/connector-for-ai-agents/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/MuhammadHusnainAli/connector-for-ai-agents/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/MuhammadHusnainAli/connector-for-ai-agents/releases/tag/v0.1.0
