#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RAG 流程编排模块 (Pipeline)

整合所有 RAG 组件，提供端到端的文档入库和查询接口。

这是 V2 的核心模块，将以下组件串联：
- DocumentLoader: 加载文档
- TextChunker: 文本分块
- Embedder: 向量化
- VectorStore: 向量存储
- Retriever: 相似度检索

使用示例:
    from rag.pipeline import RAGPipeline

    # 创建 Pipeline
    pipeline = RAGPipeline()

    # 1. 文档入库
    pipeline.ingest_document("mydoc.pdf")

    # 2. 查询
    result = pipeline.query("文档里说了什么？")
    print(result["answer"])
    print(result["sources"])
"""

import sys
from pathlib import Path

# 将父目录添加到 Python 路径
sys.path.append(str(Path(__file__).parent.parent))

from typing import List, Dict, Any, Optional
from langchain_core.documents import Document

# 从同级模块导入所有组件
from .loader import DocumentLoader
from .chunker import TextChunker
from .embedder import Embedder
from .vectorstore import VectorStore
from .retriever import Retriever, RAGPromptBuilder

# 导入 Config 用于获取配置
from config import Config


class RAGPipeline:
    """
    RAG 流程编排器

    整合文档加载、分块、向量化、存储、检索全流程。
    对外提供简洁的接口：ingest_document 和 query。

    属性:
        loader: DocumentLoader 实例
        chunker: TextChunker 实例
        embedder: Embedder 实例
        vectorstore: VectorStore 实例
        retriever: Retriever 实例
        prompt_builder: RAGPromptBuilder 实例
    """

    def __init__(
        self,
        collection_name: str = "documents",
        chunk_size: int = 1000,
        chunk_overlap: int = 100,
        search_k: int = 4
    ):
        """
        初始化 RAG Pipeline

        会自动创建和配置所有需要的组件。

        Args:
            collection_name: Chroma 集合名称
            chunk_size: 文本分块大小
            chunk_overlap: 文本分块重叠大小
            search_k: 默认检索数量
        """
        print("=" * 50)
        print("初始化 RAG Pipeline")
        print("=" * 50)

        # 步骤 1: 初始化 Embedder
        # Embedder 需要先创建，因为 VectorStore 需要知道向量维度
        self.embedder = Embedder()

        # 获取向量维度用于创建 VectorStore
        embedding_dim = self.embedder.get_dimension()

        # 步骤 2: 初始化 VectorStore
        self.vectorstore = VectorStore(
            collection_name=collection_name,
            embedding_dimension=embedding_dim
        )

        # 步骤 3: 初始化其他组件
        self.loader = DocumentLoader()
        self.chunker = TextChunker(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap
        )
        self.retriever = Retriever(
            embedder=self.embedder,
            vectorstore=self.vectorstore,
            search_k=search_k
        )
        self.prompt_builder = RAGPromptBuilder()

        print("\n✓ RAG Pipeline 初始化完成")
        print(f"  向量维度: {embedding_dim}")
        print(f"  集合名称: {collection_name}")
        print(f"  分块大小: {chunk_size} / 重叠: {chunk_overlap}")
        print(f"  检索数量: {search_k}")

    def ingest_document(self, file_path: str) -> bool:
        """
        文档入库流程

        完整的文档处理流程：
        1. 加载文档
        2. 文本分块
        3. 向量化
        4. 存储到向量数据库

        Args:
            file_path: 文档路径（支持 PDF、TXT、MD）

        Returns:
            成功返回 True，失败返回 False

        使用示例:
            success = pipeline.ingest_document("mydoc.pdf")
            if success:
                print("文档入库成功")
        """
        # 去除路径中可能的引号（用户输入时常会加引号）
        # strip('"') 移除首尾的引号
        file_path = file_path.strip('"').strip("'")

        print(f"\n{'=' * 50}")
        print(f"文档入库: {Path(file_path).name}")
        print(f"{'=' * 50}")

        try:
            # 步骤 1: 加载文档
            print("\n📄 步骤 1/4: 加载文档")
            documents = self.loader.load(file_path)
            print(f"   原始页数/块数: {len(documents)}")

            # 步骤 2: 文本分块
            print("\n✂️ 步骤 2/4: 文本分块")
            chunks = self.chunker.split_documents(documents)
            print(f"   分块后数量: {len(chunks)}")

            # 如果只有一个块且内容很短，可能不需要分块
            # 这里仅作展示，实际可能不需要这个判断
            if len(chunks) == len(documents):
                print("   (文档较短，未进一步分块)")

            # 步骤 3: 向量化
            print("\n🔢 步骤 3/4: 向量化")
            # 提取所有块的文本内容
            texts = [chunk.page_content for chunk in chunks]
            # 批量生成向量
            embeddings = self.embedder.embed_documents(texts)
            print(f"   生成向量: {len(embeddings)} 个")
            print(f"   向量维度: {len(embeddings[0])}")

            # 步骤 4: 存储到向量数据库
            print("\n💾 步骤 4/4: 存储到向量库")
            self.vectorstore.add_documents(chunks, embeddings)

            print(f"\n✅ 文档入库完成: {Path(file_path).name}")
            return True

        except Exception as e:
            print(f"\n❌ 文档入库失败: {str(e)}")
            return False

    def ingest_directory(self, dir_path: str, recursive: bool = True) -> int:
        """
        批量入库整个目录的文档

        Args:
            dir_path: 目录路径
            recursive: 是否递归处理子目录

        Returns:
            成功入库的文件数量
        """
        print(f"\n{'=' * 50}")
        print(f"批量入库目录: {dir_path}")
        print(f"{'=' * 50}")

        try:
            # 加载目录中所有文档
            documents = self.loader.load_directory(dir_path, recursive)

            if not documents:
                print("⚠ 没有可处理的文档")
                return 0

            # 分块
            chunks = self.chunker.split_documents(documents)

            # 向量化
            texts = [chunk.page_content for chunk in chunks]
            embeddings = self.embedder.embed_documents(texts)

            # 存储
            self.vectorstore.add_documents(chunks, embeddings)

            # 统计成功数（根据 source 统计）
            sources = set(chunk.metadata.get("source") for chunk in chunks)
            print(f"\n✅ 批量入库完成: {len(sources)} 个文件，{len(chunks)} 个块")
            return len(sources)

        except Exception as e:
            print(f"\n❌ 批量入库失败: {str(e)}")
            return 0

    def query(
        self,
        question: str,
        k: int = None,
        return_context: bool = False
    ) -> Dict[str, Any]:
        """
        RAG 查询流程

        完整的问答流程：
        1. 检索相关文档
        2. 构建 Prompt
        3. 调用 LLM 生成回答
        4. 提取来源信息

        Args:
            question: 用户问题
            k: 检索文档数量，None 使用默认值
            return_context: 是否返回完整的上下文内容

        Returns:
            字典，包含：
            - question: 原始问题
            - answer: LLM 生成的回答
            - sources: 来源列表
            - context: 检索到的上下文（如果 return_context=True）

        使用示例:
            result = pipeline.query("什么是Python？")
            print(result["answer"])
            for src in result["sources"]:
                print(f"- {src}")
        """
        print(f"\n{'=' * 50}")
        print(f"RAG 查询: {question}")
        print(f"{'=' * 50}")

        # 步骤 1: 检索相关文档
        print("\n🔍 步骤 1/3: 检索相关文档")
        results = self.retriever.retrieve(question, k=k)

        if not results:
            print("⚠ 未找到相关文档")
            return {
                "question": question,
                "answer": "根据现有文档无法回答该问题。",
                "sources": [],
                "context": "" if not return_context else ""
            }

        print(f"   检索到 {len(results)} 个相关文档")
        for doc, score in results:
            source = doc.metadata.get("source", "未知")
            print(f"   - [{score:.2f}] {source}")

        # 步骤 2: 构建 Prompt
        print("\n📝 步骤 2/3: 构建 Prompt")
        context = self.retriever.format_context(results, include_source=True)
        prompt = self.prompt_builder.build(context, question)
        print(f"   Prompt 长度: {len(prompt)} 字符")

        # 步骤 3: 调用 LLM
        print("\n🤖 步骤 3/3: 生成回答")
        try:
            # 从 chat 模块导入 ChatSession
            # 使用已有的对话能力
            sys.path.append(str(Path(__file__).parent.parent))
            from chat.session import ChatSession

            # 创建临时会话用于 RAG 回答
            # 使用 RAG 专用 system prompt
            rag_system_prompt = """你是一个基于文档回答问题的助手。
请根据提供的参考文档回答问题。
如果文档中没有相关信息，请明确说明"根据现有文档无法回答"。
回答要准确、简洁，并标注信息来源。"""

            session = ChatSession(system_prompt=rag_system_prompt)

            # 发送 Prompt 并获取回答
            answer = session.chat(prompt, stream=False)

            # 提取来源信息
            sources = self._extract_sources(results)

            # 构建结果
            result = {
                "question": question,
                "answer": answer,
                "sources": sources
            }

            if return_context:
                result["context"] = context

            print(f"\n✅ 回答生成完成")
            return result

        except Exception as e:
            print(f"\n❌ 生成回答失败: {str(e)}")
            return {
                "question": question,
                "answer": f"生成回答时出错: {str(e)}",
                "sources": [],
                "context": "" if not return_context else ""
            }

    def _extract_sources(self, results: List[tuple]) -> List[Dict[str, Any]]:
        """
        从检索结果中提取来源信息

        Args:
            results: 检索结果列表

        Returns:
            来源信息列表
        """
        sources = []
        seen = set()  # 用于去重

        for doc, score in results:
            source = doc.metadata.get("source", "未知")
            page = doc.metadata.get("page")

            # 创建唯一标识用于去重
            key = f"{source}:{page}" if page is not None else source

            if key not in seen:
                seen.add(key)
                source_info = {
                    "source": source,
                    "score": round(score, 4)
                }
                if page is not None:
                    source_info["page"] = page + 1  # 转换为 1-based
                sources.append(source_info)

        return sources

    def search_only(self, query: str, k: int = 4) -> List[Dict[str, Any]]:
        """
        仅检索，不生成回答

        用于测试检索效果或查看相关文档。

        Args:
            query: 查询文本
            k: 返回结果数量

        Returns:
            检索结果列表，每个元素包含文档内容和元数据
        """
        results = self.retriever.retrieve(query, k=k)

        output = []
        for doc, score in results:
            output.append({
                "content": doc.page_content,
                "metadata": doc.metadata,
                "score": score
            })

        return output

    def list_documents(self) -> List[Dict[str, Any]]:
        """
        列出所有已入库的文档

        Returns:
            文档列表，包含 source 和 chunk_count
        """
        return self.vectorstore.list_documents()

    def delete_document(self, source: str) -> int:
        """
        删除指定来源的文档

        Args:
            source: 文档来源（文件名）

        Returns:
            删除的块数
        """
        return self.vectorstore.delete_document(source)

    def get_stats(self) -> Dict[str, Any]:
        """
        获取 Pipeline 统计信息

        Returns:
            统计字典
        """
        return {
            "collection_name": self.vectorstore.collection_name,
            "total_chunks": self.vectorstore.count(),
            "embedding_model": self.embedder.model_name,
            "embedding_dimension": self.embedder.get_dimension(),
            "chunk_size": self.chunker.chunk_size,
            "chunk_overlap": self.chunker.chunk_overlap,
            "search_k": self.retriever.search_k
        }


# ============================================
# 测试代码
# ============================================

if __name__ == "__main__":
    print("=" * 60)
    print("测试 RAGPipeline 模块")
    print("=" * 60)

    try:
        # 创建测试文档
        test_dir = Path("test_rag_docs")
        test_dir.mkdir(exist_ok=True)

        test_file = test_dir / "python_intro.txt"
        test_file.write_text("""
Python 是一种广泛使用的高级编程语言。
它由 Guido van Rossum 于 1991 年创建。

Python 的设计理念强调代码的可读性和简洁性。
它使用缩进来表示代码块，这使得代码结构清晰易读。

Python 支持多种编程范式，包括面向对象、函数式和过程式编程。
它有丰富的标准库和第三方库。

Python 在数据科学、人工智能、Web 开发等领域非常流行。
许多知名公司使用 Python，包括 Google、Facebook、Netflix 等。
""", encoding="utf-8")

        print("\n1. 初始化 Pipeline:")
        pipeline = RAGPipeline(
            collection_name="test_pipeline",
            chunk_size=200,
            chunk_overlap=20
        )

        print("\n2. 测试文档入库:")
        success = pipeline.ingest_document(str(test_file))
        print(f"   入库结果: {'成功' if success else '失败'}")

        print("\n3. 测试查询:")
        # 注意：此测试需要配置 API Key 才能调用 LLM
        # 如果没有配置，会失败
        result = pipeline.query("Python 是谁创建的？", k=2)
        print(f"   问题: {result['question']}")
        print(f"   回答: {result['answer'][:100]}...")
        print(f"   来源: {result['sources']}")

        print("\n4. 测试仅检索:")
        search_results = pipeline.search_only("Python 特点", k=2)
        print(f"   检索到 {len(search_results)} 个结果")
        for i, r in enumerate(search_results):
            print(f"   {i+1}. [{r['score']:.2f}] {r['content'][:50]}...")

        print("\n5. 测试列出文档:")
        docs = pipeline.list_documents()
        for doc in docs:
            print(f"   - {doc['source']}: {doc['count']} 块")

        print("\n6. 查看统计:")
        stats = pipeline.get_stats()
        for key, value in stats.items():
            print(f"   {key}: {value}")

        # 清理
        import shutil
        if test_dir.exists():
            shutil.rmtree(test_dir)
            print(f"\n🧹 清理测试文件")

        print("\n✓ 所有测试通过!")

    except Exception as e:
        print(f"\n✗ 测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
