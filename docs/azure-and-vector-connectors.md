# Azure, vector and database connectors

47 connectors added: Azure's control plane and the data planes of its individual
services, the vector and search databases an agent retrieves from, and the
managed graph and operational databases around them. The catalogue goes from
1,586 to 1,633 entries.

One existing definition changed: `weaviate` was categorised `other`, which kept
it out of `list_connectors(category="search")` alongside the vector databases it
belongs with. It is now `search`, `dev-tools`. Nothing else about it moved, and
no other existing entry was touched.

## What is here, and what an HTTP connector can and cannot be

This package speaks HTTP. That decides the shape of every entry below, and it is
worth being explicit about two consequences.

**A database that speaks its own wire protocol has no data-plane connector.**
`azure-postgresql` and `azure-mysql` manage *servers* -- create one, list them,
read and change their configuration, firewall rules and databases -- through
Azure Resource Manager. They do not run SQL: PostgreSQL's and MySQL's wire
protocols are not HTTP, so no HTTP connector can. The same is true of
`azure-sql-database`, `redis-cloud` and `upstash` (management APIs, not the
Redis protocol) and of `mongodb-atlas` (the Atlas Admin API, not MongoDB's
wire protocol). Where a database *does* publish an HTTP data plane -- Cosmos
DB's REST API, Neo4j's Query API, OpenSearch, Elasticsearch, Qdrant, Milvus --
that data plane is the connector.

**Azure is two APIs, not one.** The control plane lives on one host,
`management.azure.com`, and every service is a resource provider under it. The
data planes live on per-resource hosts: `contoso.search.windows.net`,
`contoso.documents.azure.com`, `contoso.vault.azure.net`. They take different
tokens and answer different questions, so they are separate connectors. Three
services appear in both forms, because both are useful:

| Service | Data plane | Control plane |
|---|---|---|
| Cosmos DB | `azure-cosmos-db` — read and write documents | `azure-cosmos-db-accounts` — accounts, keys, throughput, regions |
| AI Search | `azure-ai-search` — indexes, documents, queries | `azure-ai-search-management` — services, scale, keys |
| Storage | `azure-blob-storage` (existing), `azure-storage-queue`, `-table`, `-file` | `azure-storage-accounts` — accounts, keys, network rules |

## How the Azure connectors authenticate

Everything on `management.azure.com` and every Entra-secured data plane takes an
**app registration's client credentials** (`OAUTH2_CC`): the client id and
secret of a service principal, exchanged at
`https://login.microsoftonline.com/{tenantId}/oauth2/v2.0/token`. What differs
per service is the **scope**, and getting it wrong is the most common way an
otherwise correct Azure integration fails:

| Connector | Scope requested |
|---|---|
| every `management.azure.com` connector | `https://management.azure.com/.default` |
| `azure-cosmos-db` | `https://cosmos.azure.com/.default` |
| `azure-key-vault` | `https://vault.azure.net/.default` |
| `azure-app-configuration` | `https://azconfig.io/.default` |
| `azure-monitor-logs` | `https://api.loganalytics.io/.default` |
| `azure-service-bus` | `https://servicebus.azure.net/.default` |
| `azure-data-explorer` | `https://{clusterUri}/.default` — the cluster's own host |

Each entry carries its scope in `token_params`, so `connect()` asks for the
right audience without the caller knowing any of this.

Two Azure quirks are worth calling out, because both are invisible until a
request fails:

- **Cosmos DB does not accept a bearer token.** An Entra token goes in a
  provider-specific form, `Authorization: type=aad&ver=1.0&sig=<token>`, and
  every request must also carry `x-ms-version` and an RFC 1123 `x-ms-date`. The
  connector's `proxy.headers` build all three, so a caller sends none of them.
- **The AI services share a host.** Language, Document Intelligence, Content
  Safety and a multi-service resource all live under
  `{resource}.cognitiveservices.azure.com`, separated only by a path prefix, and
  all take the same `Ocp-Apim-Subscription-Key` header. They are separate
  connectors because their verification endpoints and api-versions differ.

`azure-storage-queue`, `azure-storage-table` and `azure-storage-file` are
aliases of the existing `azure-blob-storage` entry: same delegated Entra flow,
same storage account, different service endpoint.

## How each definition was checked

Every base url and verification endpoint was called for real, unauthenticated:

- **live 401/403** — the endpoint answered and demanded credentials, which
  proves both the url and that it is the authenticated API. Where the auth
  header shape mattered, the call was repeated with a deliberately wrong
  credential to confirm the provider recognised the header and rejected the
  *value* (Pinecone's `Api-Key`, Redis Cloud's `x-api-key`/`x-api-secret-key`
  pair, Couchbase's bearer, Qdrant Cloud's `apikey` prefix, Azure Maps'
  `subscription-key`).
- **live API response** — the endpoint answered as an API (400/405, or JSON)
  rather than as a web page.
- **per-tenant URL** / **per-subscription path** — the API lives on the
  customer's own host, or under their subscription, so the url carries a
  `connection_config` field and cannot be called without one. For those the host
  suffix and the api-version were taken from the provider's own reference:
  Azure's api-versions from the `Azure/azure-rest-api-specs` repository's
  current `stable` folders, Azure AI Search's data-plane version from
  Microsoft Learn's version list.
- **host live** — the host resolved and answered as the API, but no endpoint
  under it proves a credential, so the entry declares no verification endpoint
  rather than one that would report success for a bad key.

The Entra token endpoint was also called with the exact body these entries
generate; it parsed the request and rejected only the (fake) application id,
which confirms the grant, the scope and the encoding.

Three entries deliberately declare **no verification endpoint**, because
declaring a wrong one is worse than declaring none:

- `azure-ai-services` — a multi-service resource has no endpoint that is
  guaranteed to be enabled on it.
- `azure-ai-translator` — its only unauthenticated `GET` (`/languages`) answers
  200 without a key, so it would report a broken credential as working.
- `azure-service-bus` — this is the **message** data plane (`POST
  /{queue}/messages`, `DELETE /{queue}/messages/head`), which has no read that
  proves a credential. Service Bus's queue and namespace *inventory* lives on
  the control plane, under `Microsoft.ServiceBus` on `management.azure.com`,
  which `azure-resource-manager` reaches.

## Icons

Each new connector ships a plain lettermark in the product's brand colour rather
than a reproduction of its official logo. A logo drawn from memory would be
wrong in the details, and a wrong logo is worse than an honest initial.

## The connectors

### Azure — data plane

| id | name | auth | base url | verification endpoint | checked |
|---|---|---|---|---|---|
| `azure-ai-search` | Azure AI Search | API_KEY | `https://${connectionConfig.serviceName}.search.windows.net` | `GET /servicestats?api-version=2026-04-01` | per-tenant URL |
| `azure-cosmos-db` | Azure Cosmos DB (NoSQL) | OAUTH2_CC | `https://${connectionConfig.accountName}.documents.azure.com` | `GET /dbs` | per-tenant URL |
| `azure-key-vault` | Azure Key Vault | OAUTH2_CC | `https://${connectionConfig.vaultName}.vault.azure.net` | `GET /secrets?api-version=7.6&maxresults=1` | per-tenant URL |
| `azure-app-configuration` | Azure App Configuration | OAUTH2_CC | `https://${connectionConfig.storeName}.azconfig.io` | `GET /kv?api-version=2026-04-01` | per-tenant URL |
| `azure-monitor-logs` | Azure Monitor Logs | OAUTH2_CC | `https://api.loganalytics.io` | `GET /v1/workspaces/${connectionConfig.workspaceId}/metadata` | per-tenant URL |
| `azure-data-explorer` | Azure Data Explorer (Kusto) | OAUTH2_CC | `https://${connectionConfig.clusterUri}` | `POST /v1/rest/mgmt` | per-tenant URL |
| `azure-service-bus` | Azure Service Bus | OAUTH2_CC | `https://${connectionConfig.namespace}.servicebus.windows.net` | — | per-tenant URL |
| `azure-ai-services` | Azure AI Services | API_KEY | `https://${connectionConfig.resourceName}.cognitiveservices.azure.com` | — | per-tenant URL |
| `azure-ai-language` | Azure AI Language | API_KEY | `https://${connectionConfig.resourceName}.cognitiveservices.azure.com/language` | `GET /authoring/analyze-text/projects?api-version=2023-04-01&top=1` | per-tenant URL |
| `azure-document-intelligence` | Azure AI Document Intelligence | API_KEY | `https://${connectionConfig.resourceName}.cognitiveservices.azure.com/documentintelligence` | `GET /documentModels?api-version=2024-11-30` | per-tenant URL |
| `azure-content-safety` | Azure AI Content Safety | API_KEY | `https://${connectionConfig.resourceName}.cognitiveservices.azure.com/contentsafety` | `GET /text/blocklists?api-version=2024-09-01` | per-tenant URL |
| `azure-ai-translator` | Azure AI Translator | API_KEY | `https://api.cognitive.microsofttranslator.com` | — | host live (200 on /languages) |
| `azure-ai-speech` | Azure AI Speech | API_KEY | `https://${connectionConfig.region}.api.cognitive.microsoft.com` | `GET /speechtotext/v3.2/projects?skip=0&top=1` | per-tenant URL |
| `azure-maps` | Azure Maps | API_KEY | `https://atlas.microsoft.com` | `GET /timezone/enumIana/json?api-version=1.0` | live 401/403 (401) |
| `azure-storage-queue` | Azure Queue Storage | OAUTH2 | `https://${connectionConfig.accountName}.queue.core.windows.net` | `GET /?comp=list` | per-tenant URL |
| `azure-storage-table` | Azure Table Storage | OAUTH2 | `https://${connectionConfig.accountName}.table.core.windows.net` | `GET /Tables` | per-tenant URL |
| `azure-storage-file` | Azure Files | OAUTH2 | `https://${connectionConfig.accountName}.file.core.windows.net` | `GET /?comp=list` | per-tenant URL |

### Azure — control plane (Azure Resource Manager)

| id | name | auth | base url | verification endpoint | checked |
|---|---|---|---|---|---|
| `azure-resource-manager` | Azure Resource Manager | OAUTH2_CC | `https://management.azure.com` | `GET /subscriptions/${connectionConfig.subscriptionId}/resourcegroups?api-version=2025-04-01` | per-subscription path, host live 401 |
| `azure-virtual-machines` | Azure Virtual Machines | OAUTH2_CC | `https://management.azure.com` | `GET /subscriptions/${connectionConfig.subscriptionId}/providers/Microsoft.Compute/virtualMachines?api-version=2026-04-01` | per-subscription path, host live 401 |
| `azure-postgresql` | Azure Database for PostgreSQL | OAUTH2_CC | `https://management.azure.com` | `GET /subscriptions/${connectionConfig.subscriptionId}/providers/Microsoft.DBforPostgreSQL/flexibleServers?api-version=2025-08-01` | per-subscription path, host live 401 |
| `azure-mysql` | Azure Database for MySQL | OAUTH2_CC | `https://management.azure.com` | `GET /subscriptions/${connectionConfig.subscriptionId}/providers/Microsoft.DBforMySQL/flexibleServers?api-version=2024-12-30` | per-subscription path, host live 401 |
| `azure-sql-database` | Azure SQL Database | OAUTH2_CC | `https://management.azure.com` | `GET /subscriptions/${connectionConfig.subscriptionId}/providers/Microsoft.Sql/servers?api-version=2025-01-01` | per-subscription path, host live 401 |
| `azure-aks` | Azure Kubernetes Service | OAUTH2_CC | `https://management.azure.com` | `GET /subscriptions/${connectionConfig.subscriptionId}/providers/Microsoft.ContainerService/managedClusters?api-version=2026-06-01` | per-subscription path, host live 401 |
| `azure-app-service` | Azure App Service | OAUTH2_CC | `https://management.azure.com` | `GET /subscriptions/${connectionConfig.subscriptionId}/providers/Microsoft.Web/sites?api-version=2026-07-15` | per-subscription path, host live 401 |
| `azure-container-registry` | Azure Container Registry | OAUTH2_CC | `https://management.azure.com` | `GET /subscriptions/${connectionConfig.subscriptionId}/providers/Microsoft.ContainerRegistry/registries?api-version=2025-11-01` | per-subscription path, host live 401 |
| `azure-cosmos-db-accounts` | Azure Cosmos DB (Accounts) | OAUTH2_CC | `https://management.azure.com` | `GET /subscriptions/${connectionConfig.subscriptionId}/providers/Microsoft.DocumentDB/databaseAccounts?api-version=2026-03-15` | per-subscription path, host live 401 |
| `azure-ai-search-management` | Azure AI Search (Management) | OAUTH2_CC | `https://management.azure.com` | `GET /subscriptions/${connectionConfig.subscriptionId}/providers/Microsoft.Search/searchServices?api-version=2025-05-01` | per-subscription path, host live 401 |
| `azure-storage-accounts` | Azure Storage (Accounts) | OAUTH2_CC | `https://management.azure.com` | `GET /subscriptions/${connectionConfig.subscriptionId}/providers/Microsoft.Storage/storageAccounts?api-version=2026-06-01` | per-subscription path, host live 401 |

### Vector and search databases

| id | name | auth | base url | verification endpoint | checked |
|---|---|---|---|---|---|
| `qdrant` | Qdrant | API_KEY | `https://${connectionConfig.clusterUrl}` | `GET /collections` | per-tenant URL |
| `qdrant-cloud` | Qdrant Cloud | API_KEY | `https://api.cloud.qdrant.io` | `GET /api/cluster/v1/accounts/${connectionConfig.accountId}/clusters` | per-tenant URL |
| `opensearch` | OpenSearch | BASIC | `https://${connectionConfig.endpoint}` | `GET /_cluster/health` | per-tenant URL |
| `elasticsearch` | Elasticsearch | API_KEY | `https://${connectionConfig.endpoint}` | `GET /_cluster/health` | per-tenant URL |
| `pinecone` | Pinecone | API_KEY | `https://api.pinecone.io` | `GET /indexes` | live 401/403 (401) |
| `chroma` | Chroma Cloud | API_KEY | `https://api.trychroma.com` | `GET /api/v2/auth/identity` | live 401/403 (401) |
| `milvus` | Milvus | API_KEY | `https://${connectionConfig.endpoint}` | `POST /v2/vectordb/collections/list` | per-tenant URL |
| `zilliz-cloud` | Zilliz Cloud | API_KEY | `https://controller.api.${connectionConfig.region}.zillizcloud.com` | `GET /v1/clusters` | per-tenant URL |
| `typesense` | Typesense | API_KEY | `https://${connectionConfig.host}` | `GET /collections` | per-tenant URL |
| `marqo` | Marqo | API_KEY | `https://api.marqo.ai` | `GET /api/v2/indexes` | live 401/403 (401) |
| `turbopuffer` | turbopuffer | API_KEY | `https://${connectionConfig.region}.turbopuffer.com` | `GET /v2/namespaces` | per-tenant URL |
| `upstash-vector` | Upstash Vector | API_KEY | `https://${connectionConfig.endpoint}` | `GET /info` | per-tenant URL |

### Graph and operational databases

| id | name | auth | base url | verification endpoint | checked |
|---|---|---|---|---|---|
| `neo4j` | Neo4j | BASIC | `https://${connectionConfig.instanceUrl}` | `POST /db/${connectionConfig.database}/query/v2` | per-tenant URL |
| `neo4j-aura` | Neo4j Aura | OAUTH2_CC | `https://api.neo4j.io` | `GET /v1/instances` | live API response (400) |
| `mongodb-atlas` | MongoDB Atlas | OAUTH2_CC | `https://cloud.mongodb.com` | `GET /api/atlas/v2/groups` | live 401/403 (401) |
| `redis-cloud` | Redis Cloud | API_KEY | `https://api.redislabs.com` | `GET /v1/subscriptions` | live 401/403 (403) |
| `upstash` | Upstash | BASIC | `https://api.upstash.com` | `GET /v2/redis/databases` | live 401/403 (401) |
| `couchbase-capella` | Couchbase Capella | API_KEY | `https://cloudapi.cloud.couchbase.com` | `GET /v4/organizations` | live 401/403 (401) |
| `singlestore` | SingleStore | API_KEY | `https://api.singlestore.com` | `GET /v1/regions` | live 401/403 (401) |
