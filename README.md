# connector-for-ai-agents

**1,586 API connectors for Python — every auth field each one needs, and the code that turns filled-in fields into a working, verified connection. Sync and async.**

[![PyPI](https://img.shields.io/pypi/v/connector-for-ai-agents)](https://pypi.org/project/connector-for-ai-agents/)
[![Python](https://img.shields.io/pypi/pyversions/connector-for-ai-agents)](https://pypi.org/project/connector-for-ai-agents/)
[![CI](https://github.com/MuhammadHusnainAli/connector-for-ai-agents/actions/workflows/ci.yml/badge.svg)](https://github.com/MuhammadHusnainAli/connector-for-ai-agents/actions/workflows/ci.yml)
[![Licence](https://img.shields.io/badge/licence-Elastic%202.0-blue)](LICENSE)

Building an AI agent, an integrations page, or an internal tool that has to talk
to Stripe, Slack, HubSpot, Notion, Jira, Shopify and 1,581 other APIs? The hard
part is rarely the HTTP call. It is knowing that this provider wants a bearer
token and that one wants `X-API-KEY`, that a third needs a client-credentials
exchange against a per-tenant domain, and which endpoint proves the credentials
actually work.

This package is that knowledge, as data and code you can call:

```python
from connector_manager import ConnectorManager

with ConnectorManager() as manager:
    connection = manager.connect("sendgrid", credentials={"apiKey": "SG.…"})
    print(connection.verified)                       # True — checked against the live API
    print(manager.request(connection, "GET", "/v3/scopes").json())
```

No network needed to browse the catalogue. No OAuth server to run. No secrets
stored on your behalf.

---

## Contents

- [Why this exists](#why-this-exists)
- [Install](#install)
- [Quick start](#quick-start)
- [Browse the catalogue](#browse-the-catalogue)
- [Ask what a connector needs](#ask-what-a-connector-needs)
- [Connect](#connect)
- [Use the connection and keep it alive](#use-the-connection-and-keep-it-alive)
- [Sync and async](#sync-and-async)
- [Auth mode coverage](#auth-mode-coverage)
- [OAuth connectors](#oauth-connectors)
- [Using this from an AI agent](#using-this-from-an-ai-agent)
- [Command line](#command-line)
- [How it is put together](#how-it-is-put-together)
- [Adding your own auth mode](#adding-your-own-auth-mode)
- [FAQ](#faq)
- [What is deliberately not here](#what-is-deliberately-not-here)
- [Project files](#project-files)

## Why this exists

- **1,586 connectors, bundled.** Auth mode, field definitions, base url and a
  verification endpoint for each. No API calls to browse them, no rate limits,
  no service to sign up for. Works offline and in air-gapped builds.
- **1,190 connect end to end from user input alone.** API keys, basic auth,
  client credentials, multi-step token exchanges, locally signed JWTs, WSSE and
  OAuth 1.0a request signing all complete inside the library.
- **Verified, not assumed.** `connect()` calls the provider's own verification
  endpoint, so you learn the credentials are wrong at the moment they are
  entered, not on the first real request an hour later.
- **One implementation, sync and async.** Each auth flow is written once as a
  generator of requests and driven by either client, so the two managers cannot
  drift apart.
- **Built for forms and for tools.** Every connector describes its own fields —
  title, description, example, regex, enum, secret, order — so you can render a
  connection form, or hand an LLM a tool spec, straight from the catalogue.
- **Typed, tested, small.** Full type hints with `py.typed`, 98 tests covering
  every connector in the catalogue, and four runtime dependencies.
- **Your security model stays yours.** Connections come back as plain objects.
  Where they live and how they are encrypted is your call.

```
┌─ this package ─────────────────────────────┐   ┌─ your application ───────┐
│ list connectors  (id, name, icon, auth)    │   │ OAuth redirect flow      │
│ describe auth    (which fields, validation)│   │ secret storage/encryption│
│ connect          (token exchange + verify) │-->│ connection persistence   │
│ refresh / authenticated request            │<--│ tenants, users, policies │
└────────────────────────────────────────────┘   └──────────────────────────┘
```

## Install

```bash
pip install connector-for-ai-agents
uv add connector-for-ai-agents
```

Python 3.10+. Runtime dependencies: `httpx`, `PyYAML`, `PyJWT`, `cryptography`.
The distribution carries the connector definitions and all 1,591 logos, so
nothing is fetched at runtime.

The distribution is named `connector-for-ai-agents`; the import is
`connector_manager`:

```python
from connector_manager import ConnectorManager, AsyncConnectorManager, Connection
```

<details>
<summary>Installing from git, or working on this repository</summary>

```bash
# straight from git
uv pip install git+https://github.com/MuhammadHusnainAli/connector-for-ai-agents
pip install "connector-for-ai-agents @ git+https://github.com/MuhammadHusnainAli/connector-for-ai-agents"

# working on this repo
git clone https://github.com/MuhammadHusnainAli/connector-for-ai-agents
cd connector-for-ai-agents
uv sync --extra dev        # or: pip install -e ".[dev]"
uv run pytest -q
```

`uv build` (or `python -m build`) produces the wheel and sdist in `dist/`.
</details>

## Quick start

Four calls cover the whole lifecycle: find a connector, ask what it needs,
connect, then call the API.

```python
from connector_manager import ConnectorManager

manager = ConnectorManager()

# 1. find it
manager.list_connectors(search="sendgrid")        # [Connector(id='sendgrid', …)]

# 2. ask what it needs — enough to render a form or a tool spec
manager.describe_auth("sendgrid")
# {'connector_id': 'sendgrid', 'auth_mode': 'API_KEY', 'self_service': True,
#  'credentials': [{'name': 'apiKey', 'title': 'API Key', 'required': True, …}], …}

# 3. connect — validates the fields, runs any token exchange, verifies the result
connection = manager.connect("sendgrid", credentials={"apiKey": "SG.…"})
connection.verified                                # True

# 4. call the API with the credentials applied for you
manager.request(connection, "GET", "/v3/scopes").json()
```

Persist the connection wherever you like:

```python
saved = connection.to_dict()                       # JSON-safe dict for your DB or vault
connection = Connection.from_dict(saved)
```

## Browse the catalogue

```python
len(manager)                       # 1586
manager.categories()               # 31 categories: 'crm', 'accounting', 'hr', …
manager.auth_modes()               # {'API_KEY': 899, 'OAUTH2': 361, 'OAUTH2_CC': 110, …}

for connector in manager.list_connectors(category="crm", limit=3):
    print(connector.id, connector.display_name, connector.auth_mode.value)

manager.get_icon("hubspot")                            # inline SVG string
manager.list_connectors_dict(include_icon=True)        # JSON-ready (icons are large)
```

Filters: `search`, `category`, `auth_mode`, `supported_only`,
`self_service_only`, `limit`, `offset`.

### Pagination

1,586 connectors is too many to hand a UI at once. Ask for a page by number or
by raw `offset` and you get a `ConnectorPage` carrying the items **and** the
numbers a picker needs — including `total`, counted before paging, so rendering
"showing 21-40 of 1,586" never costs a second call.

```python
page = manager.paginate_connectors(page=2, page_size=20, category="crm")

page.items                                 # list[Connector] for this page
list(page)                                 # a page is iterable, sized, indexable
page.total                                 # 113 — matches for these filters, ignoring paging
page.page, page.pages                      # 2, 6
page.has_next, page.next_offset            # True, 40
page.first_index, page.last_index          # 21, 40

page.to_dict()                             # {"items": [...], "pagination": {...}}
```

Ordering is stable (display name, then id), so consecutive pages slice the same
sequence — no repeated or skipped rows. `page_size` defaults to 50 and is capped
at 1,000. To walk everything without holding it in memory:

```python
for page in manager.iter_connector_pages(page_size=200, self_service_only=True):
    for connector in page:
        ...
```

## Ask what a connector needs

```python
schema = manager.get_auth_schema("1password-users")

schema.auth_mode                 # <AuthMode.OAUTH2_CC>
schema.requires_external_oauth   # False — this package can complete it

for field in schema.user_fields():
    print(field.group.value, field.name, field.title, field.required, field.secret)

# connection_config  domain         API Domain      True   False   (enum of 3 regions)
# connection_config  accountId      Account ID      True   False
# credentials        client_id      Client ID       True   False
# credentials        client_secret  Client Secret   True   True
```

Every `AuthField` carries what a form needs: `title`, `description`, `example`,
`pattern`, `enum`, `format`, `secret`, `order`, `default_value`, `visible_when`.
Two groups matter:

- **`credentials`** — the secrets: `apiKey`, `client_id` / `client_secret`, …
- **`connection_config`** — per-connection non-secrets that the provider's urls
  interpolate: `domain`, `accountId`, `subdomain`, …

`manager.describe_auth(id)` returns the same thing as a plain dict.

## Connect

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

`connect()` validates every field against the connector's own rules — missing
fields, patterns, enums, all reported at once through
`ValidationError.field_errors` — runs the token exchange when the auth mode needs
one, then calls the provider's verification endpoint to prove the credentials
work.

Pass `require_verified=True` to raise instead of returning `verified=False`, or
`verify=False` to skip the network call entirely.

## Use the connection and keep it alive

```python
manager.ensure_fresh(connection)      # refresh only if expired or close to it
manager.refresh(connection)           # force a new token
manager.verify(connection)            # re-check the credentials

response = manager.request(connection, "GET", "/v1/customers")
response.status, response.json()

# or hand the fully resolved call to another runtime: a worker, an agent tool,
# a different HTTP client
manager.prepare_request(connection, "GET", "/v1/customers").to_dict()
# {'method': 'GET', 'url': 'https://…', 'headers': {'authorization': 'Bearer …'}, 'params': {}}
```

## Sync and async

Two manager classes, one implementation. Same method names throughout.

```python
from connector_manager import ConnectorManager, AsyncConnectorManager

with ConnectorManager() as manager:
    connection = manager.connect("affinity-v2", credentials={"apiKey": "…"})
    response = manager.request(connection, "GET", "/v2/persons")

async with AsyncConnectorManager() as manager:
    connection = await manager.connect("affinity-v2", credentials={"apiKey": "…"})
    response = await manager.request(connection, "GET", "/v2/persons")
```

`connect`, `import_connection`, `verify`, `refresh`, `ensure_fresh` and `request`
are coroutines on the async manager. The catalogue and schema methods —
`list_connectors`, `get_auth_schema`, `describe_auth`, `get_icon`,
`prepare_request`, `validate` — only read bundled data, so they stay synchronous
in both.

Examples elsewhere in this README use the sync manager; add `await` for async.

## Auth mode coverage

| Auth mode | Connectors | Support |
| --- | --- | --- |
| `API_KEY` | 899 | Full — connect and verify |
| `OAUTH2_CC` | 110 | Full — client-credentials exchange, including basic, custom and `private_key_jwt`, plus refresh |
| `BASIC` | 109 | Full — connect and verify |
| `TWO_STEP` | 63 | Full — token exchange, chained `additional_steps`, cookie and header extraction, refresh |
| `JWT` | 4 | Full — signed locally with HMAC, RSA or EC |
| `NONE`, `INSTALL_PLUGIN` | 3 | Full |
| `SIGNATURE` | 1 | Full — WS-Security UsernameToken |
| `TBA` | 1 | Full — OAuth 1.0a HMAC-SHA256 request signing |
| `OAUTH2` | 361 | Import tokens from your own OAuth layer; the refresh-token grant runs here |
| `MCP_OAUTH2`, `MCP_OAUTH2_GENERIC`, `OAUTH1`, `APP`, `CUSTOM` | 32 | Import tokens; request signing works once imported |
| `BILL`, `AWS_SIGV4` | 3 | Not implemented — raises `UnsupportedAuthModeError` |

**1,190 connectors connect end to end from user-supplied values alone.** The
remaining 396 need a token you obtained elsewhere, or an auth mode this package
does not implement.

## OAuth connectors

Redirect flows belong in your auth layer. Once you have tokens, import them and
everything else works the same way.

```python
manager.requires_external_oauth("slack")   # True

manager.connect("slack", credentials={})   # ExternalAuthRequiredError, explaining what is missing

connection = manager.import_connection(
    "slack",
    credentials={
        "access_token": "xoxb-…",
        "refresh_token": "…",      # optional
        "client_id": "…",          # optional — enables manager.refresh()
        "client_secret": "…",
    },
)
```

The catalogue still carries each provider's `authorization_url`, `token_url`,
scopes and PKCE quirks, so you can drive your own redirect flow from it.

## Using this from an AI agent

The catalogue is designed to be handed to a model. Every method that matters
returns plain JSON-safe dicts, so a tool layer is thin:

```python
from connector_manager import ConnectorManager, Connection

manager = ConnectorManager()

def search_connectors(query: str, page: int = 1) -> dict:
    """Find integrations by name or category."""
    return manager.paginate_connectors(search=query, page=page, page_size=20).to_dict()

def get_required_fields(connector_id: str) -> dict:
    """List exactly what the user must supply to connect."""
    return manager.describe_auth(connector_id)

def call_api(saved_connection: dict, method: str, path: str) -> dict:
    """Make an authenticated call to a connected provider."""
    connection = Connection.from_dict(saved_connection)
    manager.ensure_fresh(connection)
    return manager.request(connection, method, path).json()
```

Why it suits agent use:

- `describe_auth()` is already a field spec — names, types, whether a value is
  secret, regex, allowed values — so a model can ask the user for exactly the
  right things and validate before spending a call.
- `paginate_connectors()` bounds the context you feed a model, and `total` lets
  it reason about how much it has not seen.
- `prepare_request()` returns a resolved request without sending it, so an agent
  can show a user what it is about to do and wait for approval.
- Errors are typed and structured — `ValidationError.field_errors` names the bad
  fields, `ExternalAuthRequiredError` says what is missing — so a model can
  recover instead of guessing.
- Browsing costs no network calls, so catalogue exploration never burns rate
  limit or wall-clock time.

## Command line

Installing the package installs a `connectors` command, equivalent to
`python -m connector_manager`:

```bash
connectors list --search hubspot
connectors list --page 2 --page-size 20        # showing 21-40 of 1586 · page 2/80
connectors list --all --page-size 200          # page through everything
connectors show 1password-users                # every field it needs
connectors stats                               # totals by auth mode and category
connectors icon stripe -o stripe.svg
connectors connect affinity-v2 -c apiKey=… -o conn.json
connectors request conn.json GET /v2/persons
```

`-c` sets a credential, `-x` a connection-config value, `-i` an
integration-config value, all as `key=value`.

**Credentials are hidden when output goes to a terminal.** `connect`, `verify`,
`refresh` and `request --dry-run` redact credential values, authorization headers
and key-bearing query parameters, so secrets do not end up in scrollback or CI
logs. Pass `--show-secrets` to print them anyway. `-o FILE` writes the usable
connection with mode `0600`; it holds live credentials, so keep it out of version
control.

## How it is put together

| Module | Main classes | Role |
| --- | --- | --- |
| `manager.py` | `BaseConnectorManager`, `ConnectorManager`, `AsyncConnectorManager` | the public facade |
| `registry.py` | `ConnectorRegistry` | loads `connectors.yaml` and icons, pagination, builds `AuthSchema` |
| `models.py` | `Connector`, `ConnectorPage`, `AuthField`, `AuthSchema`, `Connection`, `AuthMode` | the data model |
| `auth/` | `AuthStrategy` subclasses | one class per auth mode |
| `flows.py` | `FlowRunner`, `AsyncFlowRunner` | drive one auth flow either sync or async |
| `http.py` | `Request`, `HttpResponse`, `HttpClient`, `AsyncHttpClient` | the only I/O in the package |
| `proxy.py` | `RequestBuilder` | base urls, auth headers, query templates, OAuth1 and TBA signing |
| `verification.py` | `CredentialVerifier`, `VerificationResult` | proves credentials work |
| `validation.py` | — | required, pattern, enum, format, `visible_when` |
| `interpolation.py` | — | the `${…}` template engine |
| `data/` | — | `connectors.yaml` and 1,591 SVG logos |

Run the suite with `uv run pytest -q` — 98 tests. Coverage includes the whole
catalogue: every connector must expose a name, an icon, a buildable auth schema
and a fully resolved request with no leftover `${…}` in urls or headers, plus
mocked connect, refresh and verify flows for each supported auth mode. The async
suite asserts the async manager returns byte-identical credentials to the sync
one for the same provider response.

## Adding your own auth mode

Subclass `AuthStrategy` and register it. Your strategy works in both managers
because it never touches an HTTP client itself: return the credentials directly
when no network is needed, or make `flow()` a generator that yields `Request`
objects and receives `HttpResponse` back.

```python
from connector_manager import AuthMode, AuthStrategy, Request, register_strategy, TokenExchangeError

class MyBillAuth(AuthStrategy):
    auth_mode = AuthMode.BILL
    refreshable = True

    def flow(self, ctx):
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

Adding a connector instead? See [CONTRIBUTING.md](CONTRIBUTING.md).

## FAQ

**Does browsing the catalogue make network calls?**
No. Definitions and logos ship inside the distribution. Only `connect`,
`verify`, `refresh` and `request` touch the network.

**Where do the connector definitions come from?**
From maintained open-source implementations of each provider's API — Nango,
Pipedream, ActivePieces and n8n — so base urls, credential placement and
verification endpoints come from working code rather than guesswork. Each one
was then called live: see [docs/added-connectors.md](docs/added-connectors.md)
for the evidence behind every connector added in 0.1.2.

**Does it store my API keys?**
No, and that is deliberate. `connect()` returns a `Connection` object and hands
it to you. Encryption, storage, rotation and tenancy are your application's job.

**Can it run the OAuth redirect flow for me?**
No. Redirects need a browser, a callback url and session state that belong in
your app. Run the flow yourself, then `import_connection()`. Client-credentials
OAuth, which needs no redirect, is fully implemented.

**How do I know a connector actually works before shipping it?**
`connect()` calls the provider's verification endpoint and reports `verified`.
From the shell: `connectors connect <id> -c apiKey=… -o conn.json`.

**What if a provider is missing, or a definition is wrong?**
Open an issue or a pull request — [CONTRIBUTING.md](CONTRIBUTING.md) covers the
shape of a good connector entry.

**Is it typed?**
Yes, fully, with `py.typed`, so your type checker sees the annotations.

**Which Python versions are supported?**
3.10 and newer, tested in CI on 3.10 through 3.13.

**Is this open source?**
It is source-available under the Elastic License 2.0. You can read, modify and
use it, including commercially, but you may not provide it to others as a hosted
or managed service. See [LICENSE](LICENSE).

## What is deliberately not here

Connection storage, secret encryption, OAuth redirect handling, webhooks and
data syncs.

A handful of connectors rely on provider-specific post-connection or
credential-verification scripts that are not implemented here. The fields those
scripts would fill are surfaced with `automated=True` so you can supply them
yourself, and such connectors report `tested=False` from `verify()`.

Documentation links are intentionally absent from the catalogue.
`connectors.yaml` carries only what is needed to authenticate and call each API:
auth mode, field definitions, base url, verification endpoint.

## Project files

| File | What it covers |
| --- | --- |
| [CHANGELOG.md](CHANGELOG.md) | What changed in each release |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Adding a connector, changing the machinery, house style |
| [SECURITY.md](SECURITY.md) | Reporting a vulnerability, and handling credentials safely |
| [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) | How we treat each other |
| [docs/added-connectors.md](docs/added-connectors.md) | Provenance and live check behind every connector added in 0.1.2 |

## Licence

Elastic License 2.0. See [LICENSE](LICENSE).
