#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
长期记忆模块 (LongTermMemory) —— V3 新增

什么是「长期记忆」？
- 短期记忆：当前这一次对话的 messages 列表（关掉程序就没了）
- 长期记忆：跨对话保存的信息，比如「用户喜欢用 Python」「用户在学 LangChain」
  即使关掉程序、下次重新打开，助手依然「记得」

为什么用 Chroma（向量数据库）来存长期记忆？
- 记忆需要「按语义检索」：用户问「我之前想学什么？」时，
  要能找到语义相关的记忆，而不是精确匹配关键词
- 这正是向量数据库擅长的：把记忆变成向量，按相似度召回
- 我们复用 V2 已经写好的 Embedder（向量化）和 VectorStore（Chroma 封装）

记忆的分类（category）：
- preference: 用户偏好（喜欢的语言、风格等）
- concept:    常用概念（用户反复提到的知识点）
- plan:       学习计划（「要复习 LangChain」）
- fact:       其他事实

设计要点：
- 记忆和知识库文档分开存放（不同的 Chroma 集合），互不干扰
- 每条记忆有唯一 source（mem_UUID），避免 ID 冲突被覆盖
"""

# 导入 sys 和 Path，用于把项目根目录加入模块搜索路径
import sys
from pathlib import Path

# 把项目根目录加入 sys.path，这样才能 import config 和 rag 包
# Path(__file__).parent.parent 是从 chat/memory.py 回到项目根目录
sys.path.append(str(Path(__file__).parent.parent))

# 导入 uuid 模块，用于生成全局唯一标识符
# uuid4() 会生成一个几乎不可能重复的随机字符串，保证每条记忆 ID 唯一
import uuid

# 导入 datetime，用于给每条记忆打上创建时间戳
from datetime import datetime

# 导入类型提示工具，让代码更清晰、IDE 更智能
from typing import List, Dict, Any, Optional

# 导入 LangChain 的 Document 类型
# VectorStore.add_documents 需要 Document 对象作为输入
from langchain_core.documents import Document

# 导入配置
from config import Config

# 复用 V2 已经写好的向量化和向量存储组件
# 这就是「不重复造轮子」——记忆本质上也是一段需要检索的文本
from rag.embedder import Embedder
from rag.vectorstore import VectorStore


class LongTermMemory:
    """
    长期记忆管理类

    负责把「值得记住的信息」存进向量数据库，并在需要时按语义召回。

    使用示例:
        memory = LongTermMemory()                 # 创建记忆模块
        memory.remember("我在学 LangChain", "plan")  # 记住一件事
        results = memory.recall("我在学什么？")       # 按语义召回
        text = memory.format_for_prompt("学习")      # 拼成可注入提示词的文本
    """

    def __init__(self):
        """
        初始化长期记忆模块

        流程：
        1. 创建 Embedder（把文本变成向量）
        2. 创建 VectorStore，使用专门的记忆集合（与文档知识库分开）
        """
        print("初始化长期记忆模块...")

        # 步骤 1: 创建向量化器
        # Embedder 内部会自动选择 OpenAI / 硅基流动 等后端
        self.embedder = Embedder()

        # 获取向量维度（不同模型维度不同，必须和数据库匹配）
        embedding_dim = self.embedder.get_dimension()

        # 步骤 2: 创建向量存储
        # collection_name 用 Config.MEMORY_COLLECTION（默认 long_term_memory）
        # 这样记忆和知识库文档（documents 集合）分开存放
        self.vectorstore = VectorStore(
            collection_name=Config.MEMORY_COLLECTION,
            embedding_dimension=embedding_dim
        )

        print("✓ 长期记忆模块就绪")

    def remember(
        self,
        content: str,
        category: str = "fact",
        extra_metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        记住一条信息（写入长期记忆）

        Args:
            content: 要记住的内容文本，例如「用户在学 LangChain」
            category: 记忆分类，可选 preference / concept / plan / fact
            extra_metadata: 额外的元数据（可选），比如 {"topic": "LangChain"}
                            注意：Chroma 的 metadata 只能存字符串/数字/布尔，不能存列表或 None

        Returns:
            这条记忆的唯一标识 source（字符串），可用于后续删除

        使用示例:
            source = memory.remember("我喜欢简洁的代码风格", "preference")
        """
        # 生成这条记忆的唯一 source 标识
        # uuid.uuid4() 生成随机 UUID，.hex 取其 32 位十六进制字符串
        # 加上 "mem_" 前缀，方便一眼看出这是一条记忆
        # 为什么要唯一？因为 VectorStore 用 source 生成文档 ID，
        # 如果 source 重复，新记忆会覆盖旧记忆
        source = f"mem_{uuid.uuid4().hex}"

        # 组装元数据字典
        # metadata 会和向量一起存进数据库，检索时可以拿回来
        metadata = {
            "source": source,                          # 唯一标识
            "category": category,                      # 分类
            "content": content,                        # 原文（方便直接读取）
            "created_at": datetime.now().isoformat()   # 创建时间（ISO 格式字符串）
        }

        # 如果调用者传了额外元数据，合并进来
        # dict.update() 把另一个字典的键值对合并到当前字典
        if extra_metadata:
            metadata.update(extra_metadata)

        # 把内容包装成 LangChain 的 Document 对象
        # page_content 是正文，metadata 是附加信息
        document = Document(page_content=content, metadata=metadata)

        # 把这段文本向量化
        # embed_documents 接收列表、返回列表，所以用 [content] 包一层
        embedding = self.embedder.embed_documents([content])

        # 存入向量数据库
        # add_documents 需要「文档列表」和「向量列表」一一对应
        self.vectorstore.add_documents([document], embedding)

        print(f"✓ 已记住 [{category}]: {content[:40]}...")

        # 返回 source，方便调用者以后删除这条记忆
        return source

    def recall(
        self,
        query: str,
        k: int = 3,
        category: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        按语义召回相关记忆

        Args:
            query: 查询文本，例如「我最近在学什么？」
            k: 最多返回几条记忆，默认 3
            category: 只在某个分类里找（可选），例如只找 plan

        Returns:
            记忆列表，每个元素是字典：
            {"content": 内容, "score": 相似度, "category": 分类, "metadata": 全部元数据}
            按相似度从高到低排序

        使用示例:
            memories = memory.recall("学习计划", k=2, category="plan")
        """
        # 把查询文本向量化
        query_embedding = self.embedder.embed_query(query)

        # 如果指定了分类，构造过滤条件
        # Chroma 的 where 参数用 {"字段": "值"} 表示「字段等于值」
        # None 表示不过滤（在所有记忆里找）
        filter_dict = {"category": category} if category else None

        # 在向量数据库中做相似度搜索
        # 返回 [(Document, similarity_score), ...] 列表
        results = self.vectorstore.similarity_search(
            query_embedding=query_embedding,
            k=k,
            filter_dict=filter_dict
        )

        # 把原始结果整理成更好用的字典列表
        output = []
        for doc, score in results:
            output.append({
                "content": doc.page_content,                         # 记忆内容
                "score": score,                                      # 相似度
                "category": doc.metadata.get("category", "fact"),    # 分类
                "metadata": doc.metadata                             # 完整元数据
            })

        return output

    def list_memories(
        self,
        category: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        列出所有记忆（不做相似度检索，直接读取）

        Args:
            category: 只列某个分类（可选）

        Returns:
            记忆列表，每个元素包含 content、category、source、created_at

        使用示例:
            all_plans = memory.list_memories(category="plan")
        """
        # 构造过滤条件（同 recall）
        filter_dict = {"category": category} if category else None

        # 直接用 Chroma 集合的 get 方法读取（VectorStore 暴露了 .collection）
        # get 不需要查询向量，直接按条件取出所有匹配的文档
        results = self.vectorstore.collection.get(where=filter_dict)

        # 如果没有任何记忆，返回空列表
        if not results or not results["ids"]:
            return []

        # 整理输出
        output = []
        # results["metadatas"] 是所有匹配文档的元数据列表
        for metadata in results["metadatas"]:
            output.append({
                "content": metadata.get("content", ""),
                "category": metadata.get("category", "fact"),
                "source": metadata.get("source", ""),
                "created_at": metadata.get("created_at", "")
            })

        # 按创建时间排序（新的在前）
        # reverse=True 表示降序；用 created_at 字符串排序（ISO 格式可直接比较）
        output.sort(key=lambda m: m["created_at"], reverse=True)

        return output

    def forget(self, source: str) -> bool:
        """
        删除一条记忆

        Args:
            source: 记忆的唯一标识（remember 返回的那个）

        Returns:
            删除成功返回 True，未找到返回 False
        """
        # 先按 source 查出对应的文档 ID
        results = self.vectorstore.collection.get(where={"source": source})

        # 如果没找到，返回 False
        if not results or not results["ids"]:
            print(f"⚠ 未找到记忆: {source}")
            return False

        # 删除这些 ID 对应的文档
        self.vectorstore.collection.delete(ids=results["ids"])
        print(f"✓ 已删除记忆: {source}")
        return True

    def format_for_prompt(self, query: str, k: int = 3) -> str:
        """
        把召回的记忆拼成一段文本，用于注入到 system prompt

        这是 Agent「记得用户」的关键：每次对话前，先根据当前问题
        召回相关的长期记忆，作为背景信息塞进系统提示词。

        Args:
            query: 当前用户问题，用它来召回相关记忆
            k: 召回几条记忆

        Returns:
            格式化后的记忆文本；如果没有相关记忆，返回空字符串

        使用示例:
            memory_text = memory.format_for_prompt("帮我写代码")
            system_prompt = base_prompt + memory_text
        """
        # 召回相关记忆
        memories = self.recall(query, k=k)

        # 如果没有相关记忆，返回空字符串（调用者据此决定是否拼接）
        if not memories:
            return ""

        # 构建记忆文本块
        lines = ["\n\n【关于用户的长期记忆（供参考，帮助你更懂用户）】"]
        for mem in memories:
            # 每条记忆一行：分类 + 内容
            lines.append(f"- [{mem['category']}] {mem['content']}")

        # 用换行符连接所有行
        return "\n".join(lines)


# ============================================
# 测试代码
# ============================================

# 只有直接运行本文件时才执行（import 时不执行）
if __name__ == "__main__":
    print("=" * 50)
    print("测试 LongTermMemory 模块")
    print("=" * 50)

    try:
        # 创建记忆模块
        memory = LongTermMemory()

        # 测试记住几条信息
        print("\n1. 测试记忆写入:")
        memory.remember("我正在学习 LangChain 和 LangGraph", "plan")
        memory.remember("我喜欢简洁、注释详细的 Python 代码", "preference")
        memory.remember("RAG 是检索增强生成", "concept")

        # 测试召回
        print("\n2. 测试语义召回 '我在学什么':")
        results = memory.recall("我在学什么", k=2)
        for r in results:
            print(f"   [{r['score']:.3f}] ({r['category']}) {r['content']}")

        # 测试列出所有记忆
        print("\n3. 测试列出所有记忆:")
        for m in memory.list_memories():
            print(f"   ({m['category']}) {m['content']}")

        # 测试拼接提示词
        print("\n4. 测试 format_for_prompt:")
        print(memory.format_for_prompt("代码风格"))

        print("\n✓ 所有测试通过!")

    except Exception as e:
        print(f"\n✗ 测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
