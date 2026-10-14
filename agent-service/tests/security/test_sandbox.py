"""M2#4 沙箱隔离（doc 05 DoD #4）：双容器部署下 agent-service 无 bank.db、无 DB 直连串。

说明：运行时容器内探测（docker exec find）需 Docker 环境，留 M4 compose 验证执行；
本文件以源码扫描 + compose 配置断言提供等价静态证据，结论写入渗透报告。
"""
import pathlib

from _helpers import record

REPO = pathlib.Path(__file__).resolve().parents[3]      # 仓库根
APP = pathlib.Path(__file__).resolve().parents[2] / "app"
COMPOSE = REPO / "deploy" / "docker-compose.yml"

SQLITE_ADMIT = {                                        # agent 自身库（audit/breaker/store/checkpoint）
    APP / "security" / "audit.py",
    APP / "security" / "breaker.py",
    APP / "session" / "store.py",
    APP / "graph" / "agent_graph.py",
}


def test_no_bank_db_or_db_env_reference_in_agent_source():
    """agent-service 源码不得出现 bank.db / 银行库直连串（沙箱铁律 doc 02 §1.1）。"""
    offenders = []
    for py in APP.rglob("*.py"):
        txt = py.read_text(encoding="utf-8")
        if "bank.db" in txt or '"DB_PATH"' in txt or "'DB_PATH'" in txt:
            offenders.append(py.name)
    ok = not offenders
    record("沙箱.源码无bank.db/DB直连", "沙箱隔离", ok,
           f"扫描 {len(list(APP.rglob('*.py')))} 个文件，命中 {offenders or '无'}")
    assert ok, f"发现银行库直连痕迹：{offenders}"


def test_sqlite_usage_confined_to_agent_db():
    """sqlite3/aiosqlite 仅允许出现在 agent 自身库模块（audit/breaker/store/checkpointer）。"""
    users = {py.relative_to(APP) for py in APP.rglob("*.py")
             if ("import sqlite3" in py.read_text(encoding="utf-8")
                 or "import aiosqlite" in py.read_text(encoding="utf-8"))}
    admitted = {p.relative_to(APP) for p in SQLITE_ADMIT}
    ok = users <= admitted
    record("沙箱.sqlite限定四模块", "沙箱隔离", ok, f"使用方={[str(u) for u in sorted(users)]}")
    assert ok, f"未登记的 sqlite 使用方：{users - admitted}"


def test_only_http_channel_to_bank_core():
    """唯一数据通道 = HTTP(BANK_CORE_URL)；BankClient 无任何 DB 驱动引用。"""
    client_txt = (APP / "tools" / "bank_client.py").read_text(encoding="utf-8")
    cfg_txt = (APP / "config.py").read_text(encoding="utf-8")
    ok = ("sqlite" not in client_txt and "BANK_CORE_URL" in cfg_txt
          and "http" in cfg_txt)
    record("沙箱.仅HTTP通道", "沙箱隔离", ok, "bank_client 无 DB 驱动；经 BANK_CORE_URL 访问")
    assert ok


def test_no_bank_db_file_in_agent_runtime_dirs():
    """agent-service 运行目录不得存在 bank.db（本地运行时同样成立）。"""
    hits = [str(p) for p in APP.parent.rglob("bank.db")]
    ok = not hits
    record("沙箱.运行目录无bank.db", "沙箱隔离", ok, f"命中 {hits or '无'}")
    assert ok, hits


def test_compose_dual_container_isolation():
    """compose：bank.db 卷仅挂 bank-core；agent-service 无数据卷、无 DB 环境变量。"""
    txt = COMPOSE.read_text(encoding="utf-8")
    agent_block = txt.split("agent-service:", 1)[1].split("web-app:", 1)[0]
    bank_block = txt.split("bank-core:", 1)[1].split("agent-service:", 1)[0]
    ok = ("bank-data" not in agent_block
          and "DB_PATH" not in agent_block
          and "BANK_CORE_URL=http://bank-core:8100" in agent_block
          and "bank-data" in bank_block)
    record("沙箱.compose双容器隔离", "沙箱隔离", ok,
           "agent 无卷/无DB环境变量；bank-data 仅挂 bank-core")
    assert ok, agent_block
