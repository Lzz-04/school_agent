"""附件真伪/有效性校验：调视觉模型判断上传图片是否为真实有效的证明材料。

注意：这是模型层面的"看起来像不像"判断，毕设演示用，不构成财务/法律级验证。
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

from ..llm import get_llm

# 各申请类型期望的证明材料描述
_DOC_EXPECT = {
    "leave": "医院/校医院出具的病假证明、挂号单、诊断书，或事假相关说明",
    "reimbursement": "正规发票、收据、报销单，带有金额和开票方信息",
    "venue_reservation": "场地现场照片、活动方案相关材料",
    "course_selection": "课程相关证明（一般无附件）",
}

_IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
_UPLOADS = Path(__file__).resolve().parent.parent / "uploads"


def verify_document(process_type: str, attachment_url: str, attachment_name: str = "") -> dict:
    """判断单个附件是否为真实有效证明材料。

    返回 {authentic: bool|None, reason: str, confidence: float, name: str}
    authentic=None 表示非图片或模型未启用，无法判断。
    """
    fname = Path(attachment_url).name
    ext = Path(fname).suffix.lower()
    if ext not in _IMG_EXT:
        return {"authentic": None, "reason": "非图片附件，未做视觉校验", "confidence": 0.0,
                "name": attachment_name or fname}

    fpath = _UPLOADS / fname
    if not fpath.exists():
        return {"authentic": None, "reason": "附件文件不存在", "confidence": 0.0,
                "name": attachment_name or fname}

    llm = get_llm()
    if not llm.enabled:
        return {"authentic": None, "reason": "LLM 未启用", "confidence": 0.0,
                "name": attachment_name or fname}

    # 视觉模型：文本模型不支持图片，换多视觉模型
    import os as _os
    from ..llm.client import LLMClient
    vl_model = _os.getenv("CAMPUS_VL_MODEL", "Qwen/Qwen3-VL-8B-Instruct")
    vl = LLMClient(model=vl_model)

    mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp", "gif": "gif"}.get(ext.lstrip("."), "jpeg")
    b64 = base64.b64encode(fpath.read_bytes()).decode("ascii")

    expect = _DOC_EXPECT.get(process_type, "相关证明材料")
    system = (
        "你是校园审批附件审核员。判断学生上传的图片是否是一张真实、清晰、"
        "与申请类型相符的证明材料。只输出 JSON：{\"authentic\": true/false, "
        "\"reason\": \"一句话理由\", \"confidence\": 0.0~1.0}。"
        "如果图片模糊、明显是表情包/风景照/PS痕迹重、或与申请类型无关，authentic=false。"
    )
    user_text = (
        f"申请类型：{process_type}\n期望证明材料：{expect}\n"
        f"附件文件名：{attachment_name or fname}\n请判断这张图片。"
    )
    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": user_text},
            {"type": "image_url", "image_url": {"url": f"data:image/{mime};base64,{b64}"}},
        ],
    }]

    try:
        out = vl.chat(system, messages, temperature=0.1)
        # 提取 JSON
        start = out.find("{")
        end = out.rfind("}")
        if start >= 0 and end > start:
            data = json.loads(out[start:end + 1])
            return {
                "authentic": bool(data.get("authentic")),
                "reason": str(data.get("reason", ""))[:200],
                "confidence": float(data.get("confidence", 0.5)),
                "name": attachment_name or fname,
            }
    except Exception as e:
        # 抓取响应体看具体原因
        detail = ""
        try:
            import httpx as _hx
            detail = f" | body: {getattr(e, 'response', None) and e.response.text[:300]}"
        except Exception:
            pass
        return {"authentic": None, "reason": f"校验失败: {e}{detail}", "confidence": 0.0,
                "name": attachment_name or fname}

    return {"authentic": None, "reason": "模型返回无法解析", "confidence": 0.0,
            "name": attachment_name or fname}


def verify_attachments(process_type: str, attachments: list[dict]) -> dict:
    """批量校验附件。attachments: [{"url","name","type"}]
    返回聚合结果：任一图片 authentic=true 视为材料有效。
    """
    if not attachments:
        return {"authentic": None, "reason": "无附件", "checks": []}
    checks = []
    any_authentic = False
    any_checked = False
    for a in attachments:
        if a.get("type") != "image":
            continue
        r = verify_document(process_type, a["url"], a.get("name", ""))
        checks.append(r)
        if r["authentic"] is True:
            any_authentic = True
            any_checked = True
        elif r["authentic"] is False:
            any_checked = True
    if not any_checked:
        return {"authentic": None, "reason": "无可校验的图片附件", "checks": checks}
    return {"authentic": any_authentic,
            "reason": "图片附件校验通过" if any_authentic else "图片附件未通过校验",
            "checks": checks}
