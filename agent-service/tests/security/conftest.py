"""tests/security 夹具与渗透报告导出（M2#5：`pytest tests/security/` 输出可附进安全自评报告）。"""
import os
import time

import pytest

from _helpers import RESULTS, FakeBank   # noqa: F401  （同目录辅助模块；REPORT 消费 RESULTS）


@pytest.fixture(scope="module")
def client():
    from app.main import app
    from fastapi.testclient import TestClient
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def sid():
    from _helpers import new_sid
    return new_sid()


@pytest.fixture()
def use_fake_bank():
    """替换 bank-core 客户端工厂（离线 E2E）；结束时还原，避免影响其他测试。"""
    import app.graph.agent_graph as ag
    original = ag._client_factory
    yield lambda bank: ag.set_client_factory(lambda: bank)
    ag.set_client_factory(original)


def pytest_sessionfinish(session, exitstatus):
    if not RESULTS:
        return
    report_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "report")
    os.makedirs(report_dir, exist_ok=True)
    total = len(RESULTS)
    passed = sum(1 for r in RESULTS if r["passed"])
    corpus = [r for r in RESULTS if r["category"] == "注入防御/越狱语料"
              and r["case"].startswith("corpus.J")]      # 拦截率只统计 J01-J20 语料本体
    blocked = sum(1 for r in corpus if r["passed"])
    rate = f"{blocked / len(corpus) * 100:.1f}%" if corpus else "—"
    payload = {
        "title": "银行 AI 智能体渗透测试报告（M2#5）",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "pytest_exit_code": int(exitstatus),
        "stats": {"total": total, "passed": passed, "failed": total - passed,
                  "jailbreak_corpus": len(corpus), "blocked": blocked, "block_rate": rate},
        "results": RESULTS,
    }
    import json
    with open(os.path.join(report_dir, "pentest_report.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    def _section(cat: str, title: str) -> str:
        rows = [r for r in RESULTS if r["category"] == cat]
        if not rows:
            return ""
        lines = [f"## {title}", "", "| 用例 | 结果 | 说明 |", "|---|---|---|"]
        lines += [f"| {r['case']} | {'✅ 通过' if r['passed'] else '❌ 失败'} | {r['detail']} |"
                  for r in rows]
        return "\n".join(lines) + "\n"

    md = [
        "# 银行 AI 智能体渗透测试报告（M2#5）", "",
        f"- 生成时间：{payload['generated_at']}",
        f"- 执行方式：`pytest tests/security/ -q`（退出码 {exitstatus}）",
        f"- 用例总数：{total}｜通过 {passed}｜失败 {total - passed}",
        f"- 越狱语料拦截：{blocked}/{len(corpus)}（拦截率 {rate}）", "",
        "> 可直接作为 doc 05 §2 安全自评报告「注入防御 / 幻觉防护 / 异常熔断 / 沙箱隔离」章节的验证附件。",
        "",
        _section("注入防御/越狱语料", "1. 注入防御（20 条越狱语料，doc 05 M2#1）"),
        _section("注入防御/模型路", "2. 注入模型路（LLM 分类器，fail-closed 降级）"),
        _section("幻觉校验", "3. 幻觉校验 verifier（doc 05 M2#2）"),
        _section("异常熔断", "4. 异常熔断四触发（doc 05 M2#3）"),
        _section("沙箱隔离", "5. 沙箱隔离（doc 05 M2#4）"),
        "## 结论", "",
        f"{'全部通过 ✅' if passed == total and exitstatus == 0 else '存在失败项 ❌，需修复后重跑'}",
        "",
    ]
    with open(os.path.join(report_dir, "pentest_report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    print(f"\n[渗透报告] {os.path.join(report_dir, 'pentest_report.md')}"
          f"（{passed}/{total} 通过，拦截率 {rate}）")
