#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
检索器模块 (Retriever)

基于向量相似度的文档检索实现。

检索器的作用：
- 接收用户查询（文本）
- 将查询转换为向量（使用 Embedder）
- 在向量数据库中搜索相似的文档块
- 返回最相关的 k 个结果

检索策略：
1. 相似度检索 (Similarity Search)
   - 计算查询向量与文档向量的余弦相似度
   - 返回 Top-K 最相似的文档
   - 简单高效，最常用

2. MMR (Max Marginal Relevance) - 可选进阶
   - 平衡相关性和多样性
   - 避免返回内容重复的文档
   - 适合需要多角度信息的场景

相似度计算：
- 使用余弦相似度（Cosine Similarity）
- 范围：-1（完全相反）到 1（完全相同）
- 通常 0.7+ 认为是相似的
"""

import sys
from pathlib import Path

# 将父目录添加到 Python 路径
sys.path.append(str(Path(__file__).parent.parent))

from typing import List, Tuple, Optional
from langchain_core.documents import Document

# 从同级模块导入
from .embedder import Embedder
from .vectorstore import VectorStore


class Retriever:
    """
    检索器封装类

    整合 Embedder 和 VectorStore，提供简洁的检索接口。

    工作流程：
    1. 接收查询文本
    2. Embedder 将查询转换为向量
    3. VectorStore 执行相似度搜索
    4. 返回排序后的结果（带相似度分数）

    使用示例:
        # 创建检索器
        retriever = Retriever(embedder, vectorstore)

        # 检索相关文档
        results = retriever.retrieve("什么是Python？", k=3)
        for doc, score in results:
            print(f"相似度: {score:.4f}")
            print(f"内容: {doc.page_content[:100]}")
    """

    def __init__(
        self,
        embedder: Embedder,
        vectorstore: VectorStore,
        search_k: int = 4
    ):
        """
        初始化检索器

        Args:
            embedder: Embedder 实例，用于查询向量化
            vectorstore: VectorStore 实例，用于向量搜索
            search_k: 默认返回的文档数量，默认 4

        参数选择建议：
        - search_k:
          - 3: 精确问答，需要最相关的内容
          - 4-5: 通用场景（推荐）
          - 10: 需要广泛信息，不介意噪声
        """
        # 保存依赖的组件
        self.embedder = embedder
        self.vectorstore = vectorstore
        self.search_k = search_k

        print(f"✓ Retriever 初始化完成")
        print(f"  默认检索数量: {search_k}")

    def retrieve(
        self,
        query: str,
        k: int = None,
        score_threshold: float = 0.0
    ) -> List[Tuple[Document, float]]:
        """
        检索与查询相关的文档

        这是最主要的检索方法，执行完整的检索流程。

        Args:
            query: 用户的查询文本
            k: 返回的文档数量，None 则使用默认值
            score_threshold: 相似度阈值，低于此值的文档会被过滤
                           范围 0-1，默认 0（不过滤）

        Returns:
            列表，每个元素是 (Document, similarity_score) 元组
            按相似度从高到低排序

        使用示例:
            results = retriever.retrieve("Python是什么语言？", k=3)
            for doc, score in results:
                print(f"[{score:.2f}] {doc.page_content[:50]}...")
        """
        # 如果未指定 k，使用默认值
        # 等价于: if k is None: k = self.search_k
        k = k or self.search_k

        # 步骤 1: 将查询文本转换为向量
        # 使用 Embedder 生成查询向量
        query_embedding = self.embedder.embed_query(query)

        # 步骤 2: 在向量数据库中搜索
        # 返回 (Document, score) 元组列表
        results = self.vectorstore.similarity_search(
            query_embedding=query_embedding,
            k=k
        )

        # 步骤 3: 应用相似度阈值过滤
        # filter() 函数过滤列表，只保留满足条件的元素
        # lambda 是匿名函数，接收一个参数（这里是 result）
        # result[1] 是相似度分数
        if score_threshold > 0:
            results = [
                (doc, score)
                for doc, score in results
                if score >= score_threshold
            ]

        return results

    def retrieve_with_context(
        self,
        query: str,
        k: int = None,
        context_window: int = 0
    ) -> List[Tuple[Document, float]]:
        """
        检索文档并获取上下文窗口

        除了检索到的文档块，还获取前后相邻的块，
        用于扩展上下文信息。

        Args:
            query: 用户的查询文本
            k: 返回的文档数量
            context_window: 上下文窗口大小，获取前后各 n 个块
                          0 表示不获取上下文（默认）
                          1 表示获取前后各 1 个块

        Returns:
            文档列表（包含上下文），按原始文档顺序排列

        注意：此方法目前为预留接口，完整实现需要 VectorStore 支持
              按 chunk_index 查询相邻块的功能
        """
        # 先执行基本检索
        results = self.retrieve(query, k=k)

        # 如果不需要上下文，直接返回
        if context_window == 0:
            return results

        # TODO: 实现上下文窗口扩展
        # 需要：
        # 1. 从 metadata 获取 chunk_index 和 source
        # 2. 查询 VectorStore 获取相邻的块
        # 3. 合并并排序

        # 目前先返回基本结果
        print(f"⚠ 上下文窗口功能暂未实现（预留接口）")
        return results

    def format_context(
        self,
        results: List[Tuple[Document, float]],
        include_score: bool = False,
        include_source: bool = True
    ) -> str:
        """
        将检索结果格式化为上下文字符串

        用于构建 Prompt 时插入到模板中。

        Args:
            results: 检索结果列表，(Document, score) 元组
            include_score: 是否包含相似度分数
            include_source: 是否包含来源信息

        Returns:
            格式化后的上下文字符串

        使用示例:
            results = retriever.retrieve("Python是什么？")
            context = retriever.format_context(results)
            prompt = f"基于以下文档回答问题：\n{context}\n\n问题：..."
        """
        # 如果没有结果，返回提示信息
        if not results:
            return "（没有找到相关文档）"

        # 构建上下文列表
        context_parts = []

        for i, (doc, score) in enumerate(results, start=1):
            # 每个文档块格式化为一个段落
            # [文档 i] 标签
            part = f"[文档 {i}]"

            # 可选：添加相似度分数
            if include_score:
                part += f" (相似度: {score:.2f})"

            # 可选：添加来源信息
            if include_source:
                source = doc.metadata.get("source", "未知")
                page = doc.metadata.get("page")
                if page is not None:
                    part += f" 《{source}》第{page + 1}页"
                else:
                    part += f" 《{source}》"

            # 添加文档内容
            part += f"\n{doc.page_content}\n"

            context_parts.append(part)

        # 用换行符连接所有部分
        # "\n\n" 在两个文档块之间添加空行，便于阅读
        return "\n".join(context_parts)

    def get_stats(self) -> dict:
        """
        获取检索器的统计信息

        Returns:
            统计字典，包含配置信息等
        """
        return {
            "search_k": self.search_k,
            "embedder_model": self.embedder.model_name,
            "vectorstore_collection": self.vectorstore.collection_name,
            "vectorstore_count": self.vectorstore.count()
        }


# ============================================
# 简单的 RAG Prompt 构建器
# ============================================

class RAGPromptBuilder:
    """
    RAG Prompt 构建器

    将检索结果和用户问题组合成完整的 Prompt。
    """

    # 默认的 RAG Prompt 模板
    # {context} 会被替换为检索到的文档内容
    # {question} 会被替换为用户的问题
    DEFAULT_TEMPLATE = """你是一个基于文档回答问题的助手。
请根据以下参考文档内容回答问题。如果文档中没有相关信息，请明确说明"根据现有文档无法回答"。

参考文档：
{context}

---

用户问题：{question}

请回答："""

    def __init__(self, template: str = None):
        """
        初始化 Prompt 构建器

        Args:
            template: 自定义 Prompt 模板，None 则使用默认模板
        """
        # 使用用户提供的模板或默认模板
        self.template = template or self.DEFAULT_TEMPLATE

    def build(self, context: str, question: str) -> str:
        """
        构建完整的 Prompt

        Args:
            context: 格式化后的上下文（检索到的文档内容）
            question: 用户的问题

        Returns:
            完整的 Prompt 字符串
        """
        # 使用 .format() 方法替换模板中的占位符
        return self.template.format(
            context=context,
            question=question
        )

    def build_with_sources(
        self,
        context: str,
        question: str,
        sources: List[str]
    ) -> str:
        """
        构建 Prompt 并在末尾附加来源信息（用于后续解析）

        Args:
            context: 格式化后的上下文
            question: 用户的问题
            sources: 来源列表

        Returns:
            完整的 Prompt 字符串
        """
        # 先构建基本 Prompt
        prompt = self.build(context, question)

        # 添加来源信息（作为注释，不会显示给用户，但 LLM 可以看到）
        # 实际显示的来源应该在生成回答后再添加
        return prompt


# ============================================
# 测试代码
# ============================================

if __name__ == "__main__":
    print("=" * 50)
    print("测试 Retriever 模块")
    print("=" * 50)

    # 注意：此测试需要 Embedder 和 VectorStore 正常工作
    # 可能需要配置 API Key

    try:
        from .embedder import Embedder
        from .vectorstore import VectorStore

        print("\n1. 初始化组件:")
        # 创建 Embedder
        embedder = Embedder()

        # 创建 VectorStore（使用小维度便于测试）
        vectorstore = VectorStore(
            collection_name="test_retriever",
            embedding_dimension=embedder.get_dimension()
        )

        # 添加测试数据
        print("\n2. 添加测试文档到向量库:")
        from langchain_core.documents import Document

        test_docs = [
            Document(
                page_content="Python 是一种解释型的高级编程语言，语法简洁优雅。",
                metadata={"source": "python_intro.pdf", "page": 0}
            ),
            Document(
                page_content="Java 是一种面向对象的编程语言，广泛用于企业级开发。",
                metadata={"source": "java_intro.pdf", "page": 0}
            ),
            Document(
                page_content="Python 在数据科学和人工智能领域非常流行。",
                metadata={"source": "python_intro.pdf", "page": 1}
            )
        ]

        # 生成向量并添加
        embeddings = embedder.embed_documents([doc.page_content for doc in test_docs])
        vectorstore.add_documents(test_docs, embeddings)

        print("\n3. 创建检索器并测试检索:")
        # 创建检索器
        retriever = Retriever(embedder, vectorstore, search_k=2)

        # 执行检索
        query = "Python 是什么语言？"
        results = retriever.retrieve(query, k=2)

        print(f"   查询: {query}")
        print(f"   检索到 {len(results)} 个结果:")
        for doc, score in results:
            print(f"   - [{score:.4f}] {doc.page_content[:40]}...")

        print("\n4. 测试上下文格式化:")
        context = retriever.format_context(results, include_score=True)
        print(context)

        print("\n5. 测试 Prompt 构建:")
        builder = RAGPromptBuilder()
        prompt = builder.build(context, query)
        print(f"   Prompt 长度: {len(prompt)} 字符")
        print(f"   前 200 字符:\n{prompt[:200]}...")

        print("\n✓ 所有测试通过!")

    except Exception as e:
        print(f"\n✗ 测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
