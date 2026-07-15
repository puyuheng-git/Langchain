"""每日经营驾驶舱应用服务公共接口的行为测试。"""

from datetime import date  # 按 PMS 夜审营业日重新读取驾驶舱快照。
from decimal import Decimal  # 使用精确字面值验证页面展示前的权威指标。
from io import BytesIO  # 在内存中生成浏览器上传所需的 XLSX 字节。
from pathlib import Path  # 为测试提供隔离的本地个人数据空间。

import pytest  # 验证应用服务会保留领域数据质量错误。
from openpyxl import Workbook  # 构造包含房型分段的真实 Excel 工作簿。

# 只通过酒店领域公共入口调用应用服务，不读取内部数据库表。
from enterprise.hotel import HotelDashboardService


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
    # 声明标准字段到真实 PMS 来源表头的映射。
    mapping = {
        "business_date": "营业日期",  # 营业日来源表头。
        "available_rooms": "可售房",  # 可售房来源表头。
        "rooms_sold": "已售房",  # 已售房来源表头。
        "room_revenue": "客房收入",  # 客房收入来源表头。
    }
    # 使用已手算过的标准样例构造浏览器上传字节。
    content = "营业日期,可售房,已售房,客房收入\n2026-07-13,200,150,90000\n".encode()

    # 通过公共接口完成映射保存、归档、版本化和指标计算。
    imported = service.import_upload("pms-daily.csv", content, mapping, "pms-daily")
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

    # 创建独立驾驶舱服务和包含库存分段的字段映射。
    service = HotelDashboardService(tmp_path / "enterprise")
    mapping = {
        "business_date": "营业日期",  # 营业日来源表头。
        "room_inventory_segment": "房型",  # 唯一库存分段来源表头。
        "available_rooms": "可售房",  # 可售房来源表头。
        "rooms_sold": "已售房",  # 已售房来源表头。
        "room_revenue": "客房收入",  # 客房收入来源表头。
    }
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
    snapshot = service.import_upload("pms-room-types.xlsx", buffer.getvalue(), mapping)

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
    mapping = {
        "business_date": "营业日期",  # 营业日来源表头。
        "room_inventory_segment": "房型",  # 库存分段来源表头。
        "available_rooms": "可售房",  # 可售房来源表头。
        "rooms_sold": "已售房",  # 已售房来源表头。
        "room_revenue": "客房收入",  # 收入来源表头。
    }
    content = (
        "营业日期,房型,可售房,已售房,客房收入\n"
        "2026-07-16,标准房,200,150,90000\n"
        "2026-07-16,合计,200,150,90000\n"
    ).encode()

    # 领域错误必须原样穿过应用服务，供 Streamlit 显示。
    with pytest.raises(ValueError, match="多行日报不能包含合计行: 合计"):
        service.import_upload("pms-with-total.csv", content, mapping)
