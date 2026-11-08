"""Minimal async client for the Strata server's monitoring endpoints."""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp


class StrataError(Exception):
    """Base error."""


class StrataConnectionError(StrataError):
    """Server not reachable or returned an unexpected response."""


class StrataAuthError(StrataError):
    """API key missing or wrong (HTTP 401)."""


class StrataClient:
    """Talks to GET /health and GET /metrics (JSON, the web app's Monitor feed)."""

    def __init__(self, session: aiohttp.ClientSession, url: str, api_key: str | None,
                 verify_ssl: bool = True, timeout: float = 10.0) -> None:
        self._session = session
        self._url = url.rstrip("/")
        self._api_key = api_key or None
        self._ssl = None if verify_ssl else False
        self._timeout = timeout

    @property
    def url(self) -> str:
        return self._url

    async def _get(self, path: str) -> dict[str, Any]:
        # Accept: application/json - /metrics answers in Prometheus text format for text/plain or openmetrics
        headers = {"Accept": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        try:
            async with asyncio.timeout(self._timeout):
                async with self._session.get(self._url + path, headers=headers, ssl=self._ssl) as resp:
                    if resp.status == 401:
                        raise StrataAuthError("missing or wrong API key")
                    if resp.status != 200:
                        raise StrataConnectionError(f"{path} answered HTTP {resp.status}")
                    data = await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise StrataConnectionError(f"cannot reach {self._url}{path}: {err}") from err
        except ValueError as err:  # not JSON
            raise StrataConnectionError(f"{path} did not return JSON") from err
        if not isinstance(data, dict):
            raise StrataConnectionError(f"{path} returned an unexpected payload")
        return data

    async def health(self) -> dict[str, Any]:
        """GET /health - no key needed; service == 'strata'."""
        return await self._get("/health")

    async def metrics(self) -> dict[str, Any]:
        """GET /metrics - engine, live state, last 12 requests, totals, hardware, 60 s history."""
        return await self._get("/metrics")
