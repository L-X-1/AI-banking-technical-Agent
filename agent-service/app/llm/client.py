"""LLM 客户端（doc 03 §4.1）：OpenAI 兼容 chat completions。

- `chat()` 永不抛异常：无密钥/超时/网络或解析异常 → None（调用方回退规则路）；
- `set_backend()` 为测试/演示注入点（与 injection 检测器的 set_model_classifier 同款模式）；
- `extract_json()` 从模型输出中稳健提取首个 JSON 对象（容忍 ```json 围栏与前后杂音）。
"""
import asyncio
import json

from .. import config

_backend = None   # async (system, user, *, model, temperature, max_tokens) -> str


def set_backend(fn) -> None:
    """测试注入点：替换 LLM 调用后端（None → 恢复按 LLM_API_KEY 自动选择）。"""
    global _backend
    _backend = fn


def llm_enabled() -> bool:
    """LLM 链路可用性：注入了后端或配置了密钥。"""
    return _backend is not None or bool(config.LLM_API_KEY)


async def _openai_backend(system: str, user: str, *, model: str | None,
                          temperature: float, max_tokens: int) -> str | None:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=config.LLM_API_KEY, base_url=config.LLM_BASE_URL,
                         timeout=config.LLM_TIMEOUT_SEC)
    resp = await client.chat.completions.create(
        model=model or config.LLM_MODEL, temperature=temperature, max_tokens=max_tokens,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}])
    return resp.choices[0].message.content


async def chat(system: str, user: str, *, model: str | None = None,
               temperature: float = 0.2, max_tokens: int = 800) -> str | None:
    """单次对话调用；任何失败 → None（降级，fail-safe）。"""
    fn = _backend
    if fn is None:
        if not config.LLM_API_KEY:
            return None
        fn = _openai_backend
    try:
        out = await asyncio.wait_for(
            fn(system, user, model=model, temperature=temperature, max_tokens=max_tokens),
            config.LLM_TIMEOUT_SEC)
        return (out or "").strip() or None
    except Exception:  # noqa: BLE001  超时/网络/配额 → 调用方回退规则路
        return None


def extract_json(text: str | None) -> dict | None:
    """从模型输出提取首个 JSON 对象：去围栏 → 括号配平扫描（跳过字符串）→ json.loads。"""
    if not text:
        return None
    s = text.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[-1] if "\n" in s else s
        s = s.removesuffix("```").strip()
    start = s.find("{")
    if start < 0:
        return None
    depth, in_str, esc = 0, False, False
    for i in range(start, len(s)):
        ch = s[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    data = json.loads(s[start:i + 1])
                except (ValueError, json.JSONDecodeError):
                    return None
                return data if isinstance(data, dict) else None
    return None
