# connector-for-ai-agents for Python

The Python package: `pip install connector-for-ai-agents`, imported as
`connector_manager`. Sync and async, Python 3.10+.

The Rust crate is the same library for Rust; see [RUST.md](RUST.md). Both read
the same connector catalogue and tool packs. Back to the [README](README.md).

## Contents

- [Install](#install)
- [Quick start](#quick-start)
- [Browse the catalogue](#browse-the-catalogue)
- [Ask what a connector needs](#ask-what-a-connector-needs)
- [Connect](#connect)
- [Use the connection and keep it alive](#use-the-connection-and-keep-it-alive)
- [Sync and async](#sync-and-async)
- [Auth mode coverage](#auth-mode-coverage)
- [OAuth connectors](#oauth-connectors)
- [Tools: what a connector can *do*](#tools-what-a-connector-can-do)
- [Adding tools for a connector](#adding-tools-for-a-connector)
- [Using this from an AI agent](#using-this-from-an-ai-agent)
- [Command line](#command-line)
- [How it is put together](#how-it-is-put-together)
- [Adding your own auth mode](#adding-your-own-auth-mode)
- [FAQ](#faq)
- [What is deliberately not here](#what-is-deliberately-not-here)

## Install

```bash
pip install connector-for-ai-agents
uv add connector-for-ai-agents
```

Python 3.10+. Runtime dependencies: `httpx`, `PyJWT`, `cryptography`.
The distribution carries the connector definitions and every connector's logo, so
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

# 5. or work in capabilities rather than endpoints
manager.check_tools(connection).summary()
# 'sendgrid: 9/13 tools enabled, 4 disabled, 0 unknown (scopes from provider)'
manager.call_tool(connection, "send_email", {"to": ["ada@example.com"], …})
```

Persist the connection wherever you like:

```python
saved = connection.to_dict()                       # JSON-safe dict for your DB or vault
connection = Connection.from_dict(saved)
```

## Browse the catalogue

```python
len(manager)                       # 1633
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

2,174 connectors is too many to hand a UI at once. Ask for a page by number or
by raw `offset` and you get a `ConnectorPage` carrying the items **and** the
numbers a picker needs — including `total`, counted before paging, so rendering
"showing 21-40 of 2,174" never costs a second call.

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

Examples elsewhere in this document use the sync manager; add `await` for async.

## Auth mode coverage

| Auth mode | Connectors | Support |
| --- | --- | --- |
| `API_KEY` | 921 | Full — connect and verify |
| `OAUTH2_CC` | 129 | Full — client-credentials exchange, including basic, custom and `private_key_jwt`, plus refresh |
| `BASIC` | 112 | Full — connect and verify |
| `TWO_STEP` | 63 | Full — token exchange, chained `additional_steps`, cookie and header extraction, refresh |
| `JWT` | 4 | Full — signed locally with HMAC, RSA or EC |
| `NONE`, `INSTALL_PLUGIN` | 3 | Full |
| `SIGNATURE` | 1 | Full — WS-Security UsernameToken |
| `TBA` | 1 | Full — OAuth 1.0a HMAC-SHA256 request signing |
| `OAUTH2` | 364 | Import tokens from your own OAuth layer; the refresh-token grant runs here |
| `MCP_OAUTH2`, `MCP_OAUTH2_GENERIC`, `OAUTH1`, `APP`, `CUSTOM` | 32 | Import tokens; request signing works once imported |
| `BILL`, `AWS_SIGV4` | 3 | Not implemented — raises `UnsupportedAuthModeError` |

**1,239 connectors connect end to end from user-supplied values alone.** The
remaining 399 need a token you obtained elsewhere, or an auth mode this package
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

## Tools: what a connector can *do*

A connection proves the credentials work. The next question an agent asks is
*what can I do with it* — and, when the client id and secret were granted only
part of what the app asked for, *what can I actually do with it*.

Tools answer both. Each one is a named capability with a description, typed
inputs, a described output, and the scopes the provider demands for it:

```python
manager.list_tools("outlook")                 # 54 tools
manager.get_tool("outlook", "send_email_with_file_attachments")
manager.tool_specs("outlook", format="anthropic")   # ready for the Messages API
```

### Which of them may this credential use?

`check_tools()` compares each tool's required scopes against the grant recorded
on the connection. No network, no guessing:

```python
report = manager.check_tools(connection)
report.summary()
# 'outlook: 20/54 tools enabled, 34 disabled, 0 unknown (scopes from credentials.scope)'

report.enabled_names()[:3]        # ['list_messages', 'search_messages', 'get_message']
report.status("send_email").missing_scopes    # ['Mail.Send']
report.missing_scopes()           # every scope that would unlock at least one more tool
```

Three states, not two. A tool is **disabled** only when the grant is known and
does not cover it; when nothing on the connection says what was granted — the
usual case for a bare API key — it is **unknown**, and a UI should say so rather
than grey it out.

To get the authoritative answer, ask the provider:

```python
manager.discover_scopes(connection)   # ScopeDiscovery(scopes=[...], source='provider')
manager.check_tools_live(connection)  # the same report, judged on the real grant
```

`discover_scopes` reads the access token's own claims where the provider issues
a JWT (Microsoft, Salesforce — no request at all), calls the token-info endpoint
where it has one (HubSpot, Google, SendGrid), or reads a response header
(GitHub, Slack). Where a connector declares neither, it falls back to whatever
the connection recorded, so there is always an answer — check `.known` to tell
*no scopes* from *could not tell*.

### Calling one

```python
result = manager.call_tool(connection, "send_email_with_file_attachments", {
    "to": ["ada@example.com"],
    "subject": "Q3 report",
    "body": "<p>Attached.</p>",
    "attachments": [
        {"name": "q3.pdf", "content_bytes": base64_pdf, "content_type": "application/pdf"}
    ],
})
result.ok, result.status, result.data
```

Arguments are validated against the tool's input schema first, so a bad call
fails locally with every problem named rather than as a provider 400. A tool the
recorded grant rules out raises `ToolPermissionError` before a request is sent;
an *unknown* grant never blocks, because the provider gets the final say.
`prepare_tool_request()` returns the fully authenticated request without sending
it, for runtimes that own the HTTP call or want a human to approve it first.

Everything works identically on `AsyncConnectorManager`.

### Four tiers of coverage

A connector's tools come from one of four places, and `pack.generated` says
whether a pack was written or built:

- **Hand-authored packs** — researched against the provider's own reference,
  with typed inputs, described outputs and real scope names. The best tier, and
  the only one carrying scopes.
- **Spec-generated packs** — built by `scripts/generate_from_openapi.py` from a
  provider's own published OpenAPI specification. Real paths, methods,
  parameters and descriptions, all lifted from the spec; operations it does not
  describe well enough to build a usable tool from are skipped rather than
  guessed at. Each file records the spec URL it came from. They carry no scopes
  and cover a slice of the API rather than all of it, so replacing one with a
  researched pack is a straight improvement.
- **A generated `check_connection` tool** — for a connector with no pack yet,
  built from the verification endpoint its catalogue entry already declares.
  That endpoint is real, in-repo data rather than a guess about the provider's
  API. A connector that declares no such endpoint does not get one; nothing is
  invented.
- **Raw authenticated request tools** — `get_from_api`, `post_to_api`,
  `put_to_api`, `patch_api`, `delete_from_api`. Every connector with a base url
  gets these, so none is dark. They take a path and an optional query or body,
  apply the connection's credentials, and claim nothing about which endpoints
  exist — the caller has to know the provider's API. They are the escape hatch,
  not the destination: a named tool is always better where one exists.

```python
manager.has_authored_tools("hubspot")        # True  -- a researched pack
manager.has_authored_tools("a-leads")        # False
[t.name for t in manager.list_tools("a-leads")]
# ['get_from_api', 'post_to_api', 'put_to_api', 'patch_api', 'delete_from_api']

manager.call_tool(connection, "get_from_api", {"path": "/v1/leads", "query": {"limit": 25}})
manager.tool_stats()["connectors_without_tools"]   # only those with no base url at all
```

Every connector and its full tool list is in [TOOLS.md](TOOLS.md), generated
from the registry by `python scripts/scaffold_tools.py --catalogue`.

### Coverage

Every connector exposes tools. [TOOLS.md](TOOLS.md) lists every connector, where
its tools come from and every tool name, and is regenerated by
`python scripts/scaffold_tools.py --catalogue` (CI fails if it is stale).

Every bundled tool is checked in CI: its request must build and resolve, its
templates may only read arguments it declares, every argument it declares must
reach the request, and its read-only and destructive flags must match its HTTP
verb.

## Adding tools for a connector

Tools are data, in `data/tools/<auth-mode>/<connector-id>.json` — the same
one-file-per-auth-mode sharding the connector catalogue uses. No code change, no
registry edit.

```bash
python scripts/scaffold_tools.py --new stripe   # writes the file in the right folder
python scripts/scaffold_tools.py --check        # lints every pack
python scripts/scaffold_tools.py --list         # what is covered so far
python scripts/build_index.py                   # after adding or renaming a pack
```

One tool looks like this:

```json
"create_contact": {
  "title": "Create a contact",
  "description": "Create a contact record. `properties` is a map of HubSpot internal property names to values — email, firstname, lastname, lifecyclestage and any custom property. Email is the deduplication key.",
  "category": "crm.contacts",
  "scopes": ["crm.objects.contacts.write"],
  "request": {
    "method": "POST",
    "path": "/crm/v3/objects/contacts",
    "body": {"properties": "${properties}"}
  },
  "input": {
    "properties": {"type": "object", "description": "Internal property name to value."}
  },
  "output": {
    "description": "The created contact.",
    "type": "object",
    "properties": {"id": {"type": "string"}}
  }
}
```

`scopes` means *all* of these; use `scopes_any` when any one of them will do.

`${argument}` binds at call time. A value that is exactly one placeholder keeps
the argument's own type — an object stays an object; an embedded one is
interpolated into the surrounding string. A placeholder whose argument was not
supplied drops its key, which is how optional arguments vanish from the query
string and the body rather than arriving as `null`.

An object that wanted content and got none disappears too, rather than being
sent as `{}` — which most providers read as *clear this field*. Where an
object's point is a single optional argument, `$when` makes that explicit:

```json
"body": {
  "$when": "${body}",
  "contentType": "${body_type}",
  "content": "${body}"
}
```

Renaming a draft must not PATCH an empty body over it, which is what `$when`
prevents.

Three more constructs cover the shapes providers actually want:

`$map` turns a list of plain values into a list of provider-shaped objects;
`$keyed` does the same but keys them into an object, as Planner's assignments
want; `$mime` turns ordinary fields into a base64url RFC 2822 message, which is
what Gmail's send API takes.

```json
"toRecipients": {
  "$map": {
    "source": "${to}",
    "template": {"emailAddress": {"address": "${item}"}}
  }
},
"assignments": {
  "$keyed": {
    "source": "${assignee_ids}",
    "key": "${item}",
    "value": {"@odata.type": "#microsoft.graph.plannerAssignment"}
  }
},
"raw": {
  "$mime": {
    "to": "${to}",
    "subject": "${subject}",
    "body": "${body}",
    "attachments": "${attachments}"
  }
}
```

`encoding: form` sends the body as `application/x-www-form-urlencoded` with
bracket notation for nested values, which is what Stripe and Twilio take.
`base_url_override` wins over the connector's own base url for one call.

A pack can also declare how its provider spells scopes and how to read a live
credential's real ones:

```json
"applies_to": ["outlook"],
"scope_rules": {
  "case_insensitive": true,
  "strip_prefixes": ["https://www.googleapis.com/auth/"],
  "implies": {"Mail.ReadWrite": ["Mail.Read"]}
},
"scope_discovery": {"jwt_claim": "scp"}
```

`applies_to` lists other connector ids this same pack serves. `scope_discovery`
also accepts an endpoint plus `scopes_path`, or `header:x-oauth-scopes`.

`pytest tests/test_tool_packs.py` runs the same contract as `--check` over every
bundled pack.

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

Or skip the endpoints entirely and hand the model the connector's own tools,
narrowed to what the credential may call:

```python
connection = Connection.from_dict(saved_connection)
tools = manager.check_tools(connection).specs(format="anthropic")

# ...pass `tools` to the Messages API, then run what comes back:
result = manager.call_tool(connection, tool_use.name, tool_use.input)
result.to_dict()          # {'ok': True, 'status': 200, 'data': {...}}
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
- `check_tools()` keeps a disabled capability out of the model's context
  altogether, so it cannot spend a turn attempting something the token forbids —
  and `report.missing_scopes()` tells your app exactly what to ask the user to
  re-authorise.
- `call_tool()` validates arguments against the tool's schema before sending, so
  a malformed call comes back as a list of named problems the model can fix,
  not as a provider 400.
- Every tool carries `read_only` and `destructive` flags, so an approval policy
  can gate the calls that matter without hard-coding a list of endpoints.
- Browsing costs no network calls, so catalogue exploration never burns rate
  limit or wall-clock time.

## Command line

Installing the package installs a `connectors` command, equivalent to
`python -m connector_manager`:

```bash
connectors list --search hubspot
connectors list --page 2 --page-size 20        # showing 21-40 of 1633 · page 2/82
connectors list --all --page-size 200          # page through everything
connectors show 1password-users                # every field it needs
connectors stats                               # totals by auth mode and category
connectors icon stripe -o stripe.svg
connectors connect affinity-v2 -c apiKey=… -o conn.json
connectors request conn.json GET /v2/persons

connectors tools outlook                       # every tool, grouped by category
connectors tools slack --format anthropic      # LLM tool definitions on stdout
connectors tool hubspot create_contact         # one tool: inputs, output, scopes
connectors check-tools conn.json               # enabled / disabled / unknown
connectors check-tools conn.json --live        # ask the provider for the real grant
connectors call conn.json send_email -a subject=Hi -a 'to:=["ada@example.com"]'
```

`-c` sets a credential, `-x` a connection-config value, `-i` an
integration-config value, all as `key=value`. For `call`, `-a key=value` passes a
string and `-a key:=<json>` passes anything else — lists, objects, numbers,
booleans.

`check-tools` prints one line per tool, `+` enabled, `-` disabled with the
missing scope named, `?` unknown, and ends with the set of scopes that would
unlock the rest:

```
outlook: 20/54 tools enabled, 34 disabled, 0 unknown (scopes from credentials.scope)
granted: Mail.Read Mail.ReadWrite User.Read
 + list_messages                          List mailbox messages
 - send_email                             needs Mail.Send
 - send_email_with_file_attachments       needs Mail.Send
 + create_draft                           Create a draft email
```

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
| `registry.py` | `ConnectorRegistry` | merges `data/connectors/*.json` and icons, pagination, builds `AuthSchema` |
| `models.py` | `Connector`, `ConnectorPage`, `AuthField`, `AuthSchema`, `Connection`, `AuthMode` | the data model |
| `auth/` | `AuthStrategy` subclasses | one class per auth mode |
| `flows.py` | `FlowRunner`, `AsyncFlowRunner` | drive one auth flow either sync or async |
| `http.py` | `Request`, `HttpResponse`, `HttpClient`, `AsyncHttpClient` | the only I/O in the package |
| `proxy.py` | `RequestBuilder` | base urls, auth headers, query templates, OAuth1 and TBA signing |
| `verification.py` | `CredentialVerifier`, `VerificationResult` | proves credentials work |
| `validation.py` | — | required, pattern, enum, format, `visible_when` |
| `interpolation.py` | — | the `${…}` template engine |
| `tools/models.py` | `Tool`, `ToolPack`, `ToolReport`, `ScopeRules`, `ToolResult` | the tool data model |
| `tools/registry.py` | `ToolRegistry` | resolves `data/tools/index.json`, loads a pack on first use |
| `tools/permissions.py` | `ScopeDiscoverer`, `build_report` | grant vs. required scopes, live discovery |
| `tools/executor.py` | `ToolExecutor` | argument validation, template binding, result parsing |
| `src/data/connectors/` (shared) | — | connector definitions, one JSON file per auth mode |
| `src/data/tools/` (shared) | — | tool packs, one JSON file per connector, plus `index.json` |
| `src/data/icons/` (shared) | — | one SVG logo per connector |

Run the suite with `uv run pytest -q`. Coverage includes the whole
catalogue: every connector must expose a name, an icon, a buildable auth schema
and a fully resolved request with no leftover `${…}` in urls or headers, plus
mocked connect, refresh and verify flows for each supported auth mode. The async
suite asserts the async manager returns byte-identical credentials to the sync
one for the same provider response.

Every one of the bundled tools is checked the same way: it must sit in the folder
matching its connector's auth mode, build a request that resolves with no
leftover `${…}` anywhere, read only arguments it declares, use every argument it
declares, keep its `read_only` and `destructive` flags consistent with its HTTP
verb, and serialise to a valid tool definition in all three LLM formats.

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

Documentation links are intentionally absent from the catalogue. It carries
only what is needed to authenticate and call each API: auth mode, field
definitions, base url, verification endpoint.

### Where the definitions live

The catalogue is split by auth mode, one file per mode under
`src/data/connectors/`:

```
data/connectors/api-key.json
                oauth2.json
                oauth2-cc.json
                basic.json
                two-step.json
                ...one file per auth mode
```

The registry loads every `*.json` under that directory and merges them, so the
layout is an organisational detail rather than API: ids stay unique across
files, and an alias resolves against its target wherever that target lives.
`ConnectorRegistry(connectors_file=...)` still accepts a single JSON file if you
ship your own catalogue.

`python scripts/split_connectors.py` regroups the files after an `auth_mode`
changes; `--check` reports drift and is what CI runs.

Tool packs sit alongside, sharded the same way — one file per connector, in the
folder for that connector's auth mode:

```
data/tools/oauth2/microsoft.json     54 tools  (also serves outlook)
                  hubspot.json       32
                  github.json        27
                  ...
           api-key/sendgrid.json     13
           basic/twilio.json          9
           oauth1/trello.json        12
```

`python scripts/scaffold_tools.py --new <connector-id>` writes a skeleton in the
right folder; `--check` lints every pack and is what CI runs.

## Project files

| File | What it covers |
| --- | --- |
| [CHANGELOG.md](CHANGELOG.md) | What changed in each release |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Adding a connector, changing the machinery, house style |
| [SECURITY.md](SECURITY.md) | Reporting a vulnerability, and handling credentials safely |
| [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) | How we treat each other |
| [docs/added-connectors.md](docs/added-connectors.md) | Provenance and live check behind every connector added in 0.1.2 |
| [docs/azure-and-vector-connectors.md](docs/azure-and-vector-connectors.md) | Azure's control and data planes, and the vector, graph and database connectors |
| [TOOLS.md](TOOLS.md) | Every connector and the tools it exposes, generated |
| [docs/tools.md](docs/tools.md) | The tool pack format, field by field |
| [scripts/split_connectors.py](scripts/split_connectors.py) | Regroups the catalogue into one file per auth mode |
| [scripts/scaffold_tools.py](scripts/scaffold_tools.py) | Scaffolds and lints connector tool packs |
