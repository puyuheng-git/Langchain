#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""企业智能管理工作台 Streamlit 入口。

业务人员只需要在浏览器中上传材料、选择参数并点击执行。每次上传、结果、报告、
发现项和人工复核都会保存到本机 SQLite 与案件目录，页面刷新或下次启动后仍可查看。
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

import streamlit as st

from enterprise import EnterpriseStore, ReviewWorkspace
from enterprise.sample_data import generate_samples

WORKFLOW_GROUPS = {
    "审计与合同": ["commercial_contract"],
    "人力管理": ["labor_contract", "recruitment_match"],
    "行政管理": ["policy_review", "meeting_actions"],
    "财务管理": ["expense_review", "budget_analysis"],
}

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
    elif page == "任务中心":
        page_tasks(workspace.store)
    elif page == "历史与复核":
        page_history(workspace)
    else:
        page_system(workspace)


def page_dashboard(workspace: ReviewWorkspace) -> None:
    """展示工作台总览和快捷入口说明。"""

    st.markdown(
        '<div class="hero"><h1>企业智能管理工作台</h1><p>审计、人力、行政、财务统一操作台。上传即归档，结果可追溯，敏感数据本地优先。</p></div>',
        unsafe_allow_html=True,
    )
    metrics = workspace.store.dashboard_metrics()
    columns = st.columns(5)
    columns[0].metric("累计案件", metrics["case_count"])
    columns[1].metric("待复核案件", metrics["pending_cases"])
    columns[2].metric("待复核高风险", metrics["high_findings"])
    columns[3].metric("未完成任务", metrics["open_tasks"])
    columns[4].metric("待审批", metrics["pending_approvals"])
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
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("还没有历史案件。请从左侧进入业务模块发起第一项任务。")


def page_domain(workspace: ReviewWorkspace, group: str, workflow_ids: list[str]) -> None:
    """渲染一个业务领域的任务发起页。"""

    st.markdown(
        f'<div class="hero"><h1>{group}</h1><p>选择业务流程，上传材料，执行后自动保存案件、原文件、发现项和报告。</p></div>',
        unsafe_allow_html=True,
    )
    catalog = {item["id"]: item for item in workspace.catalog()}
    workflow_id = st.selectbox(
        "业务流程", workflow_ids, format_func=lambda value: catalog[value]["label"]
    )
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
        use_ai = st.checkbox(
            "启用 Ollama/本地模型补充管理摘要",
            value=False,
            help="不启用模型时，结构化提取、规则检查和财务计算仍可完整运行。",
        )
        allow_external = False
        if use_ai:
            allow_external = st.checkbox("本地模型失败时，允许脱敏后调用外部模型", value=False)
            if allow_external:
                st.warning(
                    "该授权仅对本次案件生效。系统会先脱敏并记录 external-redacted 路线，但仍建议敏感材料只使用本地模型。"
                )
        submitted = st.form_submit_button(
            "保存材料并执行", type="primary", use_container_width=True
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
        }
        if not upload_tuples:
            st.error("请上传材料或输入会议内容。")
        else:
            with st.spinner("正在归档文件并执行本地分析……"):
                execution = workspace.execute_uploads(
                    workflow_id, upload_tuples, st.session_state["actor"], title, options
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
    tabs = st.tabs(
        ["结构化结果", "明细记录", f"风险与发现 ({len(result.get('findings', []))})", "报告与后续"]
    )
    with tabs[0]:
        fields = result.get("fields", {})
        simple_fields = [{"字段": key, "值": display_value(value)} for key, value in fields.items()]
        st.dataframe(simple_fields, use_container_width=True, hide_index=True)
    with tabs[1]:
        records = result.get("records", [])
        if records:
            st.dataframe(records, use_container_width=True, hide_index=True)
            st.download_button(
                "下载明细 JSON",
                json.dumps(records, ensure_ascii=False, indent=2, default=str),
                file_name=f"{execution['execution_id']}_records.json",
                mime="application/json",
            )
        else:
            st.info("该流程没有明细记录。")
    with tabs[2]:
        render_findings(result.get("findings", []))
    with tabs[3]:
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
            )
        st.caption(
            f"案件编号：{execution['case_id']} · 执行编号：{execution['execution_id']} · 模型路线：{result.get('model_route', 'deterministic')}"
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
                    store.create_task(
                        title.strip(), owner, due_date, priority, source="手工", details=details
                    )
                    st.success("任务已创建")
                    st.rerun()
                else:
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
        use_container_width=True,
        hide_index=True,
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
            store.update_task(selected_id, status, owner, due_date)
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
        use_container_width=True,
        hide_index=True,
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
                store.decide_approval(approval_id, decision, comment, st.session_state["actor"])
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
        use_container_width=True,
        hide_index=True,
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
        workspace.store.update_case_status(case_id, new_status, st.session_state["actor"])
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
                )
    if st.button("使用已保存附件重新执行"):
        with st.spinner("正在重新执行……"):
            execution = workspace.rerun(
                case_id, st.session_state["actor"], {"use_ai": False, "create_tasks": False}
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
        workspace.store.create_approval(case_id, action, st.session_state["actor"])
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
        use_container_width=True,
        hide_index=True,
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
            workspace.store.update_finding_review(
                finding_id, review_status, comment, st.session_state["actor"]
            )
            st.success("复核结论已保存")
            st.rerun()


def page_system(workspace: ReviewWorkspace) -> None:
    """展示模型策略、数据目录和标准样本生成入口。"""

    st.markdown(
        '<div class="hero"><h1>系统管理</h1><p>查看本地模型状态、数据保存位置和生成标准样本。</p></div>',
        unsafe_allow_html=True,
    )
    st.subheader("数据安全策略")
    st.write("- L3：员工、简历、工资、劳动合同、发票、费用和未发布预算。默认仅本地处理。")
    st.write("- L2：内部制度和会议纪要。默认本地处理，外发必须本次明确授权并先脱敏。")
    st.write("- L1：公开岗位说明和通用写作材料。可按配置使用外部模型。")
    if st.button("检查 Ollama 状态"):
        status = workspace.model_gateway.status()
        st.json(status)
        if status["local_reachable"]:
            st.success("Ollama 服务可访问")
        else:
            st.warning("Ollama 当前不可访问。确定性规则、解析和财务计算仍可使用。")
    st.subheader("本地保存位置")
    st.code(
        f"数据库：{workspace.store.db_path}\n上传文件：{workspace.store.upload_dir}\n报告：{workspace.store.report_dir}\n样本：{workspace.store.sample_dir}"
    )
    st.subheader("标准 MVP 样本")
    st.write("生成劳动合同、岗位、简历、制度、会议、费用和预算样本，所有人物和金额均为虚构。")
    if st.button("生成或更新标准样本", type="primary"):
        result = generate_samples(workspace.store.sample_dir)
        st.success("标准样本已生成")
        st.json(result)
    expected = workspace.store.sample_dir / "expected.json"
    if expected.is_file():
        st.download_button(
            "下载样本预期结果",
            expected.read_bytes(),
            file_name="expected.json",
            mime="application/json",
        )


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
