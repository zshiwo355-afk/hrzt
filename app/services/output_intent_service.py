"""输出形态识别：优先规则，模糊场景回落 chat。"""
from __future__ import annotations

import re

MARKDOWN_TABLE_SYSTEM_PROMPT = (
    "你是表格整理助手。"
    "当用户要求用表格展示时，请直接输出一个 Markdown 表格。"
    "除非用户明确要求，否则不要输出多余寒暄。"
    "如确实需要补充说明，控制在表格前后各一句以内。"
)

_FILE_VERBS = (
    "生成",
    "导出",
    "输出",
    "做成",
    "整理成",
    "写成",
    "保存成",
    "形成",
)

_REQUEST_HINTS = (
    "帮我",
    "给我",
    "请",
    "麻烦",
    "我要",
    "我想要",
    "需要",
    "来个",
    "做个",
    "做一份",
    "做一版",
    "制作",
    "创建",
    "转成",
    "转为",
    "变成",
)

_STRONG_REQUEST_HINTS = (
    "帮我",
    "给我",
    "麻烦",
    "我要",
    "我想要",
    "需要",
    "来个",
    "做个",
    "做一份",
    "做一版",
    "请生成",
    "请导出",
    "请输出",
    "请做",
    "生成一个",
    "生成一份",
    "导出",
    "输出",
    "保存成",
    "转成",
    "转为",
    "变成",
    "制作",
    "创建",
)

_DISCUSSION_HINTS = (
    "了解",
    "介绍",
    "讲讲",
    "说说",
    "解释",
    "是什么",
    "什么意思",
    "怎么做",
    "如何做",
    "教程",
    "示例",
    "例子",
    "功能",
    "能力",
    "支持",
    "会不会",
    "能不能",
    "可以生成",
    "提到",
    "包含",
    "比如",
    "例如",
    "日报",
    "周报",
    "月报",
    "今天做了什么",
    "完成了",
    "已完成",
    "已经完成",
    "实现了",
)

_DOCX_DIRECT = (
    "word",
    ".docx",
    "docx",
    "word文档",
)

_DOCX_HINT = (
    "会议纪要",
    "纪要",
    "报告",
    "方案",
    "通知",
    "合同",
    "文档",
    "说明书",
    "总结",
)

_TXT_DIRECT = (
    "txt",
    ".txt",
    "txt文件",
    "txt格式",
    "文本文件",
    "纯文本",
)

_MD_DIRECT = (
    "markdown",
    "markdown文件",
    "markdown 文档",
    ".md",
    "md",
    "md文件",
    "md 文档",
    "md格式",
)

_CSV_DIRECT = (
    "csv",
    ".csv",
    "csv文件",
    "csv 表",
)

_PDF_DIRECT = (
    "pdf",
    ".pdf",
    "pdf文件",
    "pdf文档",
    "打印版",
)

_PDF_HINT = (
    "打印版",
    "可打印",
    "归档版",
    "打印存档",
    "打印出来",
)

_PPTX_DIRECT = (
    "ppt",
    ".pptx",
    "pptx",
    "powerpoint",
    "演示文稿",
    "幻灯片",
    "课件",
)

_PPTX_HINT = (
    "汇报",
    "路演",
    "宣讲",
    "发布会",
    "演讲",
    "培训材料",
    "分享会",
    "汇报材料",
    "项目介绍",
)

_XLSX_DIRECT = (
    "excel",
    ".xlsx",
    "xlsx",
    "工作簿",
    "工作表",
    "电子表格",
)

_XLSX_HINT = (
    "表格",
    "做个表",
    "做一张表",
    "做个表格",
    "做一份表格",
    "整理成表",
    "整理成表格",
    "台账",
    "清单",
    "名单表",
    "数据表",
    "明细表",
    "统计表",
    "汇总表",
    "对照表",
    "对比表",
    "行情表",
    "排期表",
    "预算表",
    "报价表",
)

_MARKDOWN_TABLE_DIRECT = (
    "markdown表格",
    "markdown table",
    "markdown 格式表格",
    "先给我看表格",
    "直接在这里表格展示",
    "不用文件",
    "先用表格列出来给我看",
)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _contains_any(text: str, items: tuple[str, ...]) -> bool:
    return any(token in text for token in items)


def _has_request_signal(text: str) -> bool:
    return _contains_any(text, _FILE_VERBS) or _contains_any(text, _REQUEST_HINTS)


def _has_discussion_signal(text: str) -> bool:
    return _contains_any(text, _DISCUSSION_HINTS)


def _is_capability_question(text: str) -> bool:
    normalized = str(text or "").strip()
    return bool(
        re.search(
            r"(能不能|能否|可以吗|可不可以|能帮我|可以帮我|能不能帮我|是否可以|会不会|支持不支持|能不能够|可否).{0,40}(生成|做|制作|导出|转成|转为|写|创建)",
            normalized,
        )
    )


def _should_treat_direct_artifact_as_request(text: str) -> bool:
    if _is_capability_question(text):
        return False
    if not _has_request_signal(text):
        return False
    if _has_discussion_signal(text) and not _contains_any(text, _STRONG_REQUEST_HINTS):
        return False
    return True


def _looks_like_docx(text: str) -> tuple[bool, str, float]:
    if _contains_any(text, _DOCX_DIRECT):
        if _should_treat_direct_artifact_as_request(text):
            return True, "命中 Word/docx 显式关键词，且包含生成请求", 0.97
        return False, "", 0.0
    if _contains_any(text, _FILE_VERBS) and _contains_any(text, _DOCX_HINT):
        return True, "命中文档导出语义", 0.92
    return False, "", 0.0


def _looks_like_txt(text: str) -> tuple[bool, str, float]:
    if _contains_any(text, _TXT_DIRECT):
        if _should_treat_direct_artifact_as_request(text):
            return True, "命中 TXT/文本文件显式关键词，且包含生成请求", 0.97
        return False, "", 0.0
    return False, "", 0.0


def _looks_like_markdown_file(text: str) -> tuple[bool, str, float]:
    if _contains_any(text, _MD_DIRECT):
        if _should_treat_direct_artifact_as_request(text):
            return True, "命中 Markdown 文件显式关键词，且包含生成请求", 0.97
        return False, "", 0.0
    return False, "", 0.0


def _looks_like_csv(text: str) -> tuple[bool, str, float]:
    if _contains_any(text, _CSV_DIRECT):
        if _should_treat_direct_artifact_as_request(text):
            return True, "命中 CSV 显式关键词，且包含生成请求", 0.97
        return False, "", 0.0
    return False, "", 0.0


def _looks_like_pdf(text: str) -> tuple[bool, str, float]:
    if _contains_any(text, _PDF_DIRECT):
        if _should_treat_direct_artifact_as_request(text):
            return True, "命中 PDF 显式关键词，且包含生成请求", 0.97
        return False, "", 0.0
    if _contains_any(text, _FILE_VERBS) and _contains_any(text, _PDF_HINT):
        return True, "命中 PDF/打印版导出语义", 0.9
    return False, "", 0.0


def _looks_like_pptx(text: str) -> tuple[bool, str, float]:
    if _contains_any(text, _PPTX_DIRECT):
        if _should_treat_direct_artifact_as_request(text):
            return True, "命中 PPT/pptx 显式关键词，且包含生成请求", 0.97
        return False, "", 0.0
    if _contains_any(text, _FILE_VERBS) and _contains_any(text, _PPTX_HINT):
        return True, "命中演示文稿导出语义", 0.94
    if _contains_any(text, _PPTX_HINT) and _contains_any(text, _REQUEST_HINTS):
        return True, "命中演示文稿请求语义", 0.9
    return False, "", 0.0


def _looks_like_xlsx(text: str) -> tuple[bool, str, float]:
    if _contains_any(text, _XLSX_DIRECT):
        if _should_treat_direct_artifact_as_request(text):
            return True, "命中 Excel/xlsx 显式关键词，且包含生成请求", 0.97
        return False, "", 0.0
    if _contains_any(text, _MARKDOWN_TABLE_DIRECT):
        return False, "", 0.0
    if _contains_any(text, _FILE_VERBS) and _contains_any(text, _XLSX_HINT):
        return True, "命中表格文件导出语义", 0.92
    if _contains_any(text, _XLSX_HINT):
        return True, "命中表格型产物关键词，优先按 xlsx 处理", 0.88
    if "表" in text and any(token in text for token in ("做", "整理", "给我", "生成", "导出", "输出")):
        return True, "命中泛表格意图，优先按 xlsx 处理", 0.84
    return False, "", 0.0


def _looks_like_markdown_table(text: str) -> tuple[bool, str, float]:
    if _contains_any(text, _MARKDOWN_TABLE_DIRECT):
        return True, "命中表格展示显式关键词", 0.9
    return False, "", 0.0


def detect_output_intent(prompt: str, mode: str = "text") -> dict:
    raw = str(prompt or "").strip()
    if not raw or str(mode or "text").strip().lower() != "text":
        return {
            "output_mode": "chat",
            "confidence": 0.0,
            "should_use_task": False,
            "artifact_type": None,
            "reason": "非文本模式或提示词为空，回落普通聊天",
        }

    text = _normalize(raw)

    matched, reason, confidence = _looks_like_pptx(text)
    if matched:
        return {
            "output_mode": "pptx",
            "confidence": confidence,
            "should_use_task": True,
            "artifact_type": "pptx",
            "reason": reason,
        }

    matched, reason, confidence = _looks_like_csv(text)
    if matched:
        return {
            "output_mode": "csv",
            "confidence": confidence,
            "should_use_task": True,
            "artifact_type": "csv",
            "reason": reason,
        }

    matched, reason, confidence = _looks_like_xlsx(text)
    if matched:
        return {
            "output_mode": "xlsx",
            "confidence": confidence,
            "should_use_task": True,
            "artifact_type": "xlsx",
            "reason": reason,
        }

    matched, reason, confidence = _looks_like_pdf(text)
    if matched:
        return {
            "output_mode": "pdf",
            "confidence": confidence,
            "should_use_task": True,
            "artifact_type": "pdf",
            "reason": reason,
        }

    matched, reason, confidence = _looks_like_markdown_file(text)
    if matched:
        return {
            "output_mode": "md",
            "confidence": confidence,
            "should_use_task": True,
            "artifact_type": "md",
            "reason": reason,
        }

    matched, reason, confidence = _looks_like_txt(text)
    if matched:
        return {
            "output_mode": "txt",
            "confidence": confidence,
            "should_use_task": True,
            "artifact_type": "txt",
            "reason": reason,
        }

    matched, reason, confidence = _looks_like_docx(text)
    if matched:
        return {
            "output_mode": "docx",
            "confidence": confidence,
            "should_use_task": True,
            "artifact_type": "docx",
            "reason": reason,
        }

    matched, reason, confidence = _looks_like_markdown_table(text)
    if matched:
        return {
            "output_mode": "markdown_table",
            "confidence": confidence,
            "should_use_task": False,
            "artifact_type": None,
            "reason": reason,
        }

    return {
        "output_mode": "chat",
        "confidence": 0.2,
        "should_use_task": False,
        "artifact_type": None,
        "reason": "未命中明确规则，按普通聊天处理",
    }
