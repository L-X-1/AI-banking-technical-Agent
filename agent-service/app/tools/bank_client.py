"""bank-core HTTP 客户端（唯一数据通道；Agent 无 DB 直连——沙箱隔离铁律）。"""
import os
from typing import Any

import httpx

from ..config import BANK_CORE_URL, DEMO_USER_ID


class BankError(Exception):
    def __init__(self, code: str, message: str, status: int = 500) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.status = status


class BankClient:
    def __init__(self, base_url: str | None = None, user_id: str | None = None,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.base_url = base_url or BANK_CORE_URL
        self.user_id = user_id or DEMO_USER_ID
        self._transport = transport

    def _headers(self) -> dict[str, str]:
        return {"X-User-Id": self.user_id}

    async def get(self, path: str, **params: Any) -> dict:
        params = {k: v for k, v in params.items() if v is not None}
        async with httpx.AsyncClient(base_url=self.base_url, timeout=10.0,
                                     transport=self._transport, trust_env=False) as c:
            r = await c.get(path, params=params, headers=self._headers())
        return self._decode(r)

    async def post(self, path: str, payload: dict, idempotency_key: str | None = None) -> dict:
        headers = self._headers()
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        async with httpx.AsyncClient(base_url=self.base_url, timeout=10.0,
                                     transport=self._transport, trust_env=False) as c:
            r = await c.post(path, json=payload, headers=headers)
        return self._decode(r)

    @staticmethod
    def _decode(r: httpx.Response) -> dict:
        try:
            body = r.json()
        except Exception:  # noqa: BLE001
            raise BankError("BANK_BAD_RESPONSE", f"HTTP {r.status_code}", r.status_code)
        if r.status_code >= 400:
            detail = body.get("detail") if isinstance(body, dict) else None
            if isinstance(detail, dict):
                raise BankError(detail.get("code", "BANK_ERROR"), detail.get("message", ""), r.status_code)
            raise BankError("BANK_ERROR", str(detail or body), r.status_code)
        return body


def default_client() -> BankClient:
    """生产路径：真实 bank-core；测试可传 transport 注入。"""
    return BankClient(base_url=os.environ.get("BANK_CORE_URL", BANK_CORE_URL))
