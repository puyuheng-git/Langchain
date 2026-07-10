#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
合同审阅管道 (ContractReviewPipeline)

职责：把 audit 包的四个组件串成一条「确定性管道」（见 docs/adr/0001）：

    ① ContractParser    加载合同 → 全文
    ② ContractExtractor 全文 → 关键字段
    ③ RiskAnalyzer      全文 + 字段 → 风险清单
    ④ ReportGenerator   字段 + 风险 → 终端报告 + Markdown 底稿

为什么叫「确定性管道」？
- 步骤固定、顺序固定，每次执行的流程完全一样
- 与 /agent 的区别：Agent 每次自己「想」下一步做什么，
  而审计流程要求可预测、可追溯，不允许「自由发挥」

对外只暴露一个方法 review()，main.py 调它即可。
"""

# 导入 sys 用于修改模块搜索路径
import sys

# Path 用于路径处理
from pathlib import Path

# 把项目根目录加入搜索路径
sys.path.append(str(Path(__file__).parent.parent))

# 类型提示
from typing import Dict, Any

# 导入管道的四个组件（同包内用相对导入）
from .contract_parser import ContractParser
from .extractor import ContractExtractor
from .risk_analyzer import RiskAnalyzer
from .report_generator import ReportGenerator


class ContractReviewPipeline:
    """
    合同审阅管道：一个方法完成「加载→提取→分析→报告」全流程

    使用示例:
        pipeline = ContractReviewPipeline()
        result = pipeline.review("购销合同.pdf")
        if result["success"]:
            print(f"报告已保存: {result['report_path']}")
    """

    def __init__(self):
        """
        初始化管道：创建四个组件实例

        组件都是无状态的（每次调用新建 LLM 会话），
        所以管道可以复用，审多份合同不用重建。
        """
        # ① 合同解析器
        self.parser = ContractParser()
        # ② 结构化提取器
        self.extractor = ContractExtractor()
        # ③ 风险识别器
        self.analyzer = RiskAnalyzer()
        # ④ 报告生成器
        self.reporter = ReportGenerator()

    def review(self, file_path: str, save_report: bool = True) -> Dict[str, Any]:
        """
        审阅一份合同（完整管道）

        Args:
            file_path: 合同文件路径（支持 PDF/TXT/MD）
            save_report: 是否保存 Markdown 底稿（默认保存）

        Returns:
            字典，包含：
            - success: 整体是否成功（解析失败为 False；
                       提取/风险某一步失败仍算部分成功，报告会注明）
            - contract: 合同基本信息（解析结果）
            - extraction: 提取结果
            - risks: 风险识别结果
            - report_path: 底稿路径（save_report=False 时为 None）
            - error: 致命错误信息（成功时为 None）
        """
        print(f"\n{'=' * 50}")
        print(f"合同审阅: {Path(file_path).name}")
        print(f"{'=' * 50}")

        # ----- 步骤 ①: 解析合同 -----
        print("\n📂 步骤 1/4: 加载合同文件...")
        try:
            # 解析失败（文件不存在/格式不支持）是致命错误，直接返回
            contract_info = self.parser.parse(file_path)
            print(
                f"   ✓ 加载完成: {contract_info['page_count']} 页 / "
                f"{contract_info['char_count']} 字符"
            )
        except (FileNotFoundError, ValueError) as e:
            # 明确的用户输入错误，给出友好提示
            print(f"   ✗ 加载失败: {str(e)}")
            return {
                "success": False,
                # 文件名单独放一份，批量汇总时失败的合同也能显示名字
                "file_name": Path(file_path).name,
                "contract": None,
                "extraction": None,
                "risks": None,
                "report_path": None,
                "error": str(e),
            }

        # ----- 步骤 ②: 结构化提取 -----
        # extract() 内部已做优雅降级，失败也会返回结构一致的结果
        extraction = self.extractor.extract(contract_info["full_text"])

        # ----- 步骤 ③: 风险识别 -----
        # 把全文和已提取字段都给分析器（字段是地图，全文是地形）
        risk_result = self.analyzer.analyze(
            contract_info["full_text"], extraction["fields"]
        )

        # ----- 步骤 ④: 生成报告 -----
        # 终端展示（提取/风险失败时报告里会注明失败原因）
        self.reporter.display(contract_info, extraction, risk_result)

        # 按需保存 Markdown 底稿
        report_path = None
        if save_report:
            report_path = self.reporter.save_markdown(
                contract_info, extraction, risk_result
            )

        # 返回完整结果（success 表示管道走完了，
        # 各步骤自身的成败看各自的 success 字段）
        return {
            "success": True,
            # 文件名单独放一份，方便批量汇总直接读取
            "file_name": contract_info["file_name"],
            "contract": contract_info,
            "extraction": extraction,
            "risks": risk_result,
            "report_path": report_path,
            "error": None,
        }

    def review_batch(
        self, dir_path: str, recursive: bool = False, save_report: bool = True
    ) -> Dict[str, Any]:
        """
        批量审阅一个目录下的所有合同

        工作方式：
        1. 扫描目录，找出所有支持的文件（PDF/TXT/MD）
        2. 逐份调用 review()（单份审是批量审的原子单元）
        3. 生成汇总：各合同风险统计表 + 跨合同高风险摘录

        单份合同失败不会中断整批（审计场景：一份坏文件
        不该让其他 99 份白审），失败信息会记录进汇总。

        Args:
            dir_path: 合同目录路径
            recursive: 是否递归扫描子目录（默认 False，只看当前层）
            save_report: 是否保存单份底稿和批量汇总（默认保存）

        Returns:
            字典，包含：
            - success: 是否找到了可审的文件并完成了批处理
            - results: 每份合同的审阅结果列表（review() 的返回值）
            - summary_path: 批量汇总 Markdown 的路径（不保存时为 None）
            - error: 致命错误信息（成功时为 None）
        """
        # 清理路径引号并转 Path 对象
        dir_path = dir_path.strip('"').strip("'")
        path = Path(dir_path)

        # 目录不存在或不是目录，直接返回错误
        if not path.is_dir():
            error = f"目录不存在或不是目录: {dir_path}"
            print(f"✗ {error}")
            return {"success": False, "results": [], "summary_path": None, "error": error}

        # ----- 扫描支持的合同文件 -----
        # 支持的扩展名与 DocumentLoader 保持一致（单一事实来源）
        extensions = self.parser.loader.SUPPORTED_EXTENSIONS.keys()

        # 收集所有匹配的文件
        files = []
        for ext in extensions:
            if recursive:
                # rglob 递归匹配任意深度的子目录
                files.extend(path.rglob(f"*{ext}"))
            else:
                # glob 只匹配当前目录
                files.extend(path.glob(f"*{ext}"))

        # 去重（同一文件可能被多个模式匹配到）并按文件名排序
        # sorted 保证审阅顺序稳定（每次跑结果顺序一致，审计可复现）
        files = sorted(set(files))

        # 目录里没有可审的文件
        if not files:
            error = f"目录中没有支持的合同文件（PDF/TXT/MD）: {dir_path}"
            print(f"⚠ {error}")
            return {"success": False, "results": [], "summary_path": None, "error": error}

        print(f"\n{'#' * 50}")
        print(f"批量审阅: {path.name}（共 {len(files)} 份合同）")
        print(f"{'#' * 50}")

        # ----- 逐份审阅 -----
        results = []
        # enumerate 从 1 开始编号，给用户进度感
        for i, file in enumerate(files, start=1):
            print(f"\n▶ 进度 [{i}/{len(files)}]")
            try:
                # 复用单份审阅的完整管道（含单份底稿保存）
                result = self.review(str(file), save_report=save_report)
            except Exception as e:
                # 兜底：任何一份的意外错误都不中断整批
                print(f"   ✗ 意外错误: {str(e)}")
                result = {
                    "success": False,
                    "file_name": file.name,
                    "contract": None,
                    "extraction": None,
                    "risks": None,
                    "report_path": None,
                    "error": str(e),
                }
            # 无论成败都记录，汇总时统一呈现
            results.append(result)

        # ----- 生成汇总 -----
        # 终端展示汇总表
        self.reporter.display_batch_summary(results)

        # 按需保存汇总 Markdown
        summary_path = None
        if save_report:
            summary_path = self.reporter.save_batch_markdown(results, str(path))

        # 返回批处理结果
        return {
            "success": True,
            "results": results,
            "summary_path": summary_path,
            "error": None,
        }


# ============================================
# 测试代码（直接运行本文件时执行）
# ============================================

if __name__ == "__main__":
    print("=" * 50)
    print("测试 ContractReviewPipeline 模块")
    print("=" * 50)

    # 创建一份埋了风险点的测试合同
    test_file = Path("test_contract_pipeline.txt")
    test_file.write_text(
        "购销合同\n\n"
        "甲方：北京某某科技有限公司\n"
        "乙方：上海某某贸易有限公司\n\n"
        "第一条 标的：办公用服务器 50 台。\n"
        "第二条 合同金额：人民币 100 万元整。\n"
        "第三条 付款：货到后甲方适时付款。\n"
        "第四条 违约责任：乙方违约应支付合同金额 30% 的违约金。\n"
        "签订日期：2025年12月20日\n",
        encoding="utf-8",
    )

    try:
        # 注意：完整测试需要配置好 API Key（提取和风险识别要调 LLM）
        pipeline = ContractReviewPipeline()
        result = pipeline.review(str(test_file))

        # 打印整体结果
        print(f"\n管道执行: {'成功' if result['success'] else '失败'}")
        if result["report_path"]:
            print(f"底稿位置: {result['report_path']}")

    finally:
        # 清理测试文件
        test_file.unlink(missing_ok=True)
        print("\n🧹 已清理测试文件")
