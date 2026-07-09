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

# json 用于构造/解析重排序 API 的请求和响应
import json
# urllib.request 是 Python 标准库的 HTTP 客户端（零依赖，不用装 requests）
# 用于调用硅基流动的 rerank 接口
import urllib.request

from typing import List, Tuple, Optional
from langchain_core.documents import Document

# 导入配置（重排序需要 API Key 和地址）
from config import Config

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

        # ----------------------------------------
        # 【调优新增】重排序（Rerank）配置
        # ----------------------------------------
        # 什么是重排序？为什么需要它？
        # - 向量检索是「粗召回」：把问题和文档各自压缩成一个向量再比距离，
        #   速度快但精度有限——尤其当语料里到处都是相似的关键词时
        #   （比如满篇「规范/审核/命名」的会议纪要），容易把真正含答案的块挤出去
        # - 重排序模型是「精排」：把「问题+候选块」成对送入模型做交叉比对，
        #   逐对打分，精度远高于向量距离
        # - 两阶段策略：向量粗召回 top-N（大范围捞）→ 重排序精选 top-k（精确排）
        #
        # 硅基流动提供 BAAI/bge-reranker-v2-m3 重排序模型，
        # 检测到硅基流动时自动启用；其他平台没有此接口则自动关闭
        if "siliconflow" in Config.OPENAI_BASE_URL.lower():
            # 启用重排序，记录模型名
            self.rerank_model = "BAAI/bge-reranker-v2-m3"
            # 重排序分数阈值（实测校准）：
            # bge-reranker-v2-m3 对这类「条目式短块」打分整体偏低，
            # 实测真正含答案的块可能只有 0.05~0.3，无关块通常 <0.01
            # 所以阈值设 0.02：低于它才判定「知识库里没有相关内容」
            self.low_score_threshold = 0.02
            print(f"  重排序: 已启用 ({self.rerank_model})")
        else:
            # 不启用重排序（退回纯向量检索）
            self.rerank_model = None
            # 纯向量模式下用余弦相似度阈值
            self.low_score_threshold = 0.40
            print(f"  重排序: 未启用（非硅基流动平台）")

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

        # 步骤 2: 向量粗召回
        # 【调优】如果启用了重排序，先大范围召回候选，再交给重排序精选
        # 实测教训：小语料被大量「关键词相近」的噪声块主导时，
        # 真正含答案的块可能排在向量召回的第 50~60 名开外，
        # 召回太浅（如 top-20）会让重排序根本见不到答案块
        # 所以召回深度取 max(k*15, 100)，同时不超过库里的总块数
        if self.rerank_model:
            recall_k = min(max(k * 15, 100), self.vectorstore.count())
        else:
            # 没启用重排序则直接取 k 个
            recall_k = k

        # 在向量数据库中搜索
        # 返回 (Document, score) 元组列表
        results = self.vectorstore.similarity_search(
            query_embedding=query_embedding,
            k=recall_k
        )

        # 步骤 2.5: 【调优新增】重排序精排
        # 把粗召回的候选块交给重排序模型逐对打分，取分数最高的 k 个
        if self.rerank_model and results:
            results = self._rerank(query, results, top_k=k)

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

        # 步骤 4: 【调优新增】相邻块扩展
        # 一条完整的规定常常被切在两个块的边界上
        # （比如审核清单的「1、安全」在上一块，「2、代码质量」在下一块）
        # 把排名靠前的块的「前后邻居」也带上，能补全被切断的上下文
        if results:
            results = self._expand_neighbors(results)

        return results

    def _expand_neighbors(
        self,
        results: List[Tuple[Document, float]],
        top_n: int = 3,
        max_added: int = 6
    ) -> List[Tuple[Document, float]]:
        """
        相邻块扩展：给排名前 top_n 的块补充其前后相邻的块

        原理：
        - 每个块的 metadata 里有 source（所属文档）和 chunk_index（序号）
        - 「同文档、序号 ±1」的块就是物理上相邻的内容
        - 直接用 Chroma 的 get 按条件取出（本地操作，不花钱不耗时）

        Args:
            results: 已排序的检索结果
            top_n: 只给前几名扩展邻居（避免上下文爆炸），默认 3
            max_added: 最多补充几个邻居块，默认 6

        Returns:
            原结果 + 邻居块（邻居排在后面，分数略低于其锚点块）
        """
        # 用（source, chunk_index）组合做去重键
        # 集合推导式：把已有结果的键都收集起来
        existing = {
            (doc.metadata.get("source"), doc.metadata.get("chunk_index"))
            for doc, _ in results
        }

        # 收集新增的邻居块
        added = []

        # 只处理排名前 top_n 的块
        for doc, score in results[:top_n]:
            # 取出锚点块的来源和序号
            source = doc.metadata.get("source")
            idx = doc.metadata.get("chunk_index")

            # 缺少必要信息就跳过（比如手工插入的数据）
            if source is None or idx is None:
                continue

            # 尝试取前一块（idx-1）和后一块（idx+1）
            for n_idx in (idx - 1, idx + 1):
                # 序号不能是负数；已存在的不重复取
                if n_idx < 0 or (source, n_idx) in existing:
                    continue

                # 到达数量上限就不再补充
                if len(added) >= max_added:
                    break

                try:
                    # 用 Chroma 的条件查询取出这个邻居块
                    # $and 表示两个条件都要满足
                    fetch = self.vectorstore.collection.get(
                        where={"$and": [
                            {"source": source},
                            {"chunk_index": n_idx}
                        ]}
                    )

                    # 如果查到了（ids 非空），构建 Document 加入结果
                    if fetch and fetch["ids"]:
                        neighbor = Document(
                            page_content=fetch["documents"][0],
                            metadata=fetch["metadatas"][0]
                        )
                        # 邻居的分数用「锚点分数 × 0.99」：
                        # 略低于锚点，表示它是「陪同上榜」而非自己检索命中
                        added.append((neighbor, score * 0.99))
                        # 记入去重集合
                        existing.add((source, n_idx))

                except Exception:
                    # 单个邻居取失败不影响整体检索
                    continue

        # 邻居块追加在主结果后面返回
        return results + added

    def _rerank(
        self,
        query: str,
        results: List[Tuple[Document, float]],
        top_k: int
    ) -> List[Tuple[Document, float]]:
        """
        调用硅基流动的重排序 API，对候选块精排

        工作原理：
        - 把「问题」和每个「候选块」成对送入 bge-reranker-v2-m3 模型
        - 模型对每一对输出 0~1 的相关度分数（越高越相关）
        - 按分数从高到低取前 top_k 个

        Args:
            query: 用户的查询文本
            results: 向量粗召回的 (Document, 余弦分数) 列表
            top_k: 精排后保留的数量

        Returns:
            精排后的 (Document, 重排序分数) 列表
            如果 API 调用失败，退回原始的向量排序结果（保证可用性）
        """
        try:
            # 提取所有候选块的文本
            documents_text = [doc.page_content for doc, _ in results]

            # 构造 rerank API 的请求体（JSON 格式）
            payload = json.dumps({
                "model": self.rerank_model,       # 重排序模型名
                "query": query,                   # 用户问题
                "documents": documents_text,      # 候选文本列表
                "top_n": top_k                    # 只要前 top_k 个
            }).encode("utf-8")

            # 构造 HTTP 请求
            # 硅基流动的 rerank 接口地址是 {base_url}/rerank
            # Config.OPENAI_BASE_URL 形如 https://api.siliconflow.cn/v1
            req = urllib.request.Request(
                url=f"{Config.OPENAI_BASE_URL.rstrip('/')}/rerank",
                data=payload,
                headers={
                    # Bearer 认证，复用 OpenAI/硅基流动的 Key
                    "Authorization": f"Bearer {Config.OPENAI_API_KEY}",
                    "Content-Type": "application/json"
                },
                method="POST"
            )

            # 发送请求并读取响应（超时 30 秒防止卡死）
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            # 解析响应：data["results"] 是列表，
            # 每个元素包含 index（候选块的原始下标）和 relevance_score（相关度）
            reranked = []
            for item in data["results"]:
                # 用 index 找回对应的 Document 对象
                doc = results[item["index"]][0]
                # 相关度分数
                score = item["relevance_score"]
                reranked.append((doc, score))

            # API 已按分数降序返回，直接切前 top_k（保险起见再切一次）
            return reranked[:top_k]

        except Exception as e:
            # 重排序失败（网络问题、接口变更等）不应导致整个检索失败
            # 打印警告，退回向量检索的原始排序（取前 top_k）
            print(f"⚠ 重排序失败，退回向量排序: {str(e)}")
            return results[:top_k]

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
                # 只显示文件名，不显示完整路径（更干净，也便于 LLM 引用）
                # Path(source).name 从 "E:\xxx\编码规范.txt" 提取出 "编码规范.txt"
                from pathlib import Path as _Path
                source = _Path(source).name
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
    #
    # 【调优说明】模板经过针对性优化：
    # 1. 明确要求「综合归纳」——答案常分散在多个片段（多Chunk聚合/跨文件联查）
    # 2. 明确「时间线规则」——会议纪要类文档有先后，最新的规定优先（时间推理）
    # 3. 收紧「拒答条件」——只有所有片段都无关才拒答，避免轻易放弃
    # 4. 保留「不臆测」要求——文档没提的规定不能编造（防幻觉）
    DEFAULT_TEMPLATE = """你是一个基于文档回答问题的助手。请根据参考文档回答用户问题。

回答要求：
1. 仔细阅读每一个文档片段，答案可能分散在多个片段中，请综合归纳后作答
2. 如果不同片段是不同时间的规定（如会议纪要），以时间最新的规定为准；说明规定演变过程时，请标注文档中出现的具体时间（年份、日期）
3. 回答末尾标注信息来源的文档名
4. 只有当所有参考文档都与问题无关时，才回答「根据现有文档无法回答」
5. 严禁编造文档中不存在的规定；如果文档确实没有提及问题所问的内容，请明确说明「文档中未规定」，不要臆测

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
