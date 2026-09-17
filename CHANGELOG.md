# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.3] — 2026-09-18

### Changed

- **The bundled catalogue is JSON, and the package starts 84x faster.**
  `ConnectorManager()` took 13.6 seconds: it parsed all 406 tool packs --
  15 MB of YAML, 12,949 tools -- to answer a question about one connector,
  with the pure-Python YAML loader, on every construction, and nothing cached
  the result. That overruns AWS Lambda's 10-second init cap and rules out any
  runtime that builds a fresh process per request.

  The layout is unchanged -- `data/connectors/<auth-mode>.json` and
  `data/tools/<auth-mode>/<connector-id>.json` -- with `data/tools/index.json`
  beside the packs, mapping every connector id, `applies_to` aliases included,
  to the one file that serves it. `ToolRegistry` reads the index at startup and
  parses a pack the first time something asks for it, so a lookup opens one
  small file instead of all 406.

      import + ConnectorManager()     13.63s -> 0.16s
      list_tools() for one connector           0.5ms, cached thereafter
      the test suite                    795s -> 5s

  No API changed. Every one of the 12,949 tool specs was diffed field by field,
  order included, against what the YAML produced.

- **PyYAML is no longer a runtime dependency.** Nothing in the package reads
  YAML, so it moves to the `dev` extra, where `generate_from_openapi.py` still
  needs it for provider specs served as YAML. Installs are one dependency
  lighter.

- **The scripts read and write JSON**: `split_connectors.py`,
  `scaffold_tools.py --new`, and both spec generators.

### Added

- `scripts/build_index.py` rebuilds `data/tools/index.json`; `--check` fails CI
  when a pack was added or renamed without it, which would otherwise make that
  pack invisible to the registry.
- `scripts/verify_wheel.py` fails a build whose wheel lost the catalogue or its
  index, or still carries YAML -- caught before PyPI rather than after.

### Fixed

- Three Bandit B506 findings, which were `yaml.load` calls it would not accept
  as safe. There is no YAML parser in the package any more.

### Removed

- The YAML source of the catalogue, and with it 9,088 lines of comments
  recording each pack's provenance and limits. JSON holds no comments. Those
  lines remain in git history, and a pack's origin is still carried by its
  `docs_url`, `generated` and `generated_from` fields.

## [0.2.2] — 2026-09-17

### Changed

- **The WSSE password digest is SHA-256.** The WS-Security UsernameToken
  profile specifies SHA-1, and Emarsys -- the only connector on the
  `SIGNATURE` auth mode -- implements the profile as written, so this works
  only against a provider that accepts SHA-256. A password hash should not
  rest on a broken algorithm; the docstring records the departure.

### Fixed

- **The spec-fetching scripts no longer go through `urllib`.**
  `discover_openapi.py`, `generate_from_openapi.py` and
  `generate_from_google_discovery.py` opened whatever scheme they were handed,
  so a url from `--spec` or argv could read a local file instead of
  downloading a document. They use httpx, which speaks http and https and
  nothing else. `generate_from_google_discovery.py` keeps its explicit
  local-path branch.
- **The pack linter's placeholder check parses the `docs_url` host** instead of
  testing it with a substring, which let `example.com.evil.net` read as the
  scaffold placeholder.
- **README.md and TOOLS.md carry the real counts again** -- 19,966 tools,
  11,398 hand-authored across 259 packs. `altoviz`, `alai` and `akkio` became
  hand-authored without the coverage block being rebuilt, so
  `scripts/scaffold_tools.py --check` and two tests were failing.

### Security

- Bandit reports nothing at all, down from roughly 520 findings. The test
  suite is out of its scan -- `assert` is pytest's assertion model, so B101
  fired on all 457 of them -- and B105 is skipped, since it matches dictionary
  keys and this package's whole subject is credential schemas.

## [0.2.1] — 2026-09-17

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

- **Tool packs for nineteen more connectors, 1,145 tools in all**, every one
  written against the provider's own specification or reference. Fifteen
  previously shipped only the raw request tools or `check_connection`; the other
  four (`agentcard`, `agentline`, `agentset`, `ahrefs`) replace generated packs
  that held nine to twelve tools each:
  - **`ahrefs` (151)** — every operation in Ahrefs' API v3 OpenAPI description:
    Site Explorer, Keywords Explorer, SERP overview, Site Audit, Rank Tracker,
    Brand Radar (both the query-string and POST forms), Web Analytics, Search
    Console, social publishing, project management, batch analysis and the free
    public endpoints. Each `select` and `where` argument lists the columns that
    endpoint accepts, marking the ones that cost extra units, and every tool
    says whether it is free, fixed-cost or metered.
  - **`airfocus` (132)** — workspaces, items, fields, statuses and presets,
    links, relations, comments, attachments, workspace groups, templates,
    profile and team administration, from Airfocus' OpenAPI description, with
    the API-key scope Airfocus declares on each operation. Rich text is sent
    through Airfocus' markdown media type so descriptions are plain markdown.
  - **`agiliron` (128)** — CRM, products, inventory, price books, channels,
    quotes, sales and purchase orders, shipping, receiving, returns, work
    orders, notes, attachments and the Bulk-* batch endpoints, from the
    per-resource OpenAPI definitions in Agiliron's API Center.
  - **`aircall` (93) and `aircall-basic` (90)** — users (on v2 ahead of the v1
    retirement), teams, calls, conversation intelligence, trackers, dialer
    campaigns, numbers, SMS, MMS and WhatsApp in and outside the agent inbox,
    contacts, tags, webhooks, AI Voice Agent outbound calls and analytics
    exports. The Basic Auth pack leaves out the three OAuth-only integration
    endpoints.
  - **`aimfox` (69) and `aimfox-oauth` (62)** — LinkedIn accounts, campaigns
    and audiences, leads, labels, notes, conversations, templates, blacklists,
    analytics and webhooks, from Aimfox' published request collection. The API
    key pack adds the agency master-key routes; neither covers the three
    multipart voice-note and file uploads.
  - **`aiprise` (69)** — KYC and KYB sessions, user and business profiles,
    officers and related parties, documents, AML, risk-scored decisions,
    registry lookups and PDF reports, merged from the OpenAPI definitions on
    each AiPrise reference page.
  - **`agentline` (47)** — agents, phone numbers, calls with live context
    injection, SMS, the event mailbox, webhooks, voices, billing and x402
    top-ups, and API keys.
  - **`affinity-v2` (46)** — every Affinity v2 operation: companies, persons,
    opportunities, lists, list entries and field values, saved views, notes,
    emails, meetings and merges.
  - **`agencyzoom` (44)** — leads, quotes and opportunities with drivers and
    vehicles, customers, policies, email threads, pipelines and configuration
    lists. AgencyZoom's own spec refuses unauthenticated downloads, so paths come
    from two public copies of it; operations whose paths neither copy publishes
    (tasks, service tickets, files) are left out rather than guessed.
  - **`agentcard` (43)** — connect, KYC, wallet funding and withdrawals, card
    attachment, one-time cards and the conversational buy flow. The tools that
    act as a member take the member's connection token as an argument.
  - **`aidbase` (43)** — knowledge items and training, chatbots and their chats,
    ticket forms and tickets, email inboxes and emails.
  - **`air-ops` (40)** — running apps and agents, executions, knowledge base
    documents, grid exports and the AEO brand kit insights.
  - **`agentset` (28)** — namespaces, ingest jobs (with one tool per payload
    type), documents, uploads, search and hosting.
  - **`agiloft` and `agiloft-cc` (19 each)** — tables, saved searches, search,
    select, read, create, update, upsert and delete, record locks, attachments,
    action buttons, async status and choice ids, from Agiloft's REST Interface
    documentation.
  - **`aftership` (16)** — every Tracking API 2026-07 operation: trackings,
    couriers and detection, courier connections and estimated delivery dates.
  - **`agify` (6)** — age, gender and nationality prediction for one name or up
    to 100, reaching Genderize and Nationalize with the same key.

  One limitation is recorded in the `affinity-v2` header rather than worked
  around: array query arguments are sent comma-separated, and Affinity
  documents them as repeated parameters, so a multi-value `ids` or `field_ids`
  may need to be split into single-value calls.

- **Tool packs for twenty-one more connectors, 1,196 tools in all**, every one
  written against the provider's own specification or reference. All but one
  previously shipped only the generated fallbacks; `axesso-data-service`
  replaces a generated pack that double-prefixed `/amz` onto every path and so
  could not have worked:
  - **`auth0-cc` (250)** — the Auth0 Management API, from the OpenAPI 3.1
    description Auth0 publishes (472 operations): users with their roles,
    permissions, effective roles, logs, identities, sessions, refresh tokens,
    authentication methods and blocks; applications and their credentials;
    client grants; connections with their clients, keys and SCIM configuration;
    roles; organizations with members, invitations, connections and client
    grants; resource servers; actions, triggers and bindings; forms and flows;
    logs and log streams; jobs and tickets; signing and encryption keys;
    network ACLs; custom domains; the email provider and templates; attack
    protection; branding and prompts; Guardian factors; grants, sessions and
    device credentials; self-service SSO profiles; tenant settings and stats.
    Every tool carries the scope Auth0's own spec puts on it, because a
    machine-to-machine token has exactly the scopes it asked for. Paths start
    `/api/v2` since the connector's base url is only the tenant host.
  - **`autodesk` (123)** — Autodesk Platform Services, from the six OpenAPI
    files in `autodesk-platform-services/aps-sdk-openapi`: Data Management
    (hubs, projects, folders, items, versions, storage, downloads, commands),
    OSS buckets and objects with the signed S3 upload and download flows, Model
    Derivative (translation jobs, manifests, model views, properties,
    thumbnails, derivative downloads), webhooks, and the ACC account
    administration and issues APIs. Data Management speaks JSON:API, so those
    tools fill in the `{"jsonapi": {"version": "1.0"}, "data": …}` envelope and
    send `application/vnd.api+json` for you.
  - **`autotask` (120)** — the Datto Autotask PSA REST API, from the Swagger
    each zone publishes unauthenticated (2,083 paths over 240 entities).
    Tickets with their notes, charges, checklists, secondary resources,
    attachments and history; companies with contacts, locations, notes, to-dos
    and alerts; contracts with services, blocks, rates and notes; projects with
    phases, tasks and notes; time entries; configuration items and
    subscriptions; opportunities and quotes; service calls and appointments;
    products, services and billing items; resources, roles and departments.
    Generic entity tools reach the remaining 200-odd entities by name, which is
    the only sane way to cover a catalogue that size. The header explains the
    three habits that trip integrators up: reads go through `/query`, writes are
    body-only with the id *in the body*, and most entities cannot be deleted at
    all.
  - **`ayrshare` (96)** — posting, validation and analytics across the social
    networks, profiles, media, comments and messages, reviews, scheduling,
    automations and feeds, hashtags, links and generation, listening, webhooks
    and the Facebook ads surface.
  - **`axiom` (79)** — datasets and APL queries, ingest, monitors and
    notifiers, annotations, saved queries, views and virtual fields,
    dashboards, tokens, users, organizations and RBAC.
  - **`avalara` (75, also covering `avalara-sandbox`)** — AvaTax from its
    Swagger: transactions with the whole lifecycle (commit, void, adjust,
    refund, settle, verify, lock, audit), address validation and tax rates,
    companies, nexus and locations, items, tax codes and tax rules, customers
    and exemption certificates, reference data, batches, reports, users and
    settings. The header leads with the distinction that decides everything
    downstream — a SalesOrder is a quote, a SalesInvoice is a document.
  - **`aws-iam` (69)** — IAM's query protocol: users, groups, roles, policies,
    instance profiles, access keys, MFA devices, SAML and OIDC providers,
    server certificates, account aliases and password policy. Reads are `GET /`
    with `Action` and `Version`; writes are `POST /` with a form body, which is
    both AWS's recommendation and what keeps a mutating call from looking like
    a read.
  - **`auvik` (59)** — network monitoring from Auvik's own OpenAPI
    descriptions, v1 and the v2 beta: device, interface, network and component
    inventory, extended and lifecycle detail, warranty, configuration backups,
    entity notes and audits, alerts (and the API's single write, dismissing
    one), device, interface, component, service and OID statistics, SNMP poller
    settings and history, billing usage, and the SaaS Management reads.
  - **`avoma` (54)** — meetings with their insights, segments and sentiments,
    transcripts, recordings, notes and snippets, dialer calls, smart and custom
    categories, note templates, meeting types and outcomes, users, scorecard
    templates and evaluations, engagement metrics and summaries, the revenue
    intelligence timeline, and webhook subscriptions with their signing secret.
  - **`aws-inspector2` (50)** — findings, coverage, accounts and organization
    configuration, filters, reports, CIS scans, code security and tags.
  - **`autosana` (41)** — AI end-to-end testing: suites and flows, labels, runs
    with device selection and polling, hooks, and environment variables.
  - **`avanan` (36)** — the Check Point Harmony Email & Collaboration Smart
    API, from Check Point's own reference guide: entity search and actions,
    security events and actions, task polling, entity download, and the
    anti-phishing, spam, anomaly, click-time protection, anti-malware,
    URL-reputation and DLP exception surfaces.
  - **`aws` (28)** — the Cognito user-pool JSON-RPC surface a signed-in user
    can reach with their own access token: profile reads and updates, password
    and MFA management, software token and WebAuthn enrolment, devices and
    global sign-out. The `Admin*` operations are deliberately absent — they
    need pool-owner credentials, not this connector's user token.
  - **`autobound` (25)** — the Personalized Content API and the Signal API,
    which live on two hosts and share one key: content and insight generation,
    company and contact enrichment and search, the signal type registry, buyer
    intent topics, searches and bulk exports, and the free account, credit and
    log reads. Credit costs are noted per tool because Autobound bills per
    result, not per call.
  - **`awardco` (23)** — users, recognition with and without a program,
    external recognition, the social and custom feeds, and all three
    generations of the reporting API, including the asynchronous v2 task flow.
  - **`availity` (20)** — the healthcare clearinghouse transactions: 270/271
    eligibility, 276/277 claim status, 278 authorizations and referrals, and
    837 predeterminations and patient cost estimates, plus the payer list and
    the per-payer validation rules that say what each plan actually requires.
  - **`autom` (16)** — Google, Bing and Brave search scraping with the news,
    images, videos, shopping, maps, jobs and autocomplete variants, the free
    Finder lookups for country, language and location codes, and the usage and
    platform health reads. Credit costs are noted per tool.
  - **`aws-scim` (15)** — SCIM 2.0 users and groups for IAM Identity Center.
    Fully usable today, because it authenticates with a bearer token rather
    than SigV4.
  - **`axesso-data-service` (11)** — Amazon product, offer, seller, review
    profile, best-seller and deals data, read from Axesso's API Management
    portal rather than its stale published Swagger. Two tools reach the
    neighbouring stock-quantity and account-quota APIs on the same host.
  - **`aws-multi-service` (4)** — one tool per AWS wire protocol (query, JSON
    with `X-Amz-Target`, and REST-JSON), since the service is a connection
    setting and the operations therefore cannot be enumerated.
  - **`avian` (2)** — an OpenAI-compatible inference endpoint: chat completions
    and the model catalogue is its entire published surface.

  Three of these packs cannot authenticate yet, and each says so in its header
  rather than pretending otherwise: `aws-iam`, `aws-inspector2` and
  `aws-multi-service` need SigV4 signing, which `interpolation.py` does not
  implement. `aws-sigv4` keeps only its raw tools on purpose — it is a generic
  signer whose service is chosen per integration, so there is no fixed API to
  describe.

- **Tool packs for eighteen more connectors, 863 tools in all**, every one
  written against the provider's own reference or published specification. All
  eighteen previously shipped only the generated fallbacks — the raw
  `get_from_api`/`post_to_api` tools, plus `check_connection` where the
  catalogue entry declared a verification endpoint:
  - **`basecamp` (87)** — the Basecamp 4 surface, from the OpenAPI spec
    Basecamp publishes alongside its SDK: projects and their dock, people and
    project access, to-do sets, lists, groups and to-dos with completion,
    message boards and messages, comments on any recording, campfires,
    schedules, docs and files, the card table with columns, cards, moves and
    steps, automatic check-ins, search, recordings, webhooks and templates.
    The header leads with the thing that makes or breaks a Basecamp
    integration: every tool has its own id, and `get_project`'s `dock` array
    is the only place to find it.
  - **`bexio` (81)** — contacts, relations, groups and branches, then the
    whole sales chain: quotes, orders, deliveries and invoices with their
    payments and dunning reminders, plus the per-document position endpoints
    for article, custom, text, subtotal and discount rows. The lifecycle verbs
    carry the weight — issuing gives a document its number, `send_*` emails
    the customer while `mark_*_as_sent` only records it, and cancelling is not
    the same as reverting an issue. Scopes are annotated per tool, with a
    `scope_rules` entry so a write scope satisfies the matching read.
  - **`beebole` (75)** — the v2 service API in full: companies, projects,
    subprojects, tasks, absence types, people, groups and custom fields, then
    time entries with the entity-walk (`get_time_entry_entities` →
    `get_time_entry_tasks` → `create_time_entry`) the API requires, the
    submit/approve/reject/lock workflow, and the asynchronous export job pair.
    Every call is one `POST /api/v2` differing only in its `service` field, so
    HTTP status is always 200 and the real result is `status` in the body.
  - **`bigcommerce` (74)** — the catalog (products, variants, images, custom
    fields, metafields, reviews, bulk pricing, categories, brands), orders
    with shipments, transactions, refunds, captures and voids, customers,
    addresses, attributes and subscribers, price lists and their records,
    coupons and gift certificates, and server-side carts with checkout
    redirect urls. Built from BigCommerce's own OpenAPI documents, so the v2
    and v3 split is faithful: v3 answers `{data, meta}`, and the v2 order
    endpoints answer **204 with no body** when a collection is empty, which
    the header says out loud.
  - **`bill` (65)** — the Connect v3 API across both halves of the ledger:
    vendors, bills, approvals and payments on the payable side; customers,
    invoices, received payments, credit memos and payment links on the
    receivable side; plus funding accounts, classifications, documents and
    the BILL network. `create_payment` and `record_ap_payment` are
    deliberately separate tools, because one moves money and the other only
    the books. This connector's session exchange is not implemented yet, so
    the header says plainly that live calls will be rejected until it lands.
  - **`beekeeper` (63)** — streams and their group, org-unit and member
    permissions, posts with comments, likes, reactions and polls, users and
    the colleague-facing profiles, groups and memberships, org units, custom
    fields and birthday reminders, from Beekeeper's own Swagger document.
  - **`battlenet` (61)** — the World of Warcraft profile and game-data APIs:
    the signed-in player's account and collections (which need the
    `wow.profile` scope), character profiles, equipment, specialisations,
    achievements, professions, quests, encounters, Mythic+ and PvP, guilds
    and rosters, realms and connected realms, auctions, commodities and the
    token price, leaderboards, and the static reference data. Each tool builds
    the region-suffixed `namespace` its endpoint needs from a `region`
    argument, which is the parameter most often got wrong.
  - **`beehiiv` (57)** — posts (structured `blocks` or raw HTML), subscriptions
    and bulk imports, custom fields, segments, newsletter lists, automations
    and journeys, paid tiers, polls, exports, engagement metrics and webhooks,
    from beehiiv's OpenAPI document. `create_post` with `status: confirmed`
    sends the email and is described as such; `send_test_email` is the
    rehearsal.
  - **`baremetrics` (46)** — the write side (customers, plans, subscriptions,
    charges, refunds, all scoped to a source) and the read side (metrics
    summary, per-metric series and plan breakout, which are account-wide),
    plus annotations, goals, segments, custom attributes and cancellation
    insights. Cancelling a subscription and deleting one are separate tools
    with different consequences for the churn numbers.
  - **`belco` (37)** — conversations with their items, replies, notes, the
    assign/close/snooze/tag verbs, contacts scoped per shop, teams and users,
    conversation and voice metrics, and webhooks. `add_note` is called out as
    the internal alternative to a reply the customer sees.
  - **`bika` (37)** — spaces, nodes, database fields and views, the v2 record
    endpoints (list, get, create, update, delete, batch), views, automation
    triggers and runs, members, teams and roles, embed links and outgoing
    webhooks, from the OpenAPI document Bika serves. The header explains
    `fieldKey`, which decides whether cells are addressed by field name or id.
  - **`back-market` (35)** — from Back Market's own bundled OpenAPI contract:
    the category tree, listings and the CSV catalogue import with its task
    polling, orders and the orderline state machine, Backship deliveries and
    returns, the Care after-sales platform with refunds and item transfers,
    BuyBack trade-in orders, messages, counter-offer reasons and listings, and
    Backbox competitor pricing. The header spells out the state transitions,
    since shipping requires a tracking number and nothing moves backwards.
  - **`beamer` (34)** — changelog posts with comments and reactions, unread
    counts per user, the feature-request board with its comments and votes,
    users and segments, and NPS responses. The header leads with the
    array-per-language shape of `title` and `content`, which is the first
    thing to trip over.
  - **`bigdatacorp` (32)** — the Pessoas, Empresas and Endereços data APIs,
    where `q` is a key expression (`doc{CPF}`) and `Datasets` a comma-separated
    list of billed dataset names, plus the platform's batch jobs, monitoring
    subscriptions with their diffs, asynchronous queries, saved views and
    token management. The header notes that this is personal data under the
    LGPD and that each dataset in a request is charged.
  - **`bamboohr-basic` (30)** — the API-key half of BambooHR: the directory,
    employees and their history *tables* (which is where job and pay changes
    belong), changed-employee polling for incremental sync, field, table, list
    and dataset metadata, time-off requests with approvals, denials, balances
    and adjustments, who's out, custom and saved reports, files, photos and
    performance goals.
  - **`basin` (29)** — forms and their whole notification, autoreply and spam
    configuration, submissions with the read/spam/trash state the dashboard
    views are built from, webhook re-firing for a receiver that was down,
    projects, domains, form views and mail templates, from Basin's published
    Swagger document. There is deliberately no "create submission" tool:
    real submissions arrive through the public form endpoint.
  - **`baserow` (13)** — scoped to exactly what a **database token** can do,
    which the OpenAPI document states per endpoint: the token's table list,
    fields, and the row endpoints including the batch create, update and
    delete. Table and field editing need a user JWT and are deliberately
    absent rather than present and always failing.
  - **`bettercontact` (7)** — the waterfall enrichment API as it actually
    works: submit, poll, read. Batch enrichment and Lead Finder searches are
    asynchronous and answer with a request id; the two profile lookups answer
    inline. `get_credit_balance` is the cheap check before a large batch.

- **Tool packs for twenty more connectors, 2,076 tools in all**, every one
  written against the provider's own reference or its published specification.
  All twenty previously shipped only the generated fallbacks:
  - **`datadog` (310) and `datadog-oauth` (310)** — built from Datadog's own
    v1 and v2 OpenAPI documents: metrics and the v2 query language, monitors
    with their notification rules and config policies, downtimes, logs with
    their indexes, pipelines, archives and log-based metrics, events, APM
    spans, dashboards and powerpacks, notebooks, SLOs and corrections, hosts
    and tags, incidents, security rules, signals, filters, suppressions and
    findings, audit logs, Synthetics, Software Catalog, DORA, users, teams,
    roles, keys, organizations, usage and cost, and the webhook, Slack and
    PagerDuty integrations. Both versions coexist in the paths because Datadog
    keeps monitors and dashboards on v1 while adding new surfaces under v2.
    The OAuth connector mirrors the API-key one, differing only in the header
    note about scopes.
  - **`databricks-workspace` (271)** — clusters, cluster policies, instance
    pools, libraries and execution contexts; jobs and runs on the 2.2 surface;
    Delta Live Tables pipelines; the SQL statement, warehouse, query, alert and
    history APIs; Unity Catalog catalogs, schemas, tables, volumes, functions,
    grants, external locations, storage credentials, connections, system
    schemas and registered models; Delta Sharing; workspace files, repos, Git
    credentials, secrets and DBFS; model serving, vector search and Apps;
    Lakeview dashboards and Genie. Every tool sets `base_url_override`, because
    the connector's base url pins `/api/2.0` while the API spans 1.2 through
    3.0 — clusters are 2.1, jobs are 2.2, execution contexts are still 1.2.
  - **`crisp` (217) and `crisp-plugin-install` (217)** — the whole v1 REST API,
    extracted from Crisp's own TypeScript SDK route table: conversations and
    messages, people profiles with their data, events and segments, campaigns
    and templates, the helpdesk, inboxes, operators, teams, visitors,
    availability, analytics, batch operations, identity verification and the
    plugin subscription surface. The two connectors are the same API under two
    auth modes, so the packs are deliberately identical.
  - **`crowdstrike` (214)** — the Falcon security-operations core, taken from
    CrowdStrike's FalconPy endpoint definitions: alerts and detections,
    incidents and CrowdScore, hosts and host groups, custom IOCs, threat
    intelligence, Real Time Response at all three privilege tiers, Spotlight
    vulnerabilities, quarantine, the sandbox, exclusions and IOA rule groups,
    policies, users and roles, sensor deployment, Discover, Identity Protection
    and cloud posture — plus five raw tools for the ~130 services it does not
    name. Containing a host, RTR admin commands and prevention IOCs are marked
    destructive because they cut machines off the network, run arbitrary code
    as SYSTEM, and block fleet-wide.
  - **`databricks-account` (131)** — the account control plane: workspace
    provisioning with its credential, storage, network, VPC-endpoint and CMEK
    configurations, Unity Catalog metastores and their workspace assignments,
    SCIM identity and workspace permission assignments, OAuth app integrations
    and workload identity federation, budgets and log delivery, and the account
    IP access lists and network policies.
  - **`customgpt` (111)** — agents, documents, sources and contextual-RAG
    pages, conversations and messages with their citations, claims and trust
    scores, agentic tasks with their tool outputs and files, personas and
    sub-personas, custom MCP actions, labels, licenses, reports, teams, roles
    and billing.
  - **`crunchbase` (108)** — generated from the OpenAPI fragments Crunchbase
    embeds in each reference page, so it covers all six API packages:
    autocomplete, entity lookups and single-card reads for 40-odd collections,
    the predicate-language searches for each of them, deleted entities for
    incremental sync, and field metadata. The prediction and insight tools say
    which package they need, since a key without it gets a 403 rather than an
    empty result.
  - **`cryptolens` (58)** — key activation, creation, extension, blocking and
    feature flags; products and license templates; customers, data objects with
    their atomic increment and decrement, analytics, messages, subscriptions,
    resellers and end-user authentication. Every call is a form-encoded POST to
    `/api/{area}/{Method}`, and `activate_key` is flagged as the write it is —
    it consumes a seat, which is how a customer's activations get exhausted by
    code that meant only to validate.
  - **`cyberimpact` (51)** — the full published OpenAPI surface: members with
    their consent records, groups, mailings and their eight recipient
    breakdowns, templates, batch imports and API tokens. The pack distinguishes
    `opt_in_member` from `create_member`, and `unsubscribe_member` from
    `delete_member`, because Canadian anti-spam law makes those different acts.
  - **`currents` (39)** — projects, runs, instances, the tests and errors
    explorers, spec files, test signatures and results, quarantine actions,
    webhooks and the Jira integration, from the OpenAPI fragments in Currents'
    resource docs. Includes `get_failure_context`, which Currents built for
    agents specifically.
  - **`dart` (39)** — tasks, docs, comments, dartboards, folders, views, AI
    agents, skills and webhooks, from Dart's generated client. The header
    leads with the thing that breaks integrations: Dart takes titles, not ids,
    and rejects a status or assignee it does not recognise.
  - **`dailybot` (32)** — users, teams, check-ins and their responses, kudos,
    forms and workflows. The endpoints and the methods each accepts were
    confirmed against the live API's own `Allow` headers, so what is absent is
    absent because DailyBot does not offer it.
  - **`cursor` (26)** — cloud agents, runs, artifacts and usage, plus the
    private-worker and pool surface for self-hosted execution. Launching an
    agent is marked destructive: with `autoCreatePR` it opens a pull request
    against a real repository.
  - **`cursor-admin` (24)** — team members, daily usage and filtered usage
    events, per-member spend and spend limits, audit logs, billing groups,
    repository blocklists and model access policy. The usage reports are POSTs
    whose dates are epoch milliseconds, which is the usual reason one comes
    back empty.
  - **`crawlbase` (10)** — the crawling, scraper, leads and storage APIs, with
    the normal-versus-JavaScript token distinction that decides which rendering
    arguments work at all.
  - **`customer-io` (7)** — the seven Data Pipelines endpoints. The pack's
    header carries what the API does not: there are no DELETE endpoints, so
    deleting or suppressing a person is `track_event` with a semantic event
    name.
  - **`datacandy` (7)** — deliberately just the one endpoint the catalogue
    itself declares, plus the raw tools. DataCandy publishes no public API
    reference and geo-restricts the live API, so naming endpoints nobody has
    verified would have been fabrication; the header says so plainly.
  - **`dappier` (6)** — real-time AI model search, semantic article
    recommendations, and the Ask AI, sponsored-conversation and session
    intelligence analytics. The ZeroClick endpoints are excluded: they
    authenticate with an HMAC signature rather than this connection's token.

- **Tool packs for nine more connectors, 351 tools in all**, every one written
  against the provider's own reference. All nine previously shipped only the
  generated fallbacks — the raw `get_from_api`/`post_to_api` tools, plus
  `check_connection` where the catalogue entry declared a verification
  endpoint:
  - **`hubstaff` (179)** — the whole Hubstaff v2 surface: organizations,
    members, projects, tasks and global to-dos; raw and daily activities with
    their `/updates` counterparts, which are what an incremental sync must poll
    since a back-dated edit never appears in a `time_slot` query; timesheets,
    manual time requests and time edit logs; screenshots, notes, tracking
    states and the app/url settings that govern them; Insights, tool
    classifications and smart notification rules; teams, clients, invoices,
    payments, budgets, limits and rates; time off and overtime policies,
    requests, balances and holidays; attendance, job sites, locations,
    invites, integrations, the audit log and webhooks.
  - **`anthropic-admin` (50)** — the Admin API control plane: members, invites,
    RBAC groups, roles and permissions, workspaces and their members, service
    accounts inside a workspace, API keys, rate limits, CMEK external keys, and
    the usage, cost and Claude Code analytics reports. Every "update" is a POST
    to the resource's own path — this API has no PATCH — and the tools that
    need an `org:admin` OAuth token rather than an Admin key say so.
  - **`anrok` (26)** — generated-quality coverage of the sales tax API from
    Anrok's published OpenAPI document: saved and ephemeral tax calculation,
    voids and negations with their expected-version guard, customers, exemption
    certificates and certificate requests, products and product tax categories,
    integration product mappings, address resolution, tax ID validation and
    filings. Every call is a POST, ids sit in the path behind an `id:` prefix,
    and amounts are integers in the currency's smallest unit.
  - **`anthropic` (23)** — the Claude API data plane, deliberately split from
    `anthropic-admin` the way the credentials are: messages and token counting,
    the six message-batch calls, models, files, Agent Skills, and the Managed
    Agents beta (agents, environments, sessions and their events, each carrying
    its own `anthropic-beta` header). Multipart file upload is not reachable
    through a JSON proxy, so the pack reads and deletes files but does not
    claim to upload them.
  - **`whatsapp-business` (22)** — the Cloud API on the Meta graph: sending,
    templates, read receipts, media, phone-number registration and
    verification, business profiles, template management, webhook subscriptions
    and conversation analytics. The graph version is an argument on each tool
    rather than fixed by the connection, defaulting to the `v21.0` the
    connector's own verification endpoint uses.
  - **`anvil` (20)** — both halves of Anvil behind one host: the two `/api/v1`
    REST endpoints that fill and generate PDFs and answer with raw bytes, and
    the `/graphql` endpoint for Etch e-signature packets, signers, templates,
    workflows, webforms and webhooks. A `run_graphql_query` escape hatch keeps
    the rest of the schema reachable.
  - **`microsoft-teams-bot` (17)** — the Bot Framework Connector service, not
    Microsoft Graph: conversations, activities (send, reply, update, delete and
    history), conversation and activity members with the paged roster Teams
    requires for a channel, attachments, and the two Teams-specific `/v3/teams/`
    extensions for team details and channel lists.
  - **`hubspot-mcp` (7)** — the Model Context Protocol methods HubSpot's remote
    MCP server answers: `initialize`, tools, prompts and resources. The server
    decides which CRM operations it exposes, so `list_server_tools` is the only
    honest way to discover the surface; for the CRM REST API itself, use the
    `hubspot` connector.
  - **`hullo` (7)** — the whole Direct API: account, attributes, sending and
    reading messages, and member upsert, read and opt-out. Members are keyed on
    the phone number rather than an id, and an upsert on an unknown number
    sends an opt-in text rather than creating a messageable member.

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

- **`agify` sent its API key under a name the API ignores.** The catalogue
  entry passed the key as `api_key`; Agify, Genderize and Nationalize read
  `apikey`, and silently serve an unauthenticated request when it is missing.
  Every call therefore ran on the anonymous 100-names-a-day allowance instead
  of the subscription, and a wrong key never failed. Checked against the live
  hosts: `api_key=bogus` answers 200 with data, `apikey=bogus` answers 401. The
  entry now sends `apikey`.

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

[0.2.3]: https://github.com/MuhammadHusnainAli/connector-for-ai-agents/compare/v0.2.2...v0.2.3
[0.2.2]: https://github.com/MuhammadHusnainAli/connector-for-ai-agents/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/MuhammadHusnainAli/connector-for-ai-agents/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/MuhammadHusnainAli/connector-for-ai-agents/compare/v0.1.3...v0.2.0
[0.1.3]: https://github.com/MuhammadHusnainAli/connector-for-ai-agents/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/MuhammadHusnainAli/connector-for-ai-agents/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/MuhammadHusnainAli/connector-for-ai-agents/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/MuhammadHusnainAli/connector-for-ai-agents/releases/tag/v0.1.0
