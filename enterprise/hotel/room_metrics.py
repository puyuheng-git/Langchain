"""从已版本化 PMS 日报计算客房权威指标。"""

from __future__ import annotations  # 延迟类型解析，保持领域类型标注简洁。

from dataclasses import dataclass  # 用不可变对象返回稳定的指标快照。
from datetime import date  # 指标按 PMS 夜审后的营业日归属。
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation  # 处理精确计算和格式错误。

from .data_workspace import DailyReportVersion  # 指标必须追溯到已归档日报版本。

# 三个标准字段共同决定首版全部客房权威指标。
_REQUIRED_ROOM_FIELDS = ("available_rooms", "rooms_sold", "room_revenue")


@dataclass(frozen=True, slots=True)
class RoomMetricsSnapshot:
    """一份可追溯到营业日报版本的客房指标快照。

    Attributes:
        business_date: PMS 夜审确定的营业日。
        report_id: 来源日报的唯一编号。
        report_version: 来源日报在同营业日下的版本号。
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
    available_rooms: int  # 房量必须以完整客房间数表达。
    rooms_sold: int  # 已售房同样使用整数，避免产生半间房。
    occupancy_rate: Decimal  # Decimal 避免二进制浮点产生展示误差。
    room_revenue: Decimal  # 金额统一保留两位小数。
    adr: Decimal  # ADR 是本地权威计算结果，不由模型改写。
    revpar: Decimal  # RevPAR 与收入和可售房保持确定性关系。


class RoomMetricsCalculator:
    """根据标准化日报记录计算客房权威指标。"""

    @staticmethod
    def calculate(report: DailyReportVersion) -> RoomMetricsSnapshot:
        """计算来源日报对应的客房指标快照。

        Args:
            report: 已完成字段映射、归档和版本化的 PMS 日报。

        Returns:
            带来源编号和版本的客房指标快照。
        """

        # 在执行任何公式前检查字段完整性，避免向调用方泄漏 KeyError。
        _validate_required_fields(report)
        # 多行日报中的房型或业务明细互不重叠，因此分别求和。
        available_rooms = sum(
            _decimal_field(row, "available_rooms", index)
            for index, row in enumerate(report.records, start=1)
        )
        # 已售房与可售房使用同一聚合口径，确保入住率分子分母一致。
        rooms_sold = sum(
            _decimal_field(row, "rooms_sold", index)
            for index, row in enumerate(report.records, start=1)
        )
        # 收入先按 Decimal 汇总，再统一执行金额舍入。
        room_revenue = sum(
            _decimal_field(row, "room_revenue", index)
            for index, row in enumerate(report.records, start=1)
        )
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


def _decimal_field(row: dict[str, object], field: str, index: int) -> Decimal:
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
    if field in {"available_rooms", "rooms_sold"} and number != number.to_integral_value():
        raise ValueError(f"{field} 必须是整数: {number}")
    # 返回已经通过语法和有限性校验的十进制数字。
    return number


def _validate_totals(
    available_rooms: Decimal,
    rooms_sold: Decimal,
) -> None:
    """验证汇总后的房量和收入可安全进入权威公式。

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
