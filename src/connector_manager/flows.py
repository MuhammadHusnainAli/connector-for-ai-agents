"""The sync/async bridge.

Anything that needs network I/O (token exchanges, verification calls) is written
once as a **flow**: a generator that yields :class:`~connector_manager.http.Request`
objects, receives :class:`~connector_manager.http.HttpResponse` objects back, and
returns its result.

:class:`FlowRunner` drives a flow with the sync client, :class:`AsyncFlowRunner`
with the async client. The auth logic itself is written exactly once.

    def flow(self, ctx):                 # a strategy method
        response = yield Request("POST", url, ...)
        return parse(response)
"""

from __future__ import annotations

from types import GeneratorType
from typing import Any, Generator, TypeVar

from .http import AsyncHttpClient, HttpClient, HttpResponse, Request

T = TypeVar("T")

#: What a flow looks like: yields requests, is sent responses, returns a result.
Flow = Generator[Request, HttpResponse, T]

#: A flow implementation may also just return its result when it needs no I/O.
FlowOrResult = "Flow[T] | T"


class BaseFlowRunner:
    """Shared bookkeeping for the two runners."""

    @staticmethod
    def _is_flow(candidate: Any) -> bool:
        return isinstance(candidate, GeneratorType)


class FlowRunner(BaseFlowRunner):
    """Drives flows against a synchronous client."""

    def __init__(self, client: HttpClient) -> None:
        self.client = client

    def run(self, flow: Any) -> Any:
        """Execute a flow (or pass through a plain result) and return its value."""
        if not self._is_flow(flow):
            return flow
        try:
            request = next(flow)
            while True:
                response = self.client.send(request)
                request = flow.send(response)
        except StopIteration as stop:
            return stop.value


class AsyncFlowRunner(BaseFlowRunner):
    """Drives the very same flows against an asynchronous client."""

    def __init__(self, client: AsyncHttpClient) -> None:
        self.client = client

    async def run(self, flow: Any) -> Any:
        if not self._is_flow(flow):
            return flow
        try:
            request = next(flow)
            while True:
                response = await self.client.send(request)
                request = flow.send(response)
        except StopIteration as stop:
            return stop.value
