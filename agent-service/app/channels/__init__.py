"""渠道包：web（流式 WS）与 im（非流式降级）共用同一 Agent/同一 trace 体系。"""
from .im import normalize_inbound, render_batch, render_outbound, resolve_action_id

__all__ = ["normalize_inbound", "render_batch", "render_outbound", "resolve_action_id"]
