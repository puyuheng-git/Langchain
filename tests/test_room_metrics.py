"""客房权威指标计算公共接口的行为测试。"""

from datetime import date  # 构造与 PMS 夜审一致的营业日。
from decimal import Decimal  # 使用十进制字面值独立验证财务计算精度。
from pathlib import Path  # 创建端到端导入所需的隔离日报文件。

import pytest  # 验证数据质量问题会被公共接口明确阻断。

# 只从酒店领域公共入口导入调用方可见的数据类型和计算器。
from enterprise.hotel import (
    DailyReportVersion,  # 构造指标引擎的公开输入类型。
    HotelDataWorkspace,  # 验证导入版本可直接进入指标引擎。
    RoomMetricsCalculator,  # 调用确定性权威指标计算。
    RoomMetricsSnapshot,  # 构造完整的独立期望结果。
)


def _report(
    records: list[dict[str, object]],
    *,
    report_id: str,
    operating_day: date,
    version: int = 1,
) -> DailyReportVersion:
    """为公共指标接口构造最小、可追溯的已导入日报。

    Args:
        records: 测试场景需要计算的标准化日报记录。
        report_id: 用于验证来源追溯的固定日报编号。
        operating_day: PMS 夜审确定的营业日。
        version: 同营业日下需要验证的日报版本号。

    Returns:
        可直接交给客房指标计算器的公共日报版本对象。
    """

    # 文件名沿用报告编号，使失败信息容易对应到测试场景。
    source_name = f"{report_id}.csv"
    # 统一填充与指标公式无关、但公共日报对象要求的追溯字段。
    return DailyReportVersion(
        id=report_id,  # 保留调用方指定的来源编号。
        template_name="pms-daily",  # 所有客房指标场景使用 PMS 日报模板。
        business_date=operating_day,  # 指标和日报使用同一营业日。
        version=version,  # 保留调用方指定的修订版本。
        records=records,  # 业务输入由各测试独立声明。
        mapping={},  # 指标引擎只依赖已经标准化的字段。
        source_name=source_name,  # 提供可读来源文件名。
        stored_path=f"hotel_imports/{report_id}/{source_name}",  # 模拟归档路径。
        sha256=f"{report_id}-sha256",  # 使用稳定测试摘要。
        imported_at="2026-07-17T00:00:00+00:00",  # 固定导入时间避免随机性。
    )


def test_standard_daily_report_calculates_authoritative_room_metrics() -> None:
    """标准客房日报可生成可追溯的入住率、ADR 和 RevPAR。

    Returns:
        None.
    """

    # 构造一份已完成归档和版本化的标准 PMS 日报。
    report = _report(
        report_id="report_standard",  # 报告编号用于验证指标来源追溯。
        operating_day=date(2026, 7, 13),  # 指标必须归属夜审营业日。
        records=[
            {
                "business_date": "2026-07-13",  # 标准化记录保留 ISO 营业日。
                "available_rooms": "200",  # 可售房来自 CSV 文本单元格。
                "rooms_sold": "150",  # 已售房来自 CSV 文本单元格。
                "room_revenue": "90000",  # 客房收入来自 CSV 文本单元格。
            }
        ],
    )

    # 通过用户确认的公共计算接口生成权威指标快照。
    metrics = RoomMetricsCalculator.calculate(report)

    # 使用独立手算结果构造完整期望对象，避免复述实现公式。
    assert metrics == RoomMetricsSnapshot(
        business_date=date(2026, 7, 13),  # 指标沿用来源日报营业日。
        report_id="report_standard",  # 快照可追溯到具体日报编号。
        report_version=1,  # 快照可追溯到具体修订版本。
        available_rooms=200,  # 可售房合计为二百间。
        rooms_sold=150,  # 已售房合计为一百五十间。
        occupancy_rate=Decimal("75.0"),  # 150/200 对应 75.0%。
        room_revenue=Decimal("90000.00"),  # 客房收入保留两位金额精度。
        adr=Decimal("600.00"),  # 90000/150 对应 ADR 600.00。
        revpar=Decimal("450.00"),  # 90000/200 对应 RevPAR 450.00。
    )


def test_zero_rooms_sold_returns_zero_rates_without_division_error() -> None:
    """零售房营业日的入住率、ADR 和 RevPAR 均稳定返回零。

    Returns:
        None.
    """

    # 构造有正常可售库存、但当日没有售房和客房收入的日报。
    report = _report(
        report_id="report_zero_sold",  # 使用固定编号验证结果来源。
        operating_day=date(2026, 7, 14),  # 设置独立营业日避免混淆。
        records=[
            {
                "business_date": "2026-07-14",  # 保留日报营业日。
                "available_rooms": "200",  # 酒店仍有二百间可售房。
                "rooms_sold": "0",  # 当日没有已售房。
                "room_revenue": "0",  # 当日没有客房收入。
            }
        ],
    )

    # 通过同一公共接口计算零售房日报。
    metrics = RoomMetricsCalculator.calculate(report)

    # 零售房场景必须返回明确的零，而不是异常或无穷值。
    assert metrics.occupancy_rate == Decimal("0.0")
    # 没有售房时 ADR 没有可分摊收入，产品口径定义为零。
    assert metrics.adr == Decimal("0.00")
    # 收入为零时 RevPAR 同样应为零。
    assert metrics.revpar == Decimal("0.00")


def test_missing_authoritative_field_is_reported_clearly() -> None:
    """日报缺少权威指标字段时返回具体记录和字段名称。

    Returns:
        None.
    """

    # 构造缺少客房收入字段的日报，模拟 PMS 模板映射遗漏。
    report = _report(
        report_id="report_missing_revenue",  # 固定来源编号便于错误定位。
        operating_day=date(2026, 7, 15),  # 设置待计算营业日。
        records=[
            {
                "business_date": "2026-07-15",  # 日报仍拥有有效营业日。
                "available_rooms": "200",  # 可售房字段存在。
                "rooms_sold": "150",  # 已售房字段存在。
                # 故意不提供 room_revenue，用于验证明确错误。
            }
        ],
    )

    # 公共接口必须把实现层 KeyError 转换为负责人可理解的信息。
    with pytest.raises(ValueError, match="第1条记录缺少字段: room_revenue"):
        RoomMetricsCalculator.calculate(report)


def test_non_numeric_room_value_is_reported_clearly() -> None:
    """日报出现非数字房量时返回具体记录、字段和值。

    Returns:
        None.
    """

    # 构造已售房被错误填写为中文文本的标准化日报。
    report = _report(
        report_id="report_non_numeric",  # 固定错误日报编号。
        operating_day=date(2026, 7, 15),  # 设置错误数据所属营业日。
        records=[
            {
                "business_date": "2026-07-15",  # 保留有效营业日。
                "available_rooms": "200",  # 可售房仍是有效数字文本。
                "rooms_sold": "一百五十",  # 故意提供不可计算的中文文本。
                "room_revenue": "90000",  # 收入仍是有效数字文本。
            }
        ],
    )

    # 业务错误必须替代 Decimal 内部异常，并指出原始错误值。
    with pytest.raises(
        ValueError,
        match="第1条记录字段 rooms_sold 不是有效数字: 一百五十",
    ):
        RoomMetricsCalculator.calculate(report)


@pytest.mark.parametrize("value", ["NaN", "Infinity"])
def test_non_finite_room_value_is_reported_clearly(value: str) -> None:
    """NaN 和无穷值不能作为客房权威指标输入。

    Args:
        value: Decimal 能解析、但不能参与经营计算的特殊值。

    Returns:
        None.
    """

    # 把特殊值放入已售房字段，其他权威输入保持有效。
    report = _report(
        report_id="report_non_finite",  # 固定特殊值日报编号。
        operating_day=date(2026, 7, 15),  # 设置特殊值所属营业日。
        records=[
            {
                "business_date": "2026-07-15",  # 保留有效营业日。
                "available_rooms": "200",  # 可售房保持正常。
                "rooms_sold": value,  # 注入 NaN 或 Infinity。
                "room_revenue": "90000",  # 收入保持正常。
            }
        ],
    )

    # 公共错误必须指出字段和原始特殊值。
    with pytest.raises(
        ValueError,
        match=f"第1条记录字段 rooms_sold 不是有限数字: {value}",
    ):
        RoomMetricsCalculator.calculate(report)


@pytest.mark.parametrize(
    ("record", "message"),
    [
        # 负可售房不可能成为有效酒店库存。
        ({"available_rooms": "-1", "rooms_sold": "0", "room_revenue": "0"}, "available_rooms 不能为负数: -1"),
        # 负已售房说明来源报表或字段映射有误。
        ({"available_rooms": "200", "rooms_sold": "-1", "room_revenue": "0"}, "rooms_sold 不能为负数: -1"),
        # 负客房收入在首版权威日报口径中必须先核验。
        ({"available_rooms": "200", "rooms_sold": "1", "room_revenue": "-1"}, "room_revenue 不能为负数: -1"),
        # 在营酒店零可售房会让入住率和 RevPAR 失去有效分母。
        ({"available_rooms": "0", "rooms_sold": "0", "room_revenue": "0"}, "可售房必须大于零"),
        # 已售房超过可售库存时先阻断，避免展示超过百分之百的错误入住率。
        ({"available_rooms": "200", "rooms_sold": "201", "room_revenue": "90000"}, "已售房不能超过可售房: 201 > 200"),
        # 可售房必须是完整客房间数，不能被输出时静默截断。
        ({"available_rooms": "200.5", "rooms_sold": "150", "room_revenue": "90000"}, "available_rooms 必须是整数: 200.5"),
        # 已售房同样不能出现半间房。
        ({"available_rooms": "200", "rooms_sold": "150.5", "room_revenue": "90000"}, "rooms_sold 必须是整数: 150.5"),
    ],
)
def test_unreasonable_room_values_are_blocked(
    record: dict[str, str], message: str
) -> None:
    """负数、零库存和售房超过库存时停止权威计算。

    Args:
        record: 本场景需要验证的标准化客房记录。
        message: 负责人应看到的具体数据质量错误。

    Returns:
        None.
    """

    # 为参数化场景补上统一营业日，保持记录结构完整。
    normalized_record = {"business_date": "2026-07-15", **record}
    # 每个场景都通过相同公共日报类型进入指标计算器。
    report = _report(
        report_id="report_unreasonable",  # 固定异常日报编号。
        operating_day=date(2026, 7, 15),  # 设置异常数据营业日。
        records=[normalized_record],  # 每次只验证一条异常记录。
    )

    # 每种不合理值都必须在公式执行前被清晰阻断。
    with pytest.raises(ValueError, match=message):
        RoomMetricsCalculator.calculate(report)


def test_disjoint_room_detail_rows_are_summed_before_rounding() -> None:
    """多个互不重复的房型明细先汇总，再计算和舍入权威指标。

    Returns:
        None.
    """

    # 两行代表两个互不重叠房型，收入合计会形成半分舍入边界。
    report = _report(
        report_id="report_room_types",  # 固定多房型日报编号。
        operating_day=date(2026, 7, 16),  # 设置多房型营业日。
        version=2,  # 使用修订版本验证来源版本保留。
        records=[
            {
                "business_date": "2026-07-16",  # 第一房型营业日。
                "available_rooms": "200",  # 第一房型可售房。
                "rooms_sold": "150",  # 第一房型已售房。
                "room_revenue": "90000",  # 第一房型客房收入。
            },
            {
                "business_date": "2026-07-16",  # 第二房型使用相同营业日。
                "available_rooms": "100",  # 第二房型可售房。
                "rooms_sold": "60",  # 第二房型已售房。
                "room_revenue": "36001.05",  # 第二房型收入形成舍入边界。
            },
        ],
    )

    # 通过公共接口计算跨房型汇总指标。
    metrics = RoomMetricsCalculator.calculate(report)

    # 可售房必须等于两行明细合计三百间。
    assert metrics.available_rooms == 300
    # 已售房必须等于两行明细合计二百一十间。
    assert metrics.rooms_sold == 210
    # 总收入先精确求和，再统一保留两位小数。
    assert metrics.room_revenue == Decimal("126001.05")
    # 汇总入住率为 70.0%。
    assert metrics.occupancy_rate == Decimal("70.0")
    # 汇总 ADR 的 600.005 按 HALF_UP 舍入为 600.01。
    assert metrics.adr == Decimal("600.01")
    # 汇总 RevPAR 的 420.0035 按两位小数显示为 420.00。
    assert metrics.revpar == Decimal("420.00")


def test_imported_csv_version_flows_directly_into_room_metrics(tmp_path: Path) -> None:
    """已导入并版本化的 CSV 日报可直接生成客房指标快照。

    Args:
        tmp_path: Pytest 为本测试提供的隔离临时目录。

    Returns:
        None.
    """

    # 创建真实本地数据工作空间并保存标准 PMS 字段映射。
    workspace = HotelDataWorkspace(tmp_path / "enterprise")
    workspace.save_mapping(
        "pms-daily",
        {
            "business_date": "营业日期",  # 映射 PMS 营业日表头。
            "available_rooms": "可售房",  # 映射可售房表头。
            "rooms_sold": "已售房",  # 映射已售房表头。
            "room_revenue": "客房收入",  # 映射客房收入表头。
        },
    )
    # 写入一份与首个权威指标样例一致的 CSV 日报。
    report_path = tmp_path / "pms-daily.csv"
    report_path.write_text(
        "营业日期,可售房,已售房,客房收入\n2026-07-13,200,150,90000\n",
        encoding="utf-8",
    )

    # 先通过公共数据接口完成字段标准化、归档和版本化。
    imported = workspace.import_report(report_path, "pms-daily")
    # 再把公共日报版本直接交给指标引擎，不读取任何内部数据库表。
    metrics = RoomMetricsCalculator.calculate(imported)

    # 端到端结果必须保留真实导入版本的编号和全部权威数字。
    assert (
        metrics.report_id,
        metrics.report_version,
        metrics.occupancy_rate,
        metrics.adr,
        metrics.revpar,
    ) == (
        imported.id,
        1,
        Decimal("75.0"),
        Decimal("600.00"),
        Decimal("450.00"),
    )


@pytest.mark.parametrize(
    ("second_available", "message"),
    [
        # 第二行负库存会被第一行较大正数抵消，但仍必须单独阻断。
        ("-1", "available_rooms 不能为负数: -1"),
        # 两行半间房可汇总为整数，但每条房型明细本身仍不合法。
        ("99.5", "available_rooms 必须是整数: 100.5"),
    ],
)
def test_invalid_detail_value_cannot_be_hidden_by_other_rows(
    second_available: str,
    message: str,
) -> None:
    """单条房型明细错误不能被其他行在汇总时抵消。

    Args:
        second_available: 第二条明细中的非法可售房值。
        message: 指标引擎应返回的数据质量错误。

    Returns:
        None.
    """

    # 第一条可售房让两行合计保持正数或整数，专门验证逐行校验。
    first_available = "201" if second_available == "-1" else "100.5"
    # 构造两个互不重复房型，其中第二行含非法明细值。
    report = _report(
        report_id="report_hidden_invalid",  # 固定逐行校验日报编号。
        operating_day=date(2026, 7, 18),  # 设置逐行校验营业日。
        records=[
            {
                "business_date": "2026-07-18",  # 第一房型营业日。
                "available_rooms": first_available,  # 正数或半间房抵消值。
                "rooms_sold": "75",  # 第一房型有效已售房。
                "room_revenue": "45000",  # 第一房型有效收入。
            },
            {
                "business_date": "2026-07-18",  # 第二房型使用同营业日。
                "available_rooms": second_available,  # 注入负数或半间房。
                "rooms_sold": "0",  # 第二房型已售房保持有效。
                "room_revenue": "0",  # 第二房型收入保持有效。
            },
        ],
    )

    # 即使汇总值表面合法，任一明细错误仍必须阻断计算。
    with pytest.raises(ValueError, match=message):
        RoomMetricsCalculator.calculate(report)
