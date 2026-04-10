#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文本分块模块 (Chunker)

将长文档切分成较小的块（chunk），便于向量化和检索。

为什么要分块？
1. 向量模型有输入长度限制（如 512/1024 tokens）
2. 检索精度：小块比大块更精确，减少无关信息
3. 成本控制：向量化按 token 计费，小块更省

分块策略对比：

1. 固定字符分块 (CharacterTextSplitter)
   - 按固定字符数切割
   - 简单快速
   - 缺点：可能切断句子

2. 递归字符分块 (RecursiveCharacterTextSplitter) ⭐ 推荐
   - 按优先级递归分割（段落 → 句子 → 词）
   - 尽量保持语义完整
   - 适合大多数场景

3. Token 分块 (TokenTextSplitter)
   - 按 token 数切割
   - 最精确控制长度
   - 需要 tokenizer

关键参数：
- chunk_size: 每个块的大小（字符数或 token 数）
- chunk_overlap: 相邻块的重叠大小

为什么需要重叠？
- 避免关键信息被切分在两个块的边界
- 保持上下文连贯性
- 推荐重叠 10%-20%
"""

import sys
from pathlib import Path

# 将父目录添加到 Python 路径
sys.path.append(str(Path(__file__).parent.parent))

from typing import List
from langchain_core.documents import Document

# LangChain 的文本分割器
# RecursiveCharacterTextSplitter: 递归分割，优先保持语义完整
# 注意：在 LangChain 0.2+ 版本中，text_splitter 已移动到 langchain_text_splitters
from langchain_text_splitters import RecursiveCharacterTextSplitter


class TextChunker:
    """
    文本分块器

    使用 RecursiveCharacterTextSplitter 将长文档切分成小块。
    支持中文和英文，保持段落、句子边界。

    分块过程：
    1. 尝试按段落分割（\n\n）
    2. 如果段落还太长，按句子分割（\n 或 .!?）
    3. 如果句子还太长，按字符分割

    使用示例:
        chunker = TextChunker(chunk_size=500, chunk_overlap=50)

        # 分块单个文档
        chunks = chunker.split_document(doc)

        # 批量分块
        all_chunks = chunker.split_documents(docs)
    """

    def __init__(
        self,
        chunk_size: int = 1000,
        chunk_overlap: int = 100,
        separators: List[str] = None
    ):
        """
        初始化文本分块器

        Args:
            chunk_size: 每个块的目标大小（字符数），默认 1000
            chunk_overlap: 相邻块的重叠大小，默认 100
            separators: 分隔符列表，按优先级排序
                       默认: ["\n\n", "\n", "。", "！", "？", ".", "!", "?", " ", ""]

        参数选择建议:
        - chunk_size:
          - 500: 适合短问答、FAQ
          - 1000: 通用场景（推荐）
          - 2000: 适合长篇文章、论文

        - chunk_overlap:
          - chunk_size 的 10%-20%
          - 1000 字符块建议重叠 100-200

        使用示例:
            # 默认配置
            chunker = TextChunker()

            # 小尺寸块（适合 FAQ）
            chunker = TextChunker(chunk_size=300, chunk_overlap=30)

            # 大尺寸块（适合论文）
            chunker = TextChunker(chunk_size=2000, chunk_overlap=200)
        """
        # 保存配置参数
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

        # 默认分隔符列表（针对中文优化）
        # 按优先级排序：先尝试在段落处分割，不行再尝试句子，最后按字符
        default_separators = [
            "\n\n",      # 段落（空行分隔）
            "\n",        # 换行
            "。",        # 中文句号
            "！",        # 中文叹号
            "？",        # 中文问号
            ".",         # 英文句号
            "!",         # 英文叹号
            "?",         # 英文问号
            " ",         # 空格
            ""           # 最后手段：任意字符
        ]

        # 如果用户提供了分隔符则使用用户的，否则使用默认
        # or 运算符：左边为真用左边，否则用右边
        self.separators = separators or default_separators

        # 创建 LangChain 的 RecursiveCharacterTextSplitter
        # 这是实际执行分块的工具
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,        # 块大小
            chunk_overlap=self.chunk_overlap,  # 重叠大小
            separators=self.separators,        # 分隔符列表
            # length_function: 计算文本长度的函数
            # len 就是 Python 内置的字符串长度函数
            length_function=len,
            # is_separator_regex: 分隔符是否正则表达式
            # False 表示普通字符串匹配
            is_separator_regex=False
        )

        print(f"✓ TextChunker 初始化完成")
        print(f"  块大小: {chunk_size} 字符")
        print(f"  重叠: {chunk_overlap} 字符")

    def split_document(self, document: Document) -> List[Document]:
        """
        将单个文档分块

        Args:
            document: 输入的 Document 对象

        Returns:
            分块后的 Document 列表
            每个块保留原始 metadata，并添加 chunk_index

        使用示例:
            chunks = chunker.split_document(doc)
            for i, chunk in enumerate(chunks):
                print(f"块 {i}: {chunk.page_content[:50]}...")
        """
        # 使用 LangChain 的 split_documents 方法
        # 注意：这个方法接收 List[Document]，所以把单个文档包装成列表
        # [document] 创建一个只包含一个元素的列表
        chunks = self.splitter.split_documents([document])

        # 为每个块添加分块相关的 metadata
        for i, chunk in enumerate(chunks):
            # chunk_index: 当前块在该文档中的序号（从0开始）
            chunk.metadata["chunk_index"] = i
            # chunk_total: 该文档被分成的总块数
            chunk.metadata["chunk_total"] = len(chunks)

        return chunks

    def split_documents(self, documents: List[Document]) -> List[Document]:
        """
        批量分块多个文档

        Args:
            documents: Document 列表

        Returns:
            所有分块后的 Document 列表（展平的）

        使用示例:
            all_chunks = chunker.split_documents(docs)
            print(f"原 {len(docs)} 个文档 → 分成 {len(all_chunks)} 个块")
        """
        # 如果没有文档，返回空列表
        if not documents:
            return []

        # 使用 LangChain 的 split_documents 批量分块
        # 内部会遍历每个文档并应用分块策略
        all_chunks = self.splitter.split_documents(documents)

        # 为每个块添加 metadata
        # 注意：需要知道每个块来自哪个文档的哪一部分
        # RecursiveCharacterTextSplitter 会保留原始 metadata
        # 我们只需要添加 chunk_index 和 chunk_total

        # 统计每个 source 的块数
        source_chunks = {}
        for chunk in all_chunks:
            source = chunk.metadata.get("source", "unknown")
            if source not in source_chunks:
                source_chunks[source] = []
            source_chunks[source].append(chunk)

        # 为每个 source 的块添加索引
        for source, chunks in source_chunks.items():
            for i, chunk in enumerate(chunks):
                chunk.metadata["chunk_index"] = i
                chunk.metadata["chunk_total"] = len(chunks)

        print(f"✓ 分块完成: {len(documents)} 个文档 → {len(all_chunks)} 个块")
        print(f"  平均每文档: {len(all_chunks) / len(documents):.1f} 块")

        return all_chunks

    def get_stats(self, documents: List[Document]) -> dict:
        """
        预览分块统计（不实际分块）

        用于在正式分块前评估分块效果。

        Args:
            documents: 待分块的文档列表

        Returns:
            统计字典，包含预估的块数等信息
        """
        # 实际分块以获取统计
        chunks = self.split_documents(documents)

        # 计算统计信息
        chunk_sizes = [len(chunk.page_content) for chunk in chunks]

        return {
            "original_docs": len(documents),
            "total_chunks": len(chunks),
            "avg_chunk_size": sum(chunk_sizes) / len(chunk_sizes) if chunk_sizes else 0,
            "min_chunk_size": min(chunk_sizes) if chunk_sizes else 0,
            "max_chunk_size": max(chunk_sizes) if chunk_sizes else 0,
            "chunk_size_setting": self.chunk_size,
            "overlap_setting": self.chunk_overlap
        }


# ============================================
# 测试代码
# ============================================

if __name__ == "__main__":
    print("=" * 50)
    print("测试 TextChunker 模块")
    print("=" * 50)

    # 创建测试文档
    # 构造一个长文档，包含多个段落和句子
    long_text = """
Python 是一种广泛使用的高级编程语言。
它由 Guido van Rossum 于 1991 年创建。

Python 的设计理念强调代码的可读性和简洁的语法。
它使用缩进来表示代码块，这使得代码结构清晰。

Python 支持多种编程范式，包括：
- 面向对象编程
- 函数式编程
- 过程式编程

Python 有丰富的标准库和第三方库。
这使得 Python 在数据科学、人工智能、Web 开发等领域非常流行。

许多知名公司使用 Python，包括 Google、Facebook、Netflix 等。
Python 也是数据科学和机器学习领域最流行的语言之一。
"""

    try:
        # 创建测试 Document
        test_doc = Document(
            page_content=long_text,
            metadata={"source": "python_intro.txt", "type": "text"}
        )

        print("\n1. 测试默认配置 (chunk_size=1000, overlap=100):")
        chunker = TextChunker()
        chunks = chunker.split_document(test_doc)
        print(f"   原文档长度: {len(long_text)} 字符")
        print(f"   分块数量: {len(chunks)}")
        for i, chunk in enumerate(chunks):
            print(f"   块 {i}: {len(chunk.page_content)} 字符")
            print(f"        metadata: {chunk.metadata}")

        print("\n2. 测试小尺寸块 (chunk_size=200, overlap=20):")
        chunker_small = TextChunker(chunk_size=200, chunk_overlap=20)
        chunks_small = chunker_small.split_document(test_doc)
        print(f"   分块数量: {len(chunks_small)}")
        for i, chunk in enumerate(chunks_small):
            preview = chunk.page_content[:40].replace("\n", " ")
            print(f"   块 {i} ({len(chunk.page_content)} 字符): {preview}...")

        print("\n3. 测试批量分块:")
        docs = [
            Document(page_content="这是第一个文档。" * 50, metadata={"source": "doc1.txt"}),
            Document(page_content="这是第二个文档。" * 50, metadata={"source": "doc2.txt"}),
        ]
        chunker = TextChunker(chunk_size=100, chunk_overlap=10)
        all_chunks = chunker.split_documents(docs)
        print(f"   原 {len(docs)} 个文档 → {len(all_chunks)} 个块")

        print("\n4. 测试统计信息:")
        stats = chunker.get_stats(docs)
        for key, value in stats.items():
            print(f"   {key}: {value}")

        print("\n✓ 所有测试通过!")

    except Exception as e:
        print(f"\n✗ 测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
