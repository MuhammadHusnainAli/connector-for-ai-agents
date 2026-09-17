# The tool pack format

A **tool** is one concrete thing an agent can do with a connector — "send an
email with a file attachment", "create a HubSpot deal", "append rows to a
sheet". It carries everything an LLM runtime needs (name, description, typed
inputs, described output) *and* everything this package needs to actually run it
(HTTP method, path, query and body templates), plus the OAuth scopes the
provider demands for it.

Tools are data. One YAML file per connector, in the folder for that connector's
auth mode:

```
src/connector_manager/data/tools/<auth-mode>/<connector-id>.yaml
```

`data/tools/oauth2/hubspot.yaml` holds every HubSpot tool and nothing else.
Adding a connector's tools means adding one file — no code change, no registry
edit.

```bash
python scripts/scaffold_tools.py --new stripe   # write the skeleton
python scripts/scaffold_tools.py --check        # lint every pack
python scripts/scaffold_tools.py --list         # what is covered so far
python scripts/scaffold_tools.py --readme       # refresh README's coverage table
python scripts/scaffold_tools.py --backlog      # what still needs a pack
pytest tests/test_tool_packs.py                 # the same contract, in CI
```

## Four ways a connector gets tools

Everything below describes a **hand-authored** pack — a file you write against
the provider's reference. That is the best tier, and the only one that always
carries scope annotations. Three others fill the gap:

**Generated from the provider's OpenAPI specification.** Where a provider
publishes a machine-readable spec, `scripts/generate_from_openapi.py` turns it
into a pack: real paths, real methods, real parameters, real descriptions, all
lifted from the spec. The file records the spec URL it came from in
`generated_from` and sets `generated: true`. Nothing is inferred — operations
the spec does not describe well enough to build a usable tool from are skipped.

```bash
# from the apis.guru directory
python scripts/generate_from_openapi.py --connector telnyx --guru telnyx.com

# from a spec URL you know
python scripts/generate_from_openapi.py --connector acme --spec https://api.acme.com/openapi.json

# discover specs on connectors' own hosts, then build in bulk
python scripts/discover_openapi.py --out plan.json
python scripts/generate_from_openapi.py --plan plan.json
```

These packs cover a representative slice of the API rather than its whole
surface, and carry no scopes, so `check_tools` reports every tool as enabled.
Replacing one with a researched pack is a straight improvement — drop the
`generated` flag when you do.

**Generated from a Google discovery document.** Google publishes a richer
description of its APIs than a normal OpenAPI spec: alongside paths, parameters
and enums, it states *the OAuth scopes each individual method requires*. That
makes `scripts/generate_from_google_discovery.py` a tier of its own — the packs
it writes cover the whole API surface and carry real per-tool scopes, so
`check_tools()` gives a truthful answer on them.

```bash
python scripts/generate_from_google_discovery.py \
    --connector google-tasks \
    --discovery "https://tasks.googleapis.com/\$discovery/rest?version=v1"

# an API the connector's own base url does not serve
python scripts/generate_from_google_discovery.py \
    --connector google-play \
    --discovery "https://androidpublisher.googleapis.com/\$discovery/rest?version=v3" \
    --base-url https://androidpublisher.googleapis.com
```

What the script adds beyond the document is presentation: readable snake_case
names in place of Google's dotted method ids (`tasklists.insert` becomes
`create_task_list`), a category per resource, and read-only and destructive
hints taken from the HTTP verb. `--rename` and `--skip` override either.

**Raw authenticated request tools.** Every connector with a base url gets
`get_from_api`, `post_to_api`, `put_to_api`, `patch_api` and `delete_from_api`.
They take a `path` plus an optional `query` object and `body`, apply the
connection's credentials, and send the request — exactly what `manager.request`
already does, exposed as tools so an agent that knows the provider's API can
drive a connector with no pack. They assert nothing about which endpoints
exist. Writing a pack for a connector replaces them.

A whole-path argument keeps its slashes; only path *segments* interpolated into
a longer template are percent-encoded.

**A synthesised `check_connection` tool.**

A connector with neither a written nor a generated pack still gets one tool,
synthesised at runtime from the `proxy.verification` endpoint its catalogue
entry already declares:

```python
manager.list_tools("manatal")            # [check_connection]
manager.tool_pack("manatal").generated   # True
```

That endpoint is real data already in the repo, so the tool genuinely works —
but it is the only call this package can vouch for on that connector, and the
tool's own description says so. A connector whose entry declares no verification
endpoint gets nothing; nothing is ever inferred about a provider's API.

Writing a pack for a connector replaces its generated tool entirely.

---

## Pack-level fields

```yaml
connector_id: microsoft            # required; must match the file name
display_name: Microsoft 365 (Graph)
docs_url: https://learn.microsoft.com/graph/api/overview
applies_to: [outlook]              # other connector ids this same pack serves
scope_rules: {...}
scope_discovery: {...}
tools: {...}
```

| Field | Required | Meaning |
| --- | --- | --- |
| `connector_id` | yes | The connector in the catalogue this pack serves. |
| `display_name` | yes | Shown by `connectors tools <id>`. |
| `docs_url` | yes | The provider's API reference. A reviewer has to be able to check the scopes. |
| `applies_to` | no | Extra connector ids served by this pack. They must share the connector's auth mode. |
| `scope_rules` | no | How the provider spells scopes; see below. |
| `scope_discovery` | no | How to read a live credential's real scopes; see below. |
| `tools` | yes | Map of tool name to definition. Names are snake_case. |

### `applies_to`, and why aliases are not followed

`outlook` is an alias of `microsoft` in the catalogue and they are the same API
behind the same token, so `microsoft.yaml` declares `applies_to: [outlook]` and
one pack serves both.

Sharing is *explicit* rather than inherited from the alias chain, because an
alias does not imply a shared API surface: `google-mail`, `google-calendar` and
`google-drive` all alias `google`, and each needs a completely different set of
tools.

---

## A tool

```yaml
tools:
  create_contact:
    title: Create a contact
    description: >-
      Create a contact record. `properties` is a map of HubSpot internal
      property names to values — email, firstname, lastname, lifecyclestage and
      any custom property. Email is the deduplication key.
    category: crm.contacts
    scopes: [crm.objects.contacts.write]
    read_only: false
    destructive: false
    notes: Engagements also need the write scope of the record they attach to.
    docs_url: https://developers.hubspot.com/docs/api/crm/contacts
    request: {...}
    input: {...}
    output: {...}
```

| Field | Required | Meaning |
| --- | --- | --- |
| `title` | no | Short human label. Defaults to the name, title-cased. |
| `description` | yes | What it does, what it returns, and when to reach for a different tool. At least 40 characters — this is what the model reads. |
| `category` | yes | Groups tools in listings, e.g. `mail.send`, `crm.deals`. |
| `scopes` | no | Scopes the caller needs **all** of. |
| `scopes_any` | no | Scopes the caller needs **any one** of. |
| `read_only` | no | True for a call that only reads. Required on `GET`; forbidden on `PUT`/`PATCH`/`DELETE`. |
| `destructive` | no | True when a mistake is not undoable — deletes, sends, payments. Required on `DELETE`. |
| `notes` | no | A caveat a reviewer or a runtime should know. |
| `docs_url` | no | Per-tool reference; defaults to the pack's. |
| `request` | yes | The HTTP call. |
| `input` | yes | The arguments, as an ordered map. May be `{}`. |
| `output` | yes | What comes back. |

`read_only` and `destructive` become MCP's `readOnlyHint` and `destructiveHint`,
so an approval policy can gate on them without hard-coding endpoints.

---

## `request`

```yaml
request:
  method: POST                 # GET, POST, PUT, PATCH, DELETE
  path: /crm/v3/objects/contacts/${contact_id}
  query:
    limit: "${limit}"
  headers:
    Prefer: 'outlook.timezone="${timezone}"'
  body:
    properties: "${properties}"
  encoding: json               # or `form`
  content: "${raw_text}"       # raw pre-encoded body, instead of `body`
  base_url_override: https://oauth2.googleapis.com
```

`path` is relative to the connector's `proxy.base_url`, which the connection
resolves — so a Shopify path starts at `/admin/api/...` and the shop's subdomain
comes from the connection. `base_url_override` wins over it for one call.

`encoding: form` sends the body as `application/x-www-form-urlencoded` with
bracket notation for nested values (`metadata[tier]=gold`), which is what Stripe
and Twilio take.

A tool never writes the connector's own credentials into its `body`. Where a
provider authenticates from inside the payload rather than from a header —
Adyntel's `api_key`/`email`, Mandrill's `key`, Sage's nested `auth` — the
catalogue records that as `proxy.body`, and the request builder merges it under
whatever the tool sent. The tool's own body wins on a conflict, nested objects
merge rather than replace, and a request with no JSON body of its own is left
alone, so a `GET` never acquires one.

### Template binding

`${argument}` binds at call time:

* a value that is **exactly one placeholder** keeps the argument's own type —
  `"${properties}"` with an object argument sends an object, not its `repr`;
* an **embedded** placeholder is interpolated into the surrounding string;
* a placeholder whose argument was **not supplied** drops its key, which is how
  optional arguments vanish from the query string and the body rather than
  arriving as `null`;
* an object that **wanted content and got none** disappears rather than being
  sent empty — `assignee: {id: "${assignee}"}` with no assignee sends nothing,
  not `assignee: {}`, which providers read as "clear this field". A template
  that literally asks for `{}` (Drive's `folder: {}`) is untouched, since it
  wanted nothing;
* values substituted into `path` are percent-encoded, so a message id with a `/`
  in it cannot address a different resource.

A placeholder that names no declared argument is left for the `RequestBuilder`
to resolve from the connection — that is how Jira's `${cloudId}` and Twilio's
`${username}` (the Account SID) get in without being tool arguments.

### `$map`

Providers overwhelmingly want a list of shaped objects where a tool should
accept a list of plain values:

```yaml
body:
  message:
    toRecipients:
      $map:
        source: "${to}"
        template: {emailAddress: {address: "${item}"}}
```

`["ada@example.com"]` becomes Graph's recipient objects. Inside `template`,
`${item}` is the element and `${index}` its position. When `source` is not
supplied the whole node disappears.

### `$keyed`

The mirror of `$map` for providers that want a map rather than a list. Planner's
`assignments` is keyed by user id, so a tool can still take a plain list of ids:

```yaml
assignments:
  $keyed:
    source: "${assignee_ids}"
    key: "${item}"
    value:
      "@odata.type": "#microsoft.graph.plannerAssignment"
      orderHint: " !"
```

### `$when`

An object whose point is one optional argument still has its defaults and
literals in it, so it survives even when that argument is absent — and
`{"contentType": "HTML"}` with no `content` reads to Graph as *set the body to
nothing*. `$when` makes the whole object conditional on the argument that
justifies it:

```yaml
body:
  $when: "${body}"          # no body argument, no body object at all
  contentType: "${body_type}"
  content: "${body}"
```

The guard accepts the same expressions as any other template, so
`$when: "${body} || ${html_body}"` keeps the node alive if either is supplied.
Reach for it wherever a nested object pairs an optional argument with a
defaulted or literal sibling — a Graph message body, a Zendesk comment, a
HubSpot filter group, a SendGrid content entry.

### `$mime`

Gmail's send endpoints accept only a raw RFC 2822 message, which is not
something a model can be asked to produce. `$mime` assembles one from ordinary
fields and base64url-encodes it:

```yaml
body:
  raw:
    $mime:
      to: "${to}"
      cc: "${cc}"
      subject: "${subject}"
      body: "${body}"
      body_type: "${body_type}"     # html (default) or text
      attachments: "${attachments}"
      in_reply_to: "${in_reply_to}" # threads the reply
```

`attachments` items are `{"name": ..., "content_bytes": <base64>,
"content_type": ...}` — the same shape the Microsoft Graph tools take, so one
caller-side attachment structure serves both providers.

---

## `input`

An ordered map of argument name to schema. `optional: true` marks an argument
optional, matching how the connector catalogue spells it.

```yaml
input:
  limit:
    type: integer
    description: How many contacts per page (1-100).
    optional: true
    default: 50
    minimum: 1
    maximum: 100
  properties:
    type: array
    description: Contact properties to return.
    optional: true
    items: {type: string}
  status:
    type: string
    description: Only contacts in this state.
    optional: true
    enum: [active, archived]
```

| Field | Meaning |
| --- | --- |
| `type` | `string`, `integer`, `number`, `boolean`, `array`, `object`. |
| `description` | Required. What it is and what shape it takes. |
| `optional` | `true` to make it optional. Everything is required by default. |
| `default` | Filled in when the argument is absent. Only on optional arguments. |
| `enum` | Allowed values. A `default` must be one of them. |
| `example` | Shown in the CLI and in the JSON Schema's `examples`. |
| `pattern`, `format` | Regex and JSON-Schema format hints. |
| `minimum`, `maximum` | Numeric bounds, enforced at call time. |
| `min_length`, `max_length` | String length, or list length. |
| `items` | Required on `array`: the element schema. |
| `properties` | On `object`: named sub-properties, descriptive. |
| `secret` | Marks a value that must not be logged. |

Arguments are validated before anything is sent, and coerced forgivingly —
`"25"` for an integer, `"true"` for a boolean, a bare value where a list is
wanted — because that is what LLM runtimes emit. Everything that fails is
reported at once, so a model can fix the whole call in one retry.

Two rules the lint enforces, both of which catch real mistakes:

* **every declared argument must be read by some template**, or it is dead
  weight in the schema the model sees;
* **no template may read an undeclared argument**, unless it is a
  connection-scoped value the connector itself resolves.

---

## `output`

```yaml
output:
  description: A page of contacts, with the cursor for the next page.
  type: object                 # object, array or string
  response_path: results       # dot path to the useful part of the response
  properties:
    results: {type: array, description: "The contact records."}
    paging: {type: object, description: "Holds next.after."}
  items: {type: object}        # required when type is array
```

`response_path` unwraps a provider envelope on the way out: Graph's `value`,
Asana's `data`, Linear's `data.issueCreate`. `call_tool` returns the unwrapped
value as `result.data`.

---

## `scope_rules`

Providers spell scopes differently enough that a plain set intersection gets the
answer wrong. Each pack declares the rules its provider follows:

```yaml
scope_rules:
  case_insensitive: true                                  # Microsoft
  strip_prefixes: ["https://www.googleapis.com/auth/"]    # Google
  expand_groups: true                                     # Accelo
  implies:                                                # hierarchical grants
    Mail.ReadWrite: [Mail.Read]
    write: [read]
```

`implies` is expanded transitively, so `admin: [write]` and `write: [read]`
together mean an `admin` grant satisfies a tool that asks for `read`.

`expand_groups` is for providers whose single scope names several objects at
once. Accelo grants `read(companies,contacts)`, which is one scope, not two —
without the rule it matches neither `read(companies)` nor `read(contacts)` and a
real grant is reported as missing. Scope splitting ignores separators inside
parentheses for the same reason, so the grant reaches the rule intact. Leave it
off unless the provider actually documents that form; everywhere else a comma is
a separator.

`scopes` on a tool means *all of these*; `scopes_any` means *any one of these*,
for the providers that accept alternatives (`Mail.Send` **or** `Mail.ReadWrite`).
A tool with neither is always enabled — the provider gates it on the credential
existing, not on a scope. That is the honest answer for Notion, Asana, Intercom
and the others whose permissions are configured on the app rather than carried
on the token.

---

## `scope_discovery`

How to ask the provider what a live credential really holds. Three shapes:

```yaml
# 1. The access token is a JWT whose claim *is* the grant. No request at all.
scope_discovery:
  jwt_claim: scp            # `roles` is also read, for app-only tokens

# 2. A token-info endpoint returns them.
scope_discovery:
  method: GET
  endpoint: /oauth/v1/access-tokens/${credentials.access_token}
  scopes_path: scopes       # dot path into the JSON response

# 3. A response header carries them.
scope_discovery:
  method: GET
  endpoint: /user
  scopes_path: "header:x-oauth-scopes"
  separator: ","
```

`base_url_override`, `query` and `headers` are also accepted, which is how
Google's `https://oauth2.googleapis.com/tokeninfo?access_token=…` is reached.

With none declared, `discover_scopes()` falls back to whatever the connection
recorded, so the caller always gets an answer — check `.known` to tell *no
scopes* from *could not tell*.

---

## What the lint checks

`python scripts/scaffold_tools.py --check`, and `tests/test_tool_packs.py` in CI:

- the file is named `<connector_id>.yaml` and sits in the folder matching that
  connector's auth mode;
- `connector_id` and every `applies_to` id exist in the catalogue and share an
  auth mode, and no connector is claimed by two packs;
- `docs_url` points at the provider's reference and is not the scaffold
  placeholder;
- tool names are snake_case and unique; descriptions are at least 40 characters;
  every tool has a category and describes its output;
- methods are one of `GET POST PUT PATCH DELETE`; paths start with `/`; a `GET`
  carries no body and is marked `read_only`; a `DELETE` is marked `destructive`;
  `read_only` and `destructive` are never both set;
- every argument is typed, described, and reached by some template; no template
  reads an undeclared argument; a path placeholder is required or has a default;
  arrays declare `items`; an enum default is one of its values;
- **every tool builds a request that actually resolves** — synthetic arguments
  are fed through the real executor and the url, query, headers and body must
  come back with no leftover `${…}`;
- **README's coverage table matches the bundled packs**, so it cannot go stale;
- **building with only the required arguments sends nothing hollow** — no empty
  object and no empty array anywhere in the body, which is what catches a
  nested object that needed a `$when` guard;
- calling a tool with no arguments names every missing required one;
- every tool serialises to a valid Anthropic, OpenAI and MCP tool definition.
