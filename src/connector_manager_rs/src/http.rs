//! HTTP plumbing, in both flavours.
//!
//! Everything that talks to a provider goes through a [`Request`] and a
//! [`Transport`]. Auth flows, verification and scope discovery are written once
//! as `async` code against `&dyn Transport`:
//!
//! * [`AsyncTransport`] (reqwest, async) serves [`crate::AsyncConnectorManager`];
//! * [`BlockingTransport`] (reqwest, blocking) serves [`crate::ConnectorManager`],
//!   whose futures complete on their first poll and are driven by [`block_on`].
//!
//! That is the Rust counterpart of the Python package's generator "flows": one
//! implementation of every auth mode, two ways to run it.

use std::collections::BTreeMap;
use std::future::Future;
use std::pin::Pin;
use std::task::{Context, Poll, Waker};
use std::time::Duration;

use serde_json::{Value, json};

use crate::error::{Error, Result};

/// Default request timeout, as in the Python package.
pub const DEFAULT_TIMEOUT: Duration = Duration::from_secs(30);

/// A boxed, sendable future.
pub type BoxFuture<'a, T> = Pin<Box<dyn Future<Output = T> + Send + 'a>>;

/// A provider call, fully described and ready to send.
#[derive(Debug, Clone, PartialEq, Default)]
pub struct Request {
    pub method: String,
    pub url: String,
    pub headers: BTreeMap<String, String>,
    /// Query parameters added to `url` when sent.
    pub params: BTreeMap<String, String>,
    /// Pre-encoded body (form string, JSON text, raw bytes...).
    pub content: Option<Vec<u8>>,
    /// Body to be JSON-encoded when sent, when `content` is `None`.
    pub json_body: Option<Value>,
}

impl Request {
    pub fn new(method: &str, url: impl Into<String>) -> Self {
        Self { method: method.to_uppercase(), url: url.into(), ..Default::default() }
    }

    pub fn header(mut self, key: &str, value: impl Into<String>) -> Self {
        self.headers.insert(key.to_lowercase(), value.into());
        self
    }

    pub fn content(mut self, body: impl Into<Vec<u8>>) -> Self {
        self.content = Some(body.into());
        self
    }

    /// The url with `params` appended, as it goes on the wire.
    pub fn full_url(&self) -> String {
        if self.params.is_empty() {
            return self.url.clone();
        }
        match url::Url::parse(&self.url) {
            Ok(mut u) => {
                {
                    let mut q = u.query_pairs_mut();
                    for (k, v) in &self.params {
                        q.append_pair(k, v);
                    }
                }
                u.to_string()
            }
            Err(_) => {
                let sep = if self.url.contains('?') { '&' } else { '?' };
                let qs: Vec<String> = self.params.iter().map(|(k, v)| format!("{}={}", enc(k), enc(v))).collect();
                format!("{}{}{}", self.url, sep, qs.join("&"))
            }
        }
    }

    /// The body bytes that will be sent.
    pub fn body_bytes(&self) -> Option<Vec<u8>> {
        if let Some(c) = &self.content {
            return Some(c.clone());
        }
        self.json_body.as_ref().map(|v| serde_json::to_vec(v).unwrap_or_default())
    }

    /// `{"method", "url", "headers", "params"}`, like Python's `to_dict`.
    pub fn to_json(&self) -> Value {
        json!({"method": self.method, "url": self.url, "headers": self.headers, "params": self.params})
    }
}

fn enc(s: &str) -> String {
    percent_encoding::utf8_percent_encode(s, percent_encoding::NON_ALPHANUMERIC).to_string()
}

/// A provider response.
#[derive(Debug, Clone, PartialEq)]
pub struct HttpResponse {
    pub status: u16,
    /// Lower-cased names; repeated headers are joined with `", "`.
    pub headers: BTreeMap<String, String>,
    pub text: String,
    pub url: String,
}

impl HttpResponse {
    pub fn ok(&self) -> bool {
        (200..300).contains(&self.status)
    }

    /// Parsed JSON body, or `None` when the body is not JSON.
    pub fn json(&self) -> Option<Value> {
        if self.text.is_empty() { None } else { serde_json::from_str(&self.text).ok() }
    }

    /// JSON when possible, raw text otherwise.
    pub fn body(&self) -> Value {
        self.json().unwrap_or_else(|| Value::String(self.text.clone()))
    }
}

/// Sends requests. Implement it to plug in your own HTTP client or a test double.
pub trait Transport: Send + Sync {
    fn send<'a>(&'a self, request: Request) -> BoxFuture<'a, Result<HttpResponse>>;
}

/// HTTP client options shared by both transports.
#[derive(Debug, Clone)]
pub struct HttpOptions {
    pub timeout: Duration,
    pub follow_redirects: bool,
    pub verify_ssl: bool,
}

impl Default for HttpOptions {
    fn default() -> Self {
        Self { timeout: DEFAULT_TIMEOUT, follow_redirects: true, verify_ssl: true }
    }
}

fn method(m: &str) -> Result<reqwest::Method> {
    reqwest::Method::from_bytes(m.to_uppercase().as_bytes()).map_err(|_| Error::request(format!("invalid HTTP method '{m}'")))
}

fn prepared(request: &Request) -> (Vec<(String, String)>, Option<Vec<u8>>) {
    let mut headers: Vec<(String, String)> = request.headers.iter().map(|(k, v)| (k.clone(), v.clone())).collect();
    let body = request.body_bytes();
    if request.content.is_none() && request.json_body.is_some() && !request.headers.contains_key("content-type") {
        headers.push(("content-type".into(), "application/json".into()));
    }
    (headers, body)
}

fn collect_headers(map: &reqwest::header::HeaderMap) -> BTreeMap<String, String> {
    let mut out: BTreeMap<String, String> = BTreeMap::new();
    for (name, value) in map {
        let value = String::from_utf8_lossy(value.as_bytes()).into_owned();
        out.entry(name.as_str().to_lowercase())
            .and_modify(|existing| {
                existing.push_str(", ");
                existing.push_str(&value);
            })
            .or_insert(value);
    }
    out
}

/// Blocking reqwest transport, for [`crate::ConnectorManager`].
pub struct BlockingTransport {
    client: reqwest::blocking::Client,
}

impl BlockingTransport {
    pub fn new(options: &HttpOptions) -> Result<Self> {
        let client = reqwest::blocking::Client::builder()
            .timeout(options.timeout)
            .redirect(if options.follow_redirects { reqwest::redirect::Policy::limited(10) } else { reqwest::redirect::Policy::none() })
            .danger_accept_invalid_certs(!options.verify_ssl)
            .build()?;
        Ok(Self { client })
    }

    /// Send now, on this thread.
    pub fn send_now(&self, request: &Request) -> Result<HttpResponse> {
        let (headers, body) = prepared(request);
        let mut builder = self.client.request(method(&request.method)?, request.full_url());
        for (k, v) in headers {
            builder = builder.header(k, v);
        }
        if let Some(b) = body {
            builder = builder.body(b);
        }
        let response = builder.send()?;
        let status = response.status().as_u16();
        let headers = collect_headers(response.headers());
        let url = response.url().to_string();
        let text = response.text()?;
        Ok(HttpResponse { status, headers, text, url })
    }
}

impl Transport for BlockingTransport {
    fn send<'a>(&'a self, request: Request) -> BoxFuture<'a, Result<HttpResponse>> {
        let result = self.send_now(&request);
        Box::pin(std::future::ready(result))
    }
}

/// Async reqwest transport, for [`crate::AsyncConnectorManager`]. Needs a Tokio runtime.
pub struct AsyncTransport {
    client: reqwest::Client,
}

impl AsyncTransport {
    pub fn new(options: &HttpOptions) -> Result<Self> {
        let client = reqwest::Client::builder()
            .timeout(options.timeout)
            .redirect(if options.follow_redirects { reqwest::redirect::Policy::limited(10) } else { reqwest::redirect::Policy::none() })
            .danger_accept_invalid_certs(!options.verify_ssl)
            .build()?;
        Ok(Self { client })
    }
}

impl Transport for AsyncTransport {
    fn send<'a>(&'a self, request: Request) -> BoxFuture<'a, Result<HttpResponse>> {
        Box::pin(async move {
            let (headers, body) = prepared(&request);
            let mut builder = self.client.request(method(&request.method)?, request.full_url());
            for (k, v) in headers {
                builder = builder.header(k, v);
            }
            if let Some(b) = body {
                builder = builder.body(b);
            }
            let response = builder.send().await?;
            let status = response.status().as_u16();
            let headers = collect_headers(response.headers());
            let url = response.url().to_string();
            let text = response.text().await?;
            Ok(HttpResponse { status, headers, text, url })
        })
    }
}

/// Drive a future whose transport completes synchronously.
///
/// The sync manager's futures never wait on anything: every `send` is a
/// [`BlockingTransport`] call that has already finished. A transport that does
/// return `Pending` belongs with [`crate::AsyncConnectorManager`] instead.
pub fn block_on<F: Future>(future: F) -> F::Output {
    let mut future = std::pin::pin!(future);
    let mut cx = Context::from_waker(Waker::noop());
    loop {
        if let Poll::Ready(value) = future.as_mut().poll(&mut cx) {
            return value;
        }
        std::thread::yield_now();
    }
}
