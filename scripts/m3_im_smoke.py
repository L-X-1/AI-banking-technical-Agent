"""M3#8 IM 通道联调冒烟（真连 bank-core:8100 + agent-service:8000）：

用法：
    python scripts/m3_im_smoke.py
    # agent-service 非 8000 端口时用环境变量覆盖（部署标准为 8200）：
    AGENT_URL=http://127.0.0.1:8200 python scripts/m3_im_smoke.py
输出：IM 文本逐轮打印 + 审计事件回放（doc 05 M3#8 验收：MockImView 页面完成一次转账确认全流程）。
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request

AGENT = os.environ.get("AGENT_URL", "http://127.0.0.1:8000")
BANK = os.environ.get("BANK_URL", "http://127.0.0.1:8100")
SID = "s_im_smoke_1"

# 沙箱代理会劫持本机请求（agent-service 的 httpx 同样 trust_env=False）：本地冒烟直连禁代理
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def get(url: str, timeout: float = 10):
    return OPENER.open(url, timeout=timeout)


def im(text: str) -> dict:
    req = urllib.request.Request(
        f"{AGENT}/api/im/webhook",
        data=json.dumps({"session_id": SID, "text": text}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    return json.loads(OPENER.open(req, timeout=30).read())


def main() -> int:
    for svc in (AGENT, BANK):
        try:
            get(f"{svc}/health", timeout=5).read()
        except (urllib.error.URLError, OSError):
            print(f"[FAIL] {svc} unreachable: start bank-core(:8100) and agent-service first; "
                  f"non-default agent port can be set via AGENT_URL env var")
            return 1

    ok = False
    trace = ""
    for t in ["给赵敏转 200，备注聚餐 AA", "1"]:
        out = im(t)
        trace = out.get("trace_id") or trace
        print(f"\n[me] {t}   (status={out['session_status']})")
        for r in out.get("replies", []):
            print(f"[zhiyin] {r}")
        if any(t2.startswith("【回执】") and "赵敏" in t2 for t2 in out.get("replies", [])):
            ok = True
        # 红链（当日累计超阈值 → 升红）：短信码以文本直输，验证后自动出回执
        if out["session_status"] == "waiting_mfa":
            code = next((re.search(r"(\d{6})", r).group(1)
                         for r in out["replies"] if re.search(r"验证码 (\d{6})", r)), "")
            out2 = im(code)
            trace = out2.get("trace_id") or trace
            print(f"\n[me] {code}   (status={out2['session_status']})")
            for r in out2.get("replies", []):
                print(f"[zhiyin] {r}")
            ok = ok or any(r.startswith("【回执】") and "赵敏" in r
                           for r in out2.get("replies", []))

    out3 = im("我的余额")
    trace = out3.get("trace_id") or trace
    print(f"\n[me] 我的余额   (status={out3['session_status']})")
    for r in out3.get("replies", []):
        print(f"[zhiyin] {r}")

    audit = json.loads(get(f"{AGENT}/api/audit/{trace}", timeout=10).read())
    print(f"\n[audit] trace={trace} events={len(audit['events'])} kinds="
          f"{' / '.join(sorted({e['node'] for e in audit['events']}))}")

    print("\n[PASS] IM degraded channel end-to-end (confirm card as text + receipt + audit replay)"
          if ok else "\n[FAIL] no transfer receipt")
    return 0 if ok else 2



if __name__ == "__main__":
    sys.exit(main())
