#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
合同解析模块 (ContractParser)

职责：把一份合同文件（PDF/TXT/MD）加载成「一整段全文」。

为什么不复用 RAG 的分块（chunker）？
- RAG 的目标是「检索」：把文档切成小块，按相似度找出相关的几块
- 审合同的目标是「通读」：审计师审合同必须从头看到尾，
  漏看任何一条条款都可能漏掉风险
- DeepSeek 支持 64K token 上下文，一般合同（几页到几十页）
  全文放进一次请求完全没问题
- 所以这里只做「加载 + 拼接」，不做分块

超长合同怎么办？
- 如果全文超过安全长度（约 3 万字符），会做「截断 + 提示」
- 第一版先这样处理，后续可以升级为「分段提取再合并」
"""

# 导入 sys 用于把项目根目录加入模块搜索路径
import sys

# Path 用于跨平台地处理文件路径
from pathlib import Path

# 把项目根目录（audit 的上一级）加入 sys.path
# 这样才能 import 项目根目录下的 config 和 rag 包
sys.path.append(str(Path(__file__).parent.parent))

# 导入类型提示：Dict 字典、Any 任意类型
from typing import Dict, Any

# 复用 V2 已有的文档加载器（支持 PDF/TXT/MD，逻辑已验证）
# 这就是「零侵入复用」：audit 包只调用 rag 包，不修改它
from rag.loader import DocumentLoader


class ContractParser:
    """
    合同解析器：文件 → 合同全文 + 基本信息

    使用示例:
        parser = ContractParser()
        result = parser.parse("购销合同.pdf")
        print(result["full_text"])    # 合同全文
        print(result["page_count"])   # 页数
    """

    # 类常量：全文的最大安全长度（字符数）
    # 为什么是 30000？DeepSeek 64K token 上下文，
    # 中文约 1 字符 = 1 token，30000 字符留足了
    # 提示词 + 输出 + 安全余量的空间
    MAX_TEXT_LENGTH = 30000

    def __init__(self):
        """
        初始化合同解析器

        内部持有一个 DocumentLoader 实例，负责实际的文件读取。
        """
        # 创建文档加载器（复用 rag 包的现成能力）
        self.loader = DocumentLoader()

    def parse(self, file_path: str) -> Dict[str, Any]:
        """
        解析合同文件，返回全文和基本信息

        Args:
            file_path: 合同文件路径（支持 PDF/TXT/MD）

        Returns:
            字典，包含：
            - file_name: 文件名（不含路径）
            - full_text: 合同全文（超长会被截断）
            - page_count: 页数（文本文件为 1）
            - char_count: 全文字符数（截断前的原始长度）
            - truncated: 是否发生了截断

        Raises:
            FileNotFoundError: 文件不存在
            ValueError: 文件格式不支持
        """
        # 去掉用户输入路径中可能带的引号（如 "合同.pdf"）
        file_path = file_path.strip('"').strip("'")

        # 转成 Path 对象，方便取文件名等信息
        path = Path(file_path)

        # 调用 DocumentLoader 加载文件
        # 返回 List[Document]，PDF 是每页一个 Document
        # 文件不存在/格式不支持时，loader 会抛出异常（由调用方处理）
        documents = self.loader.load(file_path)

        # 把所有页/块的文本按顺序拼接成一整段全文
        # "\n\n" 用两个换行分隔每页，保留页与页之间的边界感
        # doc.page_content 是每个 Document 的正文文本
        full_text = "\n\n".join(doc.page_content for doc in documents)

        # 记录原始长度（截断前），用于向用户报告
        char_count = len(full_text)

        # 判断是否超过安全长度
        truncated = char_count > self.MAX_TEXT_LENGTH

        # 如果超长，截断到安全长度并附加提示
        if truncated:
            # 切片 [:MAX_TEXT_LENGTH] 保留前 3 万字符
            full_text = full_text[: self.MAX_TEXT_LENGTH]
            # 在文末追加说明，让 LLM 知道内容不完整
            full_text += "\n\n（注意：合同过长，以上仅为前部分内容，后文已截断）"
            # 同时在控制台提醒用户
            print(f"⚠ 合同全文 {char_count} 字符，超过 {self.MAX_TEXT_LENGTH}，已截断")

        # 组装返回结果
        return {
            # path.name 是「文件名.扩展名」，不含目录
            "file_name": path.name,
            # 合同全文（可能被截断）
            "full_text": full_text,
            # 页数 = Document 数量（PDF 每页一个；TXT/MD 通常是 1）
            "page_count": len(documents),
            # 原始字符数（截断前）
            "char_count": char_count,
            # 截断标志，报告里会体现
            "truncated": truncated,
        }


# ============================================
# 测试代码（直接运行本文件时执行）
# ============================================

if __name__ == "__main__":
    print("=" * 50)
    print("测试 ContractParser 模块")
    print("=" * 50)

    # 创建一个临时的测试合同文本
    test_file = Path("test_contract.txt")
    test_file.write_text(
        "购销合同\n\n"
        "甲方：某某科技有限公司\n"
        "乙方：某某贸易有限公司\n\n"
        "第一条 合同金额：人民币 100 万元。\n"
        "第二条 履行期限：2026年1月1日至2026年12月31日。\n"
        "第三条 违约责任：任何一方违约，应支付合同金额 30% 的违约金。\n",
        encoding="utf-8",
    )

    try:
        # 创建解析器并解析测试文件
        parser = ContractParser()
        result = parser.parse(str(test_file))

        # 打印解析结果的各项信息
        print(f"\n文件名: {result['file_name']}")
        print(f"页数: {result['page_count']}")
        print(f"字符数: {result['char_count']}")
        print(f"是否截断: {result['truncated']}")
        print(f"\n全文预览:\n{result['full_text'][:200]}")

        print("\n✓ 测试通过!")

    finally:
        # 无论成功失败都删除临时测试文件
        test_file.unlink(missing_ok=True)
        print("\n🧹 已清理测试文件")
