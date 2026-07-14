"""酒店经营日报导入公共接口的行为测试。"""

from datetime import date
from pathlib import Path

import pytest
from openpyxl import Workbook

from enterprise.hotel import HotelDataWorkspace


def test_saved_mapping_imports_csv_by_business_date(tmp_path: Path) -> None:
    """负责人保存字段映射后，可导入日报并按营业日读取标准化数据。"""

    workspace = HotelDataWorkspace(tmp_path / "enterprise")
    workspace.save_mapping(
        "pms-daily",
        {
            "business_date": "营业日期",
            "available_rooms": "可售房",
            "rooms_sold": "已售房",
            "room_revenue": "客房收入",
        },
    )
    report_path = tmp_path / "pms-daily.csv"
    report_path.write_text(
        "营业日期,可售房,已售房,客房收入\n2026-07-13,200,150,90000\n",
        encoding="utf-8",
    )

    imported = workspace.import_report(report_path, "pms-daily")
    active = workspace.get_active_report(date(2026, 7, 13), "pms-daily")

    assert imported.business_date == date(2026, 7, 13)
    assert imported.version == 1
    assert imported.records == [
        {
            "business_date": "2026-07-13",
            "available_rooms": "200",
            "rooms_sold": "150",
            "room_revenue": "90000",
        }
    ]
    assert active == imported


def test_reimport_keeps_history_and_activates_latest_version(tmp_path: Path) -> None:
    """同一营业日重复导入会保留旧数据，并让最新版本参与后续读取。"""

    workspace = HotelDataWorkspace(tmp_path / "enterprise")
    workspace.save_mapping(
        "pms-daily",
        {
            "business_date": "营业日期",
            "available_rooms": "可售房",
            "rooms_sold": "已售房",
            "room_revenue": "客房收入",
        },
    )
    first_path = tmp_path / "pms-first.csv"
    first_path.write_text(
        "营业日期,可售房,已售房,客房收入\n2026-07-13,200,150,90000\n",
        encoding="utf-8",
    )
    second_path = tmp_path / "pms-corrected.csv"
    second_path.write_text(
        "营业日期,可售房,已售房,客房收入\n2026-07-13,200,160,96000\n",
        encoding="utf-8",
    )

    workspace.import_report(first_path, "pms-daily")
    corrected = workspace.import_report(second_path, "pms-daily")
    versions = workspace.list_report_versions(date(2026, 7, 13), "pms-daily")

    assert [item.version for item in versions] == [2, 1]
    assert [item.records[0]["rooms_sold"] for item in versions] == ["160", "150"]
    assert workspace.get_active_report(date(2026, 7, 13), "pms-daily") == corrected


def test_import_rejects_report_missing_a_mapped_source_column(tmp_path: Path) -> None:
    """报表缺少模板声明的字段时必须阻断，不能静默保存空值。"""

    workspace = HotelDataWorkspace(tmp_path / "enterprise")
    workspace.save_mapping(
        "pms-daily",
        {
            "business_date": "营业日期",
            "available_rooms": "可售房",
            "rooms_sold": "已售房",
        },
    )
    report_path = tmp_path / "missing-column.csv"
    report_path.write_text(
        "营业日期,可售房\n2026-07-13,200\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="缺少已映射字段: 已售房"):
        workspace.import_report(report_path, "pms-daily")


def test_saved_mapping_is_reused_for_excel_after_restart(tmp_path: Path) -> None:
    """字段映射持久化后，重新打开工作空间仍可导入 Excel 日报。"""

    root = tmp_path / "enterprise"
    workspace = HotelDataWorkspace(root)
    workspace.save_mapping(
        "pms-daily",
        {
            "business_date": "营业日期",
            "available_rooms": "可售房",
            "rooms_sold": "已售房",
        },
    )
    report_path = tmp_path / "pms-daily.xlsx"
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(["营业日期", "可售房", "已售房"])
    worksheet.append([date(2026, 7, 13), 200, 150])
    workbook.save(report_path)
    workbook.close()

    reopened = HotelDataWorkspace(root)
    imported = reopened.import_report(report_path, "pms-daily")

    assert imported.records == [
        {"business_date": "2026-07-13", "available_rooms": 200, "rooms_sold": 150}
    ]
    assert reopened.get_active_report(date(2026, 7, 13), "pms-daily") == imported


def test_import_rejects_conflicting_business_dates(tmp_path: Path) -> None:
    """一个日报包含多个营业日时，应列出冲突日期并停止导入。"""

    workspace = HotelDataWorkspace(tmp_path / "enterprise")
    workspace.save_mapping(
        "pms-daily",
        {"business_date": "营业日期", "rooms_sold": "已售房"},
    )
    report_path = tmp_path / "conflicting-dates.csv"
    report_path.write_text(
        "营业日期,已售房\n2026-07-13,150\n2026-07-14,160\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="发现多个营业日: 2026-07-13、2026-07-14",
    ):
        workspace.import_report(report_path, "pms-daily")


def test_report_version_preserves_the_mapping_used_at_import(tmp_path: Path) -> None:
    """模板后续变更时，历史日报仍保留导入当时的字段映射。"""

    workspace = HotelDataWorkspace(tmp_path / "enterprise")
    original_mapping = {"business_date": "营业日期", "rooms_sold": "已售房"}
    workspace.save_mapping("pms-daily", original_mapping)
    report_path = tmp_path / "pms-daily.csv"
    report_path.write_text(
        "营业日期,已售房\n2026-07-13,150\n",
        encoding="utf-8",
    )
    workspace.import_report(report_path, "pms-daily")

    workspace.save_mapping(
        "pms-daily",
        {"business_date": "业务日期", "rooms_sold": "出租房"},
    )
    historical = workspace.list_report_versions(date(2026, 7, 13), "pms-daily")[0]

    assert historical.mapping == original_mapping
