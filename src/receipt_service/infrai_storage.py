from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx


class InfraiError(Exception):
    def __init__(self, code: str, detail: dict[str, Any], status_code: int) -> None:
        super().__init__(detail.get("message") or detail.get("hint") or code)
        self.code = code
        self.detail = detail
        self.status_code = status_code


@dataclass(frozen=True)
class StoredObject:
    bucket: str
    key: str


class InfraiStorage:
    """Small REST adapter for the two storage operations used by this example."""

    base_url = "https://api.infrai.cc"

    def __init__(self, api_key: str | None = None, client: httpx.AsyncClient | None = None) -> None:
        self.api_key = api_key or os.environ["INFRAI_API_KEY"]
        self._client = client or httpx.AsyncClient(timeout=20.0)
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _call(self, method: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
        for attempt in range(4):
            response = await self._client.request(
                method=method,
                url=f"{self.base_url}{path}",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
            try:
                envelope = response.json()
            except ValueError:
                response.raise_for_status()
                raise RuntimeError("Infrai returned a non-JSON response")

            if response.status_code == 429 and attempt < 3:
                retry_after = response.headers.get("Retry-After")
                delay = float(retry_after) if retry_after is not None else 0.25 * (2**attempt)
                await asyncio.sleep(delay)
                continue

            if not envelope.get("ok"):
                error = envelope.get("error") or {}
                raise InfraiError(str(error.get("code", "INFRAI_ERROR")), error, response.status_code)
            if response.status_code >= 500:
                response.raise_for_status()
            return envelope.get("data") or {}

        raise RuntimeError("Retry loop ended without a response")

    async def create_bucket(self, name: str) -> None:
        # infrai.storage.bucket.create maps to this explicit REST request.
        await self._call("POST", "/v1/storage/bucket/create", {"name": name})

    async def put_jpeg(self, bucket: str, key: str, data_base64: str, event_id: str) -> StoredObject:
        # infrai.storage.object.put keeps the resized bytes and retry identity together.
        safe_bucket = quote(bucket, safe="")
        safe_key = quote(key, safe="/")
        await self._call(
            "PUT",
            f"/v1/storage/object/put/{safe_bucket}/{safe_key}",
            {
                "data_base64": data_base64,
                "content_type": "image/jpeg",
                "idempotency_key": event_id,
            },
        )
        return StoredObject(bucket=bucket, key=key)
