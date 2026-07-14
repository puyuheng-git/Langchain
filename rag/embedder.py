#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文本向量化模块 (Embedder)

Embedding（嵌入）是将文本转换为数值向量的技术。
核心思想：语义相似的文本，在向量空间中的距离也相近。

类比理解：
- 文本是人类的语言，Embedding 是机器能理解的数学表示
- 就像把地址转换为 GPS 坐标，通过坐标可以计算距离
- "猫"和" kitten"的向量距离，比"猫"和"汽车"更近

技术细节：
- 向量的维度通常是 768 或 1536（一个长数组）
- 使用余弦相似度计算两个向量的相似程度
- 相似度范围：-1（完全相反）到 1（完全相同），通常 0.7+ 算相似

支持的 Embedding 模型：
1. text-embedding-3-small (OpenAI): 1536维，效果好，需API Key
2. bge-m3 (BAAI): 768维，开源免费，可本地运行
"""

import sys
from pathlib import Path

# 将父目录添加到 Python 路径，以便导入 config 模块
# sys.path 是 Python 查找模块时会搜索的路径列表
sys.path.append(str(Path(__file__).parent.parent))

from typing import List

# 导入 LangChain 的 Embedding 封装
# LangChain 提供了统一的接口，底层可以是不同的模型
# 注意：LangChain 0.2+ 版本中，OpenAIEmbeddings 已移动到 langchain-openai
from langchain_openai import OpenAIEmbeddings

from config import Config


class Embedder:
    """
    Embedding 封装类

    提供统一的接口用于文本向量化，支持多种后端模型。
    使用 LangChain 的 Embeddings 接口，方便切换不同模型。

    使用示例:
        # 创建 Embedder 实例
        embedder = Embedder()

        # 单文本向量化
        vector = embedder.embed_query("你好，世界")
        print(len(vector))  # 输出: 1536 (维度)

        # 批量向量化
        texts = ["文本1", "文本2", "文本3"]
        vectors = embedder.embed_documents(texts)
        print(len(vectors))  # 输出: 3
    """

    def __init__(self, model_name: str = None):
        """
        初始化 Embedder

        Args:
            model_name: 指定使用的模型，None 则根据 Config 自动选择
                       可选值: "openai", "bge-m3"
        """
        # 如果没有指定模型，根据 Config.LLM_PROVIDER 选择
        # or 运算符：如果左边为真用左边，否则用右边
        self.model_name = model_name or self._auto_select_model()

        # 初始化对应的 Embedding 后端
        # _initialize_backend() 返回 LangChain 的 Embeddings 对象
        self.backend = self._initialize_backend()

        # 打印初始化信息，方便调试
        print(f"✓ Embedder 初始化完成: {self.model_name}")
        print(f"  使用模型: {self.backend.model}")
        print(f"  API地址: {self.backend.openai_api_base}")

    def _auto_select_model(self) -> str:
        """
        根据配置自动选择模型

        选择逻辑：
        - 如果有 OpenAI API Key，使用 OpenAI（效果最好）
        - 否则考虑本地模型（bge-m3）

        Returns:
            模型名称字符串
        """
        # 检查 Config 中是否有 OpenAI API Key
        # 注意：这里检查的是 OpenAI 的配置，因为 text-embedding-3-small 需要 OpenAI Key
        # 即使主 LLM 用 DeepSeek，Embedding 也可以用 OpenAI
        if Config.OPENAI_API_KEY:
            return "openai"

        # 如果没有 OpenAI Key，目前默认还是 openai
        # 后续可以改为本地模型
        # TODO: 支持本地 bge-m3 模型
        return "openai"

    def _initialize_backend(self):
        """
        初始化 Embedding 后端

        根据 model_name 创建对应的 LangChain Embeddings 对象

        Returns:
            LangChain Embeddings 对象

        Raises:
            ValueError: 如果模型名称不支持
        """
        # 使用 if-elif-else 结构处理不同的模型
        if self.model_name == "openai":
            # OpenAI Embedding
            # text-embedding-3-small 是 OpenAI 的小模型，性价比高
            # dimensions=1536 表示输出向量维度是 1536
            # 检查 API Key 是否配置
            if not Config.OPENAI_API_KEY or Config.OPENAI_API_KEY == "your_openai_api_key_here":
                raise ValueError(
                    "OPENAI_API_KEY 未配置！\n\n"
                    "RAG 功能需要 Embedding 服务，请配置以下之一：\n"
                    "1. OpenAI API Key（推荐，效果好）\n"
                    "   - 访问 https://platform.openai.com 获取\n"
                    "   - 或在 .env 中配置 OPENAI_API_KEY\n\n"
                    "2. 硅基流动（国内可用，OpenAI 兼容）\n"
                    "   - 访问 https://cloud.siliconflow.cn 注册\n"
                    "   - 配置 OPENAI_BASE_URL=https://api.siliconflow.cn/v1\n"
                    "   - 配置 OPENAI_API_KEY=你的硅基流动Key"
                )

            # 根据 base_url 判断使用哪个模型
            # OpenAI 官方使用 text-embedding-3-small
            # 硅基流动等国内平台使用 BAAI/bge-m3
            if "siliconflow" in Config.OPENAI_BASE_URL.lower():
                model_name = "BAAI/bge-m3"  # 硅基流动的 Embedding 模型
                print("   检测到硅基流动，使用 BAAI/bge-m3 模型")
            else:
                model_name = "text-embedding-3-small"  # OpenAI 官方模型

            return OpenAIEmbeddings(
                api_key=Config.OPENAI_API_KEY,      # API Key
                base_url=Config.OPENAI_BASE_URL,    # API 地址（支持代理）
                model=model_name,                   # 根据平台选择模型
            )

        elif self.model_name == "bge-m3":
            # BAAI/bge-m3 是一个开源的多语言 Embedding 模型
            # 支持中文，效果接近 OpenAI，可以本地运行
            # 需要安装: pip install sentence-transformers
            # 首次使用会自动下载模型（约 1GB）

            try:
                # 从 LangChain 导入 HuggingFace 封装
                from langchain_community.embeddings import HuggingFaceEmbeddings

                return HuggingFaceEmbeddings(
                    # 模型名称，从 HuggingFace Hub 下载
                    model_name="BAAI/bge-m3",
                    # 模型配置
                    model_kwargs={"device": "cpu"},  # 使用 CPU，如有 GPU 可改为 "cuda"
                    # 编码配置
                    encode_kwargs={"normalize_embeddings": True},  # 归一化向量
                )
            except ImportError as exc:
                # 如果没有安装 sentence-transformers，抛出错误
                raise ImportError(
                    "使用 bge-m3 需要安装 sentence-transformers:\n"
                    "pip install sentence-transformers"
                ) from exc

        else:
            # 不支持的模型名称
            raise ValueError(f"不支持的 Embedding 模型: {self.model_name}")

    def embed_query(self, text: str) -> List[float]:
        """
        将单个查询文本转换为向量

        这是用于用户提问时的向量化。
        与 embed_documents 的区别：某些模型对查询和文档使用不同的处理方式。

        Args:
            text: 输入的查询文本

        Returns:
            向量（浮点数列表），长度等于模型维度（1536 或 768）

        使用示例:
            vector = embedder.embed_query("Python是什么？")
            print(vector[:5])  # 打印前 5 个维度 [0.023, -0.156, ...]
        """
        # 调用 LangChain 后端的 embed_query 方法
        # 返回的是一个列表，包含所有维度的浮点数值
        return self.backend.embed_query(text)

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """
        批量将多个文档文本转换为向量

        这是用于文档入库时的向量化。
        批量处理比逐个处理更高效，因为可以利用 GPU 并行计算。

        Args:
            texts: 文本列表，每个元素是一个文档块

        Returns:
            向量列表，每个元素是一个浮点数列表（代表一个文档的向量）
            外层列表长度 = len(texts)
            内层列表长度 = 向量维度

        使用示例:
            docs = ["Python是编程语言", "Java也是编程语言"]
            vectors = embedder.embed_documents(docs)
            print(len(vectors))  # 输出: 2
        """
        # 调用 LangChain 后端的 embed_documents 方法
        # 会自动批量处理，提高效率
        return self.backend.embed_documents(texts)

    def get_dimension(self) -> int:
        """
        获取当前模型的向量维度

        用于创建向量数据库时指定维度。
        不同模型的维度不同，必须匹配。

        Returns:
            向量维度（如 1536 或 768）

        使用示例:
            dim = embedder.get_dimension()
            print(f"向量维度: {dim}")  # 输出: 向量维度: 1536
        """
        # 维度来自已选模型配置，初始化阶段不应为探测维度发起真实 API 请求。
        if self.model_name == "openai":
            # OpenAI 官方 text-embedding-3-small 为 1536 维；硅基流动的
            # BAAI/bge-m3 为 1024 维。
            if "siliconflow" in Config.OPENAI_BASE_URL.lower():
                return 1024
            return 1536
        if self.model_name == "bge-m3":
            return 1024
        raise ValueError(f"未知 Embedding 模型维度: {self.model_name}")


# ============================================
# 测试代码
# ============================================

if __name__ == "__main__":
    # 当直接运行此文件时，执行测试
    print("=" * 50)
    print("测试 Embedder 模块")
    print("=" * 50)

    try:
        # 创建 Embedder 实例
        embedder = Embedder()

        # 测试单文本向量化
        print("\n1. 测试单文本向量化:")
        query = "人工智能是一门研究如何让机器模拟人类智能的学科。"
        vector = embedder.embed_query(query)
        print(f"   输入文本: {query}")
        print(f"   向量维度: {len(vector)}")
        print(f"   向量前5维: {vector[:5]}")

        # 测试批量向量化
        print("\n2. 测试批量向量化:")
        docs = [
            "Python 是一种解释型编程语言。",
            "Java 是一种面向对象的编程语言。",
            "JavaScript 主要用于网页开发。"
        ]
        vectors = embedder.embed_documents(docs)
        print(f"   文档数量: {len(docs)}")
        print(f"   向量数量: {len(vectors)}")
        print(f"   每个向量维度: {len(vectors[0])}")

        # 测试相似度计算
        print("\n3. 测试语义相似度:")
        # 计算两个向量的余弦相似度
        import numpy as np

        v1 = embedder.embed_query("猫是一种宠物")
        v2 = embedder.embed_query("狗是一种宠物")
        v3 = embedder.embed_query("汽车是一种交通工具")

        # 余弦相似度计算
        # cos_sim = (A·B) / (||A|| * ||B||)
        def cosine_similarity(a, b):
            return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

        sim_1_2 = cosine_similarity(v1, v2)
        sim_1_3 = cosine_similarity(v1, v3)

        print(f"   '猫' vs '狗': {sim_1_2:.4f} (应该较高，都是宠物)")
        print(f"   '猫' vs '汽车': {sim_1_3:.4f} (应该较低，不相关)")

        print("\n✓ 所有测试通过!")

    except Exception as e:
        print(f"\n✗ 测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
