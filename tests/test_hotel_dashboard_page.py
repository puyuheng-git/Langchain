"""每日经营驾驶舱 Streamlit 页面公共行为测试。"""

from pathlib import Path  # 为页面测试提供隔离的本地个人数据空间。

from streamlit.testing.v1 import AppTest  # 通过 Streamlit 官方接口驱动真实页面组件。


def _render_dashboard_for_test(root: str) -> None:
    """在 AppTest 独立脚本中创建服务并渲染驾驶舱。

    Args:
        root: 页面测试使用的本地个人数据空间路径。

    Returns:
        None.
    """

    # AppTest 会提取本函数源码，因此依赖需要在函数内部重新导入。
    from enterprise.hotel import HotelDashboardService

    # 页面入口同样在独立脚本内导入，避免依赖测试模块全局变量。
    from enterprise.ui.hotel_dashboard import render_hotel_dashboard

    # 用调用方传入的隔离目录创建真实应用服务并渲染页面。
    render_hotel_dashboard(HotelDashboardService(root))


def test_dashboard_page_uploads_csv_and_displays_six_room_metrics(tmp_path: Path) -> None:
    """负责人上传标准 CSV 后可在页面看到六项客房指标和版本追溯。

    Args:
        tmp_path: Pytest 为本测试提供的隔离临时目录。

    Returns:
        None.
    """

    # 页面测试注入独立应用服务，避免读取真实酒店数据。
    root = tmp_path / "enterprise"
    # AppTest 直接运行公开页面包装函数，行为与主应用调用保持一致。
    app = AppTest.from_function(
        _render_dashboard_for_test,
        args=(str(root),),
    ).run()

    # 初始页面必须提供日报上传控件且没有脚本异常。
    assert len(app.file_uploader) == 1
    assert not app.exception

    # 模拟负责人在浏览器中选择标准 PMS 日报。
    content = "营业日期,可售房,已售房,客房收入\n2026-07-13,200,150,90000\n".encode()
    app.file_uploader[0].set_value(("pms-daily.csv", content, "text/csv"))
    # 点击页面主按钮，触发映射保存、归档、计算和展示。
    submit = next(button for button in app.button if button.label == "导入并生成驾驶舱")
    submit.click().run()

    # 页面必须展示负责人确认的六项权威指标卡片。
    assert [metric.label for metric in app.metric] == [
        "可售房",
        "已售房",
        "入住率",
        "客房收入",
        "平均房价（ADR）",
        "每间可售房收入（RevPAR）",
    ]
    # 三项核心比率应使用和领域引擎一致的格式化结果。
    assert [metric.value for metric in app.metric[2:]] == [
        "75.0%",
        "¥90,000.00",
        "¥600.00",
        "¥450.00",
    ]
    # 成功提示和追溯说明证明页面没有只在内存中计算。
    assert any("日报已归档" in item.value for item in app.success)
    assert any("日报版本 V1" in item.value for item in app.caption)


def test_dashboard_page_displays_data_quality_error_for_total_row(tmp_path: Path) -> None:
    """负责人上传含合计行的多行日报时可直接看到领域错误。

    Args:
        tmp_path: Pytest 为本测试提供的隔离临时目录。

    Returns:
        None.
    """

    # 用新的隔离数据空间打开每日经营驾驶舱。
    app = AppTest.from_function(
        _render_dashboard_for_test,
        args=(str(tmp_path / "enterprise"),),
    ).run()
    # 多行日报需要告诉页面房型来源表头，才能验证合计行语义。
    segment_input = next(
        item
        for item in app.text_input
        if item.label == "客房库存分段表头（多行日报填写）"
    )
    segment_input.set_value("房型")
    # 上传一行房型明细和一行重复合计数据。
    content = (
        "营业日期,房型,可售房,已售房,客房收入\n"
        "2026-07-13,标准房,200,150,90000\n"
        "2026-07-13,合计,200,150,90000\n"
    ).encode()
    app.file_uploader[0].set_value(("pms-with-total.csv", content, "text/csv"))
    # 点击同一个主按钮，让错误沿应用服务返回页面。
    submit = next(button for button in app.button if button.label == "导入并生成驾驶舱")
    submit.click().run()

    # 页面必须显示负责人可理解的合计行错误且不渲染误导性指标。
    assert any("多行日报不能包含合计行: 合计" in item.value for item in app.error)
    assert not app.metric


def test_dashboard_page_restores_saved_custom_pms_mapping(tmp_path: Path) -> None:
    """应用重启后选择已保存模板会自动回填自定义 PMS 表头。

    Args:
        tmp_path: Pytest 为本测试提供的隔离临时目录。

    Returns:
        None.
    """

    # 先通过公开服务保存一份不同于页面默认值的真实模板。
    from enterprise.hotel import (
        HotelDashboardService,  # 使用与页面相同的应用服务入口。
        HotelReportUpload,  # 构造一次完整 PMS 日报上传。
        PmsFieldMapping,  # 表达页面需要恢复的自定义表头。
    )

    # 创建自定义 PMS 字段映射，证明页面数据来自本地持久化而非默认值。
    mapping = PmsFieldMapping(
        business_date="业务日期",  # 自定义营业日表头。
        available_rooms="房间库存",  # 自定义可售房表头。
        rooms_sold="出租间夜",  # 自定义已售房表头。
        room_revenue="房费净收入",  # 自定义客房收入表头。
    )
    # 使用隔离目录保存模板和一份有效日报。
    root = tmp_path / "enterprise"
    HotelDashboardService(root).import_upload(
        HotelReportUpload(
            file_name="custom-pms.csv",  # 模拟 PMS 导出的原始文件名。
            content=(
                "业务日期,房间库存,出租间夜,房费净收入\n"
                "2026-07-20,200,150,90000\n"
            ).encode(),  # 使用自定义表头构造可验证的 CSV 字节。
            mapping=mapping,  # 保存负责人首次确认的字段映射。
            template_name="custom-pms",  # 使用页面可选择的稳定模板名。
        )
    )

    # 新建 AppTest 模拟关闭并重新打开应用。
    app = AppTest.from_function(
        _render_dashboard_for_test,
        args=(str(root),),
    ).run()
    # 在模板选择器中切换到重启前保存的自定义 PMS 模板。
    template_select = next(item for item in app.selectbox if item.label == "PMS 模板")
    template_select.set_value("custom-pms").run()

    # 页面五个字段值必须完整恢复，后续同类文件无需重新映射。
    values = {item.label: item.value for item in app.text_input}
    assert values == {
        "营业日期表头": "业务日期",
        "客房库存分段表头（多行日报填写）": "",
        "可售房表头": "房间库存",
        "已售房表头": "出租间夜",
        "客房收入表头": "房费净收入",
    }
