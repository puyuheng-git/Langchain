"""从已版本化 PMS 日报计算客房权威指标。"""

from __future__ import annotations  # 延迟类型解析，保持领域类型标注简洁。

from dataclasses import dataclass  # 用不可变对象返回稳定的指标快照。
from datetime import date  # 指标按 PMS 夜审后的营业日归属。
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation  # 处理精确计算和格式错误。
from enum import StrEnum  # 用字符串枚举集中约束三个权威来源字段。

from .data_workspace import DailyReportVersion  # 指标必须追溯到已归档日报版本。


class _RoomMetricField(StrEnum):
    """客房权威指标依赖的标准化日报字段。

    该内部枚举没有初始化参数；成员值可直接作为日报字典键，并由计算器返回指标结果。
    """

    AVAILABLE_ROOMS = "available_rooms"  # 当日可以出售的完整客房间数。
    ROOMS_SOLD = "rooms_sold"  # 当日已经售出的完整客房间数。
    ROOM_REVENUE = "room_revenue"  # 当日归属的客房收入。


# 三个枚举成员共同决定首版全部客房权威指标。
_REQUIRED_ROOM_FIELDS = tuple(_RoomMetricField)
# 两类房量字段必须逐条保持完整间数，收入字段可以包含小数。
_ROOM_COUNT_FIELDS = {_RoomMetricField.AVAILABLE_ROOMS, _RoomMetricField.ROOMS_SOLD}
# 口径版本独立于日报版本，公式或舍入规则改变时必须递增。
_ROOM_METRICS_DEFINITION_VERSION = "1.0"
# 中英文汇总标记用于识别“客房汇总”“Subtotal”等带前后缀标签。
_TOTAL_SEGMENT_MARKERS = ("合计", "总计", "小计", "汇总", "total", "subtotal", "summary")


# dataclass 自动生成不可变结果对象的初始化和比较方法，减少样板代码。
@dataclass(frozen=True, slots=True)
class RoomMetricsSnapshot:
    """一份可追溯到营业日报版本的客房指标快照。

    Attributes:
        business_date: PMS 夜审确定的营业日。
        report_id: 来源日报的唯一编号。
        report_version: 来源日报在同营业日下的版本号。
        definition_version: 本快照使用的指标公式与舍入口径版本。
        available_rooms: 当日可售房合计。
        rooms_sold: 当日已售房合计。
        occupancy_rate: 入住率百分比，保留一位小数。
        room_revenue: 客房收入，保留两位小数。
        adr: 平均房价，保留两位小数。
        revpar: 每间可售房收入，保留两位小数。
    """

    business_date: date  # 保持经营指标和来源日报使用同一时间主键。
    report_id: str  # 保存来源编号，支持下钻到归档原件。
    report_version: int  # 保存来源版本，避免修订后无法解释旧指标。
    definition_version: str  # 与日报版本分离，说明计算规则自身版本。
    available_rooms: int  # 房量必须以完整客房间数表达。
    rooms_sold: int  # 已售房同样使用整数，避免产生半间房。
    occupancy_rate: Decimal  # Decimal 避免二进制浮点产生展示误差。
    room_revenue: Decimal  # 金额统一保留两位小数。
    adr: Decimal  # ADR 是本地权威计算结果，不由模型改写。
    revpar: Decimal  # RevPAR 与收入和可售房保持确定性关系。


class RoomMetricsCalculator:
    """根据标准化日报记录计算客房权威指标。

    该类没有初始化参数；调用方直接使用静态 ``calculate`` 方法，并得到
    :class:`RoomMetricsSnapshot` 作为可追溯的计算结果。
    """

    # staticmethod 表示计算不依赖实例状态，调用方无需先创建计算器对象。
    @staticmethod
    def calculate(report: DailyReportVersion) -> RoomMetricsSnapshot:
        """计算来源日报对应的客房指标快照。

        Args:
            report: 已完成字段映射、归档和版本化的 PMS 日报。

        Returns:
            带来源编号和版本的客房指标快照。
        """

        # 多行输入先证明库存分段唯一且不含合计行，防止重复累计。
        _validate_inventory_segments(report)
        # 在执行任何公式前检查字段完整性，避免向调用方泄漏 KeyError。
        _validate_required_fields(report)
        # 多行日报中的房型或业务明细互不重叠，因此分别求和。
        available_rooms = _sum_field(report, _RoomMetricField.AVAILABLE_ROOMS)
        # 已售房与可售房使用同一聚合口径，确保入住率分子分母一致。
        rooms_sold = _sum_field(report, _RoomMetricField.ROOMS_SOLD)
        # 收入先按 Decimal 汇总，再统一执行金额舍入。
        room_revenue = _sum_field(report, _RoomMetricField.ROOM_REVENUE)
        # 在除法和舍入前验证聚合结果，避免生成误导性权威指标。
        _validate_totals(available_rooms, rooms_sold)
        # 入住率以百分比展示，并按酒店常用口径保留一位小数。
        occupancy_rate = (rooms_sold / available_rooms * Decimal("100")).quantize(
            Decimal("0.1"),
            rounding=ROUND_HALF_UP,
        )
        # 零售房时产品口径把 ADR 定义为零，避免产生除零异常。
        adr = (
            (room_revenue / rooms_sold).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )
            if rooms_sold
            else Decimal("0.00")
        )
        # RevPAR 使用客房收入除以可售房，金额保留两位小数。
        revpar = (room_revenue / available_rooms).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )
        # 返回不可变快照，防止页面展示时意外修改权威数字。
        return RoomMetricsSnapshot(
            business_date=report.business_date,  # 沿用来源日报营业日。
            report_id=report.id,  # 关联到具体归档报告。
            report_version=report.version,  # 关联到具体修订版本。
            definition_version=_ROOM_METRICS_DEFINITION_VERSION,  # 声明公式口径版本。
            available_rooms=int(available_rooms),  # 房量转换为整数输出。
            rooms_sold=int(rooms_sold),  # 已售房转换为整数输出。
            occupancy_rate=occupancy_rate,  # 保存已按口径舍入的入住率。
            room_revenue=room_revenue.quantize(  # 保存两位小数收入。
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            ),
            adr=adr,  # 保存确定性 ADR。
            revpar=revpar,  # 保存确定性 RevPAR。
        )


def _validate_required_fields(report: DailyReportVersion) -> None:
    """确认每条日报记录都包含客房指标需要的标准字段。

    Args:
        report: 已完成标准化的 PMS 日报版本。

    Returns:
        None.

    Raises:
        ValueError: 任一记录缺少权威指标字段时抛出。
    """

    # 从一开始编号，使错误与负责人看到的记录顺序一致。
    for index, row in enumerate(report.records, start=1):
        # 保持标准字段顺序，让错误文本和模板顺序稳定。
        missing = [field for field in _REQUIRED_ROOM_FIELDS if field not in row]
        # 一次列出当前记录全部缺失项，减少负责人反复修复导入。
        if missing:
            raise ValueError(f"第{index}条记录缺少字段: {', '.join(missing)}")


def _validate_inventory_segments(report: DailyReportVersion) -> None:
    """确认多行日报由唯一、非合计的库存分段组成。

    Args:
        report: 可能包含多个房型或库存分段的 PMS 日报版本。

    Returns:
        None.

    Raises:
        ValueError: 多行记录缺少分段、分段重复或包含合计标签时抛出。
    """

    # 单行日报没有重复累计可能，因此不强制额外库存分段字段。
    if len(report.records) <= 1:
        return
    # 保存已经出现的分段名称，用于发现同一库存被重复列出。
    seen: set[str] = set()
    # 从一开始编号，错误信息与负责人看到的明细顺序一致。
    for index, row in enumerate(report.records, start=1):
        # 缺失或只有空白的分段都无法证明该行与其他行互不重叠。
        segment = str(row.get("room_inventory_segment", "")).strip()
        if not segment:
            raise ValueError(f"多行日报第{index}条记录缺少 room_inventory_segment")
        # 压缩英文标签中的重复空格，并统一大小写后检查汇总标记。
        normalized_segment = " ".join(segment.casefold().split())
        # 含汇总标记的中英文标签必须在进入权威计算前被拒绝。
        if any(marker in normalized_segment for marker in _TOTAL_SEGMENT_MARKERS):
            raise ValueError(f"多行日报不能包含合计行: {segment}")
        # 同名分段说明至少有两行可能表达同一批可售房。
        if segment in seen:
            raise ValueError(f"room_inventory_segment 不能重复: {segment}")
        # 当前分段验证通过后加入集合，供后续明细比较。
        seen.add(segment)


def _sum_field(report: DailyReportVersion, field: _RoomMetricField) -> Decimal:
    """按指定权威字段汇总日报中的全部互斥明细。

    Args:
        report: 已通过库存分段检查的 PMS 日报版本。
        field: 需要汇总的标准化客房字段。

    Returns:
        全部明细转换并相加后的十进制合计。
    """

    # 每一行先独立校验再相加，错误值不能被其他明细抵消。
    return sum(
        _decimal_field(row, field, index)
        for index, row in enumerate(report.records, start=1)
    )


def _decimal_field(
    row: dict[str, object],
    field: _RoomMetricField,
    index: int,
) -> Decimal:
    """把一条标准化记录中的指定字段转换为 Decimal。

    Args:
        row: 一条已经完成字段映射的日报记录。
        field: 需要转换的标准字段名称。
        index: 从一开始的记录编号，用于生成清晰错误。

    Returns:
        可参与权威计算的十进制数字。

    Raises:
        ValueError: 来源值不能转换为有效数字时抛出。
    """

    # 保留原值用于错误提示，帮助负责人回到日报定位问题。
    value = row[field]
    # 通过字符串转换兼容 CSV 文本、Excel 整数和小数单元格。
    try:
        number = Decimal(str(value).strip())
    # Decimal 使用 InvalidOperation 表达无法解析的数字文本。
    except InvalidOperation as exc:
        raise ValueError(f"第{index}条记录字段 {field} 不是有效数字: {value}") from exc
    # NaN 和无穷值虽然可解析，但不能参与可靠比较、除法或舍入。
    if not number.is_finite():
        raise ValueError(f"第{index}条记录字段 {field} 不是有限数字: {value}")
    # 任一明细负数都必须先核验，不能在汇总时被其他正数抵消。
    if number < 0:
        raise ValueError(f"{field} 不能为负数: {number}")
    # 两类房量字段必须逐行保持完整间数，不能靠汇总抵消小数。
    if field in _ROOM_COUNT_FIELDS and number != number.to_integral_value():
        raise ValueError(f"{field} 必须是整数: {number}")
    # 返回已经通过语法和有限性校验的十进制数字。
    return number


def _validate_totals(
    available_rooms: Decimal,
    rooms_sold: Decimal,
) -> None:
    """验证汇总后的可售房与已售房关系可安全进入权威公式。

    Args:
        available_rooms: 全部明细汇总后的可售房。
        rooms_sold: 全部明细汇总后的已售房。

    Returns:
        None.

    Raises:
        ValueError: 可售房为零或已售房超过库存时抛出。
    """

    # 在营酒店可售房必须提供正数，否则入住率和 RevPAR 没有有效分母。
    if available_rooms == 0:
        raise ValueError("可售房必须大于零")
    # 首版严格阻断超过库存的售房量，避免静默展示超过百分之百入住率。
    if rooms_sold > available_rooms:
        raise ValueError(f"已售房不能超过可售房: {rooms_sold} > {available_rooms}")
