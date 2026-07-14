"""合同与审计领域工作流。"""

from __future__ import annotations

import re
from typing import Any

from enterprise.adapters.documents import ParsedDocument
from enterprise.ai.gateway import ModelGateway
from enterprise.core.models import Severity, WorkflowResult
from enterprise.domains.common import contains_any, finding, first_match


class CommercialContractWorkflow:
    """通用商业合同要素提取和确定性风险审阅。"""

    workflow_id = "commercial_contract"
    label = "商业合同审阅"
    sensitivity = "L2"

    def execute(
        self,
        documents: list[ParsedDocument],
        options: dict[str, Any],
        model_gateway: ModelGateway,
    ) -> WorkflowResult:
        """审阅第一份商业合同并输出要素与风险。"""

        if not documents:
            raise ValueError("请上传一份商业合同")
        document = documents[0]
        text = document.text
        fields = {
            "合同名称": first_match(
                text, [r"^\s*([^\n]{2,30}合同)\s*$", r"合同名称[：:]\s*([^\n]+)"], re.MULTILINE
            ),
            "甲方": first_match(text, [r"甲方[（(]?(?:买方|委托方)?[）)]?[：:]\s*([^\n]+)"]),
            "乙方": first_match(text, [r"乙方[（(]?(?:卖方|受托方)?[）)]?[：:]\s*([^\n]+)"]),
            "合同金额": first_match(
                text, [r"(?:合同总?金额|价款总额|总价)[：:]?\s*([^\n，。；]+)"]
            ),
            "生效日期": first_match(text, [r"(?:生效日期|自)[：:]?\s*(20\d{2}[^\n，。；]{3,15})"]),
            "终止日期": first_match(text, [r"(?:终止日期|至)[：:]?\s*(20\d{2}[^\n，。；]{3,15})"]),
            "付款条款": first_match(text, [r"(?:付款方式|支付方式|付款条款)[：:]?\s*([^\n]+)"]),
            "验收条款": first_match(text, [r"(?:验收标准|验收方式)[：:]?\s*([^\n]+)"]),
            "违约责任": first_match(text, [r"违约责任[：:]?\s*([^\n]+)"]),
            "争议解决": first_match(text, [r"(?:争议解决|管辖)[：:]?\s*([^\n]+)"]),
            "签署状态": "已包含签署栏"
            if contains_any(text, ["甲方盖章", "乙方盖章", "签字", "签章"])
            else "未识别到签署栏",
        }
        findings = []
        required = {
            "甲方": (Severity.HIGH, "CTR-001"),
            "乙方": (Severity.HIGH, "CTR-002"),
            "合同金额": (Severity.MEDIUM, "CTR-003"),
            "付款条款": (Severity.MEDIUM, "CTR-004"),
            "验收条款": (Severity.MEDIUM, "CTR-005"),
            "违约责任": (Severity.MEDIUM, "CTR-006"),
            "争议解决": (Severity.LOW, "CTR-007"),
        }
        for field_name, (severity, rule_id) in required.items():
            if not fields[field_name]:
                findings.append(
                    finding(
                        document,
                        "条款缺失",
                        severity,
                        f"未识别到{field_name}",
                        f"合同中未识别到明确的{field_name}，可能影响履约和争议处理。",
                        rule_id,
                        f"由业务和法务补充或确认{field_name}。",
                    )
                )
        percentage_matches = [int(value) for value in re.findall(r"(\d{1,3})\s*%", text)]
        if percentage_matches and max(percentage_matches) > 20:
            findings.append(
                finding(
                    document,
                    "惯例偏离",
                    Severity.HIGH,
                    "存在较高比例责任条款",
                    f"识别到最高 {max(percentage_matches)}% 的比例约定，需要确认是否与交易风险匹配。",
                    "CTR-008",
                    "核对该比例对应的基数、适用条件、上限和双方是否对等。",
                    f"{max(percentage_matches)}%",
                )
            )
        if contains_any(text, ["适时付款", "尽快付款", "视情况支付"]):
            findings.append(
                finding(
                    document,
                    "表述模糊",
                    Severity.MEDIUM,
                    "付款时间表述不明确",
                    "付款条款使用了缺少客观期限的表述。",
                    "CTR-009",
                    "改为明确的日期、工作日数量和付款前置条件。",
                    "付款",
                )
            )
        summary = f"已提取 {sum(bool(value) for value in fields.values())}/{len(fields)} 个合同要素，识别 {len(findings)} 条待复核事项。"
        result = WorkflowResult(
            workflow_id=self.workflow_id,
            title=fields["合同名称"] or document.name,
            summary=summary,
            fields=fields,
            metrics={
                "要素完整率": round(
                    sum(bool(value) for value in fields.values()) / len(fields) * 100, 1
                ),
                "发现项": len(findings),
                "高风险": sum(item.severity == Severity.HIGH for item in findings),
            },
            findings=findings,
            suggested_actions=[
                "由合同经办人确认提取字段",
                "由法务复核高风险条款",
                "完成后更新签署和归档状态",
            ],
        )
        _apply_ai_summary(result, document, options, model_gateway)
        return result


def _apply_ai_summary(
    result: WorkflowResult,
    document: ParsedDocument,
    options: dict[str, Any],
    gateway: ModelGateway,
) -> None:
    """在不改变规则结论的前提下，用模型补充管理摘要。"""

    if not options.get("use_ai", True):
        return
    response = gateway.run_json(
        task="commercial_contract_summary",
        system_prompt='你是合同审阅助手。只返回 JSON：{"management_summary":"..."}。不得给出最终法律结论。',
        user_content=f"合同内容：\n{document.text[:12000]}\n\n规则摘要：{result.summary}",
        sensitivity=str(options.get("_sensitivity", "L2")),
        allow_external=bool(options.get("allow_external", False)),
    )
    if response.success and response.data and response.data.get("management_summary"):
        result.summary = f"{result.summary}\n\nAI 管理摘要：{response.data['management_summary']}"
        result.model_route = response.route
    elif response.error:
        result.warnings.append(response.error)
