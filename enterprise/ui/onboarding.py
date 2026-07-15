"""酒店负责人系统引导组件。"""

from __future__ import annotations  # 延迟解析类型标注，避免运行时创建仅用于说明的类型。

import inspect  # 用来兼容项目允许的不同 Streamlit 小版本参数。
from dataclasses import dataclass  # 把每一步的文案和跳转目标组合成稳定结构。

import streamlit as st  # 提供侧边栏入口、引导对话框和交互按钮。

# 当前步骤保存在会话中，使每次按钮触发的页面重跑仍停留在正确位置。
_STEP_KEY = "onboarding_tour_step"
# 打开状态独立保存，让跳过、完成和重播可以共用同一套关闭逻辑。
_OPEN_KEY = "onboarding_tour_open"
# 已展示标记保证一个浏览器会话只会自动弹出一次，不会在普通操作后反复打扰。
_SEEN_KEY = "onboarding_tour_seen"
# 主导航键与入口页面的 radio 控件一致，使引导可以真正打开对应功能页面。
_NAVIGATION_KEY = "main_navigation"


@dataclass(frozen=True)
class TourStep:
    """系统引导中的一个负责人工作步骤。

    Attributes:
        label: 进度栏旁显示的简短阶段名称。
        title: 当前步骤的负责人任务标题。
        summary: 说明这一步为什么值得执行的摘要。
        actions: 负责人可以照着完成的具体操作。
        destination: 当前步骤在系统中的完整位置说明。
        navigation_page: 点击快捷按钮后要打开的左侧导航页面。
        tip: 结合现有产品边界给负责人的补充提醒。
    """

    label: str  # 使用短标签避免在进度说明中占用过多横向空间。
    title: str  # 用任务语言告诉负责人当前要完成什么。
    summary: str  # 用一句话解释当前步骤对经营闭环的价值。
    actions: tuple[str, ...]  # 元组创建后不能增删，因此可以保持引导内容顺序稳定。
    destination: str  # 保留完整路径，帮助负责人建立系统位置记忆。
    navigation_page: str  # 保存 radio 的真实选项值，避免用展示路径猜测页面。
    tip: str  # 补充数据质量、安全或功能边界等容易忽略的信息。


# 五个步骤按照负责人从了解系统到形成安全使用习惯的顺序排列。
TOUR_STEPS = (
    # 第一步先建立工作台用途、默认入口和人工责任的整体认知。
    TourStep(
        label="欢迎",  # 短标签用于第一步进度提示。
        title="先掌握今天最重要的事",  # 以负责人目标开场，而不是介绍技术能力。
        summary="这个工作台帮助你在十分钟内看清经营结果、发现异常并形成行动。",  # 说明产品价值。
        actions=(
            "每天从左侧的「每日经营驾驶舱」开始。",  # 指明每天最稳定的工作入口。
            "系统保存分析来源、版本和处理记录，方便后续追溯。",  # 说明留痕能力。
            "所有关键结论由你确认，系统不会替你做最终管理决策。",  # 强调人工责任边界。
        ),
        destination="每日经营驾驶舱",  # 展示当前步骤对应的完整位置。
        navigation_page="每日经营驾驶舱",  # 快捷按钮打开系统默认页面。
        tip="第一次使用不必配置 AI；日报导入和权威指标计算可以完全在本机完成。",  # 降低首次使用门槛。
    ),
    # 第二步聚焦负责人每天需要完成的权威数据入口。
    TourStep(
        label="日报",  # 短标签说明当前阶段是准备经营数据。
        title="导入昨日 PMS 日报",  # 直接使用负责人每天执行的动作命名。
        summary="先把 PMS 导出的 CSV 或 XLSX 日报变成当天可核验的经营底稿。",  # 解释导入目的。
        actions=(
            "确认营业日期、可售房、已售房和客房收入的来源表头。",  # 提醒先核对口径。
            "选择日报文件，点击「导入并生成驾驶舱」。",  # 给出页面上的实际按钮名称。
            "同一 PMS 的字段映射会保存为模板，下次可以直接复用。",  # 解释模板能减少重复操作。
        ),
        destination="每日经营驾驶舱 → 导入 PMS 经营日报",  # 保留展开组件的具体位置。
        navigation_page="每日经营驾驶舱",  # 打开包含日报导入组件的页面。
        tip="多行日报需要额外填写客房库存分段；不要把合计行与房型明细一起导入。",  # 预防常见质量错误。
    ),
    # 第三步说明首版已经提供的六项客房权威指标，而不扩大为全店总览。
    TourStep(
        label="经营",  # 短标签说明当前阶段是阅读数据。
        title="读懂客房经营结果",  # 明确首版指标范围只覆盖客房经营。
        summary="按房量、入住、收入和效率的顺序，快速判断昨日客房经营表现。",  # 给出阅读顺序。
        actions=(
            "先核对可售房与已售房，再看入住率。",  # 先确认分子分母再解释比率。
            "结合客房收入、平均房价（ADR）和每间可售房收入（RevPAR）判断量价表现。",  # 使用完整领域术语。
            "用页面底部的来源文件、日报版本和指标口径核验数据。",  # 引导负责人验证可追溯性。
        ),
        destination="每日经营驾驶舱 → 六项客房经营指标",  # 明确指标范围避免误解为全店总览。
        navigation_page="每日经营驾驶舱",  # 打开六项客房指标所在页面。
        tip="页面没有日报时不会用零值占位，避免把缺失数据误判为经营结果。",  # 解释空状态设计。
    ),
    # 第四步把专项工具、任务跟踪与人工复核连接成现有系统可完成的闭环。
    TourStep(
        label="闭环",  # 短标签说明当前阶段从看数转向行动。
        title="把异常变成行动",  # 使用管理动作而不是功能名称作为标题。
        summary="发现问题后进入相应管理工具，留下证据、负责人和复核记录。",  # 说明闭环目标。
        actions=(
            "合同、人力、行政或财务问题，从左侧对应工具箱进入。",  # 指明专项分析入口。
            "在「任务中心」跟踪行动项和待审批事项。",  # 指明执行状态入口。
            "在「历史与复核」补充人工结论，并在「运行监控」查看处理记录。",  # 指明留痕入口。
        ),
        destination="管理工具箱 → 任务中心 → 历史与复核",  # 展示完整管理路径。
        navigation_page="任务中心",  # 快捷按钮先带负责人查看行动跟踪能力。
        tip="建议每个行动写清负责人、截止时间和验收标准；任务中心当前用于跟踪执行状态。",  # 只承诺现有能力。
    ),
    # 第五步在开始正式使用前再次强调本地数据和人工决策边界。
    TourStep(
        label="安全",  # 短标签说明最后一步关注安全边界。
        title="守住数据与决策边界",  # 强调负责人需要承担的最终确认责任。
        summary="系统默认本地优先，确定性计算与人工审批始终保留在你的控制之下。",  # 概括控制原则。
        actions=(
            "原始文件、分析结果和操作记录默认保存在本地个人数据空间。",  # 强调默认存储位置属于负责人个人。
            "敏感数据不会因为启用工作台就自动发送给外部模型。",  # 说明不会静默外发。
            "付款、录用、签约、制度发布和风险关闭等最终动作必须人工确认。",  # 列出关键决策边界。
        ),
        destination="系统管理 → 数据安全与模型配置",  # 展示安全配置所在位置。
        navigation_page="系统管理",  # 快捷按钮打开安全和模型配置页。
        tip="你现在可以从「每日经营驾驶舱」开始；需要回看时，点击侧边栏的「系统使用引导」。",  # 告知重播方式。
    ),
)


def render_onboarding_tour() -> None:
    """首次进入自动展示引导，并在侧边栏提供重播入口。

    Returns:
        None. 函数直接把入口和对话框渲染到当前 Streamlit 页面。
    """

    # 先准备会话状态，保证后续读取键值时不会出现首次访问异常。
    _initialize_tour_state()
    # 重播入口固定放在侧边栏，使负责人在任意业务页面都能找到。
    with st.sidebar:
        # 点击重播后从第一步打开，避免继承上次未完成的位置造成困惑。
        if st.button(
            "系统使用引导",  # 按钮名称使用负责人容易理解的中文表达。
            key="open_onboarding_tour",  # 稳定键避免与业务页面按钮冲突。
            help="重新查看酒店负责人五步使用说明",  # 悬停文字补充按钮用途。
            use_container_width=True,  # 撑满侧边栏宽度便于发现和点击。
        ):
            # 重播始终从欢迎步骤开始，形成可预测的操作结果。
            st.session_state[_STEP_KEY] = 0
            # 标记为打开后，本轮页面立即渲染引导对话框。
            st.session_state[_OPEN_KEY] = True

    # 只有打开状态才调用对话框，普通业务操作不会额外渲染引导内容。
    if st.session_state[_OPEN_KEY]:
        # 对话框函数由下方兼容逻辑包装，可在支持的版本中使用宽布局和关闭回调。
        _show_tour_dialog()


def _initialize_tour_state() -> None:
    """为当前浏览器会话初始化一次自动引导。

    Returns:
        None. 函数只更新当前 Streamlit 会话中的引导状态。
    """

    # 没有已展示标记说明这是当前浏览器会话的首次页面运行。
    if _SEEN_KEY not in st.session_state:
        # 立即记录已展示，后续业务按钮引起的重跑不会再次自动打开。
        st.session_state[_SEEN_KEY] = True
        # 首次访问默认打开对话框，让负责人无需寻找入口。
        st.session_state[_OPEN_KEY] = True
        # 首次访问从欢迎步骤开始。
        st.session_state[_STEP_KEY] = 0
    else:
        # 兼容已有会话中缺少打开键的情况，并默认保持关闭。
        st.session_state.setdefault(_OPEN_KEY, False)
        # 兼容已有会话中缺少步骤键的情况，并默认回到第一步。
        st.session_state.setdefault(_STEP_KEY, 0)


def _render_tour_dialog() -> None:
    """渲染当前步骤以及跳转、前进、后退和退出操作。

    Returns:
        None. 函数直接把当前步骤渲染到系统引导对话框。
    """

    # 把会话中的步骤限制在合法范围，防止旧状态或手工修改导致越界。
    step_index = min(max(int(st.session_state[_STEP_KEY]), 0), len(TOUR_STEPS) - 1)
    # 读取强类型步骤后，下面的渲染无需再依赖多个平行列表。
    step = TOUR_STEPS[step_index]

    # 先显示当前位置，让负责人知道引导还剩多少内容。
    st.caption(f"第 {step_index + 1} 步，共 {len(TOUR_STEPS)} 步 · {step.label}")
    # 进度条把当前步骤换算为零到一之间的 Streamlit 进度值。
    st.progress((step_index + 1) / len(TOUR_STEPS))
    # 二级标题突出本步骤要完成的负责人任务。
    st.markdown(f"## {step.title}")
    # 摘要先解释价值，再呈现具体动作，降低理解成本。
    st.markdown(step.summary)
    # 把每个动作转换为 Markdown 列表，保持扫读顺序清楚。
    st.markdown("\n".join(f"- {action}" for action in step.actions))
    # 信息框显示功能路径，帮助负责人把说明连接到实际界面。
    st.info(f"**你会在这里完成：** {step.destination}")
    # 提示补充最容易被忽略的数据质量或安全边界。
    st.markdown(f"💡 **负责人提示：** {step.tip}")
    # 每一步都提供真实页面跳转，使引导不仅停留在文字说明。
    st.button(
        f"打开「{step.navigation_page}」",  # 按钮直接写出将要打开的页面名称。
        key="onboarding_tour_destination",  # 同一位置使用稳定键以保持控件身份。
        on_click=_open_destination,  # 点击后先运行该函数，在页面重绘前更新目标值。
        args=(step.navigation_page,),  # 把当前步骤的真实导航选项传给回调。
        use_container_width=True,  # 使用整行宽度，让页面跳转与底部翻页按钮区分开。
    )

    # 三列分别放置返回、跳过和继续，符合从左到右的操作顺序。
    back_column, skip_column, next_column = st.columns([1, 1, 1.35])
    # 第一列提供返回操作，第一步禁用以避免步骤下标变成负数。
    with back_column:
        # 点击后更新步骤并触发完整重跑，使对话框内容立即刷新。
        if st.button(
            "上一步",  # 使用符合负责人阅读习惯的返回名称。
            disabled=step_index == 0,  # 第一页没有更早内容，因此禁用按钮。
            key="onboarding_tour_previous",  # 稳定键避免与业务页按钮冲突。
            use_container_width=True,  # 按钮填满当前列以保持底部对齐。
        ):
            # 已排除第一步，因此减一后仍处于合法步骤范围。
            st.session_state[_STEP_KEY] = step_index - 1
            # 完整重跑让会话状态、对话框与主页面保持一致。
            st.rerun()
    # 第二列允许负责人先关闭引导，之后仍可通过侧边栏重播。
    with skip_column:
        # 跳过不会丢失任何业务数据，只重置引导自身状态。
        if st.button(
            "暂时跳过",  # “暂时”说明以后仍可重新查看。
            key="onboarding_tour_skip",  # 稳定键隔离跳过操作状态。
            use_container_width=True,  # 按钮填满当前列以便点击。
        ):
            # 共用关闭函数，确保跳过、完成和右上角关闭行为一致。
            _close_tour()
            # 完整重跑用于移除对话框并恢复主页面交互。
            st.rerun()
    # 第三列放置主要前进操作，并给予略大的横向空间。
    with next_column:
        # 最后一步使用不同按钮名称，明确继续会结束引导。
        final_step = step_index == len(TOUR_STEPS) - 1
        # 前四步推进内容，最后一步关闭引导并开始使用系统。
        if st.button(
            "开始使用" if final_step else "下一步",  # 根据位置显示准确动作。
            type="primary",  # 突出推荐负责人继续完成引导。
            key="onboarding_tour_next",  # 同一位置使用稳定键保持控件连续。
            use_container_width=True,  # 按钮填满主操作列。
        ):
            # 完成最后一步时直接关闭，其他步骤只向前移动一位。
            if final_step:
                # 关闭函数同时为未来重播恢复第一步。
                _close_tour()
            else:
                # 只增加一位，保留负责人已经阅读到的位置。
                st.session_state[_STEP_KEY] = step_index + 1
            # 完整重跑让新步骤或关闭状态立即反映到界面。
            st.rerun()


def _open_destination(page: str) -> None:
    """从引导直接切换到一个真实导航页面。

    Args:
        page: 主应用 radio 控件中存在的页面名称。

    Returns:
        None. 函数更新主导航并关闭当前引导。
    """

    # 设置主导航单选控件使用的固定名称，使下一次渲染直接选中目标页面。
    st.session_state[_NAVIGATION_KEY] = page
    # 跳转后关闭遮罩，让负责人可以立即操作目标页面。
    _close_tour()


def _close_tour() -> None:
    """关闭引导并把下一次重播重置到第一步。

    Returns:
        None. 函数只更新当前 Streamlit 会话中的引导状态。
    """

    # 关闭标记阻止主页面在普通重跑时再次创建对话框。
    st.session_state[_OPEN_KEY] = False
    # 重置步骤保证负责人以后点击重播时总是从欢迎页开始。
    st.session_state[_STEP_KEY] = 0


# 对话框参数按当前 Streamlit 版本动态选择，兼容项目允许的小版本差异。
_dialog_kwargs: dict[str, object] = {}
# st.dialog 自 Streamlit 1.34 起可用，项目最低版本 1.36 已包含该 API。
_dialog_parameters = inspect.signature(st.dialog).parameters
# 支持 width 的版本使用宽对话框，减少中文步骤内容的拥挤感。
if "width" in _dialog_parameters:
    # large 是 Streamlit 接受的宽度枚举值，不依赖自定义前端样式。
    _dialog_kwargs["width"] = "large"
# 支持 icon 的版本在标题旁显示指南针，增强引导入口辨识度。
if "icon" in _dialog_parameters:
    # 图标只承担视觉提示，不影响无图标版本的功能。
    _dialog_kwargs["icon"] = "🧭"
# 支持 on_dismiss 的版本在用户点击右上角关闭时同步清理打开状态。
if "on_dismiss" in _dialog_parameters:
    # 使用同一关闭函数防止关闭后因其他业务操作再次弹出。
    _dialog_kwargs["on_dismiss"] = _close_tour

# st.dialog 把普通渲染函数变成对话框函数，调用后会在页面上方显示步骤内容。
_show_tour_dialog = st.dialog("酒店负责人系统引导", **_dialog_kwargs)(_render_tour_dialog)
