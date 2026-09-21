"""对话工具：日期归一化（表单管道统一入口）。

注：旧实现 submit_leave_via_chat（对话直提请假）已被 FORM_SPECS 表单管道取代，
    无任何调用方，随 G10 清理删除；本模块仅保留被 form_validators 复用的 _to_date。
"""

from __future__ import annotations

from datetime import date


def _to_date(s: str) -> str:
    """接受 2026-10-01 / 2026/10/1 / 10月1日 等常见写法，归一化为 YYYY-MM-DD。"""
    s = s.strip().replace("/", "-").replace("年", "-").replace("月", "-").replace("日", "")
    # 中文无年份：默认今年
    parts = [p for p in s.split("-") if p]
    if len(parts) == 2:
        parts = [str(date.today().year)] + parts
    if len(parts) != 3:
        raise ValueError(f"无法解析日期: {s}")
    y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
    return date(y, m, d).isoformat()
