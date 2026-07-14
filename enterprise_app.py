#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""企业智能管理工作台 Streamlit 入口。

业务人员只需要在浏览器中上传材料、选择参数并点击执行。每次上传、结果、报告、
发现项和人工复核都会保存到本机 SQLite 与案件目录，页面刷新或下次启动后仍可查看。
"""

from __future__ import annotations

import html
import inspect
import json
import time
from pathlib import Path
from typing import Any, Callable

import streamlit as st

from enterprise import EnterpriseStore, ReviewWorkspace
from enterprise.core.catalog import LEADER_FOCUS, WORKFLOW_GROUPS
from enterprise.core.knowledge import DEPARTMENTS, DOCUMENT_TYPES
from enterprise.core.settings import SECRET_SETTING_KEYS, SECURITY_POLICY_OPTIONS
from enterprise.sample_data import generate_samples

STRETCH_KWARGS = (
    {"width": "stretch"}
    if "width" in inspect.signature(st.form_submit_button).parameters
    else {"use_container_width": True}
)

WORKFLOW_HELP = {
    "commercial_contract": "提取签约方、金额、付款、验收、违约和争议解决条款。",
    "labor_contract": "检查员工、单位、期限、工资、工时、社保、试用期和竞业限制。",
    "recruitment_match": "第一份为岗位说明，其余为简历；按证据评分，不自动淘汰。",
    "policy_review": "检查制度版本、范围、归口、审批、职责分离、例外和留存规则。",
    "meeting_actions": "提取负责人、截止日期和行动项，并自动保存到任务中心。",
    "expense_review": "复算费用，检查重复票据、限额、预算、附件、日期和审批冲突。",
    "budget_analysis": "本地计算执行率、余额、差异、超支和低执行项目。",
}

ACCEPTED_TYPES = {
    "commercial_contract": ["pdf", "docx", "txt", "md"],
    "labor_contract": ["pdf", "docx", "txt", "md"],
    "recruitment_match": ["pdf", "docx", "txt", "md"],
    "policy_review": ["pdf", "docx", "txt", "md"],
    "meeting_actions": ["pdf", "docx", "txt", "md"],
    "expense_review": ["csv", "xlsx", "xlsm"],
    "budget_analysis": ["csv", "xlsx", "xlsm"],
}


@st.cache_resource
def get_workspace() -> ReviewWorkspace:
    """跨页面复用无状态工作区和 SQLite 仓储。"""

    return ReviewWorkspace()


def apply_theme() -> None:
    """应用面向企业操作台的轻量视觉样式。"""

    st.markdown(
        """
        <style>
        .block-container {max-width: 1480px; padding-top: 1.4rem; padding-bottom: 3rem;}
        [data-testid="stSidebar"] {background: #0f2744;}
        [data-testid="stSidebar"] * {color: #f6f8fb;}
        .hero {padding: 1.35rem 1.6rem; border-radius: 16px; background: linear-gradient(120deg,#123b67,#1f6b8f); color:white; margin-bottom:1rem;}
        .hero h1 {margin:0 0 .35rem 0; font-size:2rem;}
        .hero p {margin:0; opacity:.88;}
        .notice {padding:.8rem 1rem; border-left:4px solid #1f6b8f; background:#f2f7fb; border-radius:8px; color:#18334f;}
        .risk-high {border-left:5px solid #d94141; padding:.75rem 1rem; background:#fff4f4; border-radius:8px; margin:.45rem 0;}
        .risk-medium {border-left:5px solid #e59a18; padding:.75rem 1rem; background:#fff9ec; border-radius:8px; margin:.45rem 0;}
        .risk-low {border-left:5px solid #4385c1; padding:.75rem 1rem; background:#f2f7fc; border-radius:8px; margin:.45rem 0;}
        </style>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    """渲染侧边导航和各业务页面。"""

    st.set_page_config(page_title="企业智能管理工作台", page_icon="🏢", layout="wide")
    apply_theme()
    workspace = get_workspace()
    with st.sidebar:
        st.title("🏢 企业工作台")
        actor = st.text_input("当前操作人", value=st.session_state.get("actor", "本地用户"))
        st.session_state["actor"] = actor or "本地用户"
        page = st.radio(
            "导航",
            [
                "首页",
                "审计与合同",
                "人力管理",
                "行政管理",
                "财务管理",
                "知识资料库",
                "运行监控",
                "任务中心",
                "历史与复核",
                "系统管理",
            ],
            label_visibility="collapsed",
        )
        st.caption("本地优先 · 全程留痕 · 人工最终确认")
    if page == "首页":
        page_dashboard(workspace)
    elif page in WORKFLOW_GROUPS:
        page_domain(workspace, page, WORKFLOW_GROUPS[page])
    elif page == "知识资料库":
        page_knowledge(workspace)
    elif page == "运行监控":
        page_monitor(workspace.store)
    elif page == "任务中心":
        page_tasks(workspace.store)
    elif page == "历史与复核":
        page_history(workspace)
    else:
        page_system(workspace)


def execute_logged_operation(
    store: EnterpriseStore,
    event_type: str,
    title: str,
    callback: Callable[[], Any],
    details: dict[str, Any] | None = None,
) -> Any:
    """执行一个页面操作，并把开始、成功或失败状态写入运行监控。"""

    event_id = ""
    try:
        event_id = store.start_runtime_event(
            category="operation",
            event_type=event_type,
            title=title,
            actor=st.session_state.get("actor", "本地用户"),
            details=details,
        )
    except Exception:
        pass
    try:
        result = callback()
        success = bool(getattr(result, "success", True))
        result_details: dict[str, Any] = {}
        for key in ("case_id", "execution_id", "error"):
            value = getattr(result, key, None)
            if value:
                result_details[key] = value
        if event_id:
            try:
                store.complete_runtime_event(
                    event_id,
                    "成功" if success else "失败",
                    result_details,
                )
            except Exception:
                pass
        return result
    except Exception as exc:
        if event_id:
            try:
                store.complete_runtime_event(event_id, "失败", {"error": str(exc)})
            except Exception:
                pass
        raise


def log_rejected_operation(
    store: EnterpriseStore, event_type: str, title: str, reason: str
) -> None:
    """记录因页面校验未通过而没有进入后台处理的按钮操作。"""

    try:
        event_id = store.start_runtime_event(
            category="operation",
            event_type=event_type,
            title=title,
            actor=st.session_state.get("actor", "本地用户"),
            details={"validation_error": reason},
        )
        store.complete_runtime_event(event_id, "失败", {"error": reason})
    except Exception:
        pass


def log_quick_operation(
    store: EnterpriseStore,
    event_type: str,
    title: str,
    details: dict[str, Any] | None = None,
) -> None:
    """记录下载、刷新等不需要后台回调结果的即时操作。"""

    try:
        event_id = store.start_runtime_event(
            category="operation",
            event_type=event_type,
            title=title,
            actor=st.session_state.get("actor", "本地用户"),
            details=details,
        )
        store.complete_runtime_event(event_id, "成功")
    except Exception:
        pass


def page_dashboard(workspace: ReviewWorkspace) -> None:
    """展示工作台总览和快捷入口说明。"""

    st.markdown(
        '<div class="hero"><h1>企业智能管理工作台</h1><p>审计、人力、行政、财务统一操作台。上传即归档，结果可追溯，敏感数据本地优先。</p></div>',
        unsafe_allow_html=True,
    )
    metrics = workspace.store.dashboard_metrics()
    columns = st.columns(6)
    columns[0].metric("累计案件", metrics["case_count"])
    columns[1].metric("待复核案件", metrics["pending_cases"])
    columns[2].metric("待复核高风险", metrics["high_findings"])
    columns[3].metric("未完成任务", metrics["open_tasks"])
    columns[4].metric("待审批", metrics["pending_approvals"])
    columns[5].metric("正式有效知识", metrics["knowledge_count"])
    st.subheader("业务能力")
    cards = st.columns(4)
    descriptions = [
        ("审计与合同", "商业合同要素、条款缺失、异常比例和审计底稿。"),
        ("人力管理", "劳动合同生命周期与可解释招聘匹配。"),
        ("行政管理", "制度治理、会议决定与行动项闭环。"),
        ("财务管理", "费用合规复核与预算执行差异分析。"),
    ]
    for column, (title, description) in zip(cards, descriptions, strict=True):
        with column:
            st.markdown(f"### {title}")
            st.write(description)
    st.markdown(
        '<div class="notice"><b>控制原则：</b>系统不会自动录用/淘汰候选人、签署合同、发布制度、批准费用、执行付款、调整预算或关闭风险。</div>',
        unsafe_allow_html=True,
    )
    recent = workspace.store.list_cases(limit=8)
    st.subheader("最近操作")
    if recent:
        st.dataframe(
            [
                {
                    "标题": item["title"],
                    "业务": workflow_label(workspace, item["workflow_id"]),
                    "状态": item["status"],
                    "操作人": item["actor"],
                    "更新时间": item["updated_at"],
                }
                for item in recent
            ],
            hide_index=True,
            **STRETCH_KWARGS,
        )
    else:
        st.info("还没有历史案件。请从左侧进入业务模块发起第一项任务。")


def page_domain(workspace: ReviewWorkspace, group: str, workflow_ids: list[str]) -> None:
    """渲染一个业务领域的任务发起页。"""

    st.markdown(
        f'<div class="hero"><h1>{group}</h1><p>以板块总负责人视角联查业务材料、公司章程、部门制度和历史问题。</p></div>',
        unsafe_allow_html=True,
    )
    focus_columns = st.columns(4)
    for column, focus in zip(focus_columns, LEADER_FOCUS[group], strict=True):
        column.metric(focus, "持续监测")
    department_documents = workspace.knowledge.list_documents(department=group)
    company_documents = workspace.knowledge.list_documents(department="公司级")
    st.caption(
        f"当前可对照知识：{len(department_documents)} 份本板块资料，{len(company_documents)} 份公司级资料"
    )
    catalog = {item["id"]: item for item in workspace.catalog()}
    workflow_id = st.selectbox(
        "业务流程", workflow_ids, format_func=lambda value: catalog[value]["label"]
    )
    workflow_sensitivity = catalog[workflow_id]["sensitivity"]
    security_policy = workspace.model_gateway.settings()["security_levels"][workflow_sensitivity]
    st.caption(WORKFLOW_HELP[workflow_id])
    with st.form(f"execute_{workflow_id}", clear_on_submit=False):
        title = st.text_input("案件标题（可选）", placeholder="留空时自动使用文件名")
        uploads: list[Any] = []
        jd_file = None
        resume_files: list[Any] = []
        meeting_text = ""
        if workflow_id == "recruitment_match":
            jd_file = st.file_uploader(
                "岗位说明（1 份）", type=ACCEPTED_TYPES[workflow_id], key="jd_file"
            )
            resume_files = (
                st.file_uploader(
                    "候选人简历（可多选）",
                    type=ACCEPTED_TYPES[workflow_id],
                    accept_multiple_files=True,
                    key="resume_files",
                )
                or []
            )
        else:
            uploads = st.file_uploader(
                "上传业务材料",
                type=ACCEPTED_TYPES[workflow_id],
                accept_multiple_files=workflow_id
                in {"meeting_actions", "expense_review", "budget_analysis"},
                key=f"files_{workflow_id}",
            )
            if uploads and not isinstance(uploads, list):
                uploads = [uploads]
            uploads = uploads or []
        if workflow_id == "meeting_actions":
            meeting_text = st.text_area(
                "也可以直接粘贴会议记录",
                height=160,
                placeholder="会议决定：……\n行动项：由张三负责……截止日期：2026-12-31",
            )
        blind_mode = True
        keywords = ""
        expense_limit = 5000.0
        if workflow_id == "recruitment_match":
            blind_mode = st.checkbox("盲审模式：隐藏姓名等信息参与展示", value=True)
            keywords = st.text_input("补充岗位关键词（逗号分隔，可选）")
        if workflow_id == "expense_review":
            expense_limit = st.number_input(
                "单笔重点复核阈值", min_value=0.0, value=5000.0, step=500.0
            )
        create_tasks = (
            st.checkbox("自动同步到任务中心", value=True, disabled=workflow_id != "meeting_actions")
            if workflow_id == "meeting_actions"
            else False
        )
        knowledge_enabled = st.checkbox(
            "对照知识资料库与历史案例",
            value=True,
            help="检索本板块制度、业务规范、公司章程和历史案件，并在结果中保留引用。",
        )
        knowledge_types = st.multiselect(
            "本次对照资料类型",
            DOCUMENT_TYPES,
            default=["公司章程", "部门制度", "业务规范", "历史案例", "会议决议"],
            disabled=not knowledge_enabled,
        )
        use_ai = st.checkbox(
            "启用本地模型补充管理摘要",
            value=False,
            help="不启用模型时，结构化提取、规则检查和财务计算仍可完整运行。",
        )
        allow_external = False
        if use_ai:
            st.caption(
                f"当前安全等级：{workflow_sensitivity}｜{security_policy['name']}｜"
                f"{SECURITY_POLICY_OPTIONS[security_policy['policy']]}"
            )
            external_permitted = security_policy["policy"] != "local_only"
            allow_external = st.checkbox(
                "本地模型失败时，允许脱敏后调用外部模型",
                value=False,
                disabled=not external_permitted,
            )
            if not external_permitted:
                st.info("当前等级配置为仅本地处理，本次不能启用外部模型。")
            if allow_external:
                st.warning(
                    "该授权仅对本次案件生效。所有外部调用都会先执行基础脱敏，并记录 external-redacted 路线。"
                )
        submitted = st.form_submit_button(
            "保存材料并执行", type="primary", **STRETCH_KWARGS
        )
    if submitted:
        upload_tuples: list[tuple[str, bytes, str]] = []
        if workflow_id == "recruitment_match":
            if jd_file:
                upload_tuples.append((jd_file.name, jd_file.getvalue(), jd_file.type or ""))
            upload_tuples.extend(
                (item.name, item.getvalue(), item.type or "") for item in resume_files
            )
        else:
            upload_tuples.extend((item.name, item.getvalue(), item.type or "") for item in uploads)
        if meeting_text.strip():
            upload_tuples.append(("meeting_input.txt", meeting_text.encode("utf-8"), "text/plain"))
        options = {
            "use_ai": use_ai,
            "allow_external": allow_external,
            "blind_mode": blind_mode,
            "keywords": keywords,
            "expense_limit": expense_limit,
            "create_tasks": create_tasks,
            "knowledge_enabled": knowledge_enabled,
            "knowledge_types": knowledge_types,
        }
        if not upload_tuples:
            log_rejected_operation(
                workspace.store,
                "execute_workflow",
                f"执行工作流｜{catalog[workflow_id]['label']}",
                "未上传材料或输入会议内容",
            )
            st.error("请上传材料或输入会议内容。")
        else:
            with st.spinner("正在归档文件并执行本地分析……"):
                execution = execute_logged_operation(
                    workspace.store,
                    "execute_workflow",
                    f"执行工作流｜{catalog[workflow_id]['label']}",
                    lambda: workspace.execute_uploads(
                        workflow_id,
                        upload_tuples,
                        st.session_state["actor"],
                        title,
                        options,
                    ),
                    {"workflow_id": workflow_id, "file_count": len(upload_tuples)},
                )
            st.session_state["last_execution"] = execution.to_dict()
            if execution.success:
                st.success(f"执行完成并已保存。案件编号：{execution.case_id}")
            else:
                st.error(f"执行失败，但失败记录已保存：{execution.error}")
    active = st.session_state.get("last_execution")
    if active and active.get("workflow_id") == workflow_id:
        render_execution(active, workspace.store)


def render_execution(execution: dict[str, Any], store: EnterpriseStore) -> None:
    """统一展示一次执行的摘要、指标、字段、明细和发现项。"""

    result = execution.get("result")
    if not result:
        st.error(execution.get("error") or "没有可展示的结果")
        return
    st.divider()
    st.header(result["title"])
    st.write(result["summary"])
    if result.get("warnings"):
        for warning in result["warnings"]:
            st.warning(warning)
    metric_items = list(result.get("metrics", {}).items())
    if metric_items:
        columns = st.columns(min(len(metric_items), 5))
        for index, (label, value) in enumerate(metric_items):
            columns[index % len(columns)].metric(label, value)
    knowledge_matches = result.get("knowledge_matches", [])
    tabs = st.tabs(
        [
            "结构化结果",
            "明细记录",
            f"风险与发现 ({len(result.get('findings', []))})",
            f"知识对照 ({len(knowledge_matches)})",
            "报告与后续",
        ]
    )
    with tabs[0]:
        fields = result.get("fields", {})
        simple_fields = [{"字段": key, "值": display_value(value)} for key, value in fields.items()]
        st.dataframe(simple_fields, hide_index=True, **STRETCH_KWARGS)
    with tabs[1]:
        records = result.get("records", [])
        if records:
            st.dataframe(records, hide_index=True, **STRETCH_KWARGS)
            st.download_button(
                "下载明细 JSON",
                json.dumps(records, ensure_ascii=False, indent=2, default=str),
                file_name=f"{execution['execution_id']}_records.json",
                mime="application/json",
                on_click=log_quick_operation,
                args=(
                    store,
                    "download_records",
                    "下载分析明细",
                    {"execution_id": execution["execution_id"]},
                ),
            )
        else:
            st.info("该流程没有明细记录。")
    with tabs[2]:
        render_findings(result.get("findings", []))
    with tabs[3]:
        render_knowledge_matches(knowledge_matches, store)
    with tabs[4]:
        st.markdown("### 建议后续动作")
        for action in result.get("suggested_actions", []):
            st.write(f"- {action}")
        report_path = execution.get("report_path")
        if report_path and Path(report_path).is_file():
            st.download_button(
                "下载 Markdown 报告",
                Path(report_path).read_bytes(),
                file_name=Path(report_path).name,
                mime="text/markdown",
                on_click=log_quick_operation,
                args=(
                    store,
                    "download_report",
                    "下载分析报告",
                    {"execution_id": execution["execution_id"]},
                ),
            )
        st.caption(
            f"案件编号：{execution['case_id']} · 执行编号：{execution['execution_id']} · 模型路线：{result.get('model_route', 'deterministic')}"
        )


def render_knowledge_matches(matches: list[dict[str, Any]], store: EnterpriseStore) -> None:
    """展示分析时实际召回的制度、章程和历史案例证据。"""

    if not matches:
        st.info("本次未检索到相关知识资料。可在知识资料库补充本板块有效文件。")
        return
    for item in matches:
        score = float(item.get("score", 0))
        with st.expander(
            f"{item.get('document_type', '资料')}｜{item.get('title', '')}｜相关度 {score:.1%}",
            expanded=score >= 0.25,
        ):
            columns = st.columns(5)
            columns[0].write(f"**板块**\n\n{item.get('department', '')}")
            columns[1].write(f"**版本**\n\n{item.get('version') or '未标注'}")
            columns[2].write(f"**生效日期**\n\n{item.get('effective_date') or '未标注'}")
            columns[3].write(f"**定位**\n\n{item.get('locator', '')}")
            columns[4].write(f"**效力层级**\n\n{item.get('authority_label', '未分级')}")
            st.write(f"**对照状态：** {item.get('comparison_status', '待核验')}")
            st.write(item.get("comparison", ""))
            st.code(item.get("excerpt", ""), language=None)
            if item.get("related_findings"):
                st.write("**关联本次发现：** " + "、".join(item["related_findings"]))
            for current in item.get("current_evidence", []):
                st.write(f"**当前材料证据｜{current.get('finding', '')}**")
                for evidence in current.get("evidence", []):
                    st.caption(f"{evidence.get('source', '')} · {evidence.get('locator', '')}")
                    st.code(evidence.get("excerpt", ""), language=None)
            if item.get("matched_terms"):
                st.caption("命中语义：" + "、".join(item["matched_terms"]))
            source_ref = item.get("source_ref") or "未标注"
            st.caption(f"知识来源：{source_ref}")
            stored_path = item.get("metadata", {}).get("stored_path")
            if stored_path and Path(stored_path).is_file():
                st.download_button(
                    "下载知识原件",
                    Path(stored_path).read_bytes(),
                    file_name=item.get("metadata", {}).get("file_name") or Path(stored_path).name,
                    key=f"knowledge_source_{item.get('chunk_id')}",
                    on_click=log_quick_operation,
                    args=(
                        store,
                        "download_knowledge_source",
                        f"下载知识原件｜{item.get('title', '')}",
                        {"document_id": item.get("document_id")},
                    ),
                )


def render_findings(findings: list[dict[str, Any]]) -> None:
    """按严重程度渲染证据卡片。"""

    if not findings:
        st.success("规则未识别到异常，但仍需要人工复核原始材料。")
        return
    order = {"高": 0, "中": 1, "低": 2, "提示": 3}
    for item in sorted(findings, key=lambda value: order.get(value.get("severity", "提示"), 9)):
        css = (
            "risk-high"
            if item.get("severity") == "高"
            else "risk-medium"
            if item.get("severity") == "中"
            else "risk-low"
        )
        severity = html.escape(str(item.get("severity", "")))
        title = html.escape(str(item.get("title", "")))
        description = html.escape(str(item.get("description", "")))
        rule_id = html.escape(str(item.get("rule_id", "")))
        recommendation = html.escape(str(item.get("recommendation", "")))
        st.markdown(
            f'<div class="{css}"><b>[{severity}] {title}</b><br>{description}'
            f"<br><small>规则：{rule_id} · 建议：{recommendation}</small></div>",
            unsafe_allow_html=True,
        )
        with st.expander("查看证据"):
            evidence_items = item.get("evidence", [])
            if evidence_items:
                for evidence in evidence_items:
                    st.write(f"**{evidence.get('source')} · {evidence.get('locator')}**")
                    st.code(evidence.get("excerpt", ""), language=None)
            else:
                st.write("无定位证据")


def page_knowledge(workspace: ReviewWorkspace) -> None:
    """管理并检索四个板块共用的 RAG 知识资料。"""

    st.markdown(
        '<div class="hero"><h1>知识资料库</h1><p>统一管理公司章程、部门制度、业务规范、会议决议与历史案件记忆。</p></div>',
        unsafe_allow_html=True,
    )
    documents = workspace.knowledge.list_documents()
    metrics = st.columns(5)
    for column, department in zip(metrics, DEPARTMENTS, strict=True):
        count = sum(item["department"] == department for item in documents)
        column.metric(department, count)

    list_tab, add_tab, search_tab, baseline_tab = st.tabs(
        ["资料清单", "新增资料", "语义检索", "酒店集团规划基线"]
    )
    with list_tab:
        if documents:
            st.dataframe(
                [
                    {
                        "标题": item["title"],
                        "板块": item["department"],
                        "类型": item["document_type"],
                        "版本": item["version"] or "未标注",
                        "生效日期": item["effective_date"] or "未标注",
                        "状态": item["status"],
                        "更新时间": item["updated_at"],
                    }
                    for item in documents
                ],
                hide_index=True,
                **STRETCH_KWARGS,
            )
            selected_id = st.selectbox(
                "查看或删除资料",
                [item["id"] for item in documents],
                format_func=lambda value: next(
                    item["title"] for item in documents if item["id"] == value
                ),
            )
            selected = next(item for item in documents if item["id"] == selected_id)
            with st.expander("查看正文"):
                st.text(selected["content"])
            if st.button("删除所选资料", type="secondary"):
                execute_logged_operation(
                    workspace.store,
                    "delete_knowledge",
                    f"删除知识资料｜{selected['title']}",
                    lambda: workspace.store.delete_knowledge_document(
                        selected_id, st.session_state["actor"]
                    ),
                    {"document_id": selected_id},
                )
                st.success("资料已删除")
                st.rerun()
        else:
            st.info("知识资料库为空。请新增企业有效文件或先装载规划样本。")

    with add_tab:
        with st.form("add_knowledge"):
            columns = st.columns(2)
            department = columns[0].selectbox("归属板块", DEPARTMENTS)
            document_type = columns[1].selectbox(
                "资料类型", [item for item in DOCUMENT_TYPES if item != "历史案例"]
            )
            title = st.text_input("资料标题", placeholder="例如：费用报销管理制度")
            version_columns = st.columns(2)
            version = version_columns[0].text_input("版本", placeholder="V2.1")
            effective_date = version_columns[1].text_input(
                "生效日期", placeholder="2026-01-01"
            )
            upload = st.file_uploader(
                "上传文件",
                type=["pdf", "docx", "txt", "md", "csv", "xlsx", "xlsm"],
                key="knowledge_upload",
            )
            content = st.text_area("或直接粘贴正文", height=220)
            add_submitted = st.form_submit_button(
                "保存并建立索引", type="primary", **STRETCH_KWARGS
            )
        if add_submitted:
            try:
                def save_knowledge() -> str:
                    if upload:
                        managed_title = title.strip() or upload.name
                        return workspace.knowledge.add_upload(
                            upload.name,
                            upload.getvalue(),
                            department,
                            document_type,
                            st.session_state["actor"],
                            title=managed_title,
                            version=version,
                            effective_date=effective_date,
                            source_ref=f"managed:{department}:{document_type}:{managed_title}",
                        )
                    if content.strip():
                        return workspace.knowledge.add_text(
                            title,
                            content,
                            department,
                            document_type,
                            st.session_state["actor"],
                            version=version,
                            effective_date=effective_date,
                            source_ref=f"managed:{department}:{document_type}:{title.strip()}",
                        )
                    raise ValueError("请上传文件或粘贴资料正文")

                execute_logged_operation(
                    workspace.store,
                    "save_knowledge",
                    f"保存知识资料｜{title.strip() or (upload.name if upload else '未命名')}",
                    save_knowledge,
                    {"department": department, "document_type": document_type},
                )
                st.success("资料已保存并可用于后续分析")
                st.rerun()
            except (ValueError, OSError, ImportError) as exc:
                st.error(str(exc))

    with search_tab:
        with st.form("knowledge_search"):
            query = st.text_input("检索问题", placeholder="例如：招待费超过标准如何审批")
            search_departments = st.multiselect("检索板块", DEPARTMENTS, default=DEPARTMENTS)
            search_types = st.multiselect("资料类型", DOCUMENT_TYPES, default=DOCUMENT_TYPES)
            search_submitted = st.form_submit_button("检索", type="primary")
        if search_submitted:
            matches = execute_logged_operation(
                workspace.store,
                "search_knowledge",
                "检索知识资料",
                lambda: workspace.knowledge.search(
                    query,
                    departments=search_departments or None,
                    document_types=search_types or None,
                    limit=10,
                ),
                {"query": query[:200]},
            )
            render_knowledge_matches(matches, workspace.store)

    with baseline_tab:
        st.warning("该基线仅用于酒店集团功能规划与演示；正式使用前必须替换为企业已审批的有效文件。")
        st.write(
            "基线覆盖公司治理授权、酒店采购与收入审计、劳动用工与关键岗位、印章档案与安全证照、费用支付与经营预算。"
        )
        if st.button("装载或更新规划基线", type="primary"):
            result = execute_logged_operation(
                workspace.store,
                "seed_knowledge_baseline",
                "装载酒店集团规划基线",
                lambda: workspace.knowledge.seed_hotel_baseline(st.session_state["actor"]),
            )
            st.success(f"已装载 {result['created']} 份规划资料")
            st.rerun()


def page_tasks(store: EnterpriseStore) -> None:
    """展示会议事项和人工创建任务的轻量管理页。"""

    st.markdown(
        '<div class="hero"><h1>任务中心</h1><p>集中跟踪会议行动项、整改事项和人工任务。</p></div>',
        unsafe_allow_html=True,
    )
    with st.expander("新建任务"):
        with st.form("new_task"):
            title = st.text_input("任务标题")
            columns = st.columns(3)
            owner = columns[0].text_input("负责人")
            due_date = columns[1].text_input("截止日期", placeholder="2026-12-31")
            priority = columns[2].selectbox("优先级", ["高", "中", "低"], index=1)
            details = st.text_area("说明")
            if st.form_submit_button("创建任务"):
                if title.strip():
                    execute_logged_operation(
                        store,
                        "create_task",
                        f"创建任务｜{title.strip()}",
                        lambda: store.create_task(
                            title.strip(),
                            owner,
                            due_date,
                            priority,
                            source="手工",
                            details=details,
                        ),
                    )
                    st.success("任务已创建")
                    st.rerun()
                else:
                    log_rejected_operation(
                        store, "create_task", "创建任务", "任务标题为空"
                    )
                    st.error("请输入任务标题")
    task_tab, approval_tab = st.tabs(["任务", "审批"])
    with approval_tab:
        render_approvals(store)
    with task_tab:
        render_tasks(store)


def render_tasks(store: EnterpriseStore) -> None:
    """渲染任务列表和更新表单。"""

    tasks = store.list_tasks()
    if not tasks:
        st.info("暂无任务。会议事项流程可自动创建任务。")
        return
    st.dataframe(
        [
            {
                key: item.get(key)
                for key in (
                    "title",
                    "owner",
                    "due_date",
                    "priority",
                    "status",
                    "source",
                    "updated_at",
                )
            }
            for item in tasks
        ],
        hide_index=True,
        **STRETCH_KWARGS,
    )
    selected_id = st.selectbox(
        "选择要更新的任务",
        [item["id"] for item in tasks],
        format_func=lambda value: next(item["title"] for item in tasks if item["id"] == value),
    )
    selected = next(item for item in tasks if item["id"] == selected_id)
    with st.form("update_task"):
        columns = st.columns(3)
        status = columns[0].selectbox(
            "状态",
            ["待处理", "进行中", "受阻", "已完成", "已取消"],
            index=max(
                0, ["待处理", "进行中", "受阻", "已完成", "已取消"].index(selected["status"])
            ),
        )
        owner = columns[1].text_input("负责人", value=selected.get("owner") or "")
        due_date = columns[2].text_input("截止日期", value=selected.get("due_date") or "")
        if st.form_submit_button("保存任务更新"):
            execute_logged_operation(
                store,
                "update_task",
                f"更新任务｜{selected['title']}",
                lambda: store.update_task(selected_id, status, owner, due_date),
                {"task_id": selected_id, "status": status},
            )
            st.success("任务已更新")
            st.rerun()


def render_approvals(store: EnterpriseStore, case_id: str | None = None) -> None:
    """展示审批记录，并允许非申请人作出批准或驳回决定。"""

    approvals = store.list_approvals(case_id)
    if not approvals:
        st.info("暂无审批记录。可在历史案件中发起最终动作审批。")
        return
    st.dataframe(
        [
            {
                "动作": item["action"],
                "申请人": item["requester"],
                "审批人": item["approver"],
                "状态": item["status"],
                "意见": item["comment"],
                "申请时间": item["created_at"],
            }
            for item in approvals
        ],
        hide_index=True,
        **STRETCH_KWARGS,
    )
    pending = [item for item in approvals if item["status"] == "待审批"]
    if not pending:
        return
    approval_id = st.selectbox(
        "选择待审批事项",
        [item["id"] for item in pending],
        format_func=lambda value: next(item["action"] for item in pending if item["id"] == value),
        key=f"approval_select_{case_id or 'all'}",
    )
    with st.form(f"approval_decision_{case_id or 'all'}"):
        decision = st.radio("审批决定", ["已批准", "已驳回"], horizontal=True)
        comment = st.text_area("审批意见")
        if st.form_submit_button("提交审批决定"):
            try:
                execute_logged_operation(
                    store,
                    "decide_approval",
                    "提交审批决定",
                    lambda: store.decide_approval(
                        approval_id, decision, comment, st.session_state["actor"]
                    ),
                    {"approval_id": approval_id, "decision": decision},
                )
                st.success("审批决定已保存")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))


def page_history(workspace: ReviewWorkspace) -> None:
    """查询历史案件、下载原始附件、重新执行和完成人工复核。"""

    st.markdown(
        '<div class="hero"><h1>历史与复核</h1><p>所有上传、执行结果和人工结论都保存在本机，可随时回看。</p></div>',
        unsafe_allow_html=True,
    )
    cases = workspace.store.list_cases(limit=500)
    if not cases:
        st.info("暂无历史案件。")
        return
    filter_group = st.selectbox("业务筛选", ["全部"] + list(WORKFLOW_GROUPS))
    allowed = None if filter_group == "全部" else set(WORKFLOW_GROUPS[filter_group])
    filtered = [item for item in cases if allowed is None or item["workflow_id"] in allowed]
    st.dataframe(
        [
            {
                "标题": item["title"],
                "业务": workflow_label(workspace, item["workflow_id"]),
                "状态": item["status"],
                "操作人": item["actor"],
                "更新时间": item["updated_at"],
                "案件编号": item["id"],
            }
            for item in filtered
        ],
        hide_index=True,
        **STRETCH_KWARGS,
    )
    if not filtered:
        return
    case_id = st.selectbox(
        "查看案件",
        [item["id"] for item in filtered],
        format_func=lambda value: next(item["title"] for item in filtered if item["id"] == value),
    )
    case = workspace.store.get_case(case_id)
    if not case:
        return
    columns = st.columns([3, 1])
    columns[0].subheader(case["title"])
    new_status = columns[1].selectbox(
        "案件状态",
        ["待人工复核", "补充材料", "已确认", "已关闭", "执行失败"],
        index=0
        if case["status"] not in ["待人工复核", "补充材料", "已确认", "已关闭", "执行失败"]
        else ["待人工复核", "补充材料", "已确认", "已关闭", "执行失败"].index(case["status"]),
    )
    if columns[1].button("更新案件状态"):
        execute_logged_operation(
            workspace.store,
            "update_case_status",
            f"更新案件状态｜{case['title']}",
            lambda: workspace.update_case_status(
                case_id, new_status, st.session_state["actor"]
            ),
            {"case_id": case_id, "status": new_status},
        )
        st.success("案件状态已更新")
        st.rerun()
    with st.expander(f"原始附件 ({len(case['artifacts'])})"):
        for artifact in case["artifacts"]:
            path = Path(artifact["stored_path"])
            columns = st.columns([4, 1])
            columns[0].write(f"{artifact['file_name']} · SHA256 {artifact['sha256'][:12]}…")
            if path.is_file():
                columns[1].download_button(
                    "下载",
                    path.read_bytes(),
                    file_name=artifact["file_name"],
                    key=f"artifact_{artifact['id']}",
                    on_click=log_quick_operation,
                    args=(
                        workspace.store,
                        "download_case_artifact",
                        f"下载案件附件｜{artifact['file_name']}",
                        {"case_id": case_id, "artifact_id": artifact["id"]},
                    ),
                )
    if st.button("使用已保存附件重新执行"):
        with st.spinner("正在重新执行……"):
            execution = execute_logged_operation(
                workspace.store,
                "rerun_case",
                f"重新执行案件｜{case['title']}",
                lambda: workspace.rerun(
                    case_id,
                    st.session_state["actor"],
                    {"use_ai": False, "create_tasks": False},
                ),
                {"case_id": case_id},
            )
        st.session_state["last_execution"] = execution.to_dict()
        st.success("重新执行完成" if execution.success else f"重新执行失败：{execution.error}")
        st.rerun()
    approval_actions = {
        "commercial_contract": "商业合同签署",
        "labor_contract": "劳动合同签署",
        "recruitment_match": "候选人录用决定",
        "policy_review": "制度发布",
        "meeting_actions": "会议事项关闭",
        "expense_review": "费用批准/进入付款流程",
        "budget_analysis": "预算调整",
    }
    st.subheader("最终动作审批")
    action = approval_actions.get(case["workflow_id"], "案件关闭")
    st.write(f"当前流程需要人工审批的动作：**{action}**")
    if st.button("发起审批", key=f"request_approval_{case_id}"):
        execute_logged_operation(
            workspace.store,
            "request_approval",
            f"发起审批｜{action}",
            lambda: workspace.store.create_approval(
                case_id, action, st.session_state["actor"]
            ),
            {"case_id": case_id},
        )
        st.success("审批申请已创建，请由另一位操作人处理")
        st.rerun()
    render_approvals(workspace.store, case_id)
    if case["executions"]:
        execution = case["executions"][0]
        if execution.get("result"):
            render_execution(
                {
                    "success": True,
                    "case_id": case_id,
                    "execution_id": execution["id"],
                    "workflow_id": execution["workflow_id"],
                    "result": execution["result"],
                    "report_path": str(
                        workspace.store.report_dir / f"{case_id}_{execution['id']}.md"
                    ),
                },
                workspace.store,
            )
    st.subheader("人工复核")
    findings = case["findings"]
    if not findings:
        st.info("该案件没有发现项。")
        return
    st.dataframe(
        [
            {
                "严重程度": item["severity"],
                "标题": item["title"],
                "规则": item["rule_id"],
                "复核状态": item["review_status"],
                "复核意见": item["review_comment"],
            }
            for item in findings
        ],
        hide_index=True,
        **STRETCH_KWARGS,
    )
    finding_id = st.selectbox(
        "选择发现项",
        [item["id"] for item in findings],
        format_func=lambda value: next(
            f"[{item['severity']}] {item['title']}" for item in findings if item["id"] == value
        ),
    )
    selected = next(item for item in findings if item["id"] == finding_id)
    with st.form("review_finding"):
        status_options = ["待复核", "已接受", "已驳回", "待补充材料", "已整改"]
        review_status = st.selectbox(
            "人工结论",
            status_options,
            index=status_options.index(selected["review_status"])
            if selected["review_status"] in status_options
            else 0,
        )
        comment = st.text_area("复核意见", value=selected.get("review_comment") or "")
        if st.form_submit_button("保存复核结论"):
            execute_logged_operation(
                workspace.store,
                "review_finding",
                f"保存发现复核｜{selected['title']}",
                lambda: workspace.store.update_finding_review(
                    finding_id, review_status, comment, st.session_state["actor"]
                ),
                {"finding_id": finding_id, "status": review_status},
            )
            st.success("复核结论已保存")
            st.rerun()


def page_system(workspace: ReviewWorkspace) -> None:
    """配置安全等级、模型服务、密钥、数据目录和样本。"""

    st.markdown(
        '<div class="hero"><h1>系统管理</h1><p>集中维护数据安全策略、模型连接和工作台运行参数。</p></div>',
        unsafe_allow_html=True,
    )
    settings = workspace.model_gateway.settings()
    security_tab, model_tab, data_tab = st.tabs(["安全等级", "模型服务", "数据与样本"])

    with security_tab:
        with st.form("security_settings"):
            configured_levels: dict[str, dict[str, str]] = {}
            for level in ("L1", "L2", "L3"):
                current = settings["security_levels"][level]
                st.markdown(f"#### {level}")
                columns = st.columns([1.3, 3, 2])
                name = columns[0].text_input(
                    "等级名称", value=current["name"], key=f"security_name_{level}"
                )
                description = columns[1].text_area(
                    "资料范围",
                    value=current["description"],
                    height=90,
                    key=f"security_description_{level}",
                )
                policy_keys = list(SECURITY_POLICY_OPTIONS)
                policy = columns[2].selectbox(
                    "模型路由策略",
                    policy_keys,
                    index=policy_keys.index(current["policy"]),
                    format_func=lambda value: SECURITY_POLICY_OPTIONS[value],
                    key=f"security_policy_{level}",
                )
                configured_levels[level] = {
                    "name": name.strip() or level,
                    "description": description.strip(),
                    "policy": policy,
                }
            st.markdown("#### 工作流等级映射")
            configured_workflows: dict[str, str] = {}
            workflow_columns = st.columns(2)
            for index, item in enumerate(workspace.catalog()):
                current_level = settings["workflow_sensitivity"].get(
                    item["id"], item["sensitivity"]
                )
                configured_workflows[item["id"]] = workflow_columns[index % 2].selectbox(
                    item["label"],
                    ["L1", "L2", "L3"],
                    index=["L1", "L2", "L3"].index(current_level),
                    key=f"workflow_sensitivity_{item['id']}",
                )
            save_security = st.form_submit_button(
                "保存安全等级配置", type="primary", **STRETCH_KWARGS
            )
        if save_security:
            execute_logged_operation(
                workspace.store,
                "save_security_settings",
                "保存数据安全等级",
                lambda: workspace.store.save_system_settings(
                    {
                        "security_levels": configured_levels,
                        "workflow_sensitivity": configured_workflows,
                    },
                    st.session_state["actor"],
                    SECRET_SETTING_KEYS,
                ),
            )
            st.success("安全等级配置已保存并即时生效")
            st.rerun()

    with model_tab:
        with st.form("model_settings"):
            st.caption("API Key 由操作系统凭据能力保护，企业数据库只保存引用，不会写入运行日志或分析报告。")
            st.markdown("#### 本地模型")
            local_enabled = st.checkbox("启用本地模型", value=bool(settings["local_enabled"]))
            local_columns = st.columns(2)
            local_base_url = local_columns[0].text_input(
                "本地 Base URL", value=str(settings["local_base_url"])
            )
            local_model = local_columns[1].text_input(
                "本地模型名", value=str(settings["local_model"])
            )
            local_key = st.text_input(
                "本地 API Key",
                type="password",
                placeholder="留空则保持当前值",
                help="Ollama 通常不校验密钥，可保留 ollama。",
            )
            local_key_clear = st.checkbox("清空已保存的本地 API Key")
            st.caption(
                "本地 API Key：" + ("已配置" if settings["local_api_key"] else "未配置")
            )

            st.divider()
            st.markdown("#### 外部模型")
            external_enabled = st.checkbox(
                "启用外部模型", value=bool(settings["external_enabled"])
            )
            external_columns = st.columns(2)
            external_provider = external_columns[0].text_input(
                "服务商标识", value=str(settings["external_provider"])
            )
            external_model = external_columns[1].text_input(
                "外部模型名", value=str(settings["external_model"])
            )
            external_base_url = st.text_input(
                "外部 Base URL", value=str(settings["external_base_url"])
            )
            external_key = st.text_input(
                "外部 API Key", type="password", placeholder="留空则保持当前值"
            )
            external_key_clear = st.checkbox("清空已保存的外部 API Key")
            st.caption(
                "外部 API Key："
                + ("已配置" if settings["external_api_key"] else "未配置")
            )
            numeric_columns = st.columns(2)
            model_timeout = numeric_columns[0].number_input(
                "模型超时（秒）",
                min_value=1.0,
                max_value=600.0,
                value=float(settings["model_timeout"]),
                step=1.0,
            )
            knowledge_default_limit = numeric_columns[1].number_input(
                "默认知识召回条数",
                min_value=1,
                max_value=20,
                value=int(settings["knowledge_default_limit"]),
                step=1,
            )
            save_models = st.form_submit_button(
                "保存模型配置", type="primary", **STRETCH_KWARGS
            )
        if save_models:
            updated = {
                "local_enabled": local_enabled,
                "local_base_url": local_base_url.strip(),
                "local_model": local_model.strip(),
                "local_api_key": ""
                if local_key_clear
                else local_key.strip() or settings["local_api_key"],
                "external_enabled": external_enabled,
                "external_provider": external_provider.strip(),
                "external_base_url": external_base_url.strip(),
                "external_model": external_model.strip(),
                "external_api_key": ""
                if external_key_clear
                else external_key.strip() or settings["external_api_key"],
                "model_timeout": float(model_timeout),
                "knowledge_default_limit": int(knowledge_default_limit),
            }
            execute_logged_operation(
                workspace.store,
                "save_model_settings",
                "保存模型服务配置",
                lambda: workspace.store.save_system_settings(
                    updated, st.session_state["actor"], SECRET_SETTING_KEYS
                ),
            )
            st.success("模型配置已保存并即时生效")
            st.rerun()
        if st.button("检查本地模型连接"):
            status = execute_logged_operation(
                workspace.store,
                "check_model_status",
                "检查本地模型连接",
                workspace.model_gateway.status,
            )
            st.json(status)
            if status["local_reachable"]:
                st.success("本地模型服务可访问")
            else:
                st.warning(status["local_error"] or "本地模型当前不可访问")

    with data_tab:
        st.subheader("本地保存位置")
        st.code(
            f"数据库：{workspace.store.db_path}\n上传文件：{workspace.store.upload_dir}\n知识原件：{workspace.store.root / 'knowledge_sources'}\n报告：{workspace.store.report_dir}\n样本：{workspace.store.sample_dir}"
        )
        st.subheader("标准样本")
        st.write("生成劳动合同、岗位、简历、制度、会议、费用和预算样本，所有人物和金额均为虚构。")
        if st.button("生成或更新标准样本", type="primary"):
            result = execute_logged_operation(
                workspace.store,
                "generate_samples",
                "生成标准业务样本",
                lambda: generate_samples(workspace.store.sample_dir),
            )
            st.success("标准样本已生成")
            st.json(result)
        expected = workspace.store.sample_dir / "expected.json"
        if expected.is_file():
            st.download_button(
                "下载样本预期结果",
                expected.read_bytes(),
                file_name="expected.json",
                mime="application/json",
                on_click=log_quick_operation,
                args=(
                    workspace.store,
                    "download_sample_expectations",
                    "下载样本预期结果",
                ),
            )


def page_monitor(store: EnterpriseStore) -> None:
    """展示运行中任务、按钮操作日志和模型调用情况。"""

    st.markdown(
        '<div class="hero"><h1>运行监控</h1><p>查看当前处理任务、页面操作结果和模型调用路线。</p></div>',
        unsafe_allow_html=True,
    )
    store.reconcile_stale_runtime_events()
    running = store.list_runtime_events(status="运行中")
    operations = store.list_runtime_events(category="operation", limit=300)
    model_calls = store.list_runtime_events(category="model", limit=300)
    metrics = st.columns(4)
    metrics[0].metric("运行中", len(running))
    metrics[1].metric("操作事件", len(operations))
    metrics[2].metric("模型调用", len(model_calls))
    metrics[3].metric("模型失败", sum(item["status"] == "失败" for item in model_calls))
    refresh_columns = st.columns([1, 1, 4])
    auto_refresh = refresh_columns[0].toggle("自动刷新", value=False)
    refresh_seconds = refresh_columns[1].selectbox("刷新间隔", [2, 5, 10], index=1)
    if refresh_columns[2].button("立即刷新"):
        log_quick_operation(store, "refresh_monitor", "刷新运行监控")
        st.rerun()

    current_tab, operation_tab, model_tab = st.tabs(["当前任务", "操作日志", "模型调用"])
    with current_tab:
        if running:
            render_runtime_events(running)
        else:
            st.info("当前没有正在处理的任务。")
    with operation_tab:
        render_runtime_events(operations)
    with model_tab:
        render_runtime_events(model_calls, model_view=True)
    if auto_refresh:
        time.sleep(refresh_seconds)
        st.rerun()


def render_runtime_events(events: list[dict[str, Any]], model_view: bool = False) -> None:
    """把运行事件转换为便于监控的表格。"""

    if not events:
        st.info("暂无记录。")
        return
    rows = []
    for item in events:
        details = item.get("details", {})
        row = {
            "状态": item["status"],
            "事件": item["title"],
            "操作人": item["actor"],
            "开始时间": item["started_at"],
            "结束时间": item["completed_at"] or "处理中",
        }
        if model_view:
            row.update(
                {
                    "服务商": details.get("provider", ""),
                    "模型": details.get("model", ""),
                    "路线": details.get("route", ""),
                    "敏感等级": details.get("sensitivity", ""),
                    "耗时(ms)": details.get("duration_ms", ""),
                    "错误": details.get("error", ""),
                }
            )
        else:
            row["详情"] = json.dumps(details, ensure_ascii=False, default=str)
        rows.append(row)
    st.dataframe(rows, hide_index=True, **STRETCH_KWARGS)


def workflow_label(workspace: ReviewWorkspace, workflow_id: str) -> str:
    """把工作流编号转换为业务名称。"""

    for item in workspace.catalog():
        if item["id"] == workflow_id:
            return item["label"]
    return workflow_id


def display_value(value: Any) -> str:
    """把复杂结构转换为表格可读文本。"""

    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


if __name__ == "__main__":
    main()
