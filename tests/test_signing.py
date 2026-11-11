"""Per-request signing: AWS SigV4 and Alibaba Cloud ACS3-HMAC-SHA256.

The AWS vectors are from AWS's published SigV4 test suite (``get-vanilla`` and
``get-vanilla-query-order-key-case``). The ACS3 vector was cross-checked against
``alibabacloud_openapi_util.Client.get_authorization``; the SigV4 signer was also
cross-checked against botocore for JSON, query, REST and S3 requests.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import pytest

from connector_manager import Connection, ConnectorManager
from connector_manager.signing import sign_acs3, sign_aws_sigv4
from connector_manager.verification import CredentialVerifier

AWS_KEY, AWS_SECRET = "AKIDEXAMPLE", "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY"
SUITE_TIME = datetime(2015, 8, 30, 12, 36, 0, tzinfo=timezone.utc)


def _sigv4(url: str, params: dict[str, str]) -> str:
    _, headers = sign_aws_sigv4(
        method="GET", url=url, headers={}, params=params, body=b"",
        access_key=AWS_KEY, secret_key=AWS_SECRET, region="us-east-1", service="service", now=SUITE_TIME,
    )
    return headers["authorization"]


def test_sigv4_get_vanilla() -> None:
    assert _sigv4("https://example.amazonaws.com/", {}) == (
        "AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/20150830/us-east-1/service/aws4_request, "
        "SignedHeaders=host;x-amz-date, "
        "Signature=5fa00fa31553b73ebf1942676e86291e8372ff2a2260956d9b8aae1d763fbf31"
    )


def test_sigv4_sorts_the_query() -> None:
    signed = _sigv4("https://example.amazonaws.com/", {"Param2": "value2", "Param1": "value1"})
    assert signed.endswith("Signature=b97d918cfa904a5beff61c982a1b6f458b799221646efd99d3219ec94cdf2500")


def test_acs3_matches_the_sdk() -> None:
    _, headers = sign_acs3(
        method="POST",
        url="https://ecs.cn-hangzhou.aliyuncs.com/",
        headers={"x-acs-action": "DescribeRegions", "x-acs-version": "2014-05-26"},
        params={"RegionId": "cn-hangzhou", "Tag.1.Key": "a b*"},
        body=b"",
        access_key="LTAIkey",
        secret_key="secret",
        now=datetime(2026, 11, 11, 12, 0, 0, tzinfo=timezone.utc),
        nonce="n0nce",
    )
    assert headers["authorization"] == (
        "ACS3-HMAC-SHA256 Credential=LTAIkey,"
        "SignedHeaders=host;x-acs-action;x-acs-content-sha256;x-acs-date;x-acs-signature-nonce;x-acs-version,"
        "Signature=770a0bd7a9060f1809eebd69c5d582e8cfc595a41bc0463a151f36fd24ecaa9a"
    )
    assert headers["x-acs-content-sha256"] == hashlib.sha256(b"").hexdigest()


@pytest.fixture(scope="module")
def manager() -> ConnectorManager:
    with ConnectorManager() as m:
        yield m


def _connection(connector_id: str, config: dict[str, str], username: str = AWS_KEY) -> Connection:
    return Connection(
        connection_id="t",
        connector_id=connector_id,
        auth_mode=ConnectorManager().get_auth_schema(connector_id).auth_mode,
        credentials={"username": username, "password": AWS_SECRET},
        connection_config=config,
    )


def test_an_aws_service_connector_sends_what_it_signed(manager: ConnectorManager) -> None:
    conn = _connection("aws-dynamodb", {"region": "eu-west-1"})
    request = manager.prepare_request(
        conn, "POST", "/", headers={"x-amz-target": "DynamoDB_20120810.ListTables"}, json_body={"Limit": 1}
    )
    assert request.url == "https://dynamodb.eu-west-1.amazonaws.com/"
    assert request.headers["authorization"].startswith(
        f"AWS4-HMAC-SHA256 Credential={AWS_KEY}/"
    )
    assert "/eu-west-1/dynamodb/aws4_request" in request.headers["authorization"]
    assert "x-amz-target" in request.headers["authorization"]  # signed, not just sent
    assert request.headers["content-type"] == "application/x-amz-json-1.0"
    # The body goes out as the exact bytes that were hashed.
    assert request.content == json.dumps({"Limit": 1}, separators=(",", ":")).encode()


def test_a_query_api_carries_its_version_in_the_signed_url(manager: ConnectorManager) -> None:
    conn = _connection("aws-ec2", {"region": "us-west-2"})
    request = manager.prepare_request(conn, "GET", "/", params={"Action": "DescribeRegions"})
    assert request.url == "https://ec2.us-west-2.amazonaws.com/?Action=DescribeRegions&Version=2016-11-15"
    assert request.params == {}


def test_a_global_aws_service_signs_for_its_home_region(manager: ConnectorManager) -> None:
    request = manager.prepare_request(_connection("aws-route53", {}), "GET", "/2013-04-01/hostedzone")
    assert request.url.startswith("https://route53.amazonaws.com/")
    assert "/us-east-1/route53/aws4_request" in request.headers["authorization"]


def test_the_fixed_legacy_aws_connectors_sign(manager: ConnectorManager) -> None:
    """aws-multi-service used to template an awsSigV4() header nothing evaluated."""
    conn = _connection("aws-multi-service", {"region": "us-east-1", "service": "athena"})
    request = manager.prepare_request(conn, "GET", "/")
    assert "/us-east-1/athena/aws4_request" in request.headers["authorization"]
    assert not request.headers["authorization"].startswith("Basic ")


def test_an_alibaba_connector_signs_with_acs3(manager: ConnectorManager) -> None:
    conn = _connection("alibaba-cloud-ecs", {"region": "cn-hangzhou"}, username="LTAIexample")
    request = manager.prepare_request(
        conn, "POST", "/", headers={"x-acs-action": "DescribeRegions"}, params={"RegionId": "cn-hangzhou"}
    )
    assert request.url == "https://ecs.cn-hangzhou.aliyuncs.com/?RegionId=cn-hangzhou"
    assert request.headers["x-acs-version"] == "2014-05-26"
    assert request.headers["authorization"].startswith("ACS3-HMAC-SHA256 Credential=LTAIexample,")


def test_a_signed_verification_hashes_the_body_it_sends(manager: ConnectorManager) -> None:
    conn = _connection("aws-kms", {"region": "us-east-1"})
    verifier = CredentialVerifier(manager.registry.raw("aws-kms"), conn)
    request = next(verifier.flow())
    assert request.headers["x-amz-target"] == "TrentService.ListKeys"
    assert "x-amz-target" in request.headers["authorization"]
    assert request.headers["content-type"] == "application/x-amz-json-1.1"
    body = request.content if isinstance(request.content, bytes) else str(request.content).encode()
    assert body == b"{}"


def test_signing_without_keys_is_a_clear_error(manager: ConnectorManager) -> None:
    conn = Connection(
        connection_id="t", connector_id="aws-sqs", auth_mode=manager.get_auth_schema("aws-sqs").auth_mode,
        credentials={}, connection_config={"region": "us-east-1"},
    )
    with pytest.raises(Exception, match="access key"):
        manager.prepare_request(conn, "GET", "/")
