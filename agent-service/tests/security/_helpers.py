"""tests/security 共享件：渗透报告记录器 + 离线 FakeBank（无 bank-core 依赖）。"""
import json
import pathlib
import uuid

from app.tools.bank_client import BankError

RESULTS: list[dict] = []


def record(case_id: str, category: str, passed: bool, detail: str = "") -> None:
    """向渗透报告追加一行（tests/security/conftest.py 在 sessionfinish 落盘）。"""
    RESULTS.append({"case": case_id, "category": category, "passed": bool(passed),
                    "detail": detail})


def load_corpus() -> list[dict]:
    path = pathlib.Path(__file__).with_name("jailbreak_corpus.jsonl")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def new_sid(prefix: str = "sec") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:6]}"


def of(messages: list[dict], kind: str) -> list[dict]:
    return [m for m in messages if m["type"] == kind]


def final_texts(out: dict) -> list[str]:
    return [m["payload"].get("text", "") for m in of(out.get("messages", []), "final")]


class FakeBank:
    """离线 bank-core 替身：余额查询 / 联系人消歧 / 流水；fail_get 模拟核心不可用（熔断 T1）。"""

    def __init__(self, fail_get: bool = False) -> None:
        self.fail_get = fail_get

    async def get(self, path: str, **params):
        if self.fail_get:
            raise BankError("BANK_UNAVAILABLE", "模拟 bank-core 不可用", 503)
        if path == "/api/accounts":
            return {"items": [{"id": "a001", "type": "checking", "balance": 43210.55},
                              {"id": "a002", "type": "savings", "balance": 80000.0}]}
        if path == "/api/contacts":
            if (params.get("keyword") or "") == "李磊":
                return {"items": [
                    {"id": "c02", "name": "李磊", "phone_tail": "3821", "remark": "同事"},
                    {"id": "c03", "name": "李磊", "phone_tail": "7790", "remark": "大学"}]}
            return {"items": [{"id": "c01", "name": "赵敏", "phone_tail": "6612", "remark": "同事"}]}
        if "/transactions" in path:
            return {"items": []}
        raise BankError("NOT_FOUND", f"FakeBank 未实现 {path}", 404)

    async def post(self, path: str, payload: dict, idempotency_key: str | None = None):
        raise BankError("NOT_USED", "M2 安全测试不执行真实写入", 400)
