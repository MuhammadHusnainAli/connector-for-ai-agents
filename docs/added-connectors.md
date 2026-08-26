# Connectors added in this release

629 connectors were added, taking the catalogue from 957 to 1586.
None of the existing definitions were modified.

## Where each definition comes from

Every entry is transcribed from a maintained open-source implementation of
that provider's API — the base url, where the credential goes, and the
endpoint used to verify it are read out of working code, not guessed:

- [Pipedream](https://github.com/PipedreamHQ/pipedream) — 347
- [ActivePieces](https://github.com/activepieces/activepieces) — 234
- [n8n](https://github.com/n8n-io/n8n) — 27
- [Nango](https://github.com/NangoHQ/nango) — 21

## How each one was checked

Each base url was then called for real, unauthenticated:

- **live 401/403** (367) — the endpoint answered and demanded credentials, which proves both the url and the fact that it is the authenticated API.
- **live API response** (51) — the endpoint answered as an API (400/405/422, or JSON) rather than as a web page.
- **per-tenant URL** (50) — the API lives on the customer's own host, so the url carries a `connection_config` field and cannot be called without a tenant.
- **host live** (147) — the API host resolved and responded, but no unauthenticated endpoint under it could be confirmed.
- **Nango catalogue** (14) — new providers from the upstream catalogue the existing entries came from, copied verbatim.

Definitions that failed these checks were left out rather than shipped unverified:
a wrong base url or a credential in the wrong place is worse than a missing connector.

## The connectors

| id | name | auth | base url | verification endpoint | checked | upstream |
|---|---|---|---|---|---|---|
| abstract | Abstract | API_KEY | `https://emailvalidation.abstractapi.com` |  | host live | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| abyssale | Abyssale | API_KEY | `https://api.abyssale.com` | `/templates` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| activecalculator | ActiveCalculator | API_KEY | `https://app.activecalculator.com/api/v1` | `/webhooks` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| add-event | AddEvent | API_KEY | `https://api.addevent.com` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| add-to-calendar-pro | Add to Calendar PRO | API_KEY | `https://api.add-to-calendar-pro.com/v1` |  | host live | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| adrapid | AdRapid | API_KEY | `https://api.adrapid.com` | `/banners` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| aftership | Aftership | API_KEY | `https://api.aftership.com` | `/v4/trackings` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| agencyzoom | AgencyZoom | TWO_STEP | `https://api.agencyzoom.com` |  | Nango catalogue | [Nango](https://github.com/NangoHQ/nango) |
| agentline | AgentLine | API_KEY | `https://api.agentline.cloud` | `/v1/agents` | live 401/403 (401) | [Nango](https://github.com/NangoHQ/nango) |
| agentset | Agentset | API_KEY | `https://api.agentset.ai/v1` | `/namespace` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| agify | Agify | API_KEY | `https://api.agify.io` |  | host live | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| agiliron | Agiliron | API_KEY | `https://${connectionConfig.subdomain}.agiliron.net/agiliron/api-40` |  | per-tenant URL | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| aidbase | Aidbase | API_KEY | `https://api.aidbase.ai` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| aiprise | AiPrise | API_KEY | `https://api.aiprise.com` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| air-ops | API Key | API_KEY | `https://api.airops.com` | `/public_api/airops_apps` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| airfocus | Airfocus | API_KEY | `https://api.airfocus.com/api/workspaces` |  | host live | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| aitable-ai | AITable.ai | API_KEY | `https://aitable.ai/fusion/v1` | `/spaces` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| aivoov | AiVOOV | API_KEY | `https://aivoov.com/api/v1` | `/transcribe` | live API response (200) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| akkio | Akkio | API_KEY | `https://api.akkio.com/v1` | `/models` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| alai | Alai | API_KEY | `https://slides-api.getalai.com` | `//slides-api.getalai.com/api/v1/ping` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| alchemy | Alchemy | API_KEY | `https://dashboard.alchemy.com/api` | `/create-webhook` | live API response (405) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| alien-vault | AlienVault | API_KEY | `https://otx.alienvault.com` | `/api/v1/user/me` | live 401/403 (403) | [n8n](https://github.com/n8n-io/n8n) |
| all-images-ai | All Images AI | API_KEY | `https://api.all-images.ai/v1` | `/image-generations` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| alt-text-ai | AltText.ai | API_KEY | `https://alttext.ai` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| altoviz | Altoviz | API_KEY | `https://api.altoviz.com/v1` | `/Webhooks` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| alttextify | AltTextify | API_KEY | `https://api.alttextify.net` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| alttextlab | AltTextLab | API_KEY | `https://app.alttextlab.com/api/v1` |  | host live | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| apexverify | ApexVerify | API_KEY | `https://api.apexverify.com` | `/v1/account/credits` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| api-ninjas | API Ninjas | API_KEY | `https://api.api-ninjas.com/v1` | `/iplookup` | live API response (400) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| apiary | Apiary | API_KEY | `https://api.apiary.io` | `/me/apis` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| apitemplate-io | APITemplate.io | API_KEY | `https://api.apitemplate.io` | `/v1/list-templates` | live 401/403 (401) | [n8n](https://github.com/n8n-io/n8n) |
| apiverve | APIVerve | API_KEY | `https://api.apiverve.com/v1` | `/dnslookup` | live 401/403 (403) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| appfollow | AppFollow | API_KEY | `https://api.appfollow.io` | `/account/users` | live API response (200) | [ActivePieces](https://github.com/activepieces/activepieces) |
| appointedd | Appointedd | API_KEY | `https://api.appointedd.com/v1` | `/bookings` | live 401/403 (403) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| ascora | Ascora | API_KEY | `https://api.ascora.com.au` | `/Webhooks` | live API response (400) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| asin-data-api | Asin Data API | API_KEY | `https://api.asindataapi.com` | `/collections` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| ask-handle | AskHandle | API_KEY | `https://dashboard.askhandle.com` | `/rooms` | live 401/403 (403) | [ActivePieces](https://github.com/activepieces/activepieces) |
| assemblyai | AssemblyAI | API_KEY | `https://api.assemblyai.com` | `/v2/account` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| asters | Asters | API_KEY | `https://api.asters.ai/api/external/v1.0` | `/workspaces` | live API response (200) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| async-interview | Async Interview | API_KEY | `https://app.asyncinterview.ai/api` | `/interview_responses` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| athenahealth | athenahealth | OAUTH2_CC | `https://${connectionConfig.subdomain}.platform.athenahealth.com` |  | Nango catalogue | [Nango](https://github.com/NangoHQ/nango) |
| autobound | Autobound | API_KEY | `https://api.autobound.ai/api/external` |  | host live | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| autom | Autom | API_KEY | `https://autom.dev/api/v1` | `/bing/search` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| avian | Avian | API_KEY | `https://api.avian.io` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| awardco | Awardco | API_KEY | `https://api.awardco.com/api` | `/social-feed` | live API response (400) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| axesso-data-service | Axesso Data Service | API_KEY | `https://api.axesso.de/amz` | `/amazon-search-by-keyword-asin` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| ayrshare | Ayrshare | API_KEY | `https://api.ayrshare.com/api` | `/profiles` | live 401/403 (403) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| azure-openai-service | Azure Openai Service | API_KEY | `https://${connectionConfig.resource_name}.openai.azure.com/openai` |  | per-tenant URL | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| baremetrics | Baremetrics | OAUTH2 | `https://api.baremetrics.com` | `/v1/account` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| beamer | Beamer | API_KEY | `https://api.getbeamer.com` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| beebole | Beebole | BASIC | `https://beebole-apps.com` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| beekeeper | Beekeeper | API_KEY | `https://${connectionConfig.subdomain}.beekeeper.io/api/2` |  | per-tenant URL | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| belco | Belco | API_KEY | `https://api.belco.io/v1` | `/teams` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| bexio | Bexio | OAUTH2 | `https://api.bexio.com` | `/3.0/files` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| bigdatacorp | Bigdatacorp | API_KEY | `https://plataforma.bigdatacorp.com.br` | `/enderecos` | live API response (200) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| bika | Bika.ai | API_KEY | `https://bika.ai` | `/api/openapi/bika` | live API response (200) | [ActivePieces](https://github.com/activepieces/activepieces) |
| billsby | Billsby | API_KEY | `https://public.billsby.com/api/v1/rest/core/${connectionConfig.company_domain}` |  | per-tenant URL | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| bloomerang | Bloomerang | API_KEY | `https://api.bloomerang.co/v2` | `/campaigns` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| bluecart-api | Bluecart API | API_KEY | `https://api.bluecartapi.com` | `/categories` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| bocha-search | Bocha | API_KEY | `https://api.bochaai.com` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| bokio | Bokio | API_KEY | `https://api.bokio.se` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| bolna | Bolna AI | API_KEY | `https://api.bolna.ai` | `/agent/all` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| boloforms | Boloforms | API_KEY | `https://signature-backend.boloforms.com/api/v1/signature` | `/get-all-forms/v1` | live API response (400) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| booking-experts | Booking Experts | API_KEY | `https://api.bookingexperts.com/v3` |  | host live | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| botcake | Botcake | API_KEY | `https://botcake.io/api/public_api/v1` |  | host live | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| botstar | Botstar | API_KEY | `https://apis.botstar.com/v1` | `/bots` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| boxhero | BoxHero | API_KEY | `https://rest.boxhero-app.com/v1` | `/txs` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| brandfetch | Brandfetch | API_KEY | `https://api.brandfetch.io` | `/v2/brands/brandfetch.com` | live 401/403 (401) | [n8n](https://github.com/n8n-io/n8n) |
| brave-search | Brave Search | API_KEY | `https://api.search.brave.com` | `//api.search.brave.com/res/v1/web/search` | live 401/403 (403) | [ActivePieces](https://github.com/activepieces/activepieces) |
| breeze | Breeze | API_KEY | `https://api.breeze.pm` | `/projects.json` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| bridge-interactive-platform | Bridge Interactive Platform | API_KEY | `https://api.bridgedataoutput.com/api/v2` | `/users/me` | live 401/403 (403) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| bright-data | Bright Data | API_KEY | `https://api.brightdata.com` | `/zone/get_active_zones` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| brosix | Brosix | API_KEY | `https://box-n2.brosix.com/api/v1` | `/message/send` | live API response (200) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| browse-ai | Browse AI | API_KEY | `https://api.browse.ai` | `/v2` | live 401/403 (403) | [ActivePieces](https://github.com/activepieces/activepieces) |
| browser-use | Browser Use | API_KEY | `https://api.browser-use.com/api/v3` | `/profiles` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| browserbase | Browserbase | API_KEY | `https://api.browserbase.com/v1` | `/projects` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| browserhub | Browserhub | API_KEY | `https://api.browserhub.io/v1` |  | host live | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| btcpay-server | Btcpay Server | API_KEY | `https://${connectionConfig.base_url}/api/v1` |  | per-tenant URL | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| bumpups | Bumpups | API_KEY | `https://api.bumpups.com` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| businesslogic | Businesslogic | API_KEY | `https://api.businesslogic.online` | `/describe` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| buysellads | Buysellads | API_KEY | `https://papi.buysellads.com` | `/creatives-daily-stats` | live API response (400) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| byteforms | ByteForms | API_KEY | `https://api.forms.bytesuite.io/api` | `/form` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| callerapi | CallerAPI | API_KEY | `https://callerapi.com/api/phone` |  | host live | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| callhub | Callhub | API_KEY | `https://api.callhub.io/v1` | `/webhooks` | live 401/403 (403) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| callpage | Callpage | API_KEY | `https://core.callpage.io/api` |  | host live | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| camb-ai | Camb.AI | API_KEY | `https://client.camb.ai` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| capsule-crm | Capsule CRM | OAUTH2 | `https://api.capsulecrm.com` | `/api/v2/site` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| captain-data | API key | API_KEY | `https://api.captaindata.co` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| carbone | Carbone | API_KEY | `https://api.carbone.io` | `/template` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| cardly | Cardly | API_KEY | `https://api.card.ly/v2` | `/art` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| cartloom | Cartloom | API_KEY | `https://${connectionConfig.subdomain}.cartloom.com` |  | per-tenant URL | [ActivePieces](https://github.com/activepieces/activepieces) |
| cats | Cats | API_KEY | `https://api.catsone.com/v3` | `/companies` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| cdw | CDW | API_KEY | `https://${connectionConfig.baseUrl}` |  | Nango catalogue | [Nango](https://github.com/NangoHQ/nango) |
| centralstationcrm | Centralstationcrm | API_KEY | `https://${connectionConfig.account_name}.centralstationcrm.net/api` |  | per-tenant URL | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| certopus | Certopus | API_KEY | `https://api.certopus.com` | `/certificates` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| chain-aware | ChainAware.AI | API_KEY | `https://enterprise.api.chainaware.ai` | `/fraud/audit` | live 401/403 (403) | [ActivePieces](https://github.com/activepieces/activepieces) |
| chainalysis-api | API Key | API_KEY | `https://public.chainalysis.com/api/v1` | `/address` | live 401/403 (403) | [ActivePieces](https://github.com/activepieces/activepieces) |
| chaindesk | Chaindesk | API_KEY | `https://app.chaindesk.ai` | `/api/me` | live 401/403 (403) | [ActivePieces](https://github.com/activepieces/activepieces) |
| channable | Channable | API_KEY | `https://api.channable.com/v1` |  | host live | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| chargeblast | Chargeblast | API_KEY | `https://api.chargeblast.io/api` | `/alerts` | live API response (400) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| chartboost | Chartboost | OAUTH2_CC | `https://api.chartboost.com` |  | Nango catalogue | [Nango](https://github.com/NangoHQ/nango) |
| chat-aid | Chat Aid | API_KEY | `https://api.chataid.com` | `/external/sources/custom` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| chatbot-builder | Chatbot Builder | API_KEY | `https://app.chatgptbuilder.io/api` | `/accounts/tags` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| chatbotkit | ChatBotKit | API_KEY | `https://api.chatbotkit.com/v1` | `/bot/list` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| chatforma | Chatforma | API_KEY | `https://api.pro.chatforma.com/public/v1` | `/forms` | live 401/403 (403) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| chatling | Chatling | API_KEY | `https://api.chatling.ai` | `/v2` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| chatnode | ChatNode | API_KEY | `https://api.public.chatnode.ai` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| chatsistant | Chatsistant | API_KEY | `https://app.chatsistant.com` | `/user` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| chili-piper | Chili Piper | API_KEY | `https://fire.chilipiper.com/api/fire-edge` | `/v1/org/health/ping` | live 401/403 (401) | [Nango](https://github.com/NangoHQ/nango) |
| chili-piper-mcp | Chili Piper (MCP) | MCP_OAUTH2 | `https://fire.chilipiper.com/api/fire-edge/v1/org/mcp` |  | Nango catalogue | [Nango](https://github.com/NangoHQ/nango) |
| chmeetings | Chmeetings | API_KEY | `https://api.chmeetings.com/api/v1` | `/people` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| cisco-meraki | Cisco Meraki | API_KEY | `https://api.meraki.com` | `/api/v1/organizations` | live 401/403 (401) | [n8n](https://github.com/n8n-io/n8n) |
| cisco-umbrella | Cisco Umbrella | API_KEY | `https://api.umbrella.com` |  | host live | [n8n](https://github.com/n8n-io/n8n) |
| clearbit | Clearbit | API_KEY | `https://company.clearbit.com` | `/v2/companies/find` | live 401/403 (401) | [n8n](https://github.com/n8n-io/n8n) |
| clearout | Clearout | API_KEY | `https://api.clearout.io` | `/v1/me` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| clicdata | Clicdata | OAUTH2 | `https://api.clicdata.com` | `/table` | live API response (200) | [ActivePieces](https://github.com/activepieces/activepieces) |
| clockify | Clockify | API_KEY | `https://api.clockify.me` | `/api/v1/workspaces` | live 401/403 (401) | [n8n](https://github.com/n8n-io/n8n) |
| clockodo | Clockodo | API_KEY | `https://my.clockodo.com` | `/me` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| cloudcart | Cloudcart | API_KEY | `https://${connectionConfig.domain}.cloudcart.net/api/v2` |  | per-tenant URL | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| cloudconvert | CloudConvert | OAUTH2 | `https://api.cloudconvert.com` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| cloutly | Cloutly | API_KEY | `https://app.cloutly.com/api/v1` | `/send-review-invite` | live API response (400) | [ActivePieces](https://github.com/activepieces/activepieces) |
| codacy | Codacy | API_KEY | `https://app.codacy.com/api/v3` | `/user/integrations` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| codemagic | Codemagic | API_KEY | `https://api.codemagic.io` | `/apps` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| codescene | CodeScene | API_KEY | `https://api.codescene.io/v2` | `/developer-settings` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| cody | API Key | API_KEY | `https://getcody.ai` | `/folders` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| cohere | Cohere | API_KEY | `https://api.cohere.com` | `/v2/models` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| cometapi | CometAPI | API_KEY | `https://api.cometapi.com` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| commpeak | CommPeak | API_KEY | `https://hlr.commpeak.com` |  | host live | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| connecteam | Connecteam | API_KEY | `https://api.connecteam.com` | `/forms/v1/forms` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| connectuc | ConnectUC | OAUTH2 | `https://api.connectuc.io` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| consulta-unica | Consulta Unica | API_KEY | `https://consultaunica.mx/api/v3` | `/sat` | live API response (405) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| contiguity | API Key | API_KEY | `https://api.contiguity.com` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| convert-api | ConvertAPI | API_KEY | `https://v2.convertapi.com` | `/convert/docx/to/pdf` | live 401/403 (401) | [n8n](https://github.com/n8n-io/n8n) |
| corporate-merch | CorporateMerch | API_KEY | `https://api.corporatemerch.com/v2` | `/contacts` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| countdown-api | Countdown API | API_KEY | `https://api.countdownapi.com` | `/request` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| crawlbase | Crawlbase | API_KEY | `https://api.crawlbase.com` |  | host live | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| cryptolens | Cryptolens | API_KEY | `https://api.cryptolens.io` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| currents | Currents | API_KEY | `https://api.currents.dev` | `/v1/projects` | live 401/403 (401) | [n8n](https://github.com/n8n-io/n8n) |
| customgpt | CustomGPT | API_KEY | `https://app.customgpt.ai` | `/projects` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| dailybot | Dailybot | API_KEY | `https://api.dailybot.com/v1` | `/users` | live 401/403 (403) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| dappier | API Key | API_KEY | `https://api.dappier.com` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| dart | Dart | API_KEY | `https://app.dartai.com/api/v0` | `/tasks` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| dataforb2b | DataForB2B | API_KEY | `https://api.dataforb2b.ai` | `/account` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| datafuel | DataFuel | API_KEY | `https://api.datafuel.dev` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| datocms | API key | API_KEY | `https://site-api.datocms.com` | `/users/me` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| dbt | Dbt | API_KEY | `https://${connectionConfig.region}.com/api` |  | per-tenant URL | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| deepimage | Deepimage | API_KEY | `https://deep-image.ai/rest_api/process_result` |  | host live | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| defastra | Defastra | API_KEY | `https://api.defastra.com` |  | host live | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| deftform | Deftform | API_KEY | `https://deftform.com` | `/api/v1/workspace` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| descript | Descript | API_KEY | `https://descriptapi.com` | `/v1/status` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| desktime | Desktime | API_KEY | `https://desktime.com/api/v2/json` | `/start-project` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| detecting-ai | DETECTING-AI.COM | API_KEY | `https://api.detecting-ai.com` | `/api/detect` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| devrev | Devrev | API_KEY | `https://api.devrev.ai` | `/tags.get` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| dext | Dext | API_KEY | `https://api.xavier-analytics.com` | `/clients` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| dhl | DHL | API_KEY | `https://api-eu.dhl.com` | `/track/shipments` | live 401/403 (401) | [n8n](https://github.com/n8n-io/n8n) |
| digital-pilot | DigitalPilot | API_KEY | `https://api.digitalpilot.app` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| dimo | DIMO | API_KEY | `https://vehicle-triggers-api.dimo.zone` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| dock-certs | Dock Certs | API_KEY | `https://${connectionConfig.endpoint}.dock.io` |  | per-tenant URL | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| docsautomator | DocsAutomator | API_KEY | `https://api.docsautomator.co` | `/automations` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| docsbot | DocsBot | API_KEY | `https://docsbot.ai` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| doctly | Doctly AI | API_KEY | `https://api.doctly.ai` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| documentpro | DocumentPro | API_KEY | `https://api.documentpro.ai` | `/users/me` | live 401/403 (403) | [ActivePieces](https://github.com/activepieces/activepieces) |
| documerge | DocuMerge | API_KEY | `https://app.documerge.ai` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| dolibarr | Dolibarr | API_KEY | `https://${connectionConfig.domain}/api/index.php` |  | per-tenant URL | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| donately | Donately | API_KEY | `https://api.donately.com/v2` | `/accounts` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| doppler-marketing-automation | Doppler Marketing Automation | API_KEY | `https://restapi.fromdoppler.com/accounts/${connectionConfig.account_name}` |  | per-tenant URL | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| dopplerai | Dopplerai | API_KEY | `https://api.dopplerai.com/v1` |  | host live | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| drimify | Drimify | API_KEY | `https://endpoint.drimify.com/api` | `/app_data_collections` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| drip | Drip | BASIC | `https://api.getdrip.com` | `/webhooks` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| dropcontact | Dropcontact | API_KEY | `https://api.dropcontact.io` | `/batch` | live 401/403 (403) | [n8n](https://github.com/n8n-io/n8n) |
| dub | Dub | API_KEY | `https://api.dub.co` | `/links` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| dumpling-ai | Dumpling AI | API_KEY | `https://app.dumplingai.com` | `/api/me` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| easy-peasy-ai | Easy-Peasy.AI | API_KEY | `https://easy-peasy.ai` | `/api/me` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| easybroker | Easybroker | API_KEY | `https://api.easybroker.com/v1` | `/properties` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| easypromos | Easypromos | API_KEY | `https://api.easypromosapp.com/v2` | `/promotions` | live 401/403 (403) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| easyship | Easyship | API_KEY | `https://public-api.easyship.com/2024-09` | `/webhooks` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| echtpost-postcards | Echtpost Postcards | API_KEY | `https://api.echtpost.de/v1` | `/templates` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| editionguard | EditionGuard | API_KEY | `https://app.editionguard.com` | `/api/v2/book` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| edusign | Edusign | API_KEY | `https://ext.edusign.fr` | `/v1/group` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| elastic-email | Elastic Email | API_KEY | `https://api.elasticemail.com` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| elopage | Elopage | API_KEY | `https://api.myablefy.com/api` | `/webhook_endpoints` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| email-verifier-api | Email Verifier API | API_KEY | `https://emailverifierapi.com/v2` |  | host live | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| emailit | Emailit | API_KEY | `https://api.emailit.com` | `/v2/domains` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| emailoctopus | EmailOctopus | API_KEY | `https://api.emailoctopus.com` | `/lists` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| emelia | Emelia | API_KEY | `https://graphql.emelia.io` | `/graphql` | live API response (400) | [n8n](https://github.com/n8n-io/n8n) |
| encodian | Encodian | API_KEY | `https://api.apps-encodian.com/api/v1` | `/Utility/ValidateUrlAvailability` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| endorsal | Endorsal | API_KEY | `https://api.endorsal.io/v1` |  | host live | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| enrichlayer | Enrich Layer | API_KEY | `https://enrichlayer.com` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| enrichley | Enrichley | API_KEY | `https://api.enrichley.io/api/v1` | `/validate-single-email` | live 401/403 (403) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| enrow | Enrow | API_KEY | `https://api.enrow.io` | `/email/find/single` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| epost-klara | ePost (KLARA) | API_KEY | `https://api.klara.ch` |  | Nango catalogue | [Nango](https://github.com/NangoHQ/nango) |
| esignatures | eSignatures | API_KEY | `https://esignatures.com` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| espocrm | Espocrm | API_KEY | `https://${connectionConfig.url}/api/v1` |  | per-tenant URL | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| evenium | Evenium | API_KEY | `https://evenium.com/api/1` | `/events` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| eventee | Eventee | API_KEY | `https://api.eventee.com/public/v1` | `/attendee/invite` | live API response (405) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| everhour | Everhour | API_KEY | `https://api.everhour.com` | `/users/me` | live 401/403 (403) | [ActivePieces](https://github.com/activepieces/activepieces) |
| exhibitday | ExhibitDay | API_KEY | `https://api.exhibitday.com/v1` | `/events/info` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| explorium | Explorium | API_KEY | `https://api.explorium.ai/v1` | `/prospects` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| f15five | F15five | API_KEY | `https://my.15five.com/api/public` | `/high-five` | live 401/403 (403) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| faktoora | Faktoora | API_KEY | `https://${connectionConfig.environment}.faktoora.com/api/v1` |  | per-tenant URL | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| fathom-analytics | Fathom Analytics | API_KEY | `https://api.usefathom.com` | `/v1/account` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| feedhive | FeedHive | API_KEY | `https://api.feedhive.com` | `/labels` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| fibery | Fibery | API_KEY | `https://${connectionConfig.account_name}.fibery.io/api` |  | per-tenant URL | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| fillout-forms | Fillout Forms | API_KEY | `https://api.fillout.com` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| finage | Finage | API_KEY | `https://api.finage.co.uk` | `/symbol-list/forex` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| finalscout | FinalScout | API_KEY | `https://api.finalscout.com/v1` | `/account` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| finerworks | Finerworks | API_KEY | `https://v2.api.finerworks.com/v3` | `/get_product_details` | live API response (405) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| finnhub | Finnhub | API_KEY | `https://finnhub.io/api/v1` | `/news` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| firecrawl | Firecrawl | API_KEY | `https://api.firecrawl.dev` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| flexisign | Flexisign | API_KEY | `https://api.flexisign.io/v1` | `/templates/all` | live 401/403 (403) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| flippingbook | Flippingbook | API_KEY | `https://api-tc.is.flippingbook.com/api/v1` | `/fbonline/publication` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| flock | Flock | API_KEY | `https://api.flock.co/v1` |  | host live | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| flowiseai | Flowiseai | API_KEY | `https://${connectionConfig.url}/api/v1` |  | per-tenant URL | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| flowla | Flowla | API_KEY | `https://api.flowla.com/api/v1` | `/companies` | live 401/403 (403) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| fluxguard | Fluxguard | API_KEY | `https://api.fluxguard.com` | `/account/webhook` | live 401/403 (403) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| foreplay-co | API Key | API_KEY | `https://public.api.foreplay.co` | `/me` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| formcarry | Formcarry | API_KEY | `https://formcarry.com/api` |  | host live | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| formitable | API Key | API_KEY | `https://api.formitable.com` | `/api/v1.2/restaurants` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| fragment | Fragment | API_KEY | `https://api.onfragment.com` | `/api/v1/tasks` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| freshchat | Freshchat | API_KEY | `https://${connectionConfig.chat_url}` |  | per-tenant URL | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| freshmarketer | Freshmarketer | API_KEY | `https://${connectionConfig.domain}.myfreshworks.com/crm/sales/api` |  | per-tenant URL | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| frill | Frill | API_KEY | `https://api.frill.co` | `/v1/ideas` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| gender-api | Gender API | API_KEY | `https://gender-api.com` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| genderize | Genderize | API_KEY | `https://api.genderize.io` |  | host live | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| generatebanners | GenerateBanners | BASIC | `https://api.generatebanners.com/api/v1` | `/template` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| geoapify | Geoapify | API_KEY | `https://api.geoapify.com/v1` | `/routing` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| getprospect | Getprospect | API_KEY | `https://api.getprospect.com` | `/api/v1/contacts/lists` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| getresponse | GetResponse | OAUTH2 | `https://api.getresponse.com` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| getscreenshot | Getscreenshot | API_KEY | `https://api.rasterwise.com/v1` | `/me` | live 401/403 (403) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| giftbit | Giftbit | API_KEY | `https://api-testbed.giftbit.com` | `/papi/v1` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| gigasheet | Gigasheet | API_KEY | `https://api.gigasheet.com` | `/datasets` | live 401/403 (403) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| gladia | Gladia | API_KEY | `https://api.gladia.io` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| glide | Glide | API_KEY | `https://api.glideapps.com` | `/tables` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| goody | Goody | API_KEY | `https://${connectionConfig.environment}.ongoody.com/v1` |  | per-tenant URL | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| google-maps-platform | Google Maps Platform | API_KEY | `https://places.googleapis.com/v1/places` | `/me` | live 401/403 (403) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| google-safebrowsing | Google Safebrowsing | API_KEY | `https://safebrowsing.googleapis.com/v4` | `/threatLists` | live 401/403 (403) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| grabpenny | GrabPenny | API_KEY | `https://grabpenny.com/api/v1` | `/client/tasks` | live 401/403 (403) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| graceblocks | Graceblocks | API_KEY | `https://api.graceblocks.com/v1/${connectionConfig.block_id}` |  | per-tenant URL | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| greenpt | GreenPT | API_KEY | `https://api.greenpt.ai` | `/v1/me` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| griptape | Griptape Cloud | API_KEY | `https://cloud.griptape.ai` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| groq | API Key | API_KEY | `https://api.groq.com` | `/openai/v1/models` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| groqcloud | Groqcloud | API_KEY | `https://api.groq.com/openai/v1` | `/models` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| gupshup | Gupshup | API_KEY | `https://api.gupshup.io` | `/wa/api/v1/template/msg` | live API response (405) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| habitica | Habitica | API_KEY | `https://habitica.com/api/v3` | `/challenges/user` | live API response (400) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| hail | Hail | API_KEY | `https://api.hail.so` | `/calls` | live 401/403 (401) | [Nango](https://github.com/NangoHQ/nango) |
| hail-mcp | Hail (MCP) | MCP_OAUTH2 | `https://mcp.hail.so` |  | Nango catalogue | [Nango](https://github.com/NangoHQ/nango) |
| hana | Hana | API_KEY | `https://hana-api.hanabitech.com/v1/expose-api` | `/report-groups` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| hastewire | Hastewire | API_KEY | `https://hastewire.com` | `/api/v1/me` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| heartbeat | API Key | API_KEY | `https://api.heartbeat.chat` | `/api/me` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| hedy | Hedy | API_KEY | `https://api.hedy.bot` | `/webhooks` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| helpdocs | HelpDocs | API_KEY | `https://api.helpdocs.io/v1` | `/article` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| helpspot | Helpspot | API_KEY | `https://${connectionConfig.subdomain}.helpspot.com/api/index.php` |  | per-tenant URL | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| herobot-chatbot-marketing | Herobot Chatbot Marketing | API_KEY | `https://my.herobot.app/api` |  | host live | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| hootsuite | Hootsuite | OAUTH2 | `https://platform.hootsuite.com` | `/v1/me` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| housecall-pro | Housecall Pro | API_KEY | `https://api.housecallpro.com` | `/customers` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| html-to-image | Html To Image | API_KEY | `https://api.htmlcsstoimg.com/api/v1` | `/generatePdf` | live API response (405) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| hullo | Hullo | API_KEY | `https://app.hullo.me/api/endpoints` | `/attributes` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| humanitix | Humanitix | API_KEY | `https://api.humanitix.com/v1` | `/events` | live API response (400) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| hypeauditor | HypeAuditor | API_KEY | `https://hypeauditor.com/api/method` | `/auditor.report` | live 401/403 (403) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| iloveapi | iLoveAPI | API_KEY | `https://api.ilovepdf.com` | `/v1/auth` | live API response (400) | [ActivePieces](https://github.com/activepieces/activepieces) |
| image-router | ImageRouter | API_KEY | `https://api.imagerouter.io` | `/v1/openai/images/edits` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| imagior | Imagior | API_KEY | `https://api.imagior.com` | `/templates/all` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| influencers-club | Influencers.club | API_KEY | `https://api-dashboard.influencers.club` | `/me` | live 401/403 (403) | [ActivePieces](https://github.com/activepieces/activepieces) |
| insta-charts | InstaCharts | OAUTH2 | `https://api.instacharts.io/v1` | `/templates` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| instabase | Instabase | API_KEY | `https://aihub.instabase.com/api` | `/v2/conversations` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| instasent | Instasent | API_KEY | `https://api.instasent.com` | `/v1` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| interseller | Interseller | API_KEY | `https://interseller.io/api` | `/contacts` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| intruder | Intruder | API_KEY | `https://api.intruder.io` | `/v1` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| issue-badge | IssueBadge | API_KEY | `https://app.issuebadge.com/api/v1` | `/issue/create` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| jigsawstack | JigsawStack | API_KEY | `https://api.jigsawstack.com/v1` | `/ai/sentiment` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| jina-ai | Jina AI | API_KEY | `https://deepsearch.jina.ai` | `/v1/chat/completions` | live 401/403 (401) | [n8n](https://github.com/n8n-io/n8n) |
| jogg-ai | API Key | API_KEY | `https://api.jogg.ai/v1` | `/voices` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| jooto | タスク・プロジェクト管理ツールJooto (ジョートー) | API_KEY | `https://api.jooto.com/v1` | `/boards` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| jungle-grid | Jungle Grid | API_KEY | `https://api.junglegrid.dev` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| kadoa | Kadoa | API_KEY | `https://api.kadoa.com/v2` | `/controller/overview` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| kaleido | Kaleido | API_KEY | `https://${connectionConfig.endpoint}.kaleido.io/api/v1` |  | per-tenant URL | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| kapso | Kapso | API_KEY | `https://api.kapso.ai` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| keboola | Keboola | API_KEY | `https://${connectionConfig.stack_endpoint}/v2/storage` |  | per-tenant URL | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| kite-suite | KiteSuite | API_KEY | `https://api.kitesuite.com/api/v1` | `/task` | live 401/403 (403) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| kiwihr | Kiwihr | API_KEY | `https://${connectionConfig.subdomain}.kiwihr.com/api/graphql` |  | per-tenant URL | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| kizeo-forms | Kizeo Forms API Key | API_KEY | `https://forms.kizeo.com` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| klenty | Klenty | API_KEY | `https://app.klenty.com` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| knack | Knack | API_KEY | `https://api.knack.com` | `/v1` | live 401/403 (403) | [ActivePieces](https://github.com/activepieces/activepieces) |
| knowfirst | KnowFirst | API_KEY | `https://api.knowfirst.ai/v1` | `/feed` | live 401/403 (403) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| kodagpt | Kodagpt | API_KEY | `https://kodagpt.com.br/api/v1` | `/me` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| konfhub | KonfHub | API_KEY | `https://api.konfhub.com` | `/users/me` | live 401/403 (403) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| krisp-call | KrispCall | API_KEY | `https://app.krispcall.com` | `/api/v3/platform/activepiece/me` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| kudosity | Kudosity | API_KEY | `https://api.transmitsms.com` | `/v1/account` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| landbot | Landbot | API_KEY | `https://api.landbot.io/v1` |  | host live | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| launchnotes | LaunchNotes | API_KEY | `https://api.launchnotes.io/graphql` |  | host live | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| leadboxer | LeadBoxer | API_KEY | `https://api.leadboxer.com/v1` | `/users` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| leap | Leap | API_KEY | `https://api.tryleap.ai/api/v1/images` |  | host live | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| leexi | Leexi | BASIC | `https://public-api.leexi.ai` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| lemon-squeezy | Lemon Squeezy | API_KEY | `https://api.lemonsqueezy.com` | `/v1/stores` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| letmepost | Letmepost | API_KEY | `https://api.letmepost.dev` | `/v1/media` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| letzai | LetzAI | API_KEY | `https://api.letz.ai` | `/image-edits` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| limitless-ai | Limitless AI | API_KEY | `https://api.limitless.ai/v1` | `/lifelogs` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| line | Bot Token | API_KEY | `https://api.line.me` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| line-messaging-api | Line Messaging API | API_KEY | `https://api.line.me/v2/bot` | `/message/reply` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| linkupapi | LinkupAPI | API_KEY | `https://api.linkupapi.com` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| listen-notes | Listen Notes | API_KEY | `https://listen-api.listennotes.com/api/v2` | `/search` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| livesession | LiveSession | API_KEY | `https://api.livesession.io` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| livetennisapi | Live Tennis API | API_KEY | `https://api.livetennisapi.com` | `/api/public/v1/matches` | live 401/403 (401) | [Nango](https://github.com/NangoHQ/nango) |
| lmnt | LMNT | API_KEY | `https://api.lmnt.com/v1/ai` | `/voice/list` | live 401/403 (403) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| lobstermail | API Key | API_KEY | `https://api.lobstermail.ai` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| lodgify | Lodgify | API_KEY | `https://api.lodgify.com` | `/webhooks/v1/subscribe` | live API response (405) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| logrocket | LogRocket | API_KEY | `https://api.logrocket.com/v1` | `/orgs` | live 401/403 (403) | [ActivePieces](https://github.com/activepieces/activepieces) |
| logsnag | API Key | API_KEY | `https://api.logsnag.com` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| lone-scale | LoneScale | API_KEY | `https://public-api.lonescale.com` | `/users` | live 401/403 (401) | [n8n](https://github.com/n8n-io/n8n) |
| lucidya | Lucidya | API_KEY | `https://api.lucidya.com` | `/monitors_list` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| lumin-pdf | Lumin PDF | API_KEY | `https://api.luminpdf.com/v1` | `/user/info` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| luxury-presence | Luxury Presence | API_KEY | `https://api.luxurypresence.com` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| magical-api | Magical API | API_KEY | `https://gw.magicalapi.com` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| magnetic | Magnetic | API_KEY | `https://app.magnetichq.com/Magnetic/rest` |  | host live | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| mailblaze | Mail Blaze | API_KEY | `https://control.mailblaze.com/api` | `/lists` | live API response (400) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| mailercheck | Mailercheck | API_KEY | `https://app.mailercheck.com` | `/users` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| mailercloud | Mailercloud | API_KEY | `https://cloudapi.mailercloud.com/v1` | `/list` | live API response (405) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| maileroo | Maileroo | API_KEY | `https://smtp.maileroo.com` | `/api/v2/emails` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| mailgenius | Mailgenius | API_KEY | `https://app.mailgenius.com` | `/external/api/audits` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| mails-so | mails.so | API_KEY | `https://api.mails.so/v1` | `/validate` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| malcore | Malcore | API_KEY | `https://api.malcore.io` |  | host live | [n8n](https://github.com/n8n-io/n8n) |
| manus | Manus | API_KEY | `https://api.manus.ai` | `/v1/tasks` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| manychat | Manychat | API_KEY | `https://api.manychat.com` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| mapbox | Mapbox | API_KEY | `https://api.mapbox.com` | `/tilesets/v1/validateRecipe` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| mapulus | Mapulus | API_KEY | `https://api.mapulus.com/api/v1` | `/locations` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| mastodon | Base URL | API_KEY | `https://mastodon.social` | `/api/v1/statuses` | live API response (200) | [ActivePieces](https://github.com/activepieces/activepieces) |
| mboum | Mboum | API_KEY | `https://api.mboum.com` | `/v1/crypto/coins` | live 401/403 (403) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| mctime | McTime | API_KEY | `https://mctime.com/api/v2/auth` | `/users` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| meetingpulse | MeetingPulse | API_KEY | `https://app.meet.ps/api` | `/v2/meetings` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| meilisearch | Meilisearch | API_KEY | `${connectionConfig.instanceUrl}` | `/version` | Nango catalogue | [Nango](https://github.com/NangoHQ/nango) |
| melo | Melo | API_KEY | `https://${connectionConfig.environment}.notif.immo` |  | per-tenant URL | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| memento-database | Memento Database | API_KEY | `https://api.mementodatabase.com/v1` | `/libraries` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| merge | Merge | API_KEY | `https://api.merge.dev/api/ats/v1` | `/candidates` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| mergemole | Mergemole | API_KEY | `https://mergemole.com/api` |  | host live | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| microsoft-onenote | Microsoft OneNote | OAUTH2 | `https://graph.microsoft.com` | `/v1.0/me/onenote/pages/page-id-example` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| mintlify | Mintlify | API_KEY | `https://api-dsc.mintlify.com/v1` | `/users/me` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| mixmax | Mixmax | API_KEY | `https://api.mixmax.com` | `/v1/users/me` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| moaform | Moaform | API_KEY | `https://api.moaform.com/v1` | `/forms` | live 401/403 (403) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| mobygames | Mobygames | API_KEY | `https://api.mobygames.com/v1` | `/platforms` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| moco | Moco | API_KEY | `https://${connectionConfig.domain}.mocoapp.com/api/v1` |  | per-tenant URL | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| modelry | Modelry | API_KEY | `https://api.modelry.ai/api/v1` | `/products` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| moonclerk | Moonclerk | API_KEY | `https://api.moonclerk.com` | `//api.moonclerk.com/forms` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| morningmate | Morningmate | API_KEY | `https://api.morningmate.com/v1` | `/bots` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| motion | Motion | API_KEY | `https://api.usemotion.com` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| mumble | Mumble | API_KEY | `https://app.mumble.co.il/mumbleapi` | `/get-labels` | live API response (400) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| muna-ai | Muna | API_KEY | `https://api.muna.ai` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| murf-api | Murf AI | API_KEY | `https://api.murf.ai` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| mycase-piece | MyCase | OAUTH2 | `https://external-integrations.mycase.com` | `/users/me` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| myotp-app | MyOTP.App | API_KEY | `https://api.myotp.app` | `/me` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| mysendingbox | API Key | BASIC | `https://api.mysendingbox.fr` | `/users` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| nasa | NASA | API_KEY | `https://api.nasa.gov` | `/planetary/apod` | live 401/403 (403) | [n8n](https://github.com/n8n-io/n8n) |
| nationalize | Nationalize | API_KEY | `https://api.nationalize.io` |  | host live | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| neon | Neon | API_KEY | `https://console.neon.tech/api` | `/v2/users/me` | live 401/403 (401) | [Nango](https://github.com/NangoHQ/nango) |
| neuronwriter | NEURONwriter | API_KEY | `https://app.neuronwriter.com/neuron-api/0.5/writer` | `/new-query` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| neverbounce | NeverBounce | API_KEY | `https://api.neverbounce.com` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| news-api | News API | API_KEY | `https://newsapi.org/v2` | `/top-headlines` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| newscatcher | Newscatcher | API_KEY | `https://catchall.newscatcherapi.com` | `/catchAll/jobs/user` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| nifty | Nifty | OAUTH2 | `https://openapi.niftypm.com` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| ninox | Ninox | API_KEY | `https://api.ninox.com` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| nuclino | Nuclino | API_KEY | `https://api.nuclino.com/v0` | `/items` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| oanda | Oanda | API_KEY | `https://api-fxpractice.oanda.com/v3` | `/accounts` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| ocrspace | Ocrspace | API_KEY | `https://api.ocr.space` |  | host live | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| octopush-sms | Octopush SMS | API_KEY | `https://api.octopush.com` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| offlight | OFFLIGHT | API_KEY | `https://api.offlight.work` | `/zapier/doneTasks` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| offorte | Offorte | API_KEY | `https://connect.offorte.com/api/v2/${connectionConfig.account_name}` |  | per-tenant URL | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| omni | Omni Analytics | API_KEY | `https://${connectionConfig.subdomain}.omniapp.co/api` | `/v1/whoami` | Nango catalogue | [Nango](https://github.com/NangoHQ/nango) |
| omni-co | Omni | API_KEY | `https://blobsrus.omniapp.co` | `/api/v1` | live API response (400) | [ActivePieces](https://github.com/activepieces/activepieces) |
| omnihr | Omni HR | API_KEY | `https://api.omnihr.co` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| onbee-app | Onbee App | API_KEY | `https://${connectionConfig.workspace_name}.onbee.app/api` |  | per-tenant URL | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| oncehub | Oncehub | API_KEY | `https://api.oncehub.com` | `/v2` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| oneclickimpact | 1ClickImpact | API_KEY | `https://api.1clickimpact.com` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| open-router | OpenRouter | API_KEY | `https://openrouter.ai` | `/api/v1/auth/key` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| openmic-ai | OpenMic AI | API_KEY | `https://api.openmic.ai` | `/v1` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| openperplex | Openperplex | API_KEY | `https://5e70fd93-e9b8-4b9c-b7d9-eea4580f330c.app.bhs.ai.cloud.ovh.net` |  | host live | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| opensea | Opensea | API_KEY | `https://api.opensea.io/api/v2` |  | host live | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| opnform | Opnform | API_KEY | `https://api.opnform.com` | `/open/workspaces` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| originality-ai | Originality AI | API_KEY | `https://api.originality.ai/api/v1` | `/scan/ai` | live API response (405) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| ortto | Ortto | API_KEY | `https://${connectionConfig.region}/v1` |  | per-tenant URL | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| outscraper | Outscraper | API_KEY | `https://api.app.outscraper.com` |  | host live | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| overloop | Overloop | API_KEY | `https://api.overloop.com/public/v1` | `/users` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| paperform | Paperform | API_KEY | `https://api.paperform.co` | `/forms` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| papertrail | Papertrail | API_KEY | `https://papertrailapp.com/api/v1` | `/systems.json` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| parallel | Parallel | API_KEY | `https://api.parallel.ai` | `/v1/extract` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| parseur | Parseur | API_KEY | `https://api.parseur.com` | `/user` | live 401/403 (403) | [ActivePieces](https://github.com/activepieces/activepieces) |
| parsio-io | Parsio IO | API_KEY | `https://api.parsio.io` | `/mailboxes` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| payrexx | Payrexx | API_KEY | `https://api.payrexx.com/v1.11` | `/Invoice` | live API response (422) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| paywhirl | Paywhirl | API_KEY | `https://api.paywhirl.com` | `/account` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| pdf-api-io | PDF API IO | API_KEY | `https://pdf-api.io/api` | `/templates/merge` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| pdf-app-net | PDF-app.net | API_KEY | `https://api.pdf-app.net` | `/splitt_PDF` | live 401/403 (403) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| pdf4me | PDF4me | API_KEY | `https://api.pdf4me.com` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| pdfcrowd | Pdfcrowd | BASIC | `https://api.pdfcrowd.com` | `/api/info` | live API response (400) | [ActivePieces](https://github.com/activepieces/activepieces) |
| pdfmonkey | PDFMonkey | API_KEY | `https://api.pdfmonkey.io` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| pdforge | Pdforge | API_KEY | `https://api.pdforge.com/v1` |  | host live | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| peach | Peach | API_KEY | `https://app.trypeach.io/api/v1` | `/account` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| peekalink | Peekalink | API_KEY | `https://api.peekalink.io` |  | host live | [n8n](https://github.com/n8n-io/n8n) |
| peekshot | PeekShot | API_KEY | `https://api.peekshot.com` | `/api/v1/projects` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| peerdom | Peerdom | API_KEY | `https://api.peerdom.org/v1` | `/peers` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| pexels | Pexels | API_KEY | `https://api.pexels.com/v1` | `/search` | live API response (200) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| phantombuster | Phantombuster | API_KEY | `https://api.phantombuster.com` | `/agents/launch-sync` | live 401/403 (401) | [n8n](https://github.com/n8n-io/n8n) |
| philip-hue | PhilipHue | OAUTH2 | `https://api.meethue.com` | `/route` | live 401/403 (401) | [n8n](https://github.com/n8n-io/n8n) |
| php-point-of-sale | Php Point Of Sale | API_KEY | `https://${connectionConfig.domain}/index.php/api/v1` |  | per-tenant URL | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| piloterr | Piloterr | API_KEY | `https://piloterr.com/api/v2` | `/company` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| pingback | Pingback | API_KEY | `https://connect.pingback.com/v1` | `/subscriber` | live 401/403 (403) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| pitchlane | Pitchlane | API_KEY | `https://app.pitchlane.com/api/public/v1` | `/webhooks` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| placid | Placid | API_KEY | `https://api.placid.app` | `/api/rest/templates` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| plausible | API Key | API_KEY | `https://plausible.io` | `/api/v1/sites` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| plunk | Plunk | API_KEY | `https://next-api.useplunk.com` | `/contacts` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| podio | Podio | OAUTH2 | `https://api.podio.com` | `/user` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| pollybot-ai | PollyBot AI | API_KEY | `https://pollybot.app` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| polygon | Polygon | API_KEY | `https://api.polygon.io` | `/vX/reference/financials` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| polygonscan | Polygonscan | API_KEY | `https://api.polygonscan.com/api` |  | host live | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| popupsmart | Popupsmart | API_KEY | `https://app.popupsmart.com/api` |  | host live | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| postgrid | Postgrid | API_KEY | `https://api.postgrid.com/print-mail/v1` | `/letters` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| postiz | Postiz | API_KEY | `https://api.postiz.com` | `/posts` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| postman | Postman | API_KEY | `https://api.getpostman.com` | `/workspaces` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| postmark | Postmark | API_KEY | `https://api.postmarkapp.com` | `/server` | live 401/403 (401) | [n8n](https://github.com/n8n-io/n8n) |
| predict-leads | PredictLeads | API_KEY | `https://predictleads.com` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| pro-ledger | Pro Ledger | API_KEY | `https://api.pro-ledger.com/api/v1` | `/record/get_accounts` | live 401/403 (403) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| processplan | Processplan | API_KEY | `https://${connectionConfig.regional_subdomain}.processplan.com/api/v4` |  | per-tenant URL | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| productlane | Productlane | API_KEY | `https://productlane.com/api/v1` | `/contacts` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| produktly | Produktly | API_KEY | `https://api.produktly.com` | `/api/v1/changelogs` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| prompthub | API Key | API_KEY | `https://app.prompthub.us` | `/api/v1/me` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| promptmate | API Key | API_KEY | `https://api.promptmate.io` | `/v1/apps` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| proxy-spider | Proxy-Spider | API_KEY | `https://proxy-spider.com/api` | `/ping.json` | live API response (200) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| proxycurl | Proxycurl API Key | API_KEY | `https://nubela.co` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| pubrio | API Key | API_KEY | `https://api.pubrio.com` | `/user` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| pumble | Pumble | API_KEY | `https://pumble-api-keys.addons.marketplace.cake.com` | `/listChannels` | live 401/403 (403) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| push-by-techulus | Push by Techulus | API_KEY | `https://push.techulus.com/api/v1` |  | host live | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| qawafel | Qawafel | API_KEY | `https://core.qawafel.sa` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| qualiobee | Qualiobee | API_KEY | `https://app.beehelp.fr/api/${connectionConfig.organization_uuid}` |  | per-tenant URL | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| qualys | Qualys | BASIC | `https://qualysapi.qualys.com` |  | host live | [n8n](https://github.com/n8n-io/n8n) |
| questionpro | Questionpro | API_KEY | `https://${connectionConfig.environment}.questionpro.com/a/api/v2` |  | per-tenant URL | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| quickbooks-desktop-conductor | QuickBooks Desktop (via Conductor) | API_KEY | `https://api.conductor.is` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| quizell | API Token | API_KEY | `https://api.quizell.com` | `/customers/list` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| rafflys | Rafflys | API_KEY | `https://app-sorteos.com/api/v2` | `/promotions` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| raia-ai | raia | API_KEY | `https://api.raia2.com` | `/users` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| raisely | Raisely | API_KEY | `https://api.raisely.com/v3` | `/users` | live 401/403 (403) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| rapid-url-indexer | Rapid URL Indexer | API_KEY | `https://rapidurlindexer.com/wp-json/api/v1` |  | host live | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| reachinbox | API Key | API_KEY | `https://api.reachinbox.ai` | `/api/v1` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| recorded-future | Recorded Future | API_KEY | `https://api.recordedfuture.com` | `/v2/alert/search` | live 401/403 (401) | [n8n](https://github.com/n8n-io/n8n) |
| recruitis | Recruitis | API_KEY | `https://app.recruitis.io/api2` |  | host live | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| recurly | Recurly | BASIC | `https://v3.recurly.com` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| redcircle-api | Redcircle API | API_KEY | `https://api.redcircleapi.com` | `/account` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| reform | Reform | API_KEY | `https://api.reformhq.com/v1/api` |  | host live | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| regal | Regal | API_KEY | `https://events.regalvoice.com` | `/events` | live 401/403 (403) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| remarkety | Remarkety | API_KEY | `https://app.remarkety.com/api/v2/stores/${connectionConfig.store_id}` |  | per-tenant URL | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| remote | Remote | API_KEY | `https://gateway.${connectionConfig.environment}.com/v1` |  | per-tenant URL | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| remote-retrieval | RemoteRetrieval | API_KEY | `https://remoteretrieval.com/RR-enterprise/remoteretrieval/public/index.php/api/v1` |  | host live | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| renderform | Renderform | API_KEY | `https://get.renderform.io/api` | `/v2/render` | live API response (400) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| renderio | Renderio | API_KEY | `https://renderio.dev/api/v1` | `/files` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| rendex | Rendex | API_KEY | `https://api.rendex.dev` | `/v1/credential-check` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| rendi | Rendi | API_KEY | `https://api.rendi.dev/v1` | `/files` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| rentcast | RentCast | API_KEY | `https://api.rentcast.io/v1` | `/me` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| rentman | Rentman | API_KEY | `https://api.rentman.net` | `/v1/me` | live 401/403 (403) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| repliq | RepliQ | API_KEY | `https://api.repliq.co/v2` | `/launchTemplate` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| respond-io | Respond.io | API_KEY | `https://api.respond.io` | `/space/user` | live 401/403 (403) | [ActivePieces](https://github.com/activepieces/activepieces) |
| retable | API Key | API_KEY | `https://api.retable.io` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| retailed | Retailed | API_KEY | `https://app.retailed.io/api/v1` | `/usage` | live API response (400) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| retool | Retool | API_KEY | `https://api.retool.com/api/v2` | `/user_attributes` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| reviewflowz | Reviewflowz | API_KEY | `https://app.reviewflowz.com/api/v2` | `/me` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| rhombus | Rhombus | API_KEY | `https://api2.rhombussystems.com/api` | `/video/spliceV3` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| rinkel | Rinkel | API_KEY | `https://api.rinkel.com/v1` | `/recordings` | live 401/403 (403) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| riskadvisor | RiskAdvisor | API_KEY | `https://app.riskadvisor.insure/api` | `/clients` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| robolly | API Key | API_KEY | `https://api.robolly.com` | `/user` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| robopost | Robopost | API_KEY | `https://public-api.robopost.app/v1` | `/video-tasks` | live API response (422) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| roe-ai | Roe AI | API_KEY | `https://api.roe-ai.com` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| rollbar | Rollbar | API_KEY | `https://api.rollbar.com/api/1` | `/projects` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| rosette-text-analytics | Rosette Text Analytics | API_KEY | `https://api.rosette.com/rest` | `/v1/name-translation` | live 401/403 (403) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| rumble | Rumble | API_KEY | `https://rumble.com/-livestream-api` | `/get-data` | live API response (400) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| rydership | RyderShip | OAUTH2 | `https://${connectionConfig.environment}/api` |  | Nango catalogue | [Nango](https://github.com/NangoHQ/nango) |
| saastic | Api Key | API_KEY | `https://api.saastic.com` | `/beacon/customers` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| sage-300-cre | Sage 300 Construction and Real Estate | TWO_STEP | `https://${connectionConfig.serverUrl}` |  | Nango catalogue | [Nango](https://github.com/NangoHQ/nango) |
| saleslens | SalesLens | API_KEY | `https://app.saleslens.io/api` | `/access_token/categories` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| samsara | Samsara | API_KEY | `https://api.samsara.com` | `/webhooks` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| sardis | Sardis | API_KEY | `https://api.sardis.sh` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| sare | Sare | API_KEY | `https://s.enewsletter.pl/api/v1/${connectionConfig.uid}` |  | per-tenant URL | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| satismeter | SatisMeter | API_KEY | `https://app.satismeter.com/api/v3/projects` |  | host live | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| savvycal | SavvyCal | OAUTH2 | `https://api.savvycal.com` | `/v1/me` | live 401/403 (403) | [ActivePieces](https://github.com/activepieces/activepieces) |
| scalr | Scalr | API_KEY | `https://${connectionConfig.domain}.scalr.io/api/iacp/v3` |  | per-tenant URL | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| scenario | API access key | BASIC | `https://api.cloud.scenario.com` | `/me` | live 401/403 (403) | [ActivePieces](https://github.com/activepieces/activepieces) |
| scoredetect | ScoreDetect | API_KEY | `https://api.scoredetect.com` | `/me` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| scrapecreators | Scrapecreators | API_KEY | `https://api.scrapecreators.com/v1` |  | host live | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| scrapegrapghai | ScrapeGraphAI | API_KEY | `https://api.scrapegraphai.com` | `/v1/smartscraper` | live 401/403 (403) | [ActivePieces](https://github.com/activepieces/activepieces) |
| scrapeless | Scrapeless | API_KEY | `https://api.scrapeless.com` | `/api/v1/me` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| scrapingant | ScrapingAnt | API_KEY | `https://api.scrapingant.com/v2` | `/general` | live API response (422) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| screenshotbase | Screenshotbase | API_KEY | `https://api.screenshotbase.com/v1` | `/take` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| semgrep | Semgrep | API_KEY | `https://semgrep.dev/api/v1` | `/deployments` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| send-it | SendIt | API_KEY | `https://sendit.infiniteappsai.com` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| sendbird-ai-chatbot | Sendbird AI Chatbot | API_KEY | `https://api-${connectionConfig.application_id}.sendbird.com/v3` |  | per-tenant URL | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| sendfox | SendFox | API_KEY | `https://api.sendfox.com` | `/me` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| sendpulse | SendPulse | API_KEY | `https://api.sendpulse.com` | `/me` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| sendr | Sendr | API_KEY | `https://api.sendr.io` | `/seat/me` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| sendx | SendX | API_KEY | `https://app.sendx.io/api/v1` | `/contact/track` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| senja | API Key | API_KEY | `https://api.senja.io` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| senta | Senta | API_KEY | `https://${connectionConfig.subdomain}.senta.co/api` |  | per-tenant URL | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| serpapi | SerpApi | API_KEY | `https://serpapi.com` | `/search` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| serphouse | SERPHouse | API_KEY | `https://api.serphouse.com` | `/serp/live` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| serply | Serply | API_KEY | `https://api.serply.io/v1` | `/users/me` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| serpstat | Serpstat | API_KEY | `https://api.serpstat.com` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| sevdesk | sevdesk | API_KEY | `https://my.sevdesk.de/api/v1` | `/Order` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| seven | seven | API_KEY | `https://gateway.seven.io` | `/api/hooks` | live API response (200) | [n8n](https://github.com/n8n-io/n8n) |
| shoprocket | Shoprocket | API_KEY | `https://api.shoprocket.io/v1` | `/webhooks` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| shopwaive | Shopwaive | API_KEY | `https://app.shopwaive.com/api` |  | host live | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| short-menu | Short Menu | API_KEY | `https://api.shortmenu.com` | `/links` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| shorten-rest | Shorten.REST | API_KEY | `https://api.shorten.rest` | `/api/v1/me` | live 401/403 (403) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| shortpixel | ShortPixel | API_KEY | `https://cdn.shortpixel.ai` |  | host live | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| shuffler | Shuffler | API_KEY | `https://shuffler.io` | `/api/v1/users/getusers` | live 401/403 (401) | [n8n](https://github.com/n8n-io/n8n) |
| sidetracker | Sidetracker | API_KEY | `https://app.sidetracker.io/api` | `/lists` | live 401/403 (403) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| sign-plus | Sign Plus | API_KEY | `https://restapi.sign.plus/v2` | `/envelopes` | live API response (405) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| signaturit | Signaturit | API_KEY | `https://${connectionConfig.domain}.signaturit.com/v3` |  | per-tenant URL | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| signpath | Signpath | API_KEY | `https://app.signpath.io/API/v1/${connectionConfig.organization_id}` |  | per-tenant URL | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| signrequest | Signrequest | API_KEY | `https://signrequest.com` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| similarweb-digitalrank-api | Similarweb Digitalrank API | API_KEY | `https://api.similarweb.com` | `/user-capabilities` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| simpliroute | SimpliRoute | API_KEY | `https://api.simpliroute.com` | `/v1/routes/vehicles` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| sitecreator-io | Sitecreator IO | API_KEY | `https://api.sitecreator.io/v1` | `/getContacts/newsletter` | live 401/403 (403) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| skillzrun | SkillzRun | API_KEY | `https://api.skillzrun.com/external/api` | `/users` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| skyvern | Skyvern | API_KEY | `https://api.skyvern.com` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| slashed | API Token | API_KEY | `https://venc.slashed.cloud` | `/users/me` | live 401/403 (403) | [ActivePieces](https://github.com/activepieces/activepieces) |
| slicktext | SlickText | API_KEY | `https://dev.slicktext.com/v1` | `/brands` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| slidespeak | SlideSpeak | API_KEY | `https://api.slidespeak.co` | `/api/v1` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| slite | Slite | API_KEY | `https://api.slite.com` | `/v1/me` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| smaily | Smaily | BASIC | `https://${connectionConfig.subdomain}.sendsmaily.net` |  | per-tenant URL | [ActivePieces](https://github.com/activepieces/activepieces) |
| smartsuite | SmartSuite | API_KEY | `https://app.smartsuite.com` | `/v1/me` | live 401/403 (403) | [ActivePieces](https://github.com/activepieces/activepieces) |
| smashsend | SMASHSEND | API_KEY | `https://api.smashsend.com/v1` | `/webhooks` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| smsmode | smsmode | API_KEY | `https://rest.smsmode.com` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| socialkit | Socialkit | API_KEY | `https://api.socialkit.dev` | `/youtube/stats` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| softr | Softr | API_KEY | `https://tables-api.softr.io` | `/api/v1` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| sofya | Sofya | API_KEY | `https://sofya.co` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| solcast | Solcast™ | API_KEY | `https://api.solcast.com.au` | `/monthly_averages` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| sourceforge | Sourceforge | API_KEY | `https://sourceforge.net/rest` |  | host live | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| spamcheck-ai | Spamcheck AI | API_KEY | `https://api.spamcheck.ai/api/v1` | `/spam_reports` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| sparkpost | Sparkpost | API_KEY | `https://${connectionConfig.domain}.sparkpost.com/api/v1` |  | per-tenant URL | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| specific | Specific | API_KEY | `https://public-api.specific.app/graphql` |  | host live | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| spiritme | Spiritme | API_KEY | `https://api.spiritme.tech/api` |  | host live | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| splunk | Splunk | API_KEY | `https://${connectionConfig.hostname}` | `/services/authentication/current-context?output_mode=json` | Nango catalogue | [Nango](https://github.com/NangoHQ/nango) |
| stability-ai | API Key | API_KEY | `https://api.stability.ai` | `/v1/me` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| statsig | Statsig | API_KEY | `https://statsigapi.net` | `/console/v1/users?limit=1&page=1` | live 401/403 (401) | [Nango](https://github.com/NangoHQ/nango) |
| stedi | Stedi (Healthcare) | API_KEY | `https://healthcare.us.stedi.com` | `/2024-04-01/payers?pageSize=10` | live 401/403 (401) | [Nango](https://github.com/NangoHQ/nango) |
| storeganise | Storeganise | API_KEY | `https://${connectionConfig.subdomain}.storeganise.com/api/v1/admin` |  | per-tenant URL | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| strale | Strale | API_KEY | `https://api.strale.io` | `/v1/wallet/balance` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| streamline-ai | Streamline AI | BASIC | `https://${connectionConfig.customer}.${connectionConfig.domain}/api` | `/v0/request-forms` | Nango catalogue | [Nango](https://github.com/NangoHQ/nango) |
| streamtime | Streamtime | API_KEY | `https://api.streamtime.net/v1` | `/users` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| stripo | Stripo | API_KEY | `https://my.stripo.email/emailgeneration/v1` | `/emails` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| sunshine-conversations | Sunshine Conversations | API_KEY | `https://${connectionConfig.subdomain}.zendesk.com/sc/v2/apps/${connectionConfig.app_id}` |  | per-tenant URL | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| super-carl | Super Carl | API_KEY | `https://api.supercarl.ai` | `/api/v1/network/summary` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| surveytale | SurveyTale | API_KEY | `https://app.surveytale.com` | `/api/v1/management/surveys` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| svix | Svix | API_KEY | `https://api.svix.com/api/v1` | `/event-type` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| swarmnode | SwarmNode | API_KEY | `https://api.swarmnode.ai` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| synthesia | Synthesia | API_KEY | `https://api.synthesia.io/v2` | `/videos` | live 401/403 (403) | [ActivePieces](https://github.com/activepieces/activepieces) |
| taggun | Taggun | API_KEY | `https://api.taggun.io/api` | `/account/v1/feedback` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| tavily | Tavily | API_KEY | `https://api.tavily.com` | `/usage` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| taxjar | TaxJar | API_KEY | `https://api.taxjar.com/v2` | `/customers` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| teach-n-go | Teach 'n Go | API_KEY | `https://app.teachngo.com` | `/globalApis/course_list` | live 401/403 (403) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| team-sms | Team SMS | API_KEY | `https://teamsms.io/api` | `/me` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| teamcamp | Teamcamp | API_KEY | `https://api.teamcamp.app/v1.0` | `/project` | live 401/403 (403) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| teamup | Teamup | API_KEY | `https://api.teamup.com` |  | host live | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| telnyx | Telnyx | API_KEY | `https://api.telnyx.com` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| templated | Templated | API_KEY | `https://api.templated.io/v1` | `/templates` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| templatedocs | TemplateDocs | API_KEY | `https://templatedocs.io/api/v1` | `/templates` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| templatefox | TemplateFox | API_KEY | `https://api.pdftemplateapi.com/v1` | `/account` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| tenzo | Tenzo | OAUTH2 | `https://api.gotenzo.com` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| testlocally | TestLocally | API_KEY | `https://testlocal.ly/api/v0` | `/tests` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| textcortex-ai | TextCortex AI | API_KEY | `https://api.textcortex.com` | `/v1/texts/completions` | live API response (405) | [ActivePieces](https://github.com/activepieces/activepieces) |
| thankster | API Key | API_KEY | `https://app.thankster.com/api/v1` | `/api_projects/listUserProjects` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| thinkific | Thinkific | API_KEY | `https://api.thinkific.com/api` | `/v2/webhooks` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| thoughtly | Thoughtly | API_KEY | `https://api.thought.ly` | `/interview` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| tidely | Tidely | API_KEY | `https://api.tidely.com` | `/api/v1` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| tidycal | TidyCal | API_KEY | `https://tidycal.com` | `/account` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| time-ops | API Key | API_KEY | `https://api.timeops.dk` | `/Projects` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| timebuzzer | timeBuzzer | API_KEY | `https://my.timebuzzer.com/open-api` | `/activities` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| timelines-ai | TimelinesAI | API_KEY | `https://app.timelines.ai` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| timetonic | TimeTonic | API_KEY | `https://timetonic.com/live/api.php` |  | host live | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| tmetric | TMetric | API_KEY | `https://app.tmetric.com/api/v3` | `/user` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| transifex | Transifex | API_KEY | `https://rest.api.transifex.com` |  | host live | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| transporeon-carrier-oauth2-cc | Transporeon Carrier Interface (Client Credentials) | OAUTH2_CC | `https://${connectionConfig.apiHost}/carrier_interface/openapi` | `/v1/transport` | Nango catalogue | [Nango](https://github.com/NangoHQ/nango) |
| trawlingweb | TrawlingWeb | API_KEY | `https://api.trawlingweb.com` |  | host live | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| trestle | Trestle | API_KEY | `https://api.trestleiq.com` | `/3.0/phone_intel` | live 401/403 (403) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| trint | Trint | API_KEY | `https://api.trint.com` | `/folders` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| truelayer | TrueLayer | OAUTH2 | `https://api.truelayer.com` | `/refunds` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| tubular | Tubular | API_KEY | `https://api.tubular.io/graphql` | `/me` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| twake-cloud | Twake Cloud | API_KEY | `https://plugins.twake.app` |  | host live | [n8n](https://github.com/n8n-io/n8n) |
| txt-werk | Txt Werk | API_KEY | `https://api.txtwerk.de/rest/txt` | `/analyzer` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| u301 | U301 | API_KEY | `https://api.u301.com/v2` | `/qrcode` | live 401/403 (403) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| undetectable-ai | Undetectable AI | API_KEY | `https://api.undetectable.ai` |  | host live | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| unthread | Unthread | API_KEY | `https://api.unthread.io/api` | `/customers/list` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| urlscan-io | urlscan.io | API_KEY | `https://urlscan.io` | `/user` | live 401/403 (403) | [n8n](https://github.com/n8n-io/n8n) |
| uscreen | Uscreen | API_KEY | `https://uscreen.io` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| useinbox | Inbox | BASIC | `https://useapi.useinbox.com` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| uxsniff | API Key | API_KEY | `https://api.uxsniff.com` | `/v1/list-survey` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| v7-go | V7 Go | API_KEY | `https://go.v7labs.com/api` | `/workspaces` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| vadoo-ai | Vadoo AI | API_KEY | `https://viralapi.vadoo.tv/api` | `/get_themes` | live API response (400) | [ActivePieces](https://github.com/activepieces/activepieces) |
| validatedmails | ValidatedMails | API_KEY | `https://api.validatedmails.com` | `/api-keys/me` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| valyu | Valyu | API_KEY | `https://api.valyu.ai` | `/v1/datasources` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| vapi | Vapi | API_KEY | `https://api.vapi.ai` | `/call` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| veedea | Veedea | API_KEY | `https://veedea.com/api` |  | host live | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| vestaboard | Vestaboard | API_KEY | `https://platform.vestaboard.com/v2.0` |  | host live | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| viewdns-info | ViewDNS.info | API_KEY | `https://api.viewdns.info` | `/subdomains` | live API response (400) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| virtualsms | VirtualSMS | API_KEY | `https://virtualsms.io/api/v1` | `/customer/balance` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| vision6 | Vision6 | API_KEY | `https://${connectionConfig.region}.api.vision6.com` |  | per-tenant URL | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| vlm-run | VLM Run | API_KEY | `https://api.vlm.run` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| voipstudio | VoIPstudio | API_KEY | `https://l7api.com` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| vtiger | VTiger Instance URL | BASIC | `https://code.vtiger.com` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| waitlist | Waitlist | API_KEY | `https://api.getwaitlist.com/api/v1` | `/waitlist` | live API response (400) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| waitwhile | WaitWhile | API_KEY | `https://api.waitwhile.com` | `/v2` | live API response (200) | [ActivePieces](https://github.com/activepieces/activepieces) |
| weaviate | Weaviate | API_KEY | `https://${connectionConfig.cluster_url}` |  | per-tenant URL | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| webscrape-ai | Webscrape AI | API_KEY | `https://api.webscrapeai.com` | `/scrapeWebSite` | live API response (400) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| webscraper-io | Webscraper IO | API_KEY | `https://api.webscraper.io/api/v1` | `/scraping-jobs` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| weekdone | Weekdone | OAUTH2 | `https://api.weekdone.com` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| whatsscale | WhatsScale | API_KEY | `https://proxy.whatsscale.com` | `/api/auth/test` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| whautomate | Whautomate | API_KEY | `https://api.whautomate.com/v1` | `/webhooks` | live 401/403 (403) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| whoisfreaks | WhoisFreaks | API_KEY | `https://api.whoisfreaks.com` | `/v1.0/security` | live API response (400) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| whop | Whop | API_KEY | `https://api.whop.com/api/v2` | `/plans` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| wistia | API Access Token | API_KEY | `https://api.wistia.com` | `/v1/projects.json` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| woodpecker | API Key | API_KEY | `https://api.woodpecker.co` | `/rest/v2/users` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| workamajig | Workamajig | API_KEY | `https://${connectionConfig.subdomain}.workamajig.com/api/beta1` |  | per-tenant URL | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| workiom | Workiom | API_KEY | `https://api.workiom.com/api/services/app` | `/Lists/Get` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| writesonic-bulk | Writesonic | API_KEY | `https://api.writesonic.com` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| wufoo | Wufoo | BASIC | `=https://${connectionConfig.domain}.wufoo.com` |  | per-tenant URL | [n8n](https://github.com/n8n-io/n8n) |
| xquik | Xquik | API_KEY | `https://xquik.com` | `/api/v1` | live API response (200) | [ActivePieces](https://github.com/activepieces/activepieces) |
| y-gy | Y Gy | API_KEY | `https://api.y.gy/api/v1` | `/link` | live API response (400) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| yanado | Yanado | API_KEY | `https://api.yanado.com/public-api` | `/tasks` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| youform | Youform | API_KEY | `https://app.youform.com` | `/account` | live 401/403 (401) | [ActivePieces](https://github.com/activepieces/activepieces) |
| yutori | Yutori | API_KEY | `https://api.yutori.com/v1` | `/browsing/tasks` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| z-api | Z API | API_KEY | `https://api.z-api.io/instances/${connectionConfig.instance_id}/token/${connectionConfig.token_id}` |  | per-tenant URL | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| zenscrape | Zenscrape | API_KEY | `https://app.zenscrape.com/api/v1` | `/status` | live 401/403 (403) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| zenserp | Zenserp | API_KEY | `https://app.zenserp.com/api/v2` | `/hl` | live 401/403 (403) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
| zeplin | Zeplin | API_KEY | `https://api.zeplin.dev` |  | host live | [ActivePieces](https://github.com/activepieces/activepieces) |
| zerobounce | API Key | API_KEY | `https://api.zerobounce.net/v2` | `/validate` | live 401/403 (403) | [ActivePieces](https://github.com/activepieces/activepieces) |
| zixflow | Zixflow | API_KEY | `https://api.zixflow.com/api/v1` | `/collection-records/activity-list` | live 401/403 (401) | [Pipedream](https://github.com/PipedreamHQ/pipedream) |
