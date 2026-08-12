"""HTTP plumbing, in both flavours.

Everything that talks to a provider goes through a :class:`Request` object and
one of the two clients here -- :class:`HttpClient` (sync) or
:class:`AsyncHttpClient` (async). The auth strategies never touch a client
directly: they *describe* requests and receive :class:`HttpResponse` objects
back, which is what lets a single implementation serve both worlds.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping
from urllib.parse import urlencode

import httpx

DEFAULT_TIMEOUT = 30.0


@dataclass(slots=True)
class Request:
    """A provider call, fully described and ready to send."""

    method: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    params: dict[str, str] = field(default_factory=dict)
    #: Pre-encoded body (form string, JSON string, ...).
    content: str | bytes | None = None
    #: Body to be JSON-encoded by the client.
    json_body: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "url": self.url,
            "headers": self.headers,
            "params": self.params,
        }


@dataclass(slots=True)
class HttpResponse:
    """A provider response, decoded lazily."""

    status: int
    headers: dict[str, str]
    text: str
    url: str
    _json: Any = field(default=None, repr=False)
    _parsed: bool = field(default=False, repr=False)

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def json(self) -> Any:
        """Parsed JSON body, or ``None`` when the body is not JSON."""
        if not self._parsed:
            self._parsed = True
            try:
                self._json = json.loads(self.text) if self.text else None
            except ValueError:
                self._json = None
        return self._json

    def body(self) -> Any:
        """JSON when possible, raw text otherwise."""
        parsed = self.json()
        return parsed if parsed is not None else self.text


class BaseHttpClient:
    """Shared request/response translation for both clients."""

    @staticmethod
    def _kwargs(request: Request) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "headers": {k: v for k, v in request.headers.items() if v is not None},
            "params": request.params or None,
        }
        if request.content is not None:
            kwargs["content"] = request.content
        elif request.json_body is not None:
            kwargs["json"] = request.json_body
        return kwargs

    @staticmethod
    def _response(response: httpx.Response) -> HttpResponse:
        return HttpResponse(
            status=response.status_code,
            headers={k.lower(): v for k, v in response.headers.items()},
            text=response.text,
            url=str(response.url),
        )

    @staticmethod
    def build_request(
        method: str,
        url: str,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
        data: Any = None,
        json_body: Any = None,
        content: str | bytes | None = None,
    ) -> Request:
        """Convenience constructor used by the managers and the CLI."""
        if content is None and data is not None:
            content = urlencode(data) if isinstance(data, dict) else data
        return Request(
            method=method.upper(),
            url=url,
            headers={k: str(v) for k, v in (headers or {}).items() if v is not None},
            params={k: str(v) for k, v in (params or {}).items()},
            content=content,
            json_body=json_body,
        )


class HttpClient(BaseHttpClient):
    """Synchronous client with a shared connection pool."""

    def __init__(
        self,
        timeout: float = DEFAULT_TIMEOUT,
        follow_redirects: bool = True,
        verify: bool = True,
        client: httpx.Client | None = None,
    ) -> None:
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=timeout, follow_redirects=follow_redirects, verify=verify
        )

    def send(self, request: Request) -> HttpResponse:
        return self._response(
            self._client.request(request.method, request.url, **self._kwargs(request))
        )

    def request(self, method: str, url: str, **kwargs: Any) -> HttpResponse:
        return self.send(self.build_request(method, url, **kwargs))

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "HttpClient":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


class AsyncHttpClient(BaseHttpClient):
    """Asynchronous counterpart of :class:`HttpClient`."""

    def __init__(
        self,
        timeout: float = DEFAULT_TIMEOUT,
        follow_redirects: bool = True,
        verify: bool = True,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=timeout, follow_redirects=follow_redirects, verify=verify
        )

    async def send(self, request: Request) -> HttpResponse:
        return self._response(
            await self._client.request(request.method, request.url, **self._kwargs(request))
        )

    async def request(self, method: str, url: str, **kwargs: Any) -> HttpResponse:
        return await self.send(self.build_request(method, url, **kwargs))

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> "AsyncHttpClient":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()
