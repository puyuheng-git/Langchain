"""酒店负责人系统引导的 Streamlit 页面行为测试。"""

# AppTest 使用 Streamlit 官方运行器验证真实控件状态，而不是模拟内部函数。
from streamlit.testing.v1 import AppTest


def _render_tour_for_test() -> None:
    """在独立 AppTest 脚本中渲染系统引导。

    Returns:
        None. 函数直接渲染待测试的 Streamlit 组件。
    """

    # AppTest 会提取本函数源码，因此依赖需要在函数内部重新导入。
    from enterprise.ui.onboarding import render_onboarding_tour

    # 只渲染公开组件，避免测试依赖主应用中的数据库或业务页面。
    render_onboarding_tour()


def _render_tour_with_navigation_for_test() -> None:
    """渲染与主应用使用同一状态键的简化导航和系统引导。

    Returns:
        None. 函数直接渲染供集成行为测试使用的 Streamlit 控件。
    """

    # AppTest 提取函数源码，因此依赖必须在被提取的函数内部重新导入。
    import streamlit as st  # 渲染与主应用一致的 radio 导航控件。

    from enterprise.ui.onboarding import render_onboarding_tour  # 渲染待测试的引导组件。

    # 简化导航保留引导会跳转的三个真实选项，并使用与主应用相同的稳定键。
    st.radio(
        "导航",  # 标签与主应用保持一致，便于按真实行为读取控件。
        ["每日经营驾驶舱", "任务中心", "系统管理"],  # 覆盖五步引导中的全部跳转目标。
        key="main_navigation",  # 共享键验证快捷按钮确实能控制 radio。
    )
    # 导航先实例化后再渲染引导，顺序与 enterprise_app.py 完全一致。
    render_onboarding_tour()


def _text_values(app: AppTest) -> list[str]:
    """返回当前页面和对话框中的主要说明文本。

    Args:
        app: 已完成一次运行的 Streamlit 页面测试对象。

    Returns:
        Markdown 正文和进度说明组成的文本列表。
    """

    # 标题与正文由 Markdown 渲染，步骤位置由 caption 渲染，因此合并两类组件。
    return [item.value for item in app.markdown] + [item.value for item in app.caption]


def test_tour_opens_automatically_and_advances_through_manager_workflow() -> None:
    """首次进入时自动展示引导，并按经营闭环推进五个步骤。

    Returns:
        None. 断言失败时由 Pytest 报告不符合预期的页面行为。
    """

    # 创建全新会话，模拟负责人第一次进入系统。
    app = AppTest.from_function(_render_tour_for_test).run()

    # 首次渲染不得出现脚本异常，否则引导会阻断整个主应用。
    assert not app.exception
    # 欢迎页应以负责人价值开场，而不是暴露实现或技术术语。
    assert any("先掌握今天最重要的事" in value for value in _text_values(app))
    # 负责人需要知道当前步骤和总长度，才能判断阅读成本。
    assert any("第 1 步，共 5 步" in value for value in _text_values(app))
    # 非最后一步必须提供清楚的继续操作。
    assert any(button.label == "下一步" for button in app.button)

    # 后续标题覆盖日报、客房经营、行动闭环和安全边界四个阶段。
    expected_steps = [
        "导入昨日 PMS 日报",  # 第二步说明权威经营数据入口。
        "读懂客房经营结果",  # 第三步明确首版指标范围。
        "把异常变成行动",  # 第四步连接管理工具与任务跟踪。
        "守住数据与决策边界",  # 第五步强调本地优先和人工确认。
    ]
    # 每次点击页面上当前的“下一步”，验证引导按固定顺序推进。
    for expected in expected_steps:
        # 对话框重跑后要重新读取按钮对象，避免使用上一步的过期控件引用。
        next_button = next(button for button in app.button if button.label == "下一步")
        # 点击并运行新一轮 Streamlit 脚本，使会话步骤状态生效。
        next_button.click().run()
        # 当前步骤必须出现对应任务标题，证明没有跳步或停滞。
        assert any(expected in value for value in _text_values(app))

    # 最后一步用结果导向的“开始使用”替代仍然含糊的“下一步”。
    assert any(button.label == "开始使用" for button in app.button)


def test_tour_can_be_skipped_and_replayed_from_sidebar() -> None:
    """负责人可跳过首次引导，并随时从侧边栏重新打开。

    Returns:
        None. 断言失败时由 Pytest 报告关闭或重播行为异常。
    """

    # 创建新的首次访问会话，使跳过按钮处于可操作状态。
    app = AppTest.from_function(_render_tour_for_test).run()

    # 定位并点击引导中的暂时跳过操作。
    skip_button = next(button for button in app.button if button.label == "暂时跳过")
    # 运行完整重绘，验证关闭状态不会被自动展示逻辑覆盖。
    skip_button.click().run()

    # 关闭后不再提供对话框的主要前进按钮。
    assert not any(button.label == "下一步" for button in app.button)
    # 侧边栏入口必须始终存在，允许负责人主动重新查看。
    replay_button = next(button for button in app.button if button.label == "系统使用引导")
    # 点击重播并运行新一轮页面，恢复第一步对话框。
    replay_button.click().run()

    # 重播必须重置到第一步，而不是从跳过位置继续。
    assert any("第 1 步，共 5 步" in value for value in _text_values(app))
    # 欢迎标题再次出现，证明重播内容完整恢复。
    assert any("先掌握今天最重要的事" in value for value in _text_values(app))
    # 第一页的主要前进操作应恢复可用。
    assert any(button.label == "下一步" for button in app.button)


def test_tour_destination_button_opens_the_real_navigation_page() -> None:
    """引导步骤的快捷按钮会写入主应用使用的真实导航状态。

    Returns:
        None. 断言失败时由 Pytest 报告引导与主导航没有正确连接。
    """

    # 使用带真实 radio 状态键的页面打开首次引导。
    app = AppTest.from_function(_render_tour_with_navigation_for_test).run()

    # 连续进入第四步“把异常变成行动”，其快捷目的地应为任务中心。
    for _ in range(3):
        # 每轮重绘后重新定位当前对话框中的前进按钮。
        next(button for button in app.button if button.label == "下一步").click().run()

    # 快捷按钮应写出真实目的地，避免负责人误解跳转结果。
    destination = next(
        button for button in app.button if button.label == "打开「任务中心」"
    )
    # 点击按钮会执行回调、关闭对话框并写入主导航使用的稳定键。
    destination.click().run()

    # 状态值必须与 enterprise_app.py 中 radio 的真实选项完全一致。
    assert app.radio[0].value == "任务中心"
    # 跳转后引导关闭，不遮挡负责人对目标页面的下一步操作。
    assert not any(button.label == "下一步" for button in app.button)
