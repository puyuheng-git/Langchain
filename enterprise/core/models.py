"""企业工作台共享数据模型。

这些模型只描述稳定的业务概念，不依赖 Streamlit、数据库或具体大模型，
因此命令行兼容层、Web 操作台和自动化测试都可以复用同一套接口。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4


def utc_now() -> str:
    """返回带时区的 UTC ISO 时间，便于数据库稳定排序。"""

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    """生成可读、低碰撞的业务标识。"""

    return f"{prefix}_{uuid4().hex}"


class Severity(StrEnum):
    """发现项严重程度。"""

    HIGH = "高"
    MEDIUM = "中"
    LOW = "低"
    INFO = "提示"


class Sensitivity(StrEnum):
    """数据敏感等级。"""

    L1 = "L1"
    L2 = "L2"
    L3 = "L3"


@dataclass(slots=True)
class Evidence:
    """可以回到原始材料复核的证据定位。"""

    source: str
    locator: str
    excerpt: str

    def to_dict(self) -> dict[str, str]:
        """转换为可序列化字典。"""

        return asdict(self)


@dataclass(slots=True)
class Finding:
    """一条规则或模型发现，默认必须由人工确认。"""

    category: str
    severity: Severity
    title: str
    description: str
    evidence: list[Evidence] = field(default_factory=list)
    rule_id: str = ""
    rule_version: str = "1.0"
    confidence: float = 1.0
    recommendation: str = ""
    review_status: str = "待复核"
    review_comment: str = ""
    id: str = field(default_factory=lambda: new_id("finding"))

    def to_dict(self) -> dict[str, Any]:
        """转换为适合 JSON 和数据库保存的结构。"""

        payload = asdict(self)
        payload["severity"] = self.severity.value
        return payload


@dataclass(slots=True)
class WorkflowResult:
    """所有领域工作流统一返回值。"""

    workflow_id: str
    title: str
    summary: str
    fields: dict[str, Any] = field(default_factory=dict)
    records: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    suggested_actions: list[str] = field(default_factory=list)
    knowledge_matches: list[dict[str, Any]] = field(default_factory=list)
    model_route: str = "deterministic"
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """转换为数据库、报告和 UI 都能使用的字典。"""

        return {
            "workflow_id": self.workflow_id,
            "title": self.title,
            "summary": self.summary,
            "fields": self.fields,
            "records": self.records,
            "metrics": self.metrics,
            "findings": [item.to_dict() for item in self.findings],
            "suggested_actions": self.suggested_actions,
            "knowledge_matches": self.knowledge_matches,
            "model_route": self.model_route,
            "warnings": self.warnings,
        }


@dataclass(slots=True)
class ExecutionResult:
    """工作区执行完成后返回给调用者的持久化结果。"""

    success: bool
    case_id: str
    execution_id: str
    workflow_id: str
    result: WorkflowResult | None = None
    report_path: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """转换为普通字典，兼容 Streamlit 和旧命令接口。"""

        return {
            "success": self.success,
            "case_id": self.case_id,
            "execution_id": self.execution_id,
            "workflow_id": self.workflow_id,
            "result": self.result.to_dict() if self.result else None,
            "report_path": self.report_path,
            "error": self.error,
        }
