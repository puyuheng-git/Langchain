"""酒店负责人每日经营驾驶舱 Streamlit 页面。"""

from __future__ import annotations  # 延迟类型解析，保持页面函数标注简洁。

from datetime import date  # 页面允许负责人选择 PMS 夜审营业日。
from decimal import Decimal  # 指标格式化保持 Decimal 权威精度。

import streamlit as st  # 使用项目既有 Streamlit 操作台渲染页面。

from enterprise.hotel import HotelDashboardService, HotelDashboardSnapshot  # 调用公开服务。


def render_hotel_dashboard(service: HotelDashboardService) -> None:
    """渲染日报上传、营业日恢复和六项客房指标。

    Args:
        service: 使用本地个人数据空间的驾驶舱应用服务。

    Returns:
        None.
    """

    # 页首直接说明负责人在十分钟闭环中要完成的核心动作。
    st.markdown(
        """<div class="hero"><h1>每日经营驾驶舱</h1>
        <p>导入 PMS 日报，先看昨日结果与数据质量，再进入经营行动。</p></div>""",
        unsafe_allow_html=True,
    )
    # 上传配置默认展开，首次使用无需寻找隐藏入口。
    with st.expander("导入 PMS 经营日报", expanded=True):
        # 表单保证负责人确认全部表头后才触发一次完整导入。
        with st.form("hotel-dashboard-import"):
            # 模板名称用于保存和复用同一 PMS 导出格式。
            template_name = st.text_input("模板名称", value="pms-daily")
            # 第一行配置营业日和可选库存分段来源表头。
            mapping_columns = st.columns(2)
            business_date_header = mapping_columns[0].text_input(
                "营业日期表头",
                value="营业日期",
            )
            inventory_segment_header = mapping_columns[1].text_input(
                "客房库存分段表头（多行日报填写）",
                value="",
            )
            # 第二行配置三个权威指标来源表头。
            metric_columns = st.columns(3)
            available_rooms_header = metric_columns[0].text_input(
                "可售房表头",
                value="可售房",
            )
            rooms_sold_header = metric_columns[1].text_input(
                "已售房表头",
                value="已售房",
            )
            room_revenue_header = metric_columns[2].text_input(
                "客房收入表头",
                value="客房收入",
            )
            # 文件控件只允许产品首版确认的 CSV 和 XLSX 格式。
            uploaded = st.file_uploader(
                "上传 PMS 日报",
                type=["csv", "xlsx"],
                help="文件仅在本机解析和归档，不会自动上传到外部服务。",
            )
            # 主按钮名称清楚表达导入后会立即生成驾驶舱。
            submitted = st.form_submit_button("导入并生成驾驶舱", type="primary")

    # 当前运行中的快照优先用于立即展示刚导入的结果。
    snapshot: HotelDashboardSnapshot | None = None
    # 记录本轮导入是否失败，避免同一页面重复展示相同错误。
    import_failed = False
    # 只有负责人点击提交按钮后才读取上传字节或显示缺失提示。
    if submitted:
        # 没有选择文件时给出可操作提示，不调用应用服务。
        if uploaded is None:
            st.error("请先选择 CSV 或 XLSX 日报文件。")
            import_failed = True
        else:
            # 四个必需字段始终进入映射，表头空值由领域服务明确拒绝。
            mapping = {
                "business_date": business_date_header,
                "available_rooms": available_rooms_header,
                "rooms_sold": rooms_sold_header,
                "room_revenue": room_revenue_header,
            }
            # 多行库存分段是可选映射，单行日报无需额外字段。
            if inventory_segment_header.strip():
                mapping["room_inventory_segment"] = inventory_segment_header.strip()
            # 页面只负责把上传内容交给应用服务，并展示领域错误。
            try:
                snapshot = service.import_upload(
                    uploaded.name,
                    uploaded.getvalue(),
                    mapping,
                    template_name,
                )
            # ValueError 已包含字段、营业日或合计行等负责人可理解信息。
            except ValueError as exc:
                st.error(str(exc))
                import_failed = True
            else:
                # 保存营业日，使本次交互后面的日期选择器自动对准新日报。
                st.session_state["hotel_dashboard_business_date"] = snapshot.report.business_date
                # 成功提示强调原件已经进入本地版本化归档。
                st.success("日报已归档，驾驶舱已按当前生效版本更新。")

    # 默认查看刚导入营业日；首次打开时使用本地自然日作为选择起点。
    selected_day = st.date_input(
        "查看营业日",
        value=st.session_state.get("hotel_dashboard_business_date", date.today()),
    )
    # 没有刚导入结果时，从本地数据库恢复负责人选择的营业日。
    if snapshot is None and not import_failed:
        try:
            snapshot = service.get_snapshot(selected_day, template_name)
        # 已归档日报的数据质量错误同样直接展示，等待修订版本覆盖。
        except ValueError as exc:
            st.error(str(exc))
            import_failed = True

    # 空状态说明下一步操作，不显示没有来源的零指标。
    if snapshot is None:
        if not import_failed:
            st.info("当前营业日还没有 PMS 日报，请先完成上方导入。")
        return

    # 六列指标卡按照房量、入住、收入和效率的阅读顺序排列。
    metric_columns = st.columns(6)
    metrics = snapshot.metrics
    metric_columns[0].metric("可售房", f"{metrics.available_rooms:,} 间")
    metric_columns[1].metric("已售房", f"{metrics.rooms_sold:,} 间")
    metric_columns[2].metric("入住率", f"{metrics.occupancy_rate}%")
    metric_columns[3].metric("客房收入", _money(metrics.room_revenue))
    metric_columns[4].metric("平均房价（ADR）", _money(metrics.adr))
    metric_columns[5].metric("每间可售房收入（RevPAR）", _money(metrics.revpar))
    # 来源说明把页面数字连接到原始文件、日报版本和计算口径版本。
    st.caption(
        f"来源文件：{snapshot.report.source_name} · "
        f"日报编号：{snapshot.report.id} · "
        f"日报版本 V{snapshot.report.version} · "
        f"指标口径 {metrics.definition_version}"
    )


def _money(value: Decimal) -> str:
    """把 Decimal 金额格式化为驾驶舱人民币展示文本。

    Args:
        value: 已按权威口径保留两位小数的金额。

    Returns:
        带人民币符号、千位分隔和两位小数的文本。
    """

    # Decimal 原值不转换为 float，避免展示阶段重新引入二进制误差。
    return f"¥{value:,.2f}"
