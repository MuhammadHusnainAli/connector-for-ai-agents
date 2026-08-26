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

Connectors live in `src/connector_manager/data/connectors.yaml`, one key per
connector, sorted alphabetically. A minimal API-key entry:

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

Then check your work:

```bash
python -m pytest -q                       # test_proxy asserts every connector
                                          # builds a fully resolved request
connectors show example-app               # fields render as intended
connectors connect example-app -c apiKey=... -o /tmp/c.json
connectors request /tmp/c.json GET /me    # a real call, if you have a key
```

Please don't modify existing connector definitions in the same change as adding
new ones — it makes review much harder.

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
