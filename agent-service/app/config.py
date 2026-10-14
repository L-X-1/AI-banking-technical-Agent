"""agent-service 配置（环境变量优先，全部带演示环境默认值）。"""
import os

BANK_CORE_URL = os.environ.get("BANK_CORE_URL", "http://127.0.0.1:8100")
DEMO_USER_ID = os.environ.get("DEMO_USER_ID", "u001")
AGENT_DB_PATH = os.environ.get(
    "AGENT_DB_PATH",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "agent.db"),
)

# LLM（OpenAI 兼容端点；LLM_API_KEY 缺失 → LLM 降级模式，注入仅规则路裁决）
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com")
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-chat")
LLM_GUARD_MODEL = os.environ.get("LLM_GUARD_MODEL") or LLM_MODEL   # 注入分类器可用便宜模型
LLM_GUARD_TIMEOUT_SEC = float(os.environ.get("LLM_GUARD_TIMEOUT_SEC", "4"))
LLM_TIMEOUT_SEC = float(os.environ.get("LLM_TIMEOUT_SEC", "12"))   # M3 Step 2：意图/规划/回复主链路超时

# 演示参数（与 doc 02 §8 一致）
CONFIRM_TTL_SEC = 300      # 黄色确认卡超时 5 分钟
MFA_TTL_SEC = 300
MFA_MAX_ATTEMPTS = 3       # 3 次失败锁定 15 分钟（熔断 T2，breaker.py）

