//! The connector catalogue: loading, alias resolution, filtering, paging and auth schemas.

use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};
use std::sync::Arc;

use serde_json::{Map, Value};

use crate::data::DataSource;
use crate::error::{Error, ErrorKind, Result};
use crate::models::{AuthField, AuthMode, AuthSchema, Connector, ConnectorPage, FieldGroup};

/// Page size used when a caller paginates without asking for one.
pub const DEFAULT_PAGE_SIZE: usize = 50;
/// Upper bound, so a stray huge page size cannot materialise a huge payload.
pub const MAX_PAGE_SIZE: usize = 1000;

/// Filters shared by listing, paging and counting. All empty means "everything".
#[derive(Debug, Clone, Default)]
pub struct ConnectorFilter {
    /// Case-insensitive substring of the id or display name.
    pub search: Option<String>,
    pub category: Option<String>,
    pub auth_mode: Option<AuthMode>,
    /// Drop the auth modes with no handler at all.
    pub supported_only: bool,
    /// Also drop the ones needing an external OAuth flow.
    pub self_service_only: bool,
}

impl ConnectorFilter {
    pub fn search(mut self, s: impl Into<String>) -> Self {
        self.search = Some(s.into());
        self
    }
    pub fn category(mut self, c: impl Into<String>) -> Self {
        self.category = Some(c.into());
        self
    }
    pub fn auth_mode(mut self, m: AuthMode) -> Self {
        self.auth_mode = Some(m);
        self
    }
    pub fn supported_only(mut self) -> Self {
        self.supported_only = true;
        self
    }
    pub fn self_service_only(mut self) -> Self {
        self.self_service_only = true;
        self
    }
}

/// Read-only catalogue of every connector.
#[derive(Debug, Clone)]
pub struct ConnectorRegistry {
    source: DataSource,
    connectors: Arc<BTreeMap<String, Connector>>,
}

impl ConnectorRegistry {
    /// The bundled catalogue.
    pub fn new() -> Result<Self> {
        Self::from_source(DataSource::default())
    }

    /// Load `connectors/*.json` from a data tree; icons are read from the same tree.
    pub fn from_source(source: DataSource) -> Result<Self> {
        let mut entries: Map<String, Value> = Map::new();
        let files = source.json_files("connectors");
        if files.is_empty() {
            return Err(Error::data("no connector definitions found under connectors/"));
        }
        for file in files {
            let bytes = source.read(&file).ok_or_else(|| Error::data(format!("cannot read {file}")))?;
            let chunk: Value = serde_json::from_slice(&bytes)?;
            for (key, entry) in chunk.as_object().cloned().unwrap_or_default() {
                // Two files claiming one id would make the winner depend on file order.
                if entries.contains_key(&key) {
                    return Err(Error::data(format!("duplicate connector id '{key}' in {file}")));
                }
                entries.insert(key, entry);
            }
        }
        Ok(Self::build(source, entries))
    }

    /// A custom catalogue: one object of `connector id -> definition`, as in a single JSON file.
    pub fn from_definitions(definitions: Map<String, Value>, icons: DataSource) -> Self {
        Self::build(icons, definitions)
    }

    fn build(source: DataSource, entries: Map<String, Value>) -> Self {
        let resolved = resolve_aliases(&entries);
        let connectors = resolved.into_iter().map(|(id, entry)| (id.clone(), build_connector(id, entry))).collect();
        Self { source, connectors: Arc::new(connectors) }
    }

    pub fn len(&self) -> usize {
        self.connectors.len()
    }

    pub fn is_empty(&self) -> bool {
        self.connectors.is_empty()
    }

    pub fn contains(&self, id: &str) -> bool {
        self.connectors.contains_key(id)
    }

    pub fn ids(&self) -> Vec<String> {
        self.connectors.keys().cloned().collect()
    }

    pub fn iter(&self) -> impl Iterator<Item = &Connector> {
        self.connectors.values()
    }

    pub fn get(&self, id: &str) -> Result<&Connector> {
        self.connectors.get(id).ok_or_else(|| Error::unknown_connector(id))
    }

    /// The alias-resolved definition for a connector.
    pub fn raw(&self, id: &str) -> Result<Arc<Map<String, Value>>> {
        Ok(self.get(id)?.raw.clone())
    }

    /// Every connector matching `filter`, ordered by display name then id.
    pub fn matching(&self, filter: &ConnectorFilter) -> Vec<&Connector> {
        let needle = filter.search.as_deref().unwrap_or("").trim().to_lowercase();
        let mut out: Vec<&Connector> = self
            .connectors
            .values()
            .filter(|c| filter.auth_mode.is_none_or(|m| c.auth_mode == m))
            .filter(|c| filter.category.as_ref().is_none_or(|cat| cat.is_empty() || c.categories.contains(cat)))
            .filter(|c| !filter.supported_only || c.supported())
            .filter(|c| !filter.self_service_only || c.self_service())
            .filter(|c| needle.is_empty() || c.id.to_lowercase().contains(&needle) || c.display_name.to_lowercase().contains(&needle))
            .collect();
        // A stable total order: page 1 and page 2 must slice the same sequence.
        out.sort_by(|a, b| (a.display_name.to_lowercase(), &a.id).cmp(&(b.display_name.to_lowercase(), &b.id)));
        out
    }

    /// Filtered listing, optionally sliced by `limit` / `offset`.
    pub fn list(&self, filter: &ConnectorFilter, limit: Option<usize>, offset: usize) -> Vec<Connector> {
        let matches = self.matching(filter);
        let start = offset.min(matches.len());
        let end = limit.map_or(matches.len(), |l| (start + l).min(matches.len()));
        matches[start..end].iter().map(|c| (*c).clone()).collect()
    }

    /// One page of the listing. Address it by `page` number, or by `offset` (which wins).
    pub fn paginate(&self, page: usize, page_size: usize, offset: Option<usize>, filter: &ConnectorFilter) -> Result<ConnectorPage> {
        if page < 1 {
            return Err(Error::new(ErrorKind::Validation, format!("page must be an integer >= 1, got {page}")));
        }
        if page_size < 1 {
            return Err(Error::new(ErrorKind::Validation, format!("page_size must be an integer >= 1, got {page_size}")));
        }
        if page_size > MAX_PAGE_SIZE {
            return Err(Error::new(ErrorKind::Validation, format!("page_size must be <= {MAX_PAGE_SIZE}, got {page_size}")));
        }
        let offset = offset.unwrap_or((page - 1) * page_size);
        let matches = self.matching(filter);
        let start = offset.min(matches.len());
        let end = (start + page_size).min(matches.len());
        Ok(ConnectorPage {
            items: matches[start..end].iter().map(|c| (*c).clone()).collect(),
            total: matches.len(),
            limit: page_size,
            offset,
        })
    }

    /// Walk the whole filtered listing one page at a time.
    pub fn iter_pages(&self, page_size: usize, start_offset: usize, filter: &ConnectorFilter) -> Result<Vec<ConnectorPage>> {
        let mut pages = Vec::new();
        let mut offset = start_offset;
        loop {
            let page = self.paginate(1, page_size, Some(offset), filter)?;
            if page.count() == 0 {
                // An empty first page still tells the caller the total.
                if offset == start_offset {
                    pages.push(page);
                }
                return Ok(pages);
            }
            let next = page.next_offset();
            pages.push(page);
            match next {
                Some(n) => offset = n,
                None => return Ok(pages),
            }
        }
    }

    pub fn categories(&self) -> Vec<String> {
        let set: BTreeSet<&String> = self.connectors.values().flat_map(|c| c.categories.iter()).collect();
        set.into_iter().cloned().collect()
    }

    /// Auth mode -> connector count, most common first.
    pub fn auth_modes(&self) -> Vec<(AuthMode, usize)> {
        let mut counts: HashMap<AuthMode, usize> = HashMap::new();
        for c in self.connectors.values() {
            *counts.entry(c.auth_mode).or_default() += 1;
        }
        let mut out: Vec<_> = counts.into_iter().collect();
        out.sort_by(|a, b| b.1.cmp(&a.1).then(a.0.as_str().cmp(b.0.as_str())));
        out
    }

    /// The connector's logo as an inline SVG string.
    pub fn icon(&self, id: &str) -> Option<String> {
        self.source.read(&format!("icons/{id}.svg")).map(|b| String::from_utf8_lossy(&b).into_owned())
    }

    /// Describe every input needed to connect `id`.
    pub fn auth_schema(&self, id: &str) -> Result<AuthSchema> {
        let connector = self.get(id)?;
        let entry = &connector.raw;
        let mode = connector.auth_mode;

        let mut credentials = fields(entry.get("credentials"), FieldGroup::Credentials);
        if credentials.is_empty() {
            credentials = default_credential_fields(mode);
        }
        let mut connection_config = fields(entry.get("connection_config"), FieldGroup::ConnectionConfig);
        // `connection_configuration` names values a post-connection step fills in.
        for name in entry.get("connection_configuration").and_then(Value::as_array).into_iter().flatten().filter_map(Value::as_str) {
            if !connection_config.iter().any(|f| f.name == name) {
                let mut f = AuthField::new(name, FieldGroup::ConnectionConfig);
                f.title = titleize(name);
                f.description = "Derived from the provider after connecting; supply it yourself if you need it.".into();
                f.required = false;
                f.automated = true;
                f.order = connection_config.len() as i64 + 1;
                connection_config.push(f);
            }
        }
        Ok(AuthSchema {
            connector_id: connector.id.clone(),
            display_name: connector.display_name.clone(),
            auth_mode: mode,
            supported: connector.supported(),
            self_service: connector.self_service(),
            requires_external_oauth: mode.requires_external_oauth(),
            unsupported_reason: unsupported_reason(mode).map(str::to_string),
            credentials,
            connection_config,
            integration_config: fields(entry.get("integration_config"), FieldGroup::IntegrationConfig),
            assertion_option: fields(entry.get("assertion_option"), FieldGroup::AssertionOption),
            default_scopes: entry
                .get("default_scopes")
                .and_then(Value::as_array)
                .map(|a| a.iter().filter_map(|v| v.as_str().map(str::to_string)).collect())
                .unwrap_or_default(),
            authorization_url: entry.get("authorization_url").and_then(Value::as_str).map(str::to_string),
        })
    }
}

fn unsupported_reason(mode: AuthMode) -> Option<&'static str> {
    match mode {
        AuthMode::Bill => Some("Bill.com session-token auth is not implemented yet."),
        AuthMode::AwsSigv4 => Some("AWS SigV4 request signing is not implemented yet."),
        AuthMode::App => Some("App installation flows are handled outside this package."),
        AuthMode::Custom => Some("App-scoped OAuth (CUSTOM) is handled outside this package."),
        _ => None,
    }
}

fn default_credential_fields(mode: AuthMode) -> Vec<AuthField> {
    let make = |name: &str, title: &str, desc: &str, secret: bool, required: bool, order: i64| {
        let mut f = AuthField::new(name, FieldGroup::Credentials);
        f.title = title.into();
        f.description = desc.into();
        f.secret = secret;
        f.required = required;
        f.order = order;
        f
    };
    match mode {
        AuthMode::ApiKey => vec![make("apiKey", "API Key", "Your API key.", true, true, 1)],
        AuthMode::Basic | AuthMode::InstallPlugin => vec![
            make("username", "Username", "Your username.", false, true, 1),
            make("password", "Password", "Your password.", true, true, 2),
        ],
        AuthMode::Oauth2Cc => vec![
            make("client_id", "Client ID", "Your OAuth client id.", false, true, 1),
            make("client_secret", "Client Secret", "Your OAuth client secret.", true, true, 2),
        ],
        AuthMode::Tba => vec![
            make("token_id", "Token ID", "Your token id.", false, true, 1),
            make("token_secret", "Token Secret", "Your token secret.", true, true, 2),
        ],
        AuthMode::Oauth2 => vec![
            make("access_token", "Access Token", "Access token obtained from your own OAuth flow.", true, false, 1),
            make("refresh_token", "Refresh Token", "Refresh token obtained from your own OAuth flow.", true, false, 2),
        ],
        AuthMode::Oauth1 => vec![
            make("oauth_token", "OAuth Token", "", true, false, 1),
            make("oauth_token_secret", "OAuth Token Secret", "", true, false, 2),
        ],
        _ => Vec::new(),
    }
}

/// Shallow-merge each alias entry over its target, following alias chains.
///
/// A dangling or cyclic alias leaves the entry as written rather than failing
/// the whole catalogue over one bad row.
pub(crate) fn resolve_aliases(entries: &Map<String, Value>) -> Map<String, Value> {
    fn resolve(key: &str, entries: &Map<String, Value>, done: &mut HashMap<String, Value>, pending: &mut HashSet<String>) -> Value {
        if let Some(v) = done.get(key) {
            return v.clone();
        }
        let entry = entries[key].clone();
        let alias = entry.get("alias").and_then(Value::as_str).map(str::to_string);
        let Some(alias) = alias else { return entry };
        if !entries.contains_key(&alias) || pending.contains(&alias) {
            return entry;
        }
        pending.insert(key.to_string());
        let target = resolve(&alias, entries, done, pending);
        pending.remove(key);
        let Value::Object(mut merged) = target else { return entry };
        for (k, v) in entry.as_object().into_iter().flatten() {
            if k != "alias" {
                merged.insert(k.clone(), v.clone());
            }
        }
        merged.insert("alias".into(), Value::String(alias));
        let merged = Value::Object(merged);
        done.insert(key.to_string(), merged.clone());
        merged
    }
    let mut done = HashMap::new();
    let mut pending = HashSet::new();
    entries.keys().map(|k| (k.clone(), resolve(k, entries, &mut done, &mut pending))).collect()
}

fn build_connector(id: String, entry: Value) -> Connector {
    let entry = entry.as_object().cloned().unwrap_or_default();
    let text = |v: Option<&Value>| v.and_then(Value::as_str).filter(|s| !s.is_empty()).map(str::to_string);
    Connector {
        display_name: text(entry.get("display_name")).unwrap_or_else(|| titleize(&id)),
        auth_mode: AuthMode::parse(entry.get("auth_mode").and_then(Value::as_str)),
        categories: entry
            .get("categories")
            .and_then(Value::as_array)
            .map(|a| a.iter().filter_map(|v| v.as_str().map(str::to_string)).collect())
            .unwrap_or_default(),
        base_url: text(entry.get("proxy").and_then(|p| p.get("base_url"))),
        alias: text(entry.get("alias")),
        raw: Arc::new(entry),
        id,
    }
}

pub(crate) fn truthy(v: Option<&Value>) -> bool {
    match v {
        Some(Value::Bool(b)) => *b,
        Some(Value::String(s)) => matches!(s.trim().to_lowercase().as_str(), "true" | "1" | "yes"),
        Some(Value::Number(n)) => n.as_f64().is_some_and(|f| f != 0.0),
        Some(Value::Array(a)) => !a.is_empty(),
        Some(Value::Object(o)) => !o.is_empty(),
        _ => false,
    }
}

fn text_of(v: Option<&Value>) -> Option<String> {
    match v {
        Some(Value::String(s)) => Some(s.clone()),
        Some(Value::Number(n)) => Some(n.to_string()),
        Some(Value::Bool(b)) => Some(b.to_string()),
        _ => None,
    }
}

fn fields(spec: Option<&Value>, group: FieldGroup) -> Vec<AuthField> {
    let Some(Value::Object(spec)) = spec else { return Vec::new() };
    spec.iter()
        .enumerate()
        .map(|(index, (name, raw))| {
            let empty = Map::new();
            let raw = raw.as_object().unwrap_or(&empty);
            let mut f = AuthField::new(name, group);
            f.title = text_of(raw.get("title")).filter(|s| !s.is_empty()).unwrap_or_else(|| titleize(name));
            f.description = text_of(raw.get("description")).unwrap_or_default();
            f.field_type = text_of(raw.get("type")).filter(|s| !s.is_empty()).unwrap_or_else(|| "string".into());
            f.required = !truthy(raw.get("optional"));
            f.secret = truthy(raw.get("secret"));
            f.example = text_of(raw.get("example"));
            f.pattern = text_of(raw.get("pattern"));
            f.format = text_of(raw.get("format"));
            f.default_value = text_of(raw.get("default_value"));
            f.r#enum =
                raw.get("enum").and_then(Value::as_array).map(|a| a.iter().filter_map(|v| text_of(Some(v))).collect()).unwrap_or_default();
            f.prefix = text_of(raw.get("prefix"));
            f.suffix = text_of(raw.get("suffix"));
            f.order = raw.get("order").and_then(crate::credentials::num).map(|n| n as i64).filter(|n| *n != 0).unwrap_or(index as i64 + 1);
            f.automated = truthy(raw.get("automated"));
            f.hidden = truthy(raw.get("hidden"));
            f.visible_when = raw.get("visible_when").and_then(Value::as_object).cloned();
            f
        })
        .collect()
}

/// `apiKey` -> `Api Key`, `client_id` -> `Client Id`, matching the Python helper.
pub(crate) fn titleize(name: &str) -> String {
    let base = name.replace(['_', '-'], " ");
    let mut spaced = String::new();
    for (i, ch) in base.chars().enumerate() {
        if i > 0 && ch.is_ascii_uppercase() {
            spaced.push(' ');
        }
        spaced.push(ch);
    }
    spaced
        .split_whitespace()
        .map(|part| {
            if part.chars().all(|c| !c.is_alphabetic() || c.is_lowercase()) {
                let mut cs = part.chars();
                cs.next().map(|f| f.to_uppercase().collect::<String>() + cs.as_str()).unwrap_or_default()
            } else {
                part.to_string()
            }
        })
        .collect::<Vec<_>>()
        .join(" ")
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn alias_chains_resolve() {
        let entries = json!({
            "leaf": {"alias": "middle", "display_name": "Leaf"},
            "middle": {"alias": "root", "display_name": "Middle"},
            "root": {"auth_mode": "OAUTH2", "display_name": "Root"},
            "loop": {"alias": "loop"}
        });
        let out = resolve_aliases(entries.as_object().unwrap());
        assert_eq!(out["leaf"]["auth_mode"], "OAUTH2");
        assert_eq!(out["leaf"]["display_name"], "Leaf");
        assert_eq!(out["middle"]["alias"], "root");
        assert_eq!(out["loop"]["alias"], "loop");
    }

    #[test]
    fn titles() {
        assert_eq!(titleize("apiKey"), "Api Key");
        assert_eq!(titleize("client_id"), "Client Id");
    }
}
