"""每日经营驾驶舱应用服务公共接口的行为测试。"""

from datetime import date  # 按 PMS 夜审营业日重新读取驾驶舱快照。
from decimal import Decimal  # 使用精确字面值验证页面展示前的权威指标。
from io import BytesIO  # 在内存中生成浏览器上传所需的 XLSX 字节。
from pathlib import Path  # 为测试提供隔离的本地个人数据空间。

import pytest  # 验证应用服务会保留领域数据质量错误。
from openpyxl import Workbook  # 构造包含房型分段的真实 Excel 工作簿。

# 只通过酒店领域公共入口调用应用服务和上传命令，不读取内部数据库表。
from enterprise.hotel import (
    HotelDashboardService,  # 协调上传、恢复和指标计算。
    HotelDashboardSnapshot,  # 标注测试 helper 返回的有效驾驶舱快照。
    HotelReportUpload,  # 把文件、模板和映射组成一个上传命令。
    PmsFieldMapping,  # 用强类型字段配置表达 PMS 来源表头。
)


def _make_upload(
    file_name: str,
    content: bytes,
    *,
    inventory_segment_header: str = "",
    template_name: str = "pms-daily",
) -> HotelReportUpload:
    """使用测试默认 PMS 表头创建完整上传命令。

    Args:
        file_name: 模拟浏览器提供的来源文件名。
        content: 模拟浏览器读取到的文件字节。
        inventory_segment_header: 多行日报使用的可选库存分段表头。
        template_name: 本次导入保存和使用的模板名称。

    Returns:
        可直接交给驾驶舱公共服务的强类型上传命令。
    """

    # 集中使用页面默认表头，避免每个行为测试重复同一份映射字典。
    mapping = PmsFieldMapping(room_inventory_segment=inventory_segment_header)
    # 返回同时绑定文件、映射和模板的公共上传命令。
    return HotelReportUpload(
        file_name=file_name,  # 保留每个测试需要验证的来源文件名。
        content=content,  # 使用测试准备的真实 CSV 或 XLSX 字节。
        mapping=mapping,  # 通过强类型对象避免字段参数位置错配。
        template_name=template_name,  # 默认复用首版 PMS 日报模板。
    )


def _create_active_segmented_dashboard(
    root: Path,
) -> tuple[HotelDashboardService, HotelDashboardSnapshot]:
    """创建一份可供无效修订恢复测试使用的有效 V1 驾驶舱。

    Args:
        root: 测试使用的隔离本地个人数据空间。

    Returns:
        已创建的应用服务和有效 V1 驾驶舱快照。
    """

    # 创建使用调用方隔离目录的真实驾驶舱应用服务。
    service = HotelDashboardService(root)
    # 使用两个唯一房型分段构造不会触发数据质量错误的有效日报。
    valid_content = (
        "营业日期,房型,可售房,已售房,客房收入\n"
        "2026-07-16,标准房,200,150,90000\n"
        "2026-07-16,行政房,100,60,36000\n"
    ).encode()
    # 通过公共上传接口形成当前生效的第一版驾驶舱。
    active = service.import_upload(
        _make_upload(
            "valid-v1.csv",
            valid_content,
            inventory_segment_header="房型",
        )
    )
    # 返回服务和基线快照，供不同失败次数的生命周期测试复用。
    return service, active


def _assert_invalid_total_revision(
    service: HotelDashboardService,
    file_name: str,
) -> None:
    """导入一份包含合计行的修订，并验证公共服务保留领域错误。

    Args:
        service: 已经拥有有效基线的驾驶舱应用服务。
        file_name: 本次无效修订使用的来源文件名。

    Returns:
        None.
    """

    # 每次生成相同错误内容，让差异只来自日报递增版本号。
    invalid_content = (
        "营业日期,房型,可售房,已售房,客房收入\n"
        "2026-07-16,标准房,200,150,90000\n"
        "2026-07-16,合计,200,150,90000\n"
    ).encode()
    # 无效修订必须通过公共接口返回合计行领域错误。
    with pytest.raises(ValueError, match="多行日报不能包含合计行: 合计"):
        service.import_upload(
            _make_upload(
                file_name,
                invalid_content,
                inventory_segment_header="房型",
            )
        )


def test_uploaded_csv_produces_a_dashboard_snapshot_that_survives_restart(
    tmp_path: Path,
) -> None:
    """上传 CSV 后生成指标快照，重新创建服务后仍可按营业日读取。

    Args:
        tmp_path: Pytest 为本测试提供的隔离临时目录。

    Returns:
        None.
    """

    # 创建使用临时本地数据空间的驾驶舱应用服务。
    root = tmp_path / "enterprise"
    service = HotelDashboardService(root)
    # 使用已手算过的标准样例构造浏览器上传字节。
    content = "营业日期,可售房,已售房,客房收入\n2026-07-13,200,150,90000\n".encode()

    # 通过公共接口完成映射保存、归档、版本化和指标计算。
    imported = service.import_upload(_make_upload("pms-daily.csv", content))
    # 模拟 Streamlit 刷新后重新创建应用服务。
    reopened = HotelDashboardService(root)
    restored = reopened.get_snapshot(date(2026, 7, 13), "pms-daily")

    # 首次导入必须生成手算结果对应的权威指标。
    assert (
        imported.metrics.occupancy_rate,
        imported.metrics.adr,
        imported.metrics.revpar,
    ) == (Decimal("75.0"), Decimal("600.00"), Decimal("450.00"))
    # 快照必须保留日报版本和独立指标口径版本。
    assert (imported.report.version, imported.metrics.definition_version) == (1, "1.0")
    # 页面刷新后读取到的快照必须与首次导入结果完全一致。
    assert restored == imported


def test_uploaded_xlsx_sums_unique_inventory_segments(tmp_path: Path) -> None:
    """上传 XLSX 后可按唯一客房库存分段汇总并生成快照。

    Args:
        tmp_path: Pytest 为本测试提供的隔离临时目录。

    Returns:
        None.
    """

    # 创建使用隔离个人数据空间的独立驾驶舱服务。
    service = HotelDashboardService(tmp_path / "enterprise")
    # 在内存中生成两行互不重叠房型的真实 XLSX 工作簿。
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(["营业日期", "房型", "可售房", "已售房", "客房收入"])
    worksheet.append([date(2026, 7, 16), "标准房", 200, 150, 90000])
    worksheet.append([date(2026, 7, 16), "行政房", 100, 60, 36001.05])
    buffer = BytesIO()
    workbook.save(buffer)
    workbook.close()

    # 直接把内存字节作为浏览器上传内容交给应用服务。
    snapshot = service.import_upload(
        _make_upload(
            "pms-room-types.xlsx",
            buffer.getvalue(),
            inventory_segment_header="房型",
        )
    )

    # 两个唯一库存分段必须先汇总，再按权威口径舍入。
    assert (
        snapshot.metrics.available_rooms,
        snapshot.metrics.rooms_sold,
        snapshot.metrics.room_revenue,
        snapshot.metrics.adr,
    ) == (300, 210, Decimal("126001.05"), Decimal("600.01"))


def test_dashboard_service_preserves_room_metric_validation_errors(tmp_path: Path) -> None:
    """应用服务不吞掉合计行错误，页面可直接展示领域提示。

    Args:
        tmp_path: Pytest 为本测试提供的隔离临时目录。

    Returns:
        None.
    """

    # 构造包含房型和“合计”行的 CSV 上传内容。
    service = HotelDashboardService(tmp_path / "enterprise")
    content = (
        "营业日期,房型,可售房,已售房,客房收入\n"
        "2026-07-16,标准房,200,150,90000\n"
        "2026-07-16,合计,200,150,90000\n"
    ).encode()

    # 领域错误必须原样穿过应用服务，供 Streamlit 显示。
    with pytest.raises(ValueError, match="多行日报不能包含合计行: 合计"):
        service.import_upload(
            _make_upload(
                "pms-with-total.csv",
                content,
                inventory_segment_header="房型",
            )
        )


def test_failed_metric_validation_does_not_replace_active_dashboard(tmp_path: Path) -> None:
    """无效修订保留错误，但不能替换此前正常生效的驾驶舱。

    Args:
        tmp_path: Pytest 为本测试提供的隔离临时目录。

    Returns:
        None.
    """

    # 创建有效基线，作为无效修订失败后的权威恢复目标。
    root = tmp_path / "enterprise"
    service, active = _create_active_segmented_dashboard(root)
    # 无效修订仍要把领域错误返回给当前页面。
    _assert_invalid_total_revision(service, "invalid-v2.csv")
    # 模拟页面刷新并重新创建服务，验证持久化生效状态。
    restored = HotelDashboardService(root).get_snapshot(date(2026, 7, 16))

    # 驾驶舱必须继续指向正常 V1，而不是无效 V2。
    assert restored == active


def test_repeated_invalid_revisions_never_reactivate_an_invalid_version(
    tmp_path: Path,
) -> None:
    """连续无效修订只能恢复最近有效版本，不能复活较早的无效版本。

    Args:
        tmp_path: Pytest 为本测试提供的隔离临时目录。

    Returns:
        None.
    """

    # 创建有效 V1，作为连续校验失败后的权威恢复目标。
    root = tmp_path / "enterprise"
    service, active = _create_active_segmented_dashboard(root)
    # 第一次无效修订必须返回领域错误并恢复 V1。
    _assert_invalid_total_revision(service, "invalid-v2.csv")
    # 第二次无效修订仍必须返回同一领域错误，不能把 V2 当作恢复候选。
    _assert_invalid_total_revision(service, "invalid-v3.csv")

    # 应用重启后驾驶舱仍必须指向唯一有效的 V1。
    restored = HotelDashboardService(root).get_snapshot(date(2026, 7, 16))
    assert restored == active


def test_saved_pms_mapping_can_be_listed_and_restored_after_restart(tmp_path: Path) -> None:
    """自定义 PMS 表头保存后可在服务重启时列出并恢复。

    Args:
        tmp_path: Pytest 为本测试提供的隔离临时目录。

    Returns:
        None.
    """

    # 使用不同于页面默认值的表头，证明结果来自持久化模板。
    mapping = PmsFieldMapping(
        business_date="业务日期",  # 自定义营业日表头。
        available_rooms="房间库存",  # 自定义可售房表头。
        rooms_sold="出租间夜",  # 自定义已售房表头。
        room_revenue="房费净收入",  # 自定义客房收入表头。
    )
    # 把自定义映射和 CSV 字节组成一个完整上传命令。
    upload = HotelReportUpload(
        file_name="custom-pms.csv",  # 浏览器上传文件名。
        content="业务日期,房间库存,出租间夜,房费净收入\n2026-07-20,200,150,90000\n".encode(),
        mapping=mapping,  # 本次导入使用的强类型映射。
        template_name="custom-pms",  # 使用可在页面选择的模板名称。
    )
    # 首次服务保存模板并完成有效导入。
    root = tmp_path / "enterprise"
    HotelDashboardService(root).import_upload(upload)

    # 模拟应用重启后重新创建服务。
    reopened = HotelDashboardService(root)

    # 已保存模板应出现在页面可选列表中。
    assert reopened.list_templates() == ["custom-pms"]
    # 恢复出的强类型映射必须与首次输入完全一致。
    assert reopened.get_mapping("custom-pms") == mapping
