"""提示词加载（doc 03 §3）：prompts/*.md 为唯一来源；占位符用精确替换（模板内含 JSON 花括号，禁用 str.format）。"""
import functools
import pathlib

PROMPT_DIR = pathlib.Path(__file__).resolve().parent / "prompts"


@functools.lru_cache(maxsize=None)
def load(name: str) -> str:
    """加载 prompts/<name>.md 原文（system / intent / planner / responder / injection_guard）。"""
    return (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")


def render(name: str, **placeholders: object) -> str:
    """精确替换 {placeholder}；模板中 JSON Schema 的花括号不受影响。"""
    text = load(name)
    for key, value in placeholders.items():
        text = text.replace("{" + key + "}", str(value))
    return text
