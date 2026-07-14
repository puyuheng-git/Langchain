"""领域工作流共享工具。"""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

from enterprise.adapters.documents import ParsedDocument
from enterprise.core.models import Evidence, Finding, Severity


def first_match(text: str, patterns: Iterable[str], flags: int = re.IGNORECASE) -> str:
    """按顺序返回第一个正则捕获值。"""

    for pattern in patterns:
        match = re.search(pattern, text, flags)
        if match:
            value = match.group(1) if match.groups() else match.group(0)
            return value.strip(" ：:\t\r\n。；;")
    return ""


def contains_any(text: str, keywords: Iterable[str]) -> bool:
    """判断文本是否包含任一关键词，英文不区分大小写。"""

    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def parse_date(value: Any) -> date | None:
    """把常见中文和数字日期转换为 date。"""

    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for pattern in (r"(20\d{2})[年/.-](\d{1,2})[月/.-](\d{1,2})日?", r"(20\d{2})(\d{2})(\d{2})"):
        match = re.search(pattern, text)
        if match:
            try:
                return date(*(int(part) for part in match.groups()))
            except ValueError:
                return None
    return None


def number(value: Any) -> float:
    """把带逗号、货币符号或百分号的值转换为浮点数。"""

    if value in (None, ""):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = re.sub(r"[^\d.\-]", "", str(value).replace(",", ""))
    try:
        return float(cleaned) if cleaned else 0.0
    except ValueError:
        return 0.0


def evidence(document: ParsedDocument, needle: str) -> list[Evidence]:
    """根据关键词生成一条来源证据。"""

    locator, excerpt = document.evidence_for(needle)
    return [Evidence(document.name, locator, excerpt)]


def finding(
    document: ParsedDocument,
    category: str,
    severity: Severity,
    title: str,
    description: str,
    rule_id: str,
    recommendation: str,
    needle: str = "",
    confidence: float = 1.0,
) -> Finding:
    """用统一字段构造可复核发现项。"""

    return Finding(
        category=category,
        severity=severity,
        title=title,
        description=description,
        evidence=evidence(document, needle),
        rule_id=rule_id,
        confidence=confidence,
        recommendation=recommendation,
    )


def get_option(options: dict[str, Any], key: str, default: Any = None) -> Any:
    """读取经过工作区传入的业务选项。"""

    return options.get(key, default)


def safe_title(path: str | Path, suffix: str) -> str:
    """根据文件名生成案件标题。"""

    return f"{Path(path).stem} - {suffix}"
