"""幻觉防护（doc 02 §9.2 / doc 03 §1.3）：responder 回复中的关键数值必须能追溯到工具结果。

- 抽取回复中的金额/卡号/日期等数值，与本轮 `node_results` 中的工具返回比对；
- 出现工具结果之外的数值 → 阻断重新生成（≤2 次），仍失败则保守话术（doc 03 §10 容错表）；
- 身份防冒充：不承诺任何未真正执行的动作（由渲染层保证，校验层兜底）。
"""
import re
from dataclasses import dataclass, field

# 保守话术（doc 03 §10 原文，不含任何可校验数值）
CONSERVATIVE_REPLY = "操作已处理，具体明细请查看账单或联系客服。"

_NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _canon(token: str) -> str:
    """数值归一：'¥52,300.00'→'52300'，'09'→'9'，保证两侧口径一致。"""
    s = token.replace(",", "")
    try:
        return f"{float(s):.10g}"
    except ValueError:  # pragma: no cover - 正则保证可解析
        return s


def extract_numbers(text: str) -> list[str]:
    """抽取文本中的全部数值（归一后）。"""
    return [_canon(t) for t in _NUM_RE.findall(text or "")]


def _ground_numbers(obj, out: set[str]) -> set[str]:
    """递归收集工具结果中的标量数值、字符串内嵌数值与列表长度（回复可合法引用计数）。"""
    if isinstance(obj, dict):
        for v in obj.values():
            _ground_numbers(v, out)
    elif isinstance(obj, (list, tuple)):
        out.add(_canon(str(len(obj))))
        for v in obj:
            _ground_numbers(v, out)
    elif isinstance(obj, bool):
        pass
    elif isinstance(obj, (int, float)):
        out.add(_canon(str(obj)))
    elif isinstance(obj, str):
        out.update(extract_numbers(obj))
    return out


@dataclass
class VerifyResult:
    """doc 03 §1.3：passed / hallucinated_numbers。"""
    passed: bool = True
    hallucinated_numbers: list[str] = field(default_factory=list)


class OutputVerifier:
    def verify(self, reply: str, node_results: dict) -> VerifyResult:
        """比对回复数值 ⊆ 工具结果数值；工具未返回却出现在回复中的数值即幻觉。"""
        ground: set[str] = set()
        for r in (node_results or {}).values():
            if not isinstance(r, dict):
                continue
            if r.get("ok"):
                _ground_numbers(r.get("data") or {}, ground)
            elif isinstance(r.get("error"), dict):
                # 失败结果的 error 也是工具真实返回（银行拒绝文案可被回复引用，
                # 如 M3#2「R4 超出 R2」提示），纳入溯源集合。
                _ground_numbers(r["error"], ground)
        hallucinated = sorted({n for n in extract_numbers(reply) if n not in ground})
        return VerifyResult(passed=not hallucinated, hallucinated_numbers=hallucinated)


verifier = OutputVerifier()
