"""人力资源领域工作流：劳动合同审阅与招聘匹配。"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

from enterprise.adapters.documents import ParsedDocument
from enterprise.ai.gateway import ModelGateway
from enterprise.core.models import Severity, WorkflowResult
from enterprise.domains.common import contains_any, finding, first_match, parse_date


class LaborContractWorkflow:
    """劳动合同要素提取、确定性规则检查和生命周期建议。"""

    workflow_id = "labor_contract"
    label = "劳动合同审阅"
    sensitivity = "L3"

    def execute(
        self,
        documents: list[ParsedDocument],
        options: dict[str, Any],
        model_gateway: ModelGateway,
    ) -> WorkflowResult:
        """审阅第一份劳动合同。"""

        if not documents:
            raise ValueError("请上传一份劳动合同")
        document = documents[0]
        text = document.text
        fields = {
            "员工": first_match(
                text,
                [
                    r"劳动者(?:（乙方）|\(乙方\))?[：:]\s*([^\n]+)",
                    r"(?:乙方|员工姓名)[：:]\s*([^\n]+)",
                ],
            ),
            "用人单位": first_match(
                text, [r"用人单位(?:（甲方）|\(甲方\))?[：:]\s*([^\n]+)", r"甲方[：:]\s*([^\n]+)"]
            ),
            "岗位": first_match(text, [r"(?:工作岗位|岗位|职务)[：:]\s*([^\n，。；]+)"]),
            "工作地点": first_match(text, [r"(?:工作地点|工作地)[：:]\s*([^\n，。；]+)"]),
            "合同类型": first_match(text, [r"(固定期限|无固定期限|以完成一定工作任务为期限)"]),
            "开始日期": first_match(
                text, [r"(?:合同期限|自)[：:]?\s*(20\d{2}年\d{1,2}月\d{1,2}日)"]
            ),
            "结束日期": first_match(
                text, [r"(?:至|终止日期)[：:]?\s*(20\d{2}年\d{1,2}月\d{1,2}日)"]
            ),
            "试用期": first_match(text, [r"试用期(?:为|期限为)?[：:]?\s*([^\n，。；]+)"]),
            "工资": first_match(text, [r"(?:工资|劳动报酬|月薪)[：:]?\s*([^\n，。；]+)"]),
            "工时制度": first_match(text, [r"(标准工时(?:制)?|综合计算工时(?:制)?|不定时工作制)"]),
            "社会保险": "已约定"
            if contains_any(text, ["社会保险", "五险", "养老保险"])
            else "未识别",
            "保密条款": "已约定" if "保密" in text else "未识别",
            "竞业限制": "已约定" if "竞业" in text else "未识别",
            "解除终止": "已约定"
            if contains_any(text, ["解除合同", "合同解除", "终止劳动合同"])
            else "未识别",
            "签署日期": first_match(text, [r"签订日期[：:]\s*(20\d{2}年\d{1,2}月\d{1,2}日)"]),
        }
        findings = []
        required = {
            "员工": (Severity.HIGH, "HR-LC-001"),
            "用人单位": (Severity.HIGH, "HR-LC-002"),
            "岗位": (Severity.MEDIUM, "HR-LC-003"),
            "工作地点": (Severity.MEDIUM, "HR-LC-004"),
            "开始日期": (Severity.HIGH, "HR-LC-005"),
            "工资": (Severity.HIGH, "HR-LC-006"),
            "工时制度": (Severity.MEDIUM, "HR-LC-007"),
            "签署日期": (Severity.MEDIUM, "HR-LC-008"),
        }
        for field_name, (severity, rule_id) in required.items():
            if not fields[field_name]:
                findings.append(
                    finding(
                        document,
                        "合同完整性",
                        severity,
                        f"未识别到{field_name}",
                        f"劳动合同中未识别到明确的{field_name}。",
                        rule_id,
                        f"由 HR 核对原件并补充或确认{field_name}。",
                    )
                )
        if fields["社会保险"] == "未识别":
            findings.append(
                finding(
                    document,
                    "法定事项",
                    Severity.HIGH,
                    "未识别到社会保险约定",
                    "合同未出现社会保险相关约定。",
                    "HR-LC-009",
                    "由 HR/法务确认社会保险条款及实际缴纳安排。",
                )
            )
        start = parse_date(fields["开始日期"])
        end = parse_date(fields["结束日期"])
        if start and end and end <= start:
            findings.append(
                finding(
                    document,
                    "日期冲突",
                    Severity.HIGH,
                    "合同结束日期不晚于开始日期",
                    f"开始日期为 {start}，结束日期为 {end}。",
                    "HR-LC-010",
                    "核对合同期限并更正日期。",
                    fields["结束日期"],
                )
            )
        probation_months = _probation_months(fields["试用期"])
        if start and end and probation_months:
            term_months = (end.year - start.year) * 12 + end.month - start.month
            allowed = 1 if term_months < 12 else 2 if term_months < 36 else 6
            if probation_months > allowed:
                findings.append(
                    finding(
                        document,
                        "试用期",
                        Severity.HIGH,
                        "试用期可能超过期限规则",
                        f"合同期限约 {term_months} 个月，试用期识别为 {probation_months} 个月。",
                        "HR-LC-011",
                        "由 HR/法务按适用地区法律和合同期限复核试用期。",
                        fields["试用期"],
                    )
                )
        if fields["竞业限制"] == "已约定" and not contains_any(
            text, ["竞业补偿", "经济补偿", "补偿金"]
        ):
            findings.append(
                finding(
                    document,
                    "竞业限制",
                    Severity.HIGH,
                    "竞业限制未识别到补偿安排",
                    "合同包含竞业限制，但未识别到离职后的补偿标准或支付方式。",
                    "HR-LC-012",
                    "明确竞业范围、期限、地域、补偿和解除机制。",
                    "竞业",
                )
            )
        if contains_any(fields["工作地点"], ["全国", "公司指定地点", "根据需要调整"]):
            findings.append(
                finding(
                    document,
                    "表述清晰度",
                    Severity.MEDIUM,
                    "工作地点范围较宽",
                    f"工作地点为“{fields['工作地点']}”。",
                    "HR-LC-013",
                    "明确主要工作城市、调动条件和员工确认流程。",
                    fields["工作地点"],
                )
            )
        expired = bool(end and end < date.today())
        fields["生命周期建议"] = (
            "已到期/待确认续签或终止" if expired else "待人工复核 → 签署 → 生效"
        )
        result = WorkflowResult(
            workflow_id=self.workflow_id,
            title=f"劳动合同 - {fields['员工'] or Path(document.name).stem}",
            summary=f"已提取 {sum(bool(value) for value in fields.values())}/{len(fields)} 个劳动合同要素，识别 {len(findings)} 条待复核事项。",
            fields=fields,
            metrics={
                "发现项": len(findings),
                "高风险": sum(item.severity == Severity.HIGH for item in findings),
                "合同是否到期": "是" if expired else "否",
            },
            findings=findings,
            suggested_actions=[
                "HR 核对员工与用人单位信息",
                "法务复核试用期、竞业限制和解除条款",
                "人工确认后再进入签署或续签流程",
            ],
        )
        _ai_management_summary(result, documents, options, model_gateway, self.sensitivity)
        return result


class RecruitmentMatchWorkflow:
    """基于岗位要求和简历证据的可解释匹配，不自动淘汰候选人。"""

    workflow_id = "recruitment_match"
    label = "招聘匹配"
    sensitivity = "L3"

    def execute(
        self,
        documents: list[ParsedDocument],
        options: dict[str, Any],
        model_gateway: ModelGateway,
    ) -> WorkflowResult:
        """把第一份文件作为 JD，其余文件作为候选人简历进行匹配。"""

        if len(documents) < 2:
            raise ValueError("招聘匹配至少需要 1 份岗位说明和 1 份简历")
        jd = documents[0]
        resumes = documents[1:]
        jd_keywords = _extract_job_keywords(jd.text, options.get("keywords", ""))
        required_years = _extract_years(jd.text)
        blind_mode = bool(options.get("blind_mode", True))
        weights = options.get("weights") or {"技能": 45, "经验": 25, "项目": 20, "行业": 10}
        records: list[dict[str, Any]] = []
        for index, resume in enumerate(resumes, start=1):
            resume_text = _remove_protected_attributes(resume.text)
            matched = [keyword for keyword in jd_keywords if keyword.lower() in resume_text.lower()]
            skill_score = round(len(matched) / max(len(jd_keywords), 1) * 100, 1)
            candidate_years = _extract_years(resume_text)
            experience_score = (
                100.0 if required_years <= 0 else min(candidate_years / required_years * 100, 100)
            )
            project_score = (
                100.0
                if contains_any(resume_text, ["项目", "负责", "成果", "上线", "交付"])
                else 40.0
            )
            industry_terms = [
                term
                for term in ("制造", "互联网", "金融", "零售", "医药", "审计", "人力", "财务")
                if term in jd.text
            ]
            industry_match = [term for term in industry_terms if term in resume_text]
            industry_score = (
                round(len(industry_match) / max(len(industry_terms), 1) * 100, 1)
                if industry_terms
                else 60.0
            )
            total_weight = max(sum(float(value) for value in weights.values()), 1)
            total_score = round(
                (
                    skill_score * float(weights.get("技能", 45))
                    + experience_score * float(weights.get("经验", 25))
                    + project_score * float(weights.get("项目", 20))
                    + industry_score * float(weights.get("行业", 10))
                )
                / total_weight,
                1,
            )
            records.append(
                {
                    "候选人": f"候选人 {index}" if blind_mode else Path(resume.name).stem,
                    "简历文件": resume.name,
                    "综合匹配分": total_score,
                    "技能分": skill_score,
                    "经验分": round(experience_score, 1),
                    "项目分": project_score,
                    "行业分": industry_score,
                    "匹配技能": "、".join(matched) or "未识别",
                    "经验年限证据": f"约 {candidate_years} 年" if candidate_years else "未识别",
                    "说明": "仅供人工筛选参考，不构成录用或淘汰决定",
                }
            )
        records.sort(key=lambda item: item["综合匹配分"], reverse=True)
        findings = []
        if not jd_keywords:
            findings.append(
                finding(
                    jd,
                    "岗位定义",
                    Severity.HIGH,
                    "岗位技能要求不明确",
                    "未能从 JD 中提取稳定的技能关键词。",
                    "HR-RM-001",
                    "由招聘负责人补充必备技能和可选技能。",
                )
            )
        if contains_any(jd.text, ["限男性", "限女性", "未婚", "年龄不超过", "本地户口", "籍贯"]):
            findings.append(
                finding(
                    jd,
                    "公平招聘",
                    Severity.HIGH,
                    "岗位说明可能包含受保护属性限制",
                    "JD 中出现性别、婚姻、年龄或户籍相关限制性表述。",
                    "HR-RM-002",
                    "删除与岗位胜任力无关的限制，并由 HR/法务复核。",
                )
            )
        result = WorkflowResult(
            workflow_id=self.workflow_id,
            title=f"招聘匹配 - {Path(jd.name).stem}",
            summary=f"已按证据匹配 {len(resumes)} 份简历。系统不会自动淘汰候选人，最终决定必须由招聘人员确认。",
            fields={
                "岗位文件": jd.name,
                "岗位关键词": jd_keywords,
                "要求经验": f"{required_years} 年" if required_years else "未明确",
                "盲审模式": "已启用" if blind_mode else "未启用",
                "评分权重": weights,
            },
            records=records,
            metrics={
                "候选人数": len(records),
                "最高匹配分": records[0]["综合匹配分"] if records else 0,
                "平均匹配分": round(
                    sum(item["综合匹配分"] for item in records) / max(len(records), 1), 1
                ),
            },
            findings=findings,
            suggested_actions=[
                "人工查看每项匹配证据",
                "统一记录面试反馈",
                "不得以受保护属性作为录用或淘汰依据",
            ],
        )
        _ai_management_summary(result, [jd], options, model_gateway, self.sensitivity)
        return result


def _probation_months(value: str) -> int:
    """从试用期文本提取月数。"""

    if not value:
        return 0
    month = re.search(r"(\d+)\s*个?月", value)
    if month:
        return int(month.group(1))
    day = re.search(r"(\d+)\s*天", value)
    return max(round(int(day.group(1)) / 30), 1) if day else 0


def _extract_years(text: str) -> int:
    """提取文本中最可信的工作经验年数。"""

    candidates = [
        int(value) for value in re.findall(r"(\d{1,2})\s*年(?:以上)?(?:工作|经验|从业)?", text)
    ]
    return max(candidates, default=0)


def _extract_job_keywords(text: str, custom_keywords: str) -> list[str]:
    """结合用户配置和常见技术/业务词汇提取岗位关键词。"""

    custom = [item.strip() for item in re.split(r"[,，、;；\n]", custom_keywords) if item.strip()]
    vocabulary = [
        "Python",
        "Java",
        "SQL",
        "Excel",
        "Power BI",
        "Tableau",
        "LangChain",
        "RAG",
        "大模型",
        "招聘",
        "绩效",
        "薪酬",
        "劳动法",
        "审计",
        "会计",
        "预算",
        "税务",
        "采购",
        "项目管理",
        "沟通",
        "数据分析",
        "风险管理",
        "内部控制",
        "制度建设",
        "会议管理",
    ]
    inferred = [keyword for keyword in vocabulary if keyword.lower() in text.lower()]
    return list(dict.fromkeys(custom + inferred))


def _remove_protected_attributes(text: str) -> str:
    """从参与评分的文本中移除受保护属性行。"""

    patterns = [
        r"^.*(?:性别|年龄|出生|婚姻|籍贯|民族|照片|政治面貌).*$",
        r"(?<!\d)1[3-9]\d{9}(?!\d)",
    ]
    cleaned = text
    for pattern in patterns:
        cleaned = re.sub(pattern, "[不参与评分]", cleaned, flags=re.MULTILINE)
    return cleaned


def _ai_management_summary(
    result: WorkflowResult,
    documents: list[ParsedDocument],
    options: dict[str, Any],
    gateway: ModelGateway,
    sensitivity: str,
) -> None:
    """只让模型生成补充摘要，不覆盖规则和计算结果。"""

    if not options.get("use_ai", True):
        return
    sensitivity = str(options.get("_sensitivity", sensitivity))
    combined = "\n\n".join(document.text[:6000] for document in documents)
    response = gateway.run_json(
        task=result.workflow_id,
        system_prompt='你是人力管理助手。只返回 JSON：{"management_summary":"..."}。不得做录用、淘汰、签署等最终决定。',
        user_content=f"材料：\n{combined}\n\n确定性结果：{result.summary}",
        sensitivity=sensitivity,
        allow_external=bool(options.get("allow_external", False)),
    )
    if response.success and response.data and response.data.get("management_summary"):
        result.summary += f"\n\nAI 管理摘要：{response.data['management_summary']}"
        result.model_route = response.route
    elif response.error:
        result.warnings.append(response.error)
