//! Per-request signatures for clouds that sign every call rather than send a token.
//!
//! * `proxy.aws_sigv4` — AWS Signature Version 4: `{"service": "lambda", "region": "..."}`.
//! * `proxy.acs3` — Alibaba Cloud ACS3-HMAC-SHA256: `{"version": "2014-05-26"}`.
//!
//! Access key id and secret come from the connection's `username` and
//! `password`. Both sign the request exactly as it goes on the wire.

use std::collections::BTreeMap;

use chrono::{DateTime, Utc};
use hmac::{Hmac, KeyInit, Mac};
use percent_encoding::{AsciiSet, NON_ALPHANUMERIC, percent_decode_str, utf8_percent_encode};
use sha2::{Digest, Sha256};

/// RFC 3986 unreserved characters stay literal; everything else is encoded.
const UNRESERVED: &AsciiSet = &NON_ALPHANUMERIC.remove(b'-').remove(b'_').remove(b'.').remove(b'~');
const PATH_SAFE: &AsciiSet = &UNRESERVED.remove(b'/');

fn sha256_hex(data: &[u8]) -> String {
    hex::encode(Sha256::digest(data))
}

fn hmac_sha256(key: &[u8], msg: &str) -> Vec<u8> {
    let mut mac = Hmac::<Sha256>::new_from_slice(key).expect("hmac accepts any key");
    mac.update(msg.as_bytes());
    mac.finalize().into_bytes().to_vec()
}

fn encode(value: &str) -> String {
    utf8_percent_encode(value, UNRESERVED).to_string()
}

/// The sorted, RFC 3986-encoded query both signers hash and send.
pub fn canonical_query(url_query: &str, params: &BTreeMap<String, String>) -> String {
    let mut pairs: Vec<(String, String)> =
        url::form_urlencoded::parse(url_query.as_bytes()).map(|(k, v)| (encode(&k), encode(&v))).collect();
    pairs.extend(params.iter().map(|(k, v)| (encode(k), encode(v))));
    pairs.sort();
    pairs.into_iter().map(|(k, v)| format!("{k}={v}")).collect::<Vec<_>>().join("&")
}

/// The path percent-encoded once, as it will be sent.
fn wire_path(path: &str) -> String {
    let decoded = percent_decode_str(if path.is_empty() { "/" } else { path }).decode_utf8_lossy();
    let out = utf8_percent_encode(&decoded, PATH_SAFE).to_string();
    if out.is_empty() { "/".into() } else { out }
}

fn canonical_headers(headers: &BTreeMap<String, String>, signed: &[String]) -> String {
    signed.iter().map(|name| format!("{name}:{}\n", headers[name].split_whitespace().collect::<Vec<_>>().join(" "))).collect()
}

/// `(scheme://host, path, query)` of a url.
fn split_url(url: &str) -> (String, String, String, String) {
    match url::Url::parse(url) {
        Ok(u) => {
            let host = match u.port() {
                Some(p) => format!("{}:{p}", u.host_str().unwrap_or("")),
                None => u.host_str().unwrap_or("").to_string(),
            };
            (u.scheme().to_string(), host, u.path().to_string(), u.query().unwrap_or("").to_string())
        }
        Err(_) => ("https".into(), String::new(), url.to_string(), String::new()),
    }
}

/// Inputs to one signature.
pub struct SignInput<'a> {
    pub method: &'a str,
    pub url: &'a str,
    pub headers: BTreeMap<String, String>,
    pub params: &'a BTreeMap<String, String>,
    pub body: &'a [u8],
    pub access_key: &'a str,
    pub secret_key: &'a str,
    pub session_token: Option<&'a str>,
    pub now: DateTime<Utc>,
}

/// AWS SigV4. Returns the url (path re-encoded as signed) and the signed headers.
pub fn sign_aws_sigv4(input: SignInput<'_>, region: &str, service: &str) -> (String, BTreeMap<String, String>) {
    let amz_date = input.now.format("%Y%m%dT%H%M%SZ").to_string();
    let date_stamp = input.now.format("%Y%m%d").to_string();
    let (scheme, host, path, query) = split_url(input.url);

    let mut out: BTreeMap<String, String> =
        input.headers.into_iter().map(|(k, v)| (k.to_lowercase(), v)).filter(|(k, _)| k != "authorization").collect();
    out.insert("host".into(), host.clone());
    out.insert("x-amz-date".into(), amz_date.clone());
    if let Some(t) = input.session_token.filter(|t| !t.is_empty()) {
        out.insert("x-amz-security-token".into(), t.into());
    }
    let payload_hash = sha256_hex(input.body);
    if service == "s3" {
        out.insert("x-amz-content-sha256".into(), payload_hash.clone());
    }

    let wire = wire_path(&path);
    // S3 signs the path as sent; every other service signs it encoded twice.
    let canonical_uri = if service == "s3" { wire.clone() } else { utf8_percent_encode(&wire, PATH_SAFE).to_string() };
    let signed: Vec<String> =
        out.keys().filter(|n| matches!(n.as_str(), "host" | "content-type" | "content-md5") || n.starts_with("x-amz-")).cloned().collect();
    let canonical_request = [
        input.method.to_uppercase(),
        canonical_uri,
        canonical_query(&query, input.params),
        canonical_headers(&out, &signed),
        signed.join(";"),
        payload_hash,
    ]
    .join("\n");
    let scope = format!("{date_stamp}/{region}/{service}/aws4_request");
    let string_to_sign = ["AWS4-HMAC-SHA256".to_string(), amz_date, scope.clone(), sha256_hex(canonical_request.as_bytes())].join("\n");
    let mut key = hmac_sha256(format!("AWS4{}", input.secret_key).as_bytes(), &date_stamp);
    for part in [region, service, "aws4_request"] {
        key = hmac_sha256(&key, part);
    }
    let signature = hex::encode(hmac_sha256(&key, &string_to_sign));
    out.insert(
        "authorization".into(),
        format!("AWS4-HMAC-SHA256 Credential={}/{scope}, SignedHeaders={}, Signature={signature}", input.access_key, signed.join(";")),
    );
    out.remove("host"); // the transport sets Host from the url, which is what was signed
    (format!("{scheme}://{host}{wire}"), out)
}

/// Alibaba Cloud ACS3-HMAC-SHA256. Returns the url and the signed headers.
pub fn sign_acs3(input: SignInput<'_>, nonce: &str) -> (String, BTreeMap<String, String>) {
    let (scheme, host, path, query) = split_url(input.url);
    let mut out: BTreeMap<String, String> =
        input.headers.into_iter().map(|(k, v)| (k.to_lowercase(), v)).filter(|(k, _)| k != "authorization").collect();
    out.insert("host".into(), host.clone());
    out.insert("x-acs-date".into(), input.now.format("%Y-%m-%dT%H:%M:%SZ").to_string());
    out.insert("x-acs-signature-nonce".into(), nonce.into());
    out.insert("x-acs-content-sha256".into(), sha256_hex(input.body));
    if let Some(t) = input.session_token.filter(|t| !t.is_empty()) {
        out.insert("x-acs-security-token".into(), t.into());
    }
    let wire = wire_path(&path);
    let signed: Vec<String> =
        out.keys().filter(|n| matches!(n.as_str(), "host" | "content-type") || n.starts_with("x-acs-")).cloned().collect();
    let canonical_request = [
        input.method.to_uppercase(),
        wire.clone(),
        canonical_query(&query, input.params),
        canonical_headers(&out, &signed),
        signed.join(";"),
        out["x-acs-content-sha256"].clone(),
    ]
    .join("\n");
    let string_to_sign = format!("ACS3-HMAC-SHA256\n{}", sha256_hex(canonical_request.as_bytes()));
    let signature = hex::encode(hmac_sha256(input.secret_key.as_bytes(), &string_to_sign));
    out.insert(
        "authorization".into(),
        format!("ACS3-HMAC-SHA256 Credential={},SignedHeaders={},Signature={signature}", input.access_key, signed.join(";")),
    );
    out.remove("host");
    (format!("{scheme}://{host}{wire}"), out)
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    fn input<'a>(url: &'a str, params: &'a BTreeMap<String, String>, now: DateTime<Utc>) -> SignInput<'a> {
        SignInput {
            method: "GET",
            url,
            headers: BTreeMap::new(),
            params,
            body: b"",
            access_key: "AKIDEXAMPLE",
            secret_key: "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY",
            session_token: None,
            now,
        }
    }

    /// AWS's published SigV4 test suite: get-vanilla and get-vanilla-query-order-key-case.
    #[test]
    fn sigv4_published_vectors() {
        let now = Utc.with_ymd_and_hms(2015, 8, 30, 12, 36, 0).unwrap();
        let empty = BTreeMap::new();
        let (_, h) = sign_aws_sigv4(input("https://example.amazonaws.com/", &empty, now), "us-east-1", "service");
        assert!(h["authorization"].ends_with("Signature=5fa00fa31553b73ebf1942676e86291e8372ff2a2260956d9b8aae1d763fbf31"));
        let params: BTreeMap<String, String> =
            [("Param2".to_string(), "value2".to_string()), ("Param1".to_string(), "value1".to_string())].into();
        let (_, h) = sign_aws_sigv4(input("https://example.amazonaws.com/", &params, now), "us-east-1", "service");
        assert!(h["authorization"].ends_with("Signature=b97d918cfa904a5beff61c982a1b6f458b799221646efd99d3219ec94cdf2500"));
    }

    /// The vector the Python suite pins, itself cross-checked against Alibaba's SDK.
    #[test]
    fn acs3_matches_python_and_sdk() {
        let now = Utc.with_ymd_and_hms(2026, 11, 11, 12, 0, 0).unwrap();
        let params: BTreeMap<String, String> =
            [("RegionId".to_string(), "cn-hangzhou".to_string()), ("Tag.1.Key".to_string(), "a b*".to_string())].into();
        let mut i = input("https://ecs.cn-hangzhou.aliyuncs.com/", &params, now);
        i.method = "POST";
        i.access_key = "LTAIkey";
        i.secret_key = "secret";
        i.headers.insert("x-acs-action".into(), "DescribeRegions".into());
        i.headers.insert("x-acs-version".into(), "2014-05-26".into());
        let (_, h) = sign_acs3(i, "n0nce");
        assert_eq!(
            h["authorization"],
            "ACS3-HMAC-SHA256 Credential=LTAIkey,SignedHeaders=host;x-acs-action;x-acs-content-sha256;x-acs-date;x-acs-signature-nonce;x-acs-version,Signature=770a0bd7a9060f1809eebd69c5d582e8cfc595a41bc0463a151f36fd24ecaa9a"
        );
    }
}
