# Contributing

Thanks for helping. Most contributions here are one of two things: **a new
connector** or **a fix to the connection machinery**.

## Getting set up

```bash
git clone https://github.com/MuhammadHusnainAli/connector-for-ai-agents
cd connector-for-ai-agents
uv sync --extra dev        # or: pip install -e ".[dev]"
uv run pytest -q           # or: python -m pytest -q
```

Python 3.10+ . The connector data is bundled, so the test suite needs no
network.

## Adding a connector

Connectors live in `src/connector_manager/data/connectors/`, **one file per auth
mode** — an `API_KEY` connector goes in `api-key.yaml`, an `OAUTH2` one in
`oauth2.yaml`, and so on. Within a file, one key per connector, sorted
alphabetically. A minimal API-key entry:

```yaml
example-app:
  auth_mode: API_KEY
  categories:
    - productivity
  credentials:
    apiKey:
      title: API Key
      description: Your Example App API key.
      type: string
      secret: true
  display_name: Example App
  proxy:
    base_url: https://api.example.com/v1
    headers:
      authorization: Bearer ${apiKey}
    verification:
      endpoints:
        - /me
      method: GET
```

What a good entry needs:

- **`base_url` from the provider's own API reference** — not a documentation
  site, not a marketing page, not a sandbox host.
- **The credential in the right place.** `API_KEY` connectors carry **no**
  default header: whatever `proxy.headers` or `proxy.query` says is exactly what
  gets sent. Getting the header name wrong produces a connector that always
  fails to authenticate.
- **A `verification` endpoint** that is cheap, read-only, and requires auth. Call
  it unauthenticated first — a `401` or `403` proves both the base url and the
  endpoint. Leave the block out rather than guess.
- **A per-tenant url** where the API lives on the customer's own host, written as
  `https://${connectionConfig.domain}` with a matching `connection_config` field.
- **An icon**: `src/connector_manager/data/icons/<connector-id>.svg`, a 62×62
  SVG matching the others. Use the vendor's own logo.
- **Categories** drawn from the set already in use — run `connectors stats` to
  see them.

Ids must be unique across all the files — the loader refuses a duplicate rather
than letting filename order pick a winner. An **alias** may sit in a different
file from its target; that resolves fine, but the alias belongs in the file for
the mode it ends up with, which the script below sorts out for you.

Then check your work:

```bash
python scripts/split_connectors.py        # puts every entry in the right file
python -m pytest -q                       # test_proxy asserts every connector
                                          # builds a fully resolved request
connectors show example-app               # fields render as intended
connectors connect example-app -c apiKey=... -o /tmp/c.json
connectors request /tmp/c.json GET /me    # a real call, if you have a key
```

If you change a connector's `auth_mode`, re-run the script — it moves the entry
to the matching file. CI runs `--check` and fails on a stale layout.

Please don't modify existing connector definitions in the same change as adding
new ones — it makes review much harder.

## Adding tools for a connector

A connector's *tools* are the named capabilities an agent can call with it —
`send_email_with_file_attachments`, `create_deal`, `merge_pull_request`. They
live in one YAML file per connector, in the folder for that connector's auth
mode, and adding a set needs no code change:

```bash
# If the provider publishes an OpenAPI spec, start from it rather than a blank file:
python scripts/discover_openapi.py --out plan.json          # find specs
python scripts/generate_from_openapi.py --plan plan.json    # build packs from them

python scripts/scaffold_tools.py --new stripe   # writes data/tools/oauth2/stripe.yaml
python scripts/scaffold_tools.py --check        # lints every pack, and README's coverage table
python scripts/scaffold_tools.py --readme       # refreshes that table after adding a pack
python scripts/scaffold_tools.py --backlog      # what still needs a pack, most-connected categories first
python scripts/scaffold_tools.py --catalogue    # regenerate TOOLS.md after adding a pack
python scripts/scaffold_tools.py --backlog --category crm --limit 20
pytest tests/test_tool_packs.py                 # the same contract, in CI
```

[docs/tools.md](docs/tools.md) is the field-by-field reference. What a reviewer
will look for:

- **The description is what the model reads.** Say what the tool does, what it
  returns, and when to reach for a different tool instead — `send_email` versus
  `create_draft` versus `send_email_with_link_attachments`. At least 40
  characters, and the lint enforces that floor rather than blessing it as a
  target.
- **Scopes come from the provider's own docs**, and `docs_url` has to point at
  the page they came from so a reviewer can check them. If a provider does not
  put permissions on the token at all — Notion, Asana, Intercom — declare no
  scopes and say so in the file's header comment. Guessing a scope name is worse
  than declaring none, because a wrong one disables a tool that in fact works.
- **Arguments are the tool's contract.** Every one needs a type and a
  description; every one must be read by some template; no template may read one
  that is not declared. Prefer arguments a model can fill from a conversation
  (`to`, `subject`, `body`) over ones it would have to construct (`raw`,
  `payload`) — `$map` and `$mime` exist so the provider's shape stays in the
  YAML rather than in the caller's head.
- **`read_only` and `destructive` gate approval policies**, so they must match
  the verb: `GET` is read-only, `DELETE` is destructive, and a POST that only
  reads (GraphQL, search endpoints) is read-only too.
- **Keep the pack in one file, sorted by category.** A pack that outgrows its
  file is a sign the connector wants splitting in the catalogue, not that the
  tools want scattering.

- **Guard the objects that hang on one optional argument.** A nested object
  keeps its defaults and literals even when the argument that justifies it is
  absent, and `{"contentType": "HTML"}` with no `content` tells Graph to clear
  the body. Put `$when: "${body}"` on such a node. The suite builds every tool
  with only its required arguments and fails on any empty object or array, which
  is what catches the ones you miss.

The lint builds every tool's request with synthetic arguments and fails if the
url, query, headers or body come back with a leftover `${…}` — so a pack that
passes `--check` will at least reach the provider.

## Changing the machinery

`registry.py` (catalogue), `auth/` (one module per auth mode), `proxy.py`
(request building), `interpolation.py` (`${...}` templates), `verification.py`,
`credentials.py`, `manager.py` (the sync/async facades), `__main__.py` (CLI).

Auth flows are written once as generators of requests and driven by both the
sync and async clients, so the two managers cannot drift. If you add a flow,
write it that way and it works in both.

Add a test for anything you fix. `tests/` uses a stub transport, so tests stay
offline and fast.

## House style

- Follow the surrounding code: type hints, `from __future__ import annotations`,
  short docstrings that say why rather than what.
- Comments earn their place by explaining a decision, not narrating the line.
- Keep the public API stable; `connector_manager/__init__.py` is the surface.

## Pull requests

Small and focused, with a description of what changed and how you verified it.
For a new connector, say which provider documentation you used and paste the
status code the verification endpoint returned unauthenticated.

CI runs the suite on Python 3.10–3.13 and builds the distributions. Green before
review, please.

## Security

Do not open a public issue for a security problem — see [SECURITY.md](SECURITY.md).
