# connector-for-ai-agents

A self-contained **connector + connection manager** for Python: 957 API
connectors with their logos, the exact auth fields each one needs, and the logic
to turn filled-in fields into a working, verified connection. Sync and async.

OAuth redirect flows, secret storage and multi-tenancy are **deliberately out of
scope** — `connect()` returns a plain `Connection` object and your own
auth/security layer decides where it lives.

```
┌─ this package ─────────────────────────────┐   ┌─ your app ───────────────┐
│ list connectors  (id, name, icon, auth)    │   │ OAuth redirect flow      │
│ describe auth    (which fields, validation)│   │ secret storage/encryption│
│ connect          (token exchange + verify) │──▶│ connection persistence   │
│ refresh / authenticated request            │◀──│ tenants, users, policies │
└────────────────────────────────────────────┘   └──────────────────────────┘
```

## Install into your application

It is one self-contained distribution — `connector-for-ai-agents` — that installs
with `uv` or `pip` and is imported as `connector_manager`.

```bash
# from a built wheel
uv pip install dist/connector_for_ai_agents-0.1.0-py3-none-any.whl
pip  install dist/connector_for_ai_agents-0.1.0-py3-none-any.whl

# straight from the repo / git
uv pip install git+https://github.com/MuhammadHusnainAli/connector-for-ai-agents
pip  install "connector-for-ai-agents @ git+https://github.com/MuhammadHusnainAli/connector-for-ai-agents"

# as a dependency of your app (pyproject.toml)
#   dependencies = ["connector-for-ai-agents @ git+https://github.com/…"]
uv add "connector-for-ai-agents @ git+https://github.com/MuhammadHusnainAli/connector-for-ai-agents"

# working on this repo itself
uv sync --extra dev          # or: pip install -e ".[dev]"
```

Build the artefacts with `uv build` (or `python -m build`) — they land in `dist/`
as a wheel and an sdist, each carrying the connector definitions and all 962 logos.

Then, in any application:

```python
from connector_manager import ConnectorManager, AsyncConnectorManager, Connection
```

Runtime deps: `httpx`, `PyYAML`, `PyJWT`, `cryptography`. Python 3.10+. The data
is bundled, so browsing the catalogue needs no network. The package is typed
(`py.typed`) and ships a `connectors` console script.

## Sync or async

Two manager classes, one implementation behind them. Every auth flow (token
exchanges, verification calls) is written once as a generator of requests, then
driven either by the sync client or the async one — so the two managers cannot
drift apart.

```python
from connector_manager import ConnectorManager, AsyncConnectorManager

with ConnectorManager() as manager:                       # sync
    connection = manager.connect("affinity-v2", credentials={"apiKey": "…"})
    response = manager.request(connection, "GET", "/v2/persons")

async with AsyncConnectorManager() as manager:            # async — same names
    connection = await manager.connect("affinity-v2", credentials={"apiKey": "…"})
    response = await manager.request(connection, "GET", "/v2/persons")
```

`connect`, `import_connection`, `verify`, `refresh`, `ensure_fresh` and `request`
are coroutines on the async manager. The catalogue and schema methods
(`list_connectors`, `get_auth_schema`, `get_icon`, `prepare_request`, `validate`)
are inherited from `BaseConnectorManager` and stay synchronous in both — they
only read bundled data.

The examples below use the sync manager; add `await` for the async one.

## 1. List connectors

```python
from connector_manager import ConnectorManager

manager = ConnectorManager()

len(manager)                       # 957
manager.categories()               # ['accounting', 'ats', 'banking', 'crm', ...]
manager.auth_modes()               # {'OAUTH2': 342, 'API_KEY': 310, 'OAUTH2_CC': 107, ...}

for connector in manager.list_connectors(category="crm", limit=3):
    print(connector.id, connector.display_name, connector.auth_mode.value)

svg = manager.get_icon("hubspot")                      # inline SVG string
rows = manager.list_connectors_dict(include_icon=True) # JSON-ready (icons ≈ 8 MB)
```

Filters: `search`, `category`, `auth_mode`, `supported_only` (drops the 3 auth
modes with no handler), `self_service_only` (also drops the ones needing an
external OAuth flow), `limit`, `offset`.

### Pagination

957 connectors is too many to hand a UI at once, so listings paginate. Ask for a
page by number (or by raw `offset`) and you get back a `ConnectorPage` carrying
the items **and** the numbers a picker needs — including `total`, which counts
every match *before* paging, so you never need a second call to render
"showing 21–40 of 957".

```python
page = manager.paginate_connectors(page=2, page_size=20, category="crm")

page.items            # list[Connector] for this page
list(page)            # a page is iterable, sized and indexable
page.total            # 84  — matches for these filters, ignoring paging
page.count            # 20  — items on this page
page.page, page.pages # 2, 5
page.has_next, page.has_previous          # True, True
page.next_offset, page.previous_offset    # 40, 0
page.first_index, page.last_index         # 21, 40
```

Filters apply exactly as they do to `list_connectors`, and `total` follows them.
Ordering is stable (display name, then id), so page 1 and page 2 slice the same
sequence — no repeated or skipped rows between calls.

For an HTTP API or an agent tool, serialise the whole thing in one step:

```python
manager.paginate_connectors(page=2, page_size=20).to_dict()
# {"items": [{...}, ...], "pagination": {"total": 957, "page": 2, "pages": 48,
#  "has_next": true, "next_offset": 40, "first_index": 21, "last_index": 40, ...}}
```

`to_dict(include_icon=True)` inlines each page's SVGs — safe per page, unlike a
full dump. `page.pagination()` returns just the metadata.

To process the whole catalogue without holding it all in memory, walk the pages:

```python
for page in manager.iter_connector_pages(page_size=200, self_service_only=True):
    print(f"{page.page}/{page.pages}")
    for connector in page:
        ...
```

Page addressing: `page` is 1-based; `offset` wins when both are given (and the
reported `page` is derived from it). `page_size` defaults to `DEFAULT_PAGE_SIZE`
(50) and is capped at `MAX_PAGE_SIZE` (1000); invalid values raise `ValueError`.
A page past the end comes back empty but still reports the real `total`.
`list_connectors(limit=..., offset=...)` still returns a plain list when you
don't need the metadata.

## 2. Ask what a connector needs

```python
schema = manager.get_auth_schema("1password-users")

schema.auth_mode                 # <AuthMode.OAUTH2_CC>
schema.requires_external_oauth   # False -> this package can complete it

for field in schema.user_fields():
    print(field.group.value, field.name, field.title, field.required, field.secret)

# connection_config domain     API Domain    True  False   (enum of 3 regions)
# connection_config accountId  Account ID    True  False
# credentials       client_id  Client ID     True  False
# credentials       client_secret Client Secret True True
```

Each `AuthField` carries what a form needs: `title`, `description`, `example`,
`pattern`, `enum`, `format`, `secret`, `order`, `default_value`.
`manager.describe_auth(id)` returns the same thing as JSON (handy as an agent
tool spec). Two field groups matter:

- **`credentials`** — the secrets (`apiKey`, `client_id`/`client_secret`, …).
- **`connection_config`** — per-connection non-secrets the provider's URLs
  interpolate (`domain`, `accountId`, `subdomain`, …).

## 3. Connect

```python
connection = manager.connect(
    "1password-users",
    credentials={"client_id": "…", "client_secret": "…"},
    connection_config={"domain": "api.1password.com", "accountId": "XLQ…"},
)

connection.verified        # True — the provider's verification endpoint answered 2xx
connection.access_token    # the minted token
connection.expires_at
```

`connect()` validates every field against the connector's rules (missing fields,
patterns, enums — all errors at once via `ValidationError.field_errors`), runs the
token exchange when the auth mode needs one, then calls the provider's
`verification` endpoint to prove the credentials work. Pass
`require_verified=True` to make a failed check raise instead of returning
`verified=False`, or `verify=False` to skip the network call.

**Store it yourself:**

```python
saved = connection.to_dict()          # plain JSON-safe dict → your DB/vault
connection = Connection.from_dict(saved)
```

## 4. Keep it alive and use it

```python
manager.ensure_fresh(connection)      # refreshes only if expired/about to expire
manager.refresh(connection)           # force a new token
manager.verify(connection)            # re-check credentials

response = manager.request(connection, "GET", "/v1/customers")
response.status, response.json()

# or hand the resolved call to another runtime (async client, worker, agent tool)
manager.prepare_request(connection, "GET", "/v1/customers").to_dict()
# {'method': 'GET', 'url': 'https://…', 'headers': {'authorization': 'Bearer …'}, 'params': {}}
```

## Auth mode coverage

| Auth mode | Connectors | Support |
| --- | --- | --- |
| `API_KEY` | 310 | ✅ connect + verify |
| `BASIC` | 95 | ✅ connect + verify |
| `OAUTH2_CC` | 107 | ✅ client-credentials exchange (incl. basic / custom / `private_key_jwt`) + refresh |
| `TWO_STEP` | 61 | ✅ token exchange, chained `additional_steps`, cookie/header extraction, refresh |
| `JWT` | 4 | ✅ locally signed (HMAC / RSA / EC) |
| `SIGNATURE` | 1 | ✅ WSSE UsernameToken |
| `TBA` | 1 | ✅ OAuth 1.0a HMAC-SHA256 request signing |
| `NONE`, `INSTALL_PLUGIN` | 3 | ✅ |
| `OAUTH2` | 342 | ⤴ import tokens from your OAuth layer; refresh-token grant implemented here |
| `OAUTH1`, `MCP_OAUTH2`, `MCP_OAUTH2_GENERIC`, `APP`, `CUSTOM` | 30 | ⤴ import-only (request signing works once imported) |
| `BILL`, `AWS_SIGV4` | 3 | ❌ not implemented — raises `UnsupportedAuthModeError` |

582 connectors connect end-to-end with nothing but user-supplied values.

### OAuth connectors

```python
manager.requires_external_oauth("slack")   # True

# calling connect() without tokens tells you exactly what is missing
manager.connect("slack", credentials={})   # ExternalAuthRequiredError

# after your own OAuth flow:
connection = manager.import_connection(
    "slack",
    credentials={
        "access_token": "xoxb-…",
        "refresh_token": "…",     # optional
        "client_id": "…",         # optional — enables manager.refresh()
        "client_secret": "…",
    },
)
```

## CLI

Installing the package also installs a `connectors` command (identical to
`python -m connector_manager`):

```bash
connectors list --search hubspot
connectors list --page 2 --page-size 20          # showing 21-40 of 957 · page 2/48
connectors list --offset 40 --page-size 20       # same page, addressed by offset
connectors list --all --page-size 200            # page through everything
connectors show 1password-users        # every field it needs
connectors stats
connectors icon stripe -o stripe.svg
connectors connect affinity-v2 -c apiKey=… -o conn.json
connectors request conn.json GET /v2/persons
```

`-c` sets a credential, `-x` a connection-config value, `-i` an integration-config
value (all `key=value`).

## Layout

| Module | Main class(es) | Role |
| --- | --- | --- |
| `manager.py` | `BaseConnectorManager`, `ConnectorManager`, `AsyncConnectorManager` | the public facade |
| `registry.py` | `ConnectorRegistry` | loads `connectors.yaml` (aliases resolved), icons, pagination, builds `AuthSchema` |
| `models.py` | `Connector`, `ConnectorPage`, `AuthField`, `AuthSchema`, `Connection`, `AuthMode` | the data model |
| `auth/` | `AuthStrategy` subclasses (`ApiKeyAuth`, `BasicAuth`, `OAuth2ClientCredentialsAuth`, `TwoStepAuth`, `JwtAuth`, `SignatureAuth`, `TbaAuth`, `OAuth2ImportAuth`, …) | one class per auth mode |
| `flows.py` | `FlowRunner`, `AsyncFlowRunner` | drive one auth flow either sync or async |
| `http.py` | `Request`, `HttpResponse`, `HttpClient`, `AsyncHttpClient` | the only I/O in the package |
| `proxy.py` | `RequestBuilder` | resolves base urls, auth headers, query templates, OAuth1/TBA signing |
| `verification.py` | `CredentialVerifier`, `VerificationResult` | runs `proxy.verification` to prove credentials work |
| `validation.py` | — | field validation (required, pattern, enum, format, `visible_when`) |
| `interpolation.py` | — | the `${…}` template engine (`base64`, `sha256Hex`, `hmacSha1Hex`, `fingerprint`, `now`, `\|\|`) |
| `data/` | — | `connectors.yaml` + 962 SVG logos |

### Extending

Subclass `AuthStrategy` and register it — your strategy works in both the sync
and the async manager, because it never touches an HTTP client itself. Implement
`flow()`: return the credentials dict directly when no network is needed, or make
it a generator that yields `Request` objects and receives `HttpResponse` back.

```python
from connector_manager import AuthMode, AuthStrategy, Request, register_strategy

class MyBillAuth(AuthStrategy):
    auth_mode = AuthMode.BILL
    refreshable = True

    def flow(self, ctx):                       # ctx.provider = raw providers.yaml entry
        response = yield Request(
            "POST",
            "https://api.bill.com/api/v2/Login.json",
            content=f"userName={ctx.credentials['username']}",
        )
        if not response.ok:
            raise TokenExchangeError("login failed", status=response.status)
        return {"type": "BILL", "token": response.json()["sessionId"]}

register_strategy(MyBillAuth())
```

## Tests

```bash
uv run pytest -q          # 75 tests (or: .venv/bin/python -m pytest tests -q)
```

Coverage includes the whole catalogue: every connector must expose a name, an
icon, a buildable auth schema, and a fully resolved request (no leftover
`${…}` in urls or headers), plus mocked connect/refresh/verify flows for each
supported auth mode — and the async suite asserts the async manager returns
byte-identical credentials to the sync one for the same provider response.

## Not in scope

Connection storage, secret encryption, OAuth redirect handling, webhooks and
syncs. A handful of connectors also rely on provider-specific post-connection or
credential-verification scripts that are not implemented here; the fields those
scripts would fill are surfaced as `automated=True` so you can supply them
yourself, and such connectors report `tested=False` from `verify()`.

Documentation links are intentionally absent from the catalogue: `connectors.yaml`
carries only what is needed to authenticate and call each API (auth mode, field
definitions, base url, verification endpoint).

## Licence

See `LICENSE`.
