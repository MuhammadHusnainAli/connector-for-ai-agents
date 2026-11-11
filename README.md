# connector-for-ai-agents

**2,000+ API connectors for Python and Rust: the auth fields each one needs, the
code that turns them into a working, verified connection, and tools an AI agent
can call on every connector.**

[![PyPI](https://img.shields.io/pypi/v/connector-for-ai-agents)](https://pypi.org/project/connector-for-ai-agents/)
[![Python](https://img.shields.io/pypi/pyversions/connector-for-ai-agents)](https://pypi.org/project/connector-for-ai-agents/)
[![crates.io](https://img.shields.io/crates/v/connector-for-ai-agents)](https://crates.io/crates/connector-for-ai-agents)
[![CI](https://github.com/MuhammadHusnainAli/connector-for-ai-agents/actions/workflows/ci.yml/badge.svg)](https://github.com/MuhammadHusnainAli/connector-for-ai-agents/actions/workflows/ci.yml)
[![Licence](https://img.shields.io/badge/licence-Elastic%202.0-blue)](LICENSE)

Talking to Stripe, Slack, HubSpot, AWS, Azure or Google Cloud is rarely hard
because of the HTTP call. It is hard because each provider authenticates
differently: a bearer token here, `X-API-KEY` there, a client-credentials
exchange against a per-tenant domain, a signed request on every call. This
project is that knowledge, as data plus a library in two languages.

## Python

```bash
pip install connector-for-ai-agents
```

```python
from connector_manager import ConnectorManager

with ConnectorManager() as manager:
    connection = manager.connect("affinity-v2", credentials={"apiKey": "..."})
    print(connection.verified)                      # checked against the live API
    print(manager.request(connection, "GET", "/v2/persons").json())
```

Full documentation: **[PYTHON.md](PYTHON.md)**.

## Rust

```bash
cargo add connector-for-ai-agents serde_json
```

```rust
use connector_manager::{Call, ConnectOptions, ConnectorManager};
use serde_json::json;

let manager = ConnectorManager::new()?;
let mut connection = manager.connect("affinity-v2", ConnectOptions::new().credentials(json!({"apiKey": "..."})))?;
let response = manager.request(&mut connection, Call::new("GET", "/v2/persons"))?;
```

Full documentation: **[RUST.md](RUST.md)**.

## What you get

- **The catalogue, offline.** 2,000+ connectors, each with its auth mode, every
  field it needs (title, example, pattern, enum, secret), base url and the
  endpoint that proves credentials work. Browsing never touches the network.
- **Connections that work.** API keys, basic auth, OAuth2 client credentials,
  multi-step logins, locally signed JWTs, WSSE, OAuth 1.0a, AWS SigV4 and
  Alibaba Cloud ACS3 signing all complete inside the library, then get verified.
  OAuth redirect flows stay in your app; import the tokens and they are kept fresh.
- **Tools on every connector.** Named capabilities with typed inputs and the
  scopes the provider demands, exported as Anthropic, OpenAI or MCP tool
  definitions, plus a report of which ones a given credential may actually call.
  [TOOLS.md](TOOLS.md) lists every connector and its tools.
- **Sync and async in both languages.** Each auth flow is written once and run
  either way.
- **Your security model stays yours.** Connections are plain objects. Storage,
  encryption and tenancy are up to you.

## One catalogue, two libraries

The Python package and the Rust crate read the same data, so they agree on every
connector, field and tool, and a connection saved by one loads in the other.
They share one version number too: each release tag publishes the same version
to PyPI and crates.io.
`scripts/check_rust_parity.py` builds every connector's schema, a request
through every connector and every tool in both libraries and compares them; CI
fails if they ever differ.

```
src/connector_manager/          Python package (imported as connector_manager)
src/connector_manager/data/     the shared catalogue: connectors, tool packs, icons
src/connector_manager_rs/       Rust crate (imported as connector_manager)
scripts/                        catalogue, tool-pack and parity tooling
```

## More

| | |
| --- | --- |
| [PYTHON.md](PYTHON.md) | Python documentation: install, connect, tools, agents, CLI, internals |
| [RUST.md](RUST.md) | Rust documentation: the same, for the crate |
| [TOOLS.md](TOOLS.md) | Every connector and the tools it exposes (generated) |
| [CHANGELOG.md](CHANGELOG.md) | What changed in each release |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Adding a connector or a tool pack, house style |
| [SECURITY.md](SECURITY.md) | Reporting a vulnerability, handling credentials safely |

## Licence

Source-available under the Elastic License 2.0: use, modify and ship it,
including commercially, but do not offer it as a hosted or managed service. See
[LICENSE](LICENSE).
