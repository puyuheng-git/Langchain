"""行政管理领域工作流：制度审阅和会议行动项。"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

from enterprise.adapters.documents import ParsedDocument
from enterprise.ai.gateway import ModelGateway
from enterprise.core.models import Severity, WorkflowResult
from enterprise.domains.common import contains_any, finding, first_match, parse_date


class PolicyReviewWorkflow:
    """检查制度要素、职责分离、例外和版本状态。"""

    workflow_id = "policy_review"
    label = "制度审阅"
    sensitivity = "L2"

    def execute(
        self,
        documents: list[ParsedDocument],
        options: dict[str, Any],
        model_gateway: ModelGateway,
    ) -> WorkflowResult:
        """审阅第一份制度文件。"""

        if not documents:
            raise ValueError("请上传一份制度文件")
        document = documents[0]
        text = document.text
        fields = {
            "制度名称": first_match(
                text, [r"^\s*([^\n]{2,40}(?:制度|办法|规定|细则))\s*$"], re.MULTILINE
            ),
            "制度编号": first_match(text, [r"(?:制度编号|文件编号|编号)[：:]\s*([^\n]+)"]),
            "版本": first_match(text, [r"(?:版本号|版本)[：:]\s*([^\n]+)"]),
            "适用范围": first_match(text, [r"适用范围[：:]\s*([^\n]+)"]),
            "归口部门": first_match(text, [r"(?:归口部门|责任部门|制度所有者)[：:]\s*([^\n]+)"]),
            "审批人": first_match(text, [r"(?:审批人|批准人|批准部门)[：:]\s*([^\n]+)"]),
            "生效日期": first_match(text, [r"(?:生效日期|实施日期)[：:]\s*(20\d{2}[^\n]+)"]),
            "职责描述": "已识别" if contains_any(text, ["职责", "负责", "责任"]) else "未识别",
            "审批流程": "已识别"
            if contains_any(text, ["审批流程", "审批程序", "提交审批"])
            else "未识别",
            "权限标准": "已识别"
            if contains_any(text, ["权限", "审批额度", "金额标准", "授权"])
            else "未识别",
            "例外规则": "已识别" if contains_any(text, ["例外", "特殊情况", "豁免"]) else "未识别",
            "修订记录": "已识别"
            if contains_any(text, ["修订记录", "版本记录", "修订历史"])
            else "未识别",
        }
        findings = []
        required = {
            "制度编号": (Severity.MEDIUM, "ADM-PL-001"),
            "版本": (Severity.MEDIUM, "ADM-PL-002"),
            "适用范围": (Severity.HIGH, "ADM-PL-003"),
            "归口部门": (Severity.HIGH, "ADM-PL-004"),
            "审批人": (Severity.HIGH, "ADM-PL-005"),
            "生效日期": (Severity.MEDIUM, "ADM-PL-006"),
        }
        for field_name, (severity, rule_id) in required.items():
            if not fields[field_name]:
                findings.append(
                    finding(
                        document,
                        "制度完整性",
                        severity,
                        f"未识别到{field_name}",
                        f"制度未明确识别{field_name}。",
                        rule_id,
                        f"由归口部门补充{field_name}并完成版本确认。",
                    )
                )
        if contains_any(text, ["经办人自行审批", "申请人审批", "申请并批准", "同一人办理和审批"]):
            findings.append(
                finding(
                    document,
                    "职责分离",
                    Severity.HIGH,
                    "可能存在不相容职责未分离",
                    "制度允许申请、经办或执行人员同时完成审批。",
                    "ADM-PL-007",
                    "将申请、审批、执行和复核角色分离，并规定替代审批机制。",
                    "审批",
                )
            )
        if fields["例外规则"] == "未识别":
            findings.append(
                finding(
                    document,
                    "例外管理",
                    Severity.MEDIUM,
                    "未识别到例外处理规则",
                    "制度未明确紧急或特殊事项如何申请例外、由谁批准及如何留痕。",
                    "ADM-PL-008",
                    "补充例外申请、审批、时限、补录和定期复盘要求。",
                )
            )
        if not contains_any(text, ["保存期限", "留存期限", "归档年限"]):
            findings.append(
                finding(
                    document,
                    "记录留存",
                    Severity.MEDIUM,
                    "未识别到资料留存期限",
                    "制度未明确申请、审批和执行证据的保管期限。",
                    "ADM-PL-009",
                    "根据法规和公司档案规则补充留存介质、责任人和期限。",
                )
            )
        effective = parse_date(fields["生效日期"])
        if effective and effective > date.today():
            lifecycle = "已批准/待生效"
        elif effective:
            lifecycle = "已生效/待确认现行有效"
        else:
            lifecycle = "草稿/待完善"
        fields["生命周期建议"] = lifecycle
        result = WorkflowResult(
            workflow_id=self.workflow_id,
            title=fields["制度名称"] or Path(document.name).stem,
            summary=f"已检查制度元数据、职责分离、例外和留痕要求，识别 {len(findings)} 条待复核事项。",
            fields=fields,
            metrics={
                "发现项": len(findings),
                "高风险": sum(item.severity == Severity.HIGH for item in findings),
                "生命周期": lifecycle,
            },
            findings=findings,
            suggested_actions=[
                "归口部门确认制度元数据",
                "相关部门会签职责和审批权限",
                "批准后发布并保留版本记录",
            ],
        )
        _ai_summary(result, [document], options, model_gateway)
        return result


class MeetingActionWorkflow:
    """从会议纪要中提取决定、负责人、期限和待办事项。"""

    workflow_id = "meeting_actions"
    label = "会议事项"
    sensitivity = "L2"

    def execute(
        self,
        documents: list[ParsedDocument],
        options: dict[str, Any],
        model_gateway: ModelGateway,
    ) -> WorkflowResult:
        """汇总一份或多份会议纪要中的行动项。"""

        if not documents:
            raise ValueError("请上传会议纪要或输入会议内容")
        records: list[dict[str, Any]] = []
        findings = []
        for document in documents:
            extracted = _extract_action_items(document)
            records.extend(extracted)
            for item in extracted:
                if not item["负责人"]:
                    findings.append(
                        finding(
                            document,
                            "会议行动项",
                            Severity.HIGH,
                            "行动项缺少负责人",
                            item["事项"],
                            "ADM-MT-001",
                            "由会议主持人指定唯一主责人。",
                            item["事项"][:20],
                        )
                    )
                if not item["截止日期"]:
                    findings.append(
                        finding(
                            document,
                            "会议行动项",
                            Severity.MEDIUM,
                            "行动项缺少截止日期",
                            item["事项"],
                            "ADM-MT-002",
                            "补充明确日期或可计算的工作日时限。",
                            item["事项"][:20],
                        )
                    )
                due = parse_date(item["截止日期"])
                if due and due < date.today() and item["状态"] != "已完成":
                    findings.append(
                        finding(
                            document,
                            "逾期风险",
                            Severity.HIGH,
                            "行动项已超过截止日期",
                            f"{item['事项']}，截止日期 {due}。",
                            "ADM-MT-003",
                            "负责人更新进展、阻塞原因和新的承诺日期。",
                            item["截止日期"],
                        )
                    )
        fields = {
            "会议文件数": len(documents),
            "会议名称": first_match(
                documents[0].text,
                [r"(?:会议名称|会议主题)[：:]\s*([^\n]+)", r"^\s*([^\n]{2,40}会议)\s*$"],
                re.MULTILINE,
            )
            or Path(documents[0].name).stem,
            "会议日期": first_match(documents[0].text, [r"(?:会议日期|日期|时间)[：:]\s*([^\n]+)"]),
            "参会人员": first_match(
                documents[0].text, [r"(?:参会人员|与会人员|参会人)[：:]\s*([^\n]+)"]
            ),
            "会议决定": [
                line.strip()
                for line in documents[0].text.splitlines()
                if contains_any(line, ["决定", "决议", "一致同意"])
            ][:10],
        }
        result = WorkflowResult(
            workflow_id=self.workflow_id,
            title=f"会议事项 - {fields['会议名称']}",
            summary=f"从 {len(documents)} 份会议材料中提取 {len(records)} 项行动项，识别 {len(findings)} 条责任或时限问题。",
            fields=fields,
            records=records,
            metrics={
                "行动项": len(records),
                "缺负责人": sum(not item["负责人"] for item in records),
                "缺截止日期": sum(not item["截止日期"] for item in records),
                "高风险": sum(item.severity == Severity.HIGH for item in findings),
            },
            findings=findings,
            suggested_actions=[
                "主持人确认会议决定",
                "逐项确认主责人和截止日期",
                "将行动项同步到任务中心并跟踪闭环",
            ],
        )
        _ai_summary(result, documents, options, model_gateway)
        return result


def _extract_action_items(document: ParsedDocument) -> list[dict[str, Any]]:
    """按逐行语法提取显式行动项，并保留来源。"""

    items: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(document.text.splitlines(), start=1):
        line = raw_line.strip(" -•\t")
        if len(line) < 5 or not contains_any(
            line, ["负责", "完成", "跟进", "提交", "行动项", "待办"]
        ):
            continue
        owner = first_match(
            line,
            [
                r"(?:负责人|责任人|主责)[：:]?\s*([\u4e00-\u9fa5A-Za-z·]{2,20})",
                r"由\s*([\u4e00-\u9fa5A-Za-z·]{2,20})\s*(?:负责|牵头)",
                r"([\u4e00-\u9fa5A-Za-z·]{2,15}(?:部|组|中心))\s*(?:负责|牵头)",
            ],
        )
        deadline = first_match(
            line,
            [
                r"(?:截止日期|截止|于|在)[：:]?\s*(20\d{2}[年/.-]\d{1,2}[月/.-]\d{1,2}日?)",
                r"(20\d{2}-\d{1,2}-\d{1,2})",
            ],
        )
        priority = "高" if contains_any(line, ["紧急", "立即", "最高优先级"]) else "中"
        status = "已完成" if contains_any(line, ["已完成", "已关闭"]) else "待处理"
        items.append(
            {
                "事项": line[:300],
                "负责人": owner,
                "截止日期": deadline,
                "优先级": priority,
                "状态": status,
                "来源": f"{document.name} 第 {line_number} 行",
            }
        )
    return items


def _ai_summary(
    result: WorkflowResult,
    documents: list[ParsedDocument],
    options: dict[str, Any],
    gateway: ModelGateway,
) -> None:
    """让本地模型补充行政管理摘要，不替代制度批准或会议确认。"""

    if not options.get("use_ai", True):
        return
    content = "\n\n".join(document.text[:6000] for document in documents)
    response = gateway.run_json(
        task=result.workflow_id,
        system_prompt='你是行政管理助手。只返回 JSON：{"management_summary":"..."}。不得替代制度批准或会议决策。',
        user_content=f"材料：\n{content}\n\n确定性结果：{result.summary}",
        sensitivity="L2",
        allow_external=bool(options.get("allow_external", False)),
    )
    if response.success and response.data and response.data.get("management_summary"):
        result.summary += f"\n\nAI 管理摘要：{response.data['management_summary']}"
        result.model_route = response.route
    elif response.error:
        result.warnings.append(response.error)
