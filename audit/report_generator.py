#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
报告生成模块 (ReportGenerator)

职责：把「提取结果 + 风险清单」组装成审计人员可读的报告。

两种输出：
1. 终端展示：装了 Rich 就用彩色表格，没装就退回纯文本（与 main.py 同款优雅降级）
2. Markdown 底稿：保存到 data/reports/，作为审计底稿的雏形
   （领域术语见 CONTEXT.md「审计底稿」——审计结论必须留痕可复核）

为什么终端展示和 Markdown 分开两套逻辑？
- 终端是「给人当场看」的，讲究醒目（颜色/表格线）
- Markdown 是「存档 + 未来喂给可视化界面」的，讲究结构规范
- 未来做 Web 界面时（见问题 11 的决策），直接读 Markdown 或
  复用本模块的结构化数据即可，不用改上游管道
"""

# 导入 sys 用于修改模块搜索路径
import sys

# datetime 用于生成报告的时间戳和文件名
from datetime import datetime

# Path 用于路径处理
from pathlib import Path

# 把项目根目录加入搜索路径
sys.path.append(str(Path(__file__).parent.parent))

# 类型提示
from typing import Dict, Any, List, Optional

# 导入 Config 拿数据目录配置
from config import Config

# 复用提取器里的字段说明字典，作为报告里的「字段中文名」
# 这样字段定义只维护一份，报告与提取永远一致
from audit.extractor import EXTRACTION_FIELDS

# 尝试导入 Rich（可选依赖，与 main.py 相同的降级模式）
try:
    # Console 输出、Table 表格、Panel 面板
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel

    # Rich 可用标志
    USE_RICH = True
except ImportError:
    # 未安装 Rich 时退回纯文本输出
    USE_RICH = False


# ============================================
# 报告保存目录
# ============================================

# 审计报告统一保存在 data/reports/ 目录下
# Config.DATA_DIR 是项目的 data/ 目录
REPORTS_DIR = Config.DATA_DIR / "reports"

# 风险等级对应的 Rich 颜色（终端展示用）
LEVEL_COLORS = {"高": "red", "中": "yellow", "低": "green"}

# 风险等级对应的 emoji（纯文本和 Markdown 都可用）
LEVEL_ICONS = {"高": "🔴", "中": "🟡", "低": "🟢"}


class ReportGenerator:
    """
    审计报告生成器：提取结果 + 风险清单 → 终端展示 + Markdown 底稿

    使用示例:
        gen = ReportGenerator()
        # 终端展示
        gen.display(contract_info, extraction, risk_result)
        # 保存 Markdown
        path = gen.save_markdown(contract_info, extraction, risk_result)
    """

    def __init__(self):
        """
        初始化报告生成器

        创建 Rich Console（如果可用），供后续输出使用。
        """
        # Rich 可用就创建 Console 实例，否则为 None
        self.console = Console() if USE_RICH else None

    # ----------------------------------------
    # 终端展示
    # ----------------------------------------

    def display(
        self,
        contract_info: Dict[str, Any],
        extraction: Dict[str, Any],
        risk_result: Dict[str, Any],
    ) -> None:
        """
        在终端展示完整的审阅报告

        Args:
            contract_info: ContractParser.parse() 的结果
            extraction: ContractExtractor.extract() 的结果
            risk_result: RiskAnalyzer.analyze() 的结果
        """
        print("\n📄 步骤 4/4: 生成审阅报告")

        # ----- 第一部分: 报告头 -----
        # 拼出概要信息：文件名、页数、字数、是否截断
        header = (
            f"合同文件: {contract_info['file_name']}\n"
            f"页数: {contract_info['page_count']} | "
            f"字符数: {contract_info['char_count']}"
        )
        # 如果发生截断，加醒目提示（审计场景必须知道「看的不是全文」）
        if contract_info["truncated"]:
            header += "\n⚠ 注意: 合同过长已截断，以下分析仅覆盖前部分内容"

        # Rich 可用就用面板展示，否则纯文本
        if USE_RICH:
            self.console.print(Panel(header, title="📑 合同审阅报告", border_style="blue"))
        else:
            print("\n===== 📑 合同审阅报告 =====")
            print(header)

        # ----- 第二部分: 关键字段表 -----
        self._display_fields(extraction)

        # ----- 第三部分: 风险清单 -----
        self._display_risks(risk_result)

    def _display_fields(self, extraction: Dict[str, Any]) -> None:
        """
        展示关键字段表格

        Args:
            extraction: ContractExtractor.extract() 的结果
        """
        # 提取失败时给出提示并返回
        if not extraction["success"]:
            print(f"\n⚠ 关键字段提取失败: {extraction['error']}")
            return

        # 拿到字段字典
        fields = extraction["fields"]

        if USE_RICH:
            # 用 Rich Table 画表格
            table = Table(title="📋 关键要素", show_lines=False)
            # 两列：要素名 / 内容
            table.add_column("要素", style="cyan", no_wrap=True)
            table.add_column("内容", style="white")

            # 按 EXTRACTION_FIELDS 定义的顺序逐行填入
            for key, label in EXTRACTION_FIELDS.items():
                # 取字段值；None 显示为「—（未约定/未提取到）」
                value = fields.get(key)
                display_value = str(value) if value is not None else "—"
                # label 是「甲方（全称）」这种说明，取括号前的主干更简洁
                # split("（") 按全角括号切开取第一段
                short_label = label.split("（")[0]
                table.add_row(short_label, display_value)

            # 输出表格
            self.console.print(table)
        else:
            # 纯文本表格：对齐靠固定宽度
            print("\n----- 📋 关键要素 -----")
            for key, label in EXTRACTION_FIELDS.items():
                value = fields.get(key)
                display_value = str(value) if value is not None else "—"
                short_label = label.split("（")[0]
                # :<12 左对齐占 12 格，让冒号大致对齐
                print(f"  {short_label:<12}: {display_value}")

    def _display_risks(self, risk_result: Dict[str, Any]) -> None:
        """
        展示风险清单

        Args:
            risk_result: RiskAnalyzer.analyze() 的结果
        """
        # 风险识别失败时提示并返回
        if not risk_result["success"]:
            print(f"\n⚠ 风险识别失败: {risk_result['error']}")
            return

        # 拿到风险列表
        risks = risk_result["risks"]

        # 没有风险时也要明确说出来（审计报告的「无保留意见」）
        if not risks:
            print("\n✅ 未识别出明显风险条款")
            return

        if USE_RICH:
            # 用 Rich Table 展示风险清单
            table = Table(title=f"⚠️ 风险清单（共 {len(risks)} 条）", show_lines=True)
            table.add_column("等级", no_wrap=True)
            table.add_column("涉及条款", max_width=30)
            table.add_column("风险分析", max_width=40)
            table.add_column("审计建议", max_width=30)

            # 逐条添加，等级列用对应颜色渲染
            for risk in risks:
                # 用 Rich 标记语法给等级上色：[red]高[/red]
                color = LEVEL_COLORS[risk["level"]]
                level_text = f"[{color}]{risk['level']}[/{color}]"
                table.add_row(level_text, risk["clause"], risk["reason"], risk["suggestion"])

            self.console.print(table)
        else:
            # 纯文本模式：逐条打印
            print(f"\n----- ⚠️ 风险清单（共 {len(risks)} 条）-----")
            for i, risk in enumerate(risks, start=1):
                # 等级前加 emoji 圆点区分
                icon = LEVEL_ICONS[risk["level"]]
                print(f"\n  {i}. {icon} [{risk['level']}] {risk['clause']}")
                print(f"     分析: {risk['reason']}")
                print(f"     建议: {risk['suggestion']}")

    # ----------------------------------------
    # Markdown 底稿
    # ----------------------------------------

    def save_markdown(
        self,
        contract_info: Dict[str, Any],
        extraction: Dict[str, Any],
        risk_result: Dict[str, Any],
        filepath: Optional[str] = None,
    ) -> Path:
        """
        把审阅报告保存为 Markdown 底稿

        Args:
            contract_info: ContractParser.parse() 的结果
            extraction: ContractExtractor.extract() 的结果
            risk_result: RiskAnalyzer.analyze() 的结果
            filepath: 保存路径（可选），默认自动命名到 data/reports/

        Returns:
            实际保存的文件路径（Path 对象）
        """
        # 确保报告目录存在
        # parents=True 连父目录一起创建，exist_ok=True 已存在不报错
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)

        # 没有指定路径时自动命名：review_合同名_时间戳.md
        if filepath is None:
            # Path().stem 取合同文件名（去扩展名）
            stem = Path(contract_info["file_name"]).stem
            # strftime 格式化当前时间为「20260710_153000」形式
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = REPORTS_DIR / f"review_{stem}_{timestamp}.md"
        else:
            # 用户给了路径就直接用
            filepath = Path(filepath)

        # ----- 拼装 Markdown 内容 -----
        # 用列表收集每一行，最后 join，比字符串拼接高效且清晰
        lines: List[str] = []

        # 标题和元信息
        lines.append(f"# 合同审阅报告：{contract_info['file_name']}")
        lines.append("")
        lines.append(f"- 审阅时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"- 页数: {contract_info['page_count']}")
        lines.append(f"- 字符数: {contract_info['char_count']}")
        # 截断提示写进底稿（可追溯性要求）
        if contract_info["truncated"]:
            lines.append("- ⚠ **注意: 合同过长已截断，本报告仅覆盖前部分内容**")
        lines.append("")

        # 关键要素表（Markdown 表格语法）
        lines.append("## 一、关键要素")
        lines.append("")
        if extraction["success"]:
            # 表头行和分隔行是 Markdown 表格的固定语法
            lines.append("| 要素 | 内容 |")
            lines.append("|------|------|")
            for key, label in EXTRACTION_FIELDS.items():
                value = extraction["fields"].get(key)
                display_value = str(value) if value is not None else "—"
                # 表格单元格里的竖线会破坏表格，替换成全角
                display_value = display_value.replace("|", "｜")
                short_label = label.split("（")[0]
                lines.append(f"| {short_label} | {display_value} |")
        else:
            lines.append(f"> 提取失败: {extraction['error']}")
        lines.append("")

        # 风险清单
        lines.append("## 二、风险清单")
        lines.append("")
        if not risk_result["success"]:
            lines.append(f"> 风险识别失败: {risk_result['error']}")
        elif not risk_result["risks"]:
            lines.append("未识别出明显风险条款。")
        else:
            # 每条风险一个小节，结构对应审计底稿「发现→依据→建议」
            for i, risk in enumerate(risk_result["risks"], start=1):
                icon = LEVEL_ICONS[risk["level"]]
                lines.append(f"### {i}. {icon} [{risk['level']}] {risk['clause']}")
                lines.append("")
                lines.append(f"- **风险分析**: {risk['reason']}")
                lines.append(f"- **审计建议**: {risk['suggestion']}")
                lines.append("")

        # 落款说明（AI 辅助的免责与定位：辅助工具，结论需人工复核）
        lines.append("---")
        lines.append("")
        lines.append("> 本报告由 AI 辅助生成，供审计参考，最终结论以审计师人工复核为准。")
        lines.append("")

        # 写入文件（UTF-8 编码保证中文正常）
        filepath.write_text("\n".join(lines), encoding="utf-8")

        # 告知用户保存位置
        print(f"\n💾 审阅底稿已保存: {filepath}")

        return filepath


    # ----------------------------------------
    # 批量审阅汇总
    # ----------------------------------------

    def display_batch_summary(self, batch_results: List[Dict[str, Any]]) -> None:
        """
        在终端展示批量审阅的汇总表

        Args:
            batch_results: 多份合同的审阅结果列表，
                          每个元素是 ContractReviewPipeline.review() 的返回值
        """
        # 统计整体情况：总数、成功数
        total = len(batch_results)
        # 生成器 + sum：解析成功的合同数
        ok = sum(1 for r in batch_results if r["success"])

        # 汇总头信息
        header = f"共审阅 {total} 份合同，成功 {ok} 份，失败 {total - ok} 份"

        if USE_RICH:
            self.console.print(Panel(header, title="📊 批量审阅汇总", border_style="blue"))

            # 汇总表：每份合同一行，展示风险统计
            table = Table(title="各合同风险概览", show_lines=False)
            table.add_column("合同", style="cyan", max_width=30)
            table.add_column("高", justify="center")
            table.add_column("中", justify="center")
            table.add_column("低", justify="center")
            table.add_column("状态", no_wrap=True)

            # 逐份合同统计各等级风险数量
            for r in batch_results:
                if not r["success"]:
                    # 解析失败的合同：风险列显示 —，状态标红
                    table.add_row(
                        r.get("file_name", "未知"), "—", "—", "—",
                        "[red]失败[/red]"
                    )
                    continue

                # 从风险结果里数出各等级条数
                risks = r["risks"]["risks"] if r["risks"]["success"] else []
                high = sum(1 for x in risks if x["level"] == "高")
                mid = sum(1 for x in risks if x["level"] == "中")
                low = sum(1 for x in risks if x["level"] == "低")

                # 有高风险的合同状态标红提示，否则绿色通过
                status = "[red]需关注[/red]" if high > 0 else "[green]正常[/green]"
                table.add_row(
                    r["contract"]["file_name"],
                    # 高风险数量用红色渲染更醒目（0 就普通显示）
                    f"[red]{high}[/red]" if high else "0",
                    str(mid), str(low), status,
                )

            self.console.print(table)
        else:
            # 纯文本模式的汇总
            print(f"\n===== 📊 批量审阅汇总 =====")
            print(header)
            for r in batch_results:
                if not r["success"]:
                    print(f"  ✗ {r.get('file_name', '未知')}: 审阅失败")
                    continue
                risks = r["risks"]["risks"] if r["risks"]["success"] else []
                high = sum(1 for x in risks if x["level"] == "高")
                mid = sum(1 for x in risks if x["level"] == "中")
                low = sum(1 for x in risks if x["level"] == "低")
                mark = "⚠" if high > 0 else "✓"
                print(f"  {mark} {r['contract']['file_name']}: "
                      f"高 {high} / 中 {mid} / 低 {low}")

    def save_batch_markdown(
        self,
        batch_results: List[Dict[str, Any]],
        dir_name: str,
        filepath: Optional[str] = None,
    ) -> Path:
        """
        把批量审阅汇总保存为 Markdown

        汇总报告包含两部分：
        1. 总览表：每份合同的风险统计（对应审计的「项目风险热图」思路）
        2. 高风险摘录：把所有合同的高风险条款集中列出，方便优先处理

        Args:
            batch_results: 多份合同的审阅结果列表
            dir_name: 被审阅的目录名（用于报告标题和文件命名）
            filepath: 保存路径（可选），默认自动命名到 data/reports/

        Returns:
            实际保存的文件路径
        """
        # 确保报告目录存在
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)

        # 自动命名：batch_目录名_时间戳.md
        if filepath is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            # Path().name 取目录的最后一段作为名字
            safe_name = Path(dir_name).name or "contracts"
            filepath = REPORTS_DIR / f"batch_{safe_name}_{timestamp}.md"
        else:
            filepath = Path(filepath)

        # 收集 Markdown 行
        lines: List[str] = []

        # 标题和元信息
        total = len(batch_results)
        ok = sum(1 for r in batch_results if r["success"])
        lines.append(f"# 批量合同审阅汇总：{Path(dir_name).name}")
        lines.append("")
        lines.append(f"- 审阅时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"- 合同总数: {total}（成功 {ok} / 失败 {total - ok}）")
        lines.append("")

        # ----- 第一部分: 总览表 -----
        lines.append("## 一、风险总览")
        lines.append("")
        lines.append("| 合同 | 高风险 | 中风险 | 低风险 | 单份底稿 |")
        lines.append("|------|--------|--------|--------|----------|")

        for r in batch_results:
            if not r["success"]:
                # 失败的合同也要记录（审计留痕：哪些没审到）
                lines.append(f"| {r.get('file_name', '未知')} | — | — | — | 审阅失败 |")
                continue

            risks = r["risks"]["risks"] if r["risks"]["success"] else []
            high = sum(1 for x in risks if x["level"] == "高")
            mid = sum(1 for x in risks if x["level"] == "中")
            low = sum(1 for x in risks if x["level"] == "低")
            # 单份底稿的文件名（有保存时），方便交叉查阅
            report_name = r["report_path"].name if r["report_path"] else "—"
            lines.append(
                f"| {r['contract']['file_name']} | {high} | {mid} | {low} | {report_name} |"
            )
        lines.append("")

        # ----- 第二部分: 高风险摘录 -----
        lines.append("## 二、高风险条款摘录（跨合同汇总）")
        lines.append("")

        # 收集所有合同的高风险条目
        has_high = False
        for r in batch_results:
            # 跳过失败的和没有风险结果的
            if not r["success"] or not r["risks"]["success"]:
                continue
            # 过滤出该合同的高风险条目
            highs = [x for x in r["risks"]["risks"] if x["level"] == "高"]
            if not highs:
                continue

            has_high = True
            # 以合同名为小节标题
            lines.append(f"### {r['contract']['file_name']}")
            lines.append("")
            for risk in highs:
                lines.append(f"- 🔴 **{risk['clause']}**")
                lines.append(f"  - 风险分析: {risk['reason']}")
                lines.append(f"  - 审计建议: {risk['suggestion']}")
            lines.append("")

        # 一条高风险都没有时也要写明（「无保留意见」）
        if not has_high:
            lines.append("所有合同均未发现高风险条款。")
            lines.append("")

        # 落款
        lines.append("---")
        lines.append("")
        lines.append("> 本汇总由 AI 辅助生成，供审计参考，最终结论以审计师人工复核为准。")
        lines.append("")

        # 写入文件
        filepath.write_text("\n".join(lines), encoding="utf-8")
        print(f"\n💾 批量汇总已保存: {filepath}")

        return filepath


# ============================================
# 测试代码（直接运行本文件时执行）
# ============================================

if __name__ == "__main__":
    print("=" * 50)
    print("测试 ReportGenerator 模块")
    print("=" * 50)

    # 构造模拟数据（不调用 LLM，纯测试格式化逻辑）
    mock_contract = {
        "file_name": "测试购销合同.pdf",
        "full_text": "……",
        "page_count": 5,
        "char_count": 4200,
        "truncated": False,
    }
    mock_extraction = {
        "success": True,
        "error": None,
        "fields": {
            "contract_name": "购销合同",
            "party_a": "北京某某科技有限公司",
            "party_b": "上海某某贸易有限公司",
            "other_parties": None,
            "subject_matter": "办公用服务器 50 台",
            "contract_value": "人民币 100 万元整",
            "payment_terms": "货到后甲方适时付款",
            "term_start": "2026-01-01",
            "term_end": "2026-12-31",
            "liquidated_damages": "乙方违约支付合同金额 30% 违约金",
            "jurisdiction": None,
            "sign_date": "2025-12-20",
        },
    }
    mock_risks = {
        "success": True,
        "error": None,
        "risks": [
            {
                "level": "高",
                "clause": "乙方违约应支付合同金额 30% 的违约金",
                "reason": "违约金比例明显偏高，且仅约束乙方，权利义务不对等",
                "suggestion": "核实定价依据，建议改为双向且不超过实际损失的合理比例",
            },
            {
                "level": "中",
                "clause": "货到后甲方适时付款",
                "reason": "「适时」无明确期限，付款义务模糊，易引发争议",
                "suggestion": "建议明确为「货到验收合格后 X 日内付款」",
            },
        ],
    }

    # 测试终端展示
    gen = ReportGenerator()
    gen.display(mock_contract, mock_extraction, mock_risks)

    # 测试 Markdown 保存
    path = gen.save_markdown(mock_contract, mock_extraction, mock_risks)

    # 验证文件确实生成了
    print(f"\n文件存在: {path.exists()}")
    print("\n✓ 测试完成!")
