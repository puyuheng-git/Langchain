#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
风险识别模块 (RiskAnalyzer)

职责：审阅合同全文 + 已提取的关键字段，标记异常条款（领域术语见
CONTEXT.md「风险识别」「关键条款异常」）。

审计视角的「风险」是什么？
- 条款明显偏离行业惯例（如违约金 30%，法定支持上限通常按损失的 30% 上浮）
- 权利义务明显不对等（只约束一方的违约责任）
- 关键条款缺失（没有约定付款节点、没有验收标准、没有争议解决方式）
- 表述模糊可能引发争议（「适时付款」「质量合格」无标准）

第一版的实现策略（见 docs/adr/0002）：
- 风险判断标准直接写在 Prompt 里（「你是有 10 年经验的审计专家…」）
- 不写死代码规则，因为合同类型千差万别，LLM 的泛化判断更实用
- 后续版本可以把规则外移到配置文件，做成「风险规则库」

输出的每条风险包含四要素：
    等级(level) / 条款(clause) / 理由(reason) / 建议(suggestion)
这对应审计底稿的「发现 → 依据 → 建议」结构。
"""

# 导入 sys 用于修改模块搜索路径
import sys

# json 用于解析 LLM 返回的 JSON
import json

# re 用于剥离代码块标记和抢救 JSON
import re

# Path 用于路径处理
from pathlib import Path

# 把项目根目录加入搜索路径
sys.path.append(str(Path(__file__).parent.parent))

# 类型提示：List 列表、Dict 字典、Any 任意类型
from typing import List, Dict, Any

# 复用 ChatSession 调用 LLM
from chat.session import ChatSession


# ============================================
# 风险等级定义
# ============================================

# 合法的风险等级（用于校验模型输出）
# 高：可能造成重大损失，必须处理
# 中：存在隐患，建议修改
# 低：瑕疵或提示性问题，可以接受
VALID_LEVELS = ("高", "中", "低")


class RiskAnalyzer:
    """
    合同风险识别器：合同全文 + 关键字段 → 风险条目列表

    使用示例:
        analyzer = RiskAnalyzer()
        result = analyzer.analyze(full_text, extracted_fields)
        for risk in result["risks"]:
            print(risk["level"], risk["clause"], risk["reason"])
    """

    def __init__(self):
        """
        初始化风险识别器

        与提取器同理：每次 analyze() 新建临时会话，无需初始化状态。
        """
        # 保留构造方法以便未来注入自定义风险规则库
        pass

    def _build_prompt(self, full_text: str, fields: Dict[str, Any]) -> str:
        """
        构建风险识别的提示词

        Prompt 设计思路：
        1. 角色设定：10 年经验的财务/内部审计专家（激发领域知识）
        2. 给出「审什么」的检查清单（对等性/惯例偏离/缺失/模糊）
        3. 把已提取的字段一并给模型——字段是「地图」，全文是「地形」，
           两者对照能发现「字段之间的矛盾」（如金额与付款节点对不上）
        4. 严格 JSON 输出 + 「没有风险就输出空数组」，禁止硬凑

        Args:
            full_text: 合同全文
            fields: ContractExtractor 提取出的字段字典

        Returns:
            拼装好的完整提示词
        """
        # 把已提取字段序列化成 JSON 文本，附在提示词里
        # ensure_ascii=False 保持中文可读，indent=2 缩进美化
        fields_json = json.dumps(fields, ensure_ascii=False, indent=2)

        # 拼装提示词
        prompt = f"""你将审阅一份合同。以下是已提取的关键要素和合同全文。

已提取的关键要素：
{fields_json}

请从财务审计和内部审计的角度，识别这份合同中的风险点。重点检查：
1. 权利义务是否对等（是否只约束一方）
2. 关键条款是否偏离常见商业惯例（如违约金比例过高/过低）
3. 关键条款是否缺失（付款节点、验收标准、争议解决、保密、知识产权等）
4. 表述是否模糊、可能引发执行争议
5. 关键要素之间是否矛盾（如总金额与付款分期加总不一致）

输出要求：
- 严格输出 JSON 数组，每个元素是一个风险对象，包含以下键：
  "level": 风险等级，只能是「高」「中」「低」之一
  "clause": 涉及的条款（引用原文关键句，不超过 50 字）
  "reason": 为什么是风险（客观分析，不超过 100 字）
  "suggestion": 审计建议（如何核实或修改，不超过 80 字）
- 按风险等级从高到低排序
- 确实没有风险就输出空数组 []
- 只输出 JSON 数组本身，不要解释文字或代码块标记
- 禁止编造合同中不存在的内容

合同全文：
---
{full_text}
---"""

        return prompt

    def _parse_json_reply(self, reply: str) -> List[Dict[str, Any]]:
        """
        解析 LLM 返回的 JSON 数组

        与 extractor 的解析逻辑类似，但目标是数组 [...] 而不是对象 {...}。

        Args:
            reply: LLM 原始回复

        Returns:
            风险字典的列表；解析失败抛出 ValueError
        """
        # 去掉首尾空白
        text = reply.strip()

        # 剥掉可能的 ```json ... ``` 代码块标记
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

        # 尝试直接解析
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # 失败则用正则找「第一个 [ 到最后一个 ]」的片段
            match = re.search(r"\[.*\]", text, re.DOTALL)
            if not match:
                raise ValueError(f"无法从模型回复中解析出 JSON 数组: {reply[:200]}")
            data = json.loads(match.group(0))

        # 校验：必须是列表
        if not isinstance(data, list):
            raise ValueError("模型输出不是 JSON 数组")

        return data

    def _sanitize_risks(self, risks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        清洗模型输出的风险条目

        模型输出不可全信，做三件事：
        1. 丢弃缺少必要键的条目
        2. 等级不在「高/中/低」里的归为「中」
        3. 按等级排序（高→中→低），保证报告呈现顺序稳定

        Args:
            risks: 解析出的原始风险列表

        Returns:
            清洗排序后的风险列表
        """
        # 存放清洗后的条目
        cleaned = []

        # 逐条检查
        for item in risks:
            # 跳过不是字典的元素（防模型输出字符串混入）
            if not isinstance(item, dict):
                continue

            # 四个必要键至少要有 clause 和 reason 才有意义
            if not item.get("clause") or not item.get("reason"):
                continue

            # 等级不合法时归为「中」（宁可提示也不静默丢弃）
            level = item.get("level")
            if level not in VALID_LEVELS:
                level = "中"

            # 组装成统一结构（缺 suggestion 时给默认话术）
            cleaned.append({
                "level": level,
                "clause": str(item["clause"]),
                "reason": str(item["reason"]),
                "suggestion": str(item.get("suggestion") or "建议人工复核该条款"),
            })

        # 按等级排序：用字典把等级映射成数字（高=0 排最前）
        level_order = {"高": 0, "中": 1, "低": 2}
        # sorted 的 key 参数：按映射出的数字升序排
        cleaned.sort(key=lambda r: level_order[r["level"]])

        return cleaned

    def analyze(self, full_text: str, fields: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行风险识别

        Args:
            full_text: 合同全文
            fields: 已提取的关键字段（来自 ContractExtractor）

        Returns:
            字典，包含：
            - risks: 风险条目列表（每条含 level/clause/reason/suggestion）
            - success: 是否成功
            - error: 失败时的错误信息（成功时为 None）
        """
        print("\n⚠️ 步骤 3/4: 识别风险条款...")

        # 构建提示词
        prompt = self._build_prompt(full_text, fields)

        try:
            # 创建风险分析专用会话
            # 角色设定：资深审计专家，只依据原文判断
            session = ChatSession(
                system_prompt=(
                    "你是一名有 10 年经验的财务审计与内部审计专家，"
                    "擅长审阅合同并识别风险。你只依据合同原文做客观判断，"
                    "只输出 JSON，绝不编造。"
                )
            )

            # 温度 0.2：风险判断需要一点点「联想力」（对比行业惯例），
            # 但仍然要以稳定为主，所以比提取(0.1)略高、远低于闲聊(0.7)
            session.temperature = 0.2

            # 放大 token 上限防止长合同被截断（同 extractor）
            session.max_history_tokens = 60000

            # 调用 LLM，拿完整回复
            # quiet=True 静默模式：原始 JSON 不打印到终端
            # （风险清单会在报告环节以表格形式呈现，中间产物无需展示）
            reply = session.chat(prompt, stream=False, quiet=True)

            # 解析 + 清洗
            risks = self._sanitize_risks(self._parse_json_reply(reply))

            # 给用户反馈各等级的数量
            # 生成器 + sum 统计每个等级的条数
            high = sum(1 for r in risks if r["level"] == "高")
            mid = sum(1 for r in risks if r["level"] == "中")
            low = sum(1 for r in risks if r["level"] == "低")
            print(f"   ✓ 识别完成: 高风险 {high} 条 / 中风险 {mid} 条 / 低风险 {low} 条")

            # 返回成功结果
            return {"risks": risks, "success": True, "error": None}

        except Exception as e:
            # 失败时优雅降级：空风险列表 + 错误信息
            print(f"   ✗ 风险识别失败: {str(e)}")
            return {"risks": [], "success": False, "error": str(e)}


# ============================================
# 测试代码（直接运行本文件时执行）
# ============================================

if __name__ == "__main__":
    print("=" * 50)
    print("测试 RiskAnalyzer 模块")
    print("=" * 50)

    # 迷你测试合同：故意埋了几个风险点
    # - 违约金 30% 偏高
    # - 只约束乙方的违约责任（不对等）
    # - 没有验收标准
    test_text = (
        "购销合同\n\n"
        "甲方：北京某某科技有限公司\n"
        "乙方：上海某某贸易有限公司\n\n"
        "第一条 标的：办公用服务器 50 台。\n"
        "第二条 合同金额：人民币 100 万元整。\n"
        "第三条 付款：货到后甲方适时付款。\n"
        "第四条 违约责任：乙方违约应支付合同金额 30% 的违约金。\n"
    )

    # 模拟已提取的字段（真实使用时来自 ContractExtractor）
    test_fields = {
        "contract_name": "购销合同",
        "party_a": "北京某某科技有限公司",
        "party_b": "上海某某贸易有限公司",
        "contract_value": "人民币 100 万元整",
        "payment_terms": "货到后甲方适时付款",
        "liquidated_damages": "乙方违约应支付合同金额 30% 的违约金",
        "jurisdiction": None,
    }

    # 注意：本测试需要配置好 API Key 才能真正调用 LLM
    analyzer = RiskAnalyzer()
    result = analyzer.analyze(test_text, test_fields)

    # 打印分析结果
    print(f"\n成功: {result['success']}")
    for risk in result["risks"]:
        print(f"\n[{risk['level']}] {risk['clause']}")
        print(f"  理由: {risk['reason']}")
        print(f"  建议: {risk['suggestion']}")
