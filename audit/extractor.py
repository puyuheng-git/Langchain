#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
结构化提取模块 (ContractExtractor)

职责：把「非结构化的合同全文」变成「结构化的关键字段表」。

这是审计工作台的核心一步（领域术语见 CONTEXT.md「结构化提取」）：
- 审计师拿到合同第一件事就是提取要素：谁签的、多少钱、多久、违约怎么办
- 人工提取一份合同要 10~20 分钟，LLM 几十秒完成
- 结构化之后才能做后续的风险识别、台账汇总、批量对比

技术要点——「让 LLM 输出 JSON」：
- 在提示词里明确要求「只输出 JSON，不要多余文字」
- 用 json.loads() 解析模型返回
- 模型偶尔会在 JSON 外面包 ```json 代码块，要先剥掉
- 解析失败时优雅降级：返回带错误标记的结果，不让程序崩溃
"""

# 导入 sys 用于修改模块搜索路径
import sys

# json 用于解析 LLM 返回的 JSON 字符串
import json

# re 正则模块，用于从模型回复中剥离代码块标记
import re

# Path 用于路径处理
from pathlib import Path

# 把项目根目录加入搜索路径，才能导入 chat 包
sys.path.append(str(Path(__file__).parent.parent))

# 类型提示
from typing import Dict, Any

# 复用 V1 的 ChatSession 调用 LLM（和 RAGPipeline 的做法一致）
from chat.session import ChatSession


# ============================================
# 提取字段的定义（给 LLM 的「表格模板」）
# ============================================

# 这个字典定义了要提取的所有字段和每个字段的说明
# 集中放在模块顶部的好处：以后要增删字段只改这里
EXTRACTION_FIELDS = {
    "contract_name": "合同名称/标题",
    "party_a": "甲方（全称）",
    "party_b": "乙方（全称）",
    "other_parties": "其他签约方（如有，没有则为 null）",
    "subject_matter": "合同标的（货物/服务/工程的简述）",
    "contract_value": "合同金额（含币种，如「人民币 100 万元」；未约定则为 null）",
    "payment_terms": "付款方式与节点（简述）",
    "term_start": "履行期限开始日（YYYY-MM-DD，未明确则为 null）",
    "term_end": "履行期限结束日（YYYY-MM-DD，未明确则为 null）",
    "liquidated_damages": "违约责任条款（简述，含违约金比例/金额）",
    "jurisdiction": "争议解决方式与管辖（如「某某市人民法院诉讼」「某仲裁委仲裁」）",
    "sign_date": "签订日期（YYYY-MM-DD，未明确则为 null）",
}


class ContractExtractor:
    """
    合同结构化提取器：合同全文 → 关键字段字典

    使用示例:
        extractor = ContractExtractor()
        fields = extractor.extract(full_text)
        print(fields["contract_value"])   # "人民币 100 万元"
    """

    def __init__(self):
        """
        初始化提取器

        提取是「一次性任务」不是多轮对话，
        所以每次 extract() 时新建临时会话，__init__ 里不用做什么。
        """
        # 目前无需初始化状态，保留构造方法以便未来扩展
        # （例如注入自定义字段模板）
        pass

    def _build_prompt(self, full_text: str) -> str:
        """
        构建提取指令的提示词（Prompt）

        Prompt 设计思路：
        1. 明确角色：审计助理，只做客观提取，不发挥
        2. 给出字段清单和每个字段的说明（来自 EXTRACTION_FIELDS）
        3. 严格要求输出 JSON、找不到就填 null——禁止编造是审计场景的底线

        Args:
            full_text: 合同全文

        Returns:
            拼装好的完整提示词字符串
        """
        # 把字段字典拼成「"字段名": 说明」的清单文本
        # join + 生成器表达式：对每个键值对生成一行
        field_lines = "\n".join(
            f'  "{key}": {desc}' for key, desc in EXTRACTION_FIELDS.items()
        )

        # 用 f-string 拼装完整提示词
        # 三引号字符串可以跨多行，格式清晰
        prompt = f"""请从下面的合同文本中提取关键信息，严格按 JSON 格式输出。

需要提取的字段（键名必须完全一致）：
{{
{field_lines}
}}

提取规则：
1. 只依据合同原文提取，禁止推测或编造
2. 合同中找不到的信息，对应字段填 null
3. 金额保留原文写法（如「人民币壹佰万元整（¥1,000,000）」）
4. 只输出 JSON 对象本身，不要输出任何解释文字或代码块标记

合同文本：
---
{full_text}
---"""

        return prompt

    def _parse_json_reply(self, reply: str) -> Dict[str, Any]:
        """
        解析 LLM 返回的 JSON 文本

        模型有时不听话，会输出：
        - ```json ... ``` 代码块包裹
        - JSON 前后带解释文字
        这里做两层容错：先剥代码块，再用正则找最外层的 {...}

        Args:
            reply: LLM 的原始回复文本

        Returns:
            解析出的字典；解析失败抛出 ValueError
        """
        # 第一步：去掉首尾空白
        text = reply.strip()

        # 第二步：如果被 ```json ... ``` 或 ``` ... ``` 包裹，剥掉标记
        # re.sub 用正则替换：^```(json)?\s* 匹配开头的代码块标记
        text = re.sub(r"^```(?:json)?\s*", "", text)
        # 同样去掉结尾的 ```
        text = re.sub(r"\s*```$", "", text)

        # 第三步：尝试直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # 直接解析失败：可能 JSON 前后混了解释文字
            # 用正则找「第一个 { 到最后一个 }」之间的内容再试一次
            # re.DOTALL 让 . 也能匹配换行符
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                # match.group(0) 是匹配到的完整 JSON 片段
                return json.loads(match.group(0))
            # 还是不行就抛出明确的错误
            raise ValueError(f"无法从模型回复中解析出 JSON: {reply[:200]}")

    def extract(self, full_text: str) -> Dict[str, Any]:
        """
        执行结构化提取

        Args:
            full_text: 合同全文（来自 ContractParser.parse()["full_text"]）

        Returns:
            字典，包含：
            - fields: 提取出的字段字典（键见 EXTRACTION_FIELDS）
            - success: 是否成功
            - error: 失败时的错误信息（成功时为 None）
        """
        print("\n📋 步骤 2/4: 结构化提取关键字段...")

        # 构建提示词
        prompt = self._build_prompt(full_text)

        try:
            # 创建一个专用于提取的临时会话
            # system_prompt 定义角色：客观、严谨的审计助理
            session = ChatSession(
                system_prompt=(
                    "你是一名严谨的审计助理，负责从合同中客观提取信息。"
                    "你只输出 JSON，绝不编造合同中不存在的内容。"
                )
            )

            # 温度调到 0.1：提取任务要求最大程度的确定性
            # 温度越低，模型输出越稳定、越少「自由发挥」
            session.temperature = 0.1

            # 放大历史 token 上限，防止长合同 prompt 被 ChatSession
            # 的历史截断逻辑误删（与 RAGPipeline 的调优一致）
            session.max_history_tokens = 60000

            # 发送提示词，stream=False 拿到完整回复字符串
            # quiet=True 静默模式：原始 JSON 不打印到终端
            # （用户只需要看最终的格式化报告，不需要看中间产物）
            reply = session.chat(prompt, stream=False, quiet=True)

            # 解析 JSON 回复
            fields = self._parse_json_reply(reply)

            # 统计提取到多少个非空字段，给用户反馈
            # 生成器表达式 + sum：值不是 None 的字段计数
            filled = sum(1 for v in fields.values() if v is not None)
            print(f"   ✓ 提取完成: {filled}/{len(EXTRACTION_FIELDS)} 个字段有值")

            # 返回成功结果
            return {"fields": fields, "success": True, "error": None}

        except Exception as e:
            # 任何环节失败（网络/解析/额度），都优雅降级
            # 返回空字段 + 错误信息，让管道能继续给出部分报告
            print(f"   ✗ 提取失败: {str(e)}")
            return {
                # 所有字段填 null，保持结构一致
                "fields": {key: None for key in EXTRACTION_FIELDS},
                "success": False,
                "error": str(e),
            }


# ============================================
# 测试代码（直接运行本文件时执行）
# ============================================

if __name__ == "__main__":
    print("=" * 50)
    print("测试 ContractExtractor 模块")
    print("=" * 50)

    # 一段迷你测试合同（真实使用时来自 ContractParser）
    test_text = (
        "购销合同\n\n"
        "甲方：北京某某科技有限公司\n"
        "乙方：上海某某贸易有限公司\n\n"
        "第一条 标的：办公用服务器 50 台。\n"
        "第二条 合同金额：人民币 100 万元整。\n"
        "第三条 履行期限：2026年1月1日至2026年12月31日。\n"
        "第四条 付款：签约后 7 日内预付 50%，验收后付清尾款。\n"
        "第五条 违约责任：任何一方违约，应支付合同金额 30% 的违约金。\n"
        "第六条 争议解决：提交北京仲裁委员会仲裁。\n"
        "签订日期：2025年12月20日\n"
    )

    # 注意：本测试需要配置好 API Key 才能真正调用 LLM
    extractor = ContractExtractor()
    result = extractor.extract(test_text)

    # 打印提取结果
    print(f"\n成功: {result['success']}")
    if result["success"]:
        # json.dumps 美化打印字典
        # ensure_ascii=False 让中文正常显示而不是 \uXXXX
        print(json.dumps(result["fields"], ensure_ascii=False, indent=2))
    else:
        print(f"错误: {result['error']}")
