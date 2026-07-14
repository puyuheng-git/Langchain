#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
向量数据库模块 (VectorStore)

基于 Chroma 的向量存储和检索实现。

什么是向量数据库？
- 传统数据库存储结构化数据（如表格）
- 向量数据库存储向量（Embedding），支持相似度搜索
- 类比：传统数据库是"精确匹配"，向量数据库是"语义相似匹配"

Chroma 特点：
- 零配置：无需服务器，本地文件存储
- Python 原生：纯 Python 实现，易于使用
- 持久化：数据保存在本地文件，程序重启不丢失
- 轻量级：适合个人项目和小型应用

核心概念：
- Collection: 集合，类似数据库的表，存储一组相关文档
- Document: 文档，包含文本内容、向量、元数据
- Embedding: 向量，文档的数学表示
- Distance: 距离/相似度，用于衡量两个向量的相近程度

使用场景：
1. 文档入库：将文本 + 向量存入 Chroma
2. 相似度搜索：根据查询向量找出最相似的文档
"""

import hashlib
import sys
from pathlib import Path

# 将父目录添加到 Python 路径
sys.path.append(str(Path(__file__).parent.parent))

from typing import Any, Dict, List, Optional, Tuple

# 导入 ChromaDB
# Chroma 是一个开源的嵌入式向量数据库
import chromadb
from chromadb.config import Settings

# 导入 LangChain 的 Document 类型
# Document 是 LangChain 中用于表示文档的标准数据结构
from langchain_core.documents import Document

from config import Config


class VectorStore:
    """
    向量数据库封装类

    提供简化的接口用于：
    - 文档存储（add_documents）
    - 相似度搜索（similarity_search）
    - 集合管理（create/delete collection）

    使用示例:
        # 创建 VectorStore 实例
        vs = VectorStore()

        # 添加文档
        docs = [
            Document(page_content="Python 是编程语言", metadata={"source": "a.txt"}),
            Document(page_content="Java 也是编程语言", metadata={"source": "b.txt"})
        ]
        vs.add_documents(docs)

        # 搜索
        results = vs.similarity_search("编程语言", k=2)
        for doc in results:
            print(doc.page_content)
    """

    def __init__(
        self,
        collection_name: str = "documents",
        embedding_dimension: int = 1536
    ):
        """
        初始化向量数据库

        Args:
            collection_name: 集合名称，类似数据库的表名
                            可以创建多个集合存储不同类型的文档
            embedding_dimension: 向量维度，必须与 Embedding 模型匹配
                                OpenAI: 1536, bge-m3: 768
        """
        # 保存配置参数
        self.collection_name = collection_name
        self.embedding_dimension = embedding_dimension

        # Chroma 数据存储路径
        # 保存在 data/chroma_db/ 目录下
        self.persist_directory = str(Config.DATA_DIR / "chroma_db")

        # 初始化 Chroma 客户端
        # PersistentClient 会将数据持久化到磁盘
        self.client = chromadb.PersistentClient(
            path=self.persist_directory,
            # Settings 用于配置 Chroma 的行为
            settings=Settings(
                # anonymized_telemetry=False 关闭匿名遥测（隐私考虑）
                anonymized_telemetry=False,
                # allow_reset=True 允许重置数据库（清空所有数据）
                allow_reset=True
            )
        )

        # 获取或创建集合
        # 如果集合已存在则获取，不存在则创建
        self.collection = self._get_or_create_collection()

        print("✓ VectorStore 初始化完成")
        print(f"  集合名称: {collection_name}")
        print(f"  向量维度: {embedding_dimension}")
        print(f"  存储路径: {self.persist_directory}")

    def _get_or_create_collection(self):
        """
        获取或创建 Chroma 集合

        Returns:
            Chroma Collection 对象
        """
        try:
            # 尝试获取已存在的集合
            # get_collection 如果集合不存在会抛出异常
            collection = self.client.get_collection(name=self.collection_name)
            print(f"  使用已有集合: {self.collection_name}")
            return collection

        except Exception:
            # 集合不存在，创建新集合
            # create_collection 创建新集合
            collection = self.client.create_collection(
                name=self.collection_name,
                # metadata 用于存储集合的元数据
                metadata={"hnsw:space": "cosine"}  # 使用余弦相似度
            )
            print(f"  创建新集合: {self.collection_name}")
            return collection

    def add_documents(
        self,
        documents: List[Document],
        embeddings: List[List[float]]
    ) -> None:
        """
        添加文档到向量数据库

        这是文档入库的核心方法，将文档的文本、向量和元数据一起存储。

        Args:
            documents: Document 对象列表，每个包含 page_content 和 metadata
            embeddings: 向量列表，与 documents 一一对应
                        embeddings[i] 是 documents[i] 的向量表示

        重要说明：
        - documents 和 embeddings 的长度必须相同
        - 每个文档会被分配一个唯一 ID
        - 如果 ID 已存在，会覆盖原有数据

        使用示例:
            docs = [Document(page_content="Hello", metadata={"source": "a.txt"})]
            embs = [[0.1, 0.2, ...]]  # 对应的向量
            vs.add_documents(docs, embs)
        """
        # 检查输入有效性
        if len(documents) != len(embeddings):
            raise ValueError(
                f"documents 和 embeddings 数量不匹配: "
                f"{len(documents)} vs {len(embeddings)}"
            )

        # 如果没有文档，直接返回
        if not documents:
            print("⚠ 没有文档需要添加")
            return

        # 准备 Chroma 需要的数据格式
        # Chroma 需要三个列表：ids, embeddings, documents, metadatas

        # 同一来源重新入库前先移除旧分块，避免文档修改后旧内容继续被检索。
        sources = {
            str(doc.metadata.get("source", "unknown"))
            for doc in documents
        }
        for source in sources:
            self.collection.delete(where={"source": source})

        # ID 由来源、分块序号和内容共同计算，重复执行可稳定覆盖相同内容。
        ids = []
        for i, doc in enumerate(documents):
            # 从 metadata 中获取文件名，如果没有则使用 "unknown"
            source = doc.metadata.get("source", "unknown")
            digest_input = f"{source}\0{i}\0{doc.page_content}".encode("utf-8")
            doc_id = f"doc_{hashlib.sha256(digest_input).hexdigest()}"
            ids.append(doc_id)

        # documents: 文本内容列表
        # 从 Document 对象中提取 page_content
        texts = [doc.page_content for doc in documents]

        # metadatas: 元数据列表
        # 从 Document 对象中提取 metadata
        metadatas = [doc.metadata for doc in documents]

        # upsert 同时支持首次写入和相同 ID 的更新。
        self.collection.upsert(
            ids=ids,                    # 唯一标识符列表
            embeddings=embeddings,      # 向量列表
            documents=texts,            # 原始文本列表
            metadatas=metadatas         # 元数据列表
        )

        print(f"✓ 成功添加 {len(documents)} 个文档到向量数据库")

    def similarity_search(
        self,
        query_embedding: List[float],
        k: int = 4,
        filter_dict: Optional[Dict[str, Any]] = None
    ) -> List[Tuple[Document, float]]:
        """
        相似度搜索

        根据查询向量找出最相似的 k 个文档。
        这是 RAG 检索的核心方法。

        Args:
            query_embedding: 查询文本的向量表示
            k: 返回最相似的 k 个文档，默认 4
            filter_dict: 可选的过滤条件，用于元数据筛选
                        例如 {"source": "xxx.pdf"} 只搜索特定文件

        Returns:
            列表，每个元素是 (Document, similarity_score) 元组
            Document: 匹配的文档对象
            similarity_score: 相似度分数（余弦相似度，越高越相似）

        使用示例:
            query_vec = embedder.embed_query("什么是Python？")
            results = vs.similarity_search(query_vec, k=3)
            for doc, score in results:
                print(f"相似度: {score:.4f}, 内容: {doc.page_content[:50]}")
        """
        # 调用 Chroma 的 query 方法
        # query_embeddings: 查询向量（列表的列表，支持批量查询）
        # n_results: 返回结果数量
        # where: 过滤条件（可选）
        results = self.collection.query(
            query_embeddings=[query_embedding],  # 注意：需要包装成列表
            n_results=k,
            where=filter_dict  # 如果为 None，Chroma 会忽略
        )

        # 解析 Chroma 返回的结果
        # Chroma 返回的是嵌套列表结构，需要转换为 List[(Document, score)]

        output = []

        # results 包含 ids, distances, documents, metadatas 等字段
        # 因为我们只查询了一个向量，所以取第 0 个元素
        # 如果批量查询，会有多个结果列表

        # 获取返回的文档数量（可能没有 k 个，如果数据库中文档不足）
        num_results = len(results["ids"][0]) if results["ids"] else 0

        for i in range(num_results):
            # 构建 Document 对象
            doc = Document(
                page_content=results["documents"][0][i],
                metadata=results["metadatas"][0][i]
            )

            # 获取相似度分数
            # Chroma 返回的是距离（distance），余弦距离 = 1 - 相似度
            # 所以相似度 = 1 - distance
            distance = results["distances"][0][i]
            similarity = 1 - distance

            output.append((doc, similarity))

        return output

    def delete_document(self, source: str) -> int:
        """
        删除指定来源的所有文档

        Args:
            source: 文档来源（metadata 中的 source 字段）
                   通常是文件名

        Returns:
            删除的文档数量

        使用示例:
            count = vs.delete_document("mydoc.pdf")
            print(f"删除了 {count} 个文档块")
        """
        # 首先查询符合条件的文档
        # where 参数用于元数据过滤
        results = self.collection.get(
            where={"source": source}
        )

        # 如果没有匹配的文档，返回 0
        if not results or not results["ids"]:
            print(f"⚠ 没有找到来源为 '{source}' 的文档")
            return 0

        # 获取所有匹配的文档 ID
        ids_to_delete = results["ids"]

        # 删除这些文档
        self.collection.delete(ids=ids_to_delete)

        print(f"✓ 删除了 {len(ids_to_delete)} 个来自 '{source}' 的文档块")
        return len(ids_to_delete)

    def list_documents(self) -> List[Dict[str, Any]]:
        """
        列出所有已存储的文档来源

        Returns:
            文档来源列表，每个字典包含 source 和 count
            例如 [{"source": "a.pdf", "count": 5}, {"source": "b.txt", "count": 3}]

        使用示例:
            docs = vs.list_documents()
            for doc in docs:
                print(f"{doc['source']}: {doc['count']} 块")
        """
        # 获取集合中的所有文档
        results = self.collection.get()

        if not results or not results["ids"]:
            return []

        # 统计每个 source 的文档数量
        source_counts = {}

        for metadata in results["metadatas"]:
            source = metadata.get("source", "unknown")
            source_counts[source] = source_counts.get(source, 0) + 1

        # 转换为列表格式
        output = [
            {"source": source, "count": count}
            for source, count in source_counts.items()
        ]

        # 按 source 名称排序
        output.sort(key=lambda x: x["source"])

        return output

    def count(self) -> int:
        """
        获取集合中的文档总数

        Returns:
            文档数量
        """
        return self.collection.count()

    def reset(self) -> None:
        """
        清空整个集合（危险操作！）

        删除集合中的所有文档，不可恢复。
        用于重新开始或测试。
        """
        # 获取所有文档 ID
        results = self.collection.get()

        if results and results["ids"]:
            # 删除所有文档
            self.collection.delete(ids=results["ids"])
            print(f"✓ 已清空集合，删除了 {len(results['ids'])} 个文档")
        else:
            print("⚠ 集合已经是空的")


# ============================================
# 测试代码
# ============================================

if __name__ == "__main__":
    print("=" * 50)
    print("测试 VectorStore 模块")
    print("=" * 50)

    try:
        # 创建 VectorStore 实例
        # 使用 3 维向量便于测试（实际使用 1536 或 768）
        vs = VectorStore(
            collection_name="test_collection",
            embedding_dimension=3
        )

        print("\n1. 测试添加文档:")
        # 创建测试文档
        docs = [
            Document(
                page_content="Python 是一种解释型编程语言",
                metadata={"source": "python_intro.txt", "page": 1}
            ),
            Document(
                page_content="Java 是一种编译型编程语言",
                metadata={"source": "java_intro.txt", "page": 1}
            ),
            Document(
                page_content="Python 有丰富的第三方库",
                metadata={"source": "python_intro.txt", "page": 2}
            )
        ]

        # 创建测试向量（实际应该来自 Embedder）
        # 这里手动创建简单的向量用于测试
        embeddings = [
            [1.0, 0.0, 0.0],  # 对应 Python 文档 1
            [0.0, 1.0, 0.0],  # 对应 Java 文档
            [0.9, 0.1, 0.0]   # 对应 Python 文档 2（与 doc1 相似）
        ]

        vs.add_documents(docs, embeddings)

        print("\n2. 测试文档总数:")
        total = vs.count()
        print(f"   数据库中共有 {total} 个文档块")

        print("\n3. 测试列出所有文档来源:")
        sources = vs.list_documents()
        for src in sources:
            print(f"   {src['source']}: {src['count']} 块")

        print("\n4. 测试相似度搜索:")
        # 使用与 doc1 相似的查询向量
        query_vec = [1.0, 0.0, 0.0]
        results = vs.similarity_search(query_vec, k=2)
        print("   搜索结果:")
        for doc, score in results:
            print(f"   - 相似度: {score:.4f}, 内容: {doc.page_content[:30]}...")

        print("\n5. 测试删除文档:")
        deleted = vs.delete_document("java_intro.txt")
        print(f"   删除后剩余文档数: {vs.count()}")

        print("\n✓ 所有测试通过!")

    except Exception as e:
        print(f"\n✗ 测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
