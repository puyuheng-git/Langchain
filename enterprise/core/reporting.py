"""统一 Markdown 报告生成器。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import WorkflowResult


def save_markdown_report(
    report_dir: Path,
    case_id: str,
    execution_id: str,
    result: WorkflowResult,
) -> Path:
    """保存包含摘要、计算、发现、证据和人工复核声明的报告。"""

    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"{case_id}_{execution_id}.md"
    lines = [
        f"# {result.title}",
        "",
        f"- 案件编号：`{case_id}`",
        f"- 执行编号：`{execution_id}`",
        f"- 工作流：`{result.workflow_id}`",
        f"- 模型路线：`{result.model_route}`",
        "",
        "## 执行摘要",
        "",
        result.summary,
        "",
        "> 本报告由规则和可选 AI 辅助生成。录用、签署、制度发布、费用审批、付款、预算调整和风险关闭必须由有权限人员确认。",
        "",
        "## 关键指标",
        "",
    ]
    for key, value in result.metrics.items():
        lines.append(f"- **{key}**：{_display(value)}")
    lines.extend(["", "## 结构化字段", ""])
    for key, value in result.fields.items():
        lines.append(f"- **{key}**：{_display(value)}")
    lines.extend(["", "## 发现项", ""])
    if not result.findings:
        lines.append("未识别到规则发现项，仍需人工复核原始材料。")
    for index, item in enumerate(result.findings, start=1):
        lines.extend(
            [
                f"### {index}. [{item.severity.value}] {item.title}",
                "",
                f"- 类别：{item.category}",
                f"- 规则：{item.rule_id} / {item.rule_version}",
                f"- 说明：{item.description}",
                f"- 建议：{item.recommendation}",
                f"- 人工状态：{item.review_status}",
            ]
        )
        for evidence in item.evidence:
            lines.append(f"- 证据：{evidence.source} · {evidence.locator} · {evidence.excerpt}")
        lines.append("")
    if result.records:
        lines.extend(
            [
                "## 明细记录",
                "",
                "```json",
                json.dumps(result.records, ensure_ascii=False, indent=2, default=str),
                "```",
                "",
            ]
        )
    if result.knowledge_matches:
        lines.extend(["## RAG 知识对照", ""])
        for index, item in enumerate(result.knowledge_matches, start=1):
            lines.extend(
                [
                    f"### {index}. {item.get('title', '')}",
                    "",
                    f"- 板块/类型：{item.get('department', '')} / {item.get('document_type', '')}",
                    f"- 效力层级：{item.get('authority_label', '未分级')}",
                    f"- 版本：{item.get('version') or '未标注'}",
                    f"- 相关度：{item.get('score', 0):.1%}",
                    f"- 定位：{item.get('locator', '')}",
                    f"- 对照意见：{item.get('comparison', '')}",
                    f"- 关联本次发现：{'、'.join(item.get('related_findings', [])) or '无直接关联'}",
                    f"- 知识来源：{item.get('source_ref') or '未标注'}",
                    f"- 引用原文：{item.get('excerpt', '')}",
                    "",
                ]
            )
            for current in item.get("current_evidence", []):
                lines.append(f"- 当前发现：{current.get('finding', '')}")
                for evidence in current.get("evidence", []):
                    lines.append(
                        f"  - 当前材料证据：{evidence.get('source', '')} · "
                        f"{evidence.get('locator', '')} · {evidence.get('excerpt', '')}"
                    )
            lines.append("")
    if result.suggested_actions:
        lines.extend(["## 建议后续动作", ""])
        lines.extend(f"- {action}" for action in result.suggested_actions)
    if result.warnings:
        lines.extend(["", "## 运行提示", ""])
        lines.extend(f"- {warning}" for warning in result.warnings)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _display(value: Any) -> str:
    """把复杂值转换为报告中的单行文本。"""

    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)
