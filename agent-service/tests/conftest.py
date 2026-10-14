"""pytest 夹具：把 agent-service 根目录加入 sys.path；测试库与演示库隔离（临时 agent.db）。"""
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# M2：audit/checkpoint/pending/mfa/breaker 全部落临时库，避免污染 data/agent.db 演示数据
os.environ.setdefault("AGENT_DB_PATH",
                      os.path.join(tempfile.mkdtemp(prefix="agent_svc_test_"), "agent.db"))

# M2：注入模型路测试用注入分类器，单测环境默认离线（不依赖外网 LLM 端点；
# 需要真模型路时设置 TEST_LLM_API_KEY 后运行）
os.environ["LLM_API_KEY"] = os.environ.get("TEST_LLM_API_KEY", "")
