"""M1 联调冒烟脚本：驱动 agent-service 全链路并打印消息与审计。

用法：
  1) 先启动银行核心：cd bank-core && python -m uvicorn app.main:app --port 8100
  2) 再运行本脚本：python scripts/m1_smoke.py
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "agent-service"))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def show(title: str, out: dict) -> None:
    print("=" * 16, title)
    for m in out.get("messages", []):
        print(f"  [{m['type']}] {json.dumps(m['payload'], ensure_ascii=False)[:180]}")
    print("  session_status:", out.get("session_status"), "| trace:", out.get("trace_id"))


def main() -> int:
    with TestClient(app) as c:
        sid = "s_smoke"
        out = c.post("/api/chat", json={"session_id": sid, "text": "给赵敏转 50，备注冒烟测试"}).json()
        show("① 首轮（期望 tool_progress + confirm_card）", out)
        cards = [m for m in out.get("messages", []) if m["type"] == "confirm_card"]
        if not cards:
            print("!! 未收到确认卡，终止")
            return 1
        aid = cards[0]["payload"]["action_id"]
        out2 = c.post("/api/confirm", json={"session_id": sid, "action_id": aid, "approved": True}).json()
        show("② 确认后（期望 receipt + final）", out2)
        trace = out2.get("trace_id") or out.get("trace_id")
        data = c.get(f"/api/audit/{trace}").json()
        print("audit kinds:", data["kinds"])
        for e in data["events"]:
            print(f"    - {e['node']:<10} {json.dumps(e['payload'], ensure_ascii=False)[:120]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
