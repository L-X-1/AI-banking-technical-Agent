"""LLM 子系统（M3 Step 2，doc 03 §3）：客户端 + 提示词加载。

设计要点：
- 无 LLM_API_KEY / 超时 / 异常 → 一律返回 None，由调用方回退规则路（fail-safe，doc 03 §10）；
- 提示词以 prompts/*.md 文件为唯一来源（与 doc 03 §3.1-3.5 原文一致）；
- 测试通过 set_backend() 注入假后端，无需真实密钥即可走通 LLM 链路。
"""
from .client import chat, extract_json, llm_enabled, set_backend  # noqa: F401
from .prompts import load, render  # noqa: F401

load_prompt = load        # 图节点侧别名
render_prompt = render
