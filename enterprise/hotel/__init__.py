"""酒店负责人个人经营治理的公共接口。"""

from .dashboard import (  # 导出驾驶舱服务、快照和强类型上传命令。
    HotelDashboardService,  # 协调页面上传、模板恢复与快照读取。
    HotelDashboardSnapshot,  # 表达日报版本和客房指标的页面组合结果。
    HotelReportUpload,  # 绑定一次浏览器上传所需的文件、映射和模板。
    PmsFieldMapping,  # 表达可保存并恢复的 PMS 来源表头配置。
)
from .data_workspace import DailyReportVersion, HotelDataWorkspace  # 导出日报公共接口。
from .room_metrics import RoomMetricsCalculator, RoomMetricsSnapshot  # 导出指标公共接口。

# 限定星号导入范围，避免内部迁移和标准化对象变成公共 API。
__all__ = [
    "DailyReportVersion",  # 允许调用方把已导入日报交给指标引擎。
    "HotelDashboardService",  # 暴露上传与恢复驾驶舱快照的应用服务。
    "HotelDashboardSnapshot",  # 暴露页面所需的组合结果类型。
    "HotelReportUpload",  # 暴露绑定文件、模板和映射的上传命令。
    "HotelDataWorkspace",  # 保留日报导入与版本读取入口。
    "RoomMetricsCalculator",  # 暴露确定性客房指标计算入口。
    "RoomMetricsSnapshot",  # 暴露可追溯指标结果类型。
    "PmsFieldMapping",  # 暴露页面可保存和恢复的 PMS 表头配置。
]
