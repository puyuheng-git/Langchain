"""酒店负责人每日经营驾驶舱 Streamlit 页面。"""

from __future__ import annotations  # 延迟类型解析，保持页面函数标注简洁。

from datetime import date  # 页面允许负责人选择 PMS 夜审营业日。
from decimal import Decimal  # 指标格式化保持 Decimal 权威精度。

import streamlit as st  # 使用项目既有 Streamlit 操作台渲染页面。

from enterprise.hotel import (  # 只依赖酒店领域对外公开的稳定类型。
    HotelDashboardService,  # 协调本地日报导入、模板恢复和快照读取。
    HotelDashboardSnapshot,  # 表达页面展示需要的日报和指标组合结果。
    HotelReportUpload,  # 把一次上传的文件、映射和模板绑定成命令。
    PmsFieldMapping,  # 使用强类型 PMS 映射避免多个字符串参数错位。
)


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
    # 单独的导入组件处理模板恢复和上传，主渲染函数只编排页面流程。
    snapshot, import_failed, template_name = _render_import_panel(service)

    # 默认查看刚导入营业日；首次打开时使用本地自然日作为选择起点。
    selected_day = st.date_input(
        "查看营业日",
        value=st.session_state.get("hotel_dashboard_business_date", date.today()),
    )
    # 没有刚导入结果时，从本地数据库恢复负责人选择的营业日。
    if snapshot is None and not import_failed:
        snapshot, import_failed = _load_snapshot(service, selected_day, template_name)

    # 空状态说明下一步操作，不显示没有来源的零指标。
    if snapshot is None:
        if not import_failed:
            st.info("当前营业日还没有 PMS 日报，请先完成上方导入。")
        return

    # 指标和追溯信息分别渲染，便于后续独立增加关注事项和来源下钻。
    _render_metrics(snapshot)
    # 来源信息紧跟指标，让负责人能核验当前页面使用的具体版本。
    _render_traceability(snapshot)


def _render_import_panel(
    service: HotelDashboardService,
) -> tuple[HotelDashboardSnapshot | None, bool, str]:
    """渲染可恢复模板的 PMS 日报导入区域。

    Args:
        service: 提供模板、上传和快照能力的驾驶舱应用服务。

    Returns:
        当前导入快照、是否导入失败以及当前模板名称。
    """

    # 上传配置默认展开，首次使用无需寻找隐藏入口。
    with st.expander("导入 PMS 经营日报", expanded=True):
        # 从本地数据库读取模板，应用重启后仍能复用负责人确认过的映射。
        template_options = service.list_templates()
        # 默认模板始终可选，首次使用无需先创建配置记录。
        if "pms-daily" not in template_options:
            template_options.insert(0, "pms-daily")
        # 模板选择放在表单外，切换后页面会立即重新加载相应字段值。
        template_name = st.selectbox(
            "PMS 模板",
            options=template_options,
            accept_new_options=True,
            help="可选择已保存模板，也可输入新的模板名称。",
        )
        # 已保存模板使用持久化映射，新模板使用首版默认中文表头。
        mapping = service.get_mapping(template_name) or PmsFieldMapping()
        # 表单保证负责人确认全部表头后才触发一次完整导入。
        with st.form("hotel-dashboard-import"):
            # 第一行配置营业日和可选库存分段来源表头。
            mapping_columns = st.columns(2)
            # 模板名进入控件键，切换模板时不会串用另一模板的编辑状态。
            business_date_header = mapping_columns[0].text_input(
                "营业日期表头",
                value=mapping.business_date,
                key=f"hotel_business_date_header_{template_name}",
            )
            # 多行日报才需要库存分段；单行日报保持空值即可。
            inventory_segment_header = mapping_columns[1].text_input(
                "客房库存分段表头（多行日报填写）",
                value=mapping.room_inventory_segment,
                key=f"hotel_inventory_segment_header_{template_name}",
            )
            # 第二行配置三个权威客房指标的来源表头。
            metric_columns = st.columns(3)
            # 可售房字段决定入住率和 RevPAR 的分母。
            available_rooms_header = metric_columns[0].text_input(
                "可售房表头",
                value=mapping.available_rooms,
                key=f"hotel_available_rooms_header_{template_name}",
            )
            # 已售房字段决定入住率和平均房价的计算口径。
            rooms_sold_header = metric_columns[1].text_input(
                "已售房表头",
                value=mapping.rooms_sold,
                key=f"hotel_rooms_sold_header_{template_name}",
            )
            # 客房收入字段保持确定性金额计算的原始来源。
            room_revenue_header = metric_columns[2].text_input(
                "客房收入表头",
                value=mapping.room_revenue,
                key=f"hotel_room_revenue_header_{template_name}",
            )
            # 文件控件只允许产品首版确认的 CSV 和 XLSX 格式。
            uploaded = st.file_uploader(
                "上传 PMS 日报",
                type=["csv", "xlsx"],
                help="文件仅在本机解析和归档，不会自动上传到外部服务。",
            )
            # 主按钮名称清楚表达导入后会立即生成驾驶舱。
            submitted = st.form_submit_button("导入并生成驾驶舱", type="primary")

    # 未提交表单时只渲染当前营业日，不制造导入错误。
    if not submitted:
        return None, False, template_name
    # 没有选择文件时给出可操作提示，不调用应用服务。
    if uploaded is None:
        st.error("请先选择 CSV 或 XLSX 日报文件。")
        return None, True, template_name
    # 把五个来源表头集中为强类型映射，避免顺序错误或散落字典键。
    submitted_mapping = PmsFieldMapping(
        business_date=business_date_header,  # 保存营业日来源表头。
        available_rooms=available_rooms_header,  # 保存可售房来源表头。
        rooms_sold=rooms_sold_header,  # 保存已售房来源表头。
        room_revenue=room_revenue_header,  # 保存客房收入来源表头。
        room_inventory_segment=inventory_segment_header,  # 保存可选库存分段表头。
    )
    # 上传命令把页面读取到的数据一次性交给应用服务边界。
    upload = HotelReportUpload(
        file_name=uploaded.name,  # 保留浏览器提供的来源文件名用于追溯。
        content=uploaded.getvalue(),  # 读取完整字节供本地解析和归档。
        mapping=submitted_mapping,  # 保存本次负责人确认的字段映射。
        template_name=template_name,  # 将映射与当前模板稳定关联。
    )
    # 页面只展示应用服务返回的领域错误，不改写校验含义。
    try:
        snapshot = service.import_upload(upload)
    # ValueError 已包含字段、营业日或合计行等负责人可理解信息。
    except ValueError as exc:
        st.error(str(exc))
        return None, True, template_name
    # 保存营业日，使后面的日期选择器自动对准刚导入的日报。
    st.session_state["hotel_dashboard_business_date"] = snapshot.report.business_date
    # 成功提示强调原件已经进入本地版本化归档。
    st.success("日报已归档，驾驶舱已按当前生效版本更新。")
    # 返回新快照供本轮页面直接展示，避免再次读取数据库。
    return snapshot, False, template_name


def _load_snapshot(
    service: HotelDashboardService,
    business_date: date,
    template_name: str,
) -> tuple[HotelDashboardSnapshot | None, bool]:
    """按营业日和模板恢复当前生效的驾驶舱快照。

    Args:
        service: 提供持久化快照读取能力的驾驶舱应用服务。
        business_date: 负责人当前选择的 PMS 夜审营业日。
        template_name: 当前查看和导入使用的 PMS 模板名称。

    Returns:
        恢复到的快照以及读取是否因数据质量失败。
    """

    # 已归档日报的数据质量错误直接展示，等待有效修订版本覆盖。
    try:
        return service.get_snapshot(business_date, template_name), False
    # 领域错误保留原文，让负责人知道需要修正哪个数据问题。
    except ValueError as exc:
        st.error(str(exc))
        return None, True


def _render_metrics(snapshot: HotelDashboardSnapshot) -> None:
    """按照负责人阅读顺序展示六项客房权威指标。

    Args:
        snapshot: 已通过数据质量校验的当前驾驶舱快照。

    Returns:
        None.
    """

    # 六列指标卡按照房量、入住、收入和效率的阅读顺序排列。
    metric_columns = st.columns(6)
    # 使用快照中的权威指标对象，页面不重复计算任何业务公式。
    metrics = snapshot.metrics
    # 第一张卡展示当日可售客房库存。
    metric_columns[0].metric("可售房", f"{metrics.available_rooms:,} 间")
    # 第二张卡展示当日实际已售房量。
    metric_columns[1].metric("已售房", f"{metrics.rooms_sold:,} 间")
    # 第三张卡展示已售房除以可售房的入住率。
    metric_columns[2].metric("入住率", f"{metrics.occupancy_rate}%")
    # 第四张卡展示来源日报中的客房收入合计。
    metric_columns[3].metric("客房收入", _money(metrics.room_revenue))
    # 第五张卡展示每间已售房对应的平均房价。
    metric_columns[4].metric("平均房价（ADR）", _money(metrics.adr))
    # 第六张卡展示每间可售房对应的收入效率。
    metric_columns[5].metric("每间可售房收入（RevPAR）", _money(metrics.revpar))


def _render_traceability(snapshot: HotelDashboardSnapshot) -> None:
    """展示当前指标对应的来源文件和版本链路。

    Args:
        snapshot: 包含日报版本与指标口径版本的驾驶舱快照。

    Returns:
        None.
    """

    # 来源说明把页面数字连接到原始文件、日报版本和计算口径版本。
    st.caption(
        f"来源文件：{snapshot.report.source_name} · "
        f"日报编号：{snapshot.report.id} · "
        f"日报版本 V{snapshot.report.version} · "
        f"指标口径 {snapshot.metrics.definition_version}"
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
