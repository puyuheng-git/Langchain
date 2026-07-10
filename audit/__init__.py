#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
审计模块包 (audit) —— 审计人员的 AI 工作台

这个包实现「审合同」功能的完整管道：

    /review 合同.pdf
      │
      ├─ ① ContractParser     加载 PDF/TXT/MD 合同，拼接为全文
      ├─ ② ContractExtractor  LLM 结构化提取关键字段（签约方/金额/期限…）
      ├─ ③ RiskAnalyzer       LLM 识别异常条款，输出风险清单
      └─ ④ ReportGenerator    生成文字报告 + 表格，可保存为 Markdown

设计原则（见 docs/adr/0001）：
- 确定性管道：固定流程「加载→提取→分析→报告」，不走 Agent 多步推理
- 审计可追溯：每一步的输入输出都可以单独查看和复核
- 零侵入：不改动现有 V1~V4 任何功能，全部增量添加
"""

# 从各子模块导入核心类，方便外部直接 from audit import ContractReviewPipeline
# 这样 main.py 只需要 import 一个类就能用整个管道
from .contract_parser import ContractParser
from .extractor import ContractExtractor
from .risk_analyzer import RiskAnalyzer
from .report_generator import ReportGenerator
from .pipeline import ContractReviewPipeline

# __all__ 定义「from audit import *」时会导入哪些名字
# 也是给读者看的「这个包对外提供什么」的清单
__all__ = [
    "ContractParser",
    "ContractExtractor",
    "RiskAnalyzer",
    "ReportGenerator",
    "ContractReviewPipeline",
]
