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
        chunk_size: int = 400,
        chunk_overlap: int = 80,
        search_k: int = 6
    ):
        """
        初始化 RAG Pipeline

        会自动创建和配置所有需要的组件。

        Args:
            collection_name: Chroma 集合名称
            chunk_size: 文本分块大小
            chunk_overlap: 文本分块重叠大小
            search_k: 默认检索数量

        【调优说明】默认参数从 (1000/100/4) 调整为 (400/80/6)：
        - chunk_size 1000→400: 大块会混杂多个主题，向量被「平均稀释」，
          导致包含答案的块反而排不进 Top-K（实测正是「无法回答」的主因）。
          小块主题单一，向量更「尖锐」，检索更精准。
        - chunk_overlap 80: 保持约 20% 重叠，避免关键信息被切在边界
        - search_k 4→6: 总结/跨文件类问题需要更多片段做综合归纳
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

    def _enrich_chunks(self, chunks: List[Document]) -> List[Document]:
        """
        块内容增强：给每个块加上《文档名》前缀 + 继承最近的日期上下文

        为什么要这么做？（调优关键点）

        1. 《文档名》前缀（Contextual Chunk Headers）：
           - 一个块被单独切出来后，就「失去了它属于哪个文档」的上下文
           - 加上《编码规范》前缀后，用户问「编码规范」时相似度显著提高
           - LLM 看到块时也能知道出处，引用更准

        2. 日期继承（时间上下文传播）：
           - 会议纪要类文档的日期（如「2025年04月24日会议」）通常只出现在
             每段会议的第一个块里，后续块被切开后就「不知道自己属于哪次会议」
           - LLM 拿到没有日期的块，就无法回答「最新规定」「制度演进」类问题
           - 解决：按顺序扫描块，记住「最近出现的日期」，
             给没有日期的块补上〔时间上下文〕标注

        Args:
            chunks: 分块后的 Document 列表（同一文档的块按顺序排列）

        Returns:
            增强后的 Document 列表（原地修改并返回）
        """
        # 导入正则模块，用于在块文本中查找日期
        import re

        # 日期匹配模式，覆盖文档中出现的几种写法：
        # 「2025年04月24日」「2023-04-07」「2024-01」「2026年」等
        # 20\d{2} 匹配 2000-2099 的年份
        date_pattern = re.compile(
            r"20\d{2}\s*[年\-/.]\s*\d{1,2}(?:\s*[月\-/.]\s*\d{1,2})?[日号]?"
            r"|20\d{2}\s*年"
        )

        # 记录「每个文档最近出现的日期」
        # 键是 source（文档路径），值是最近一次匹配到的日期字符串
        last_date_by_source = {}

        # 按顺序遍历每个块（split_documents 保证同一文档的块是有序的）
        for chunk in chunks:
            # 从 metadata 取出来源（完整路径）
            source = chunk.metadata.get("source", "")
            # Path(...).stem 提取「不带扩展名的文件名」
            # 例如 "E:\xxx\编码规范.txt" → "编码规范"
            doc_name = Path(source).stem if source else "未知文档"

            # 避免重复添加前缀（重复入库时可能再走一遍）
            if chunk.page_content.startswith(f"《{doc_name}》"):
                continue

            # ----- 日期继承逻辑 -----
            # 在当前块的原文里找所有日期
            dates_in_chunk = date_pattern.findall(chunk.page_content)

            if dates_in_chunk:
                # 块里有日期：更新「最近日期」为块内最后出现的那个
                # （因为后续块属于块内最后开始的那次会议）
                last_date_by_source[source] = dates_in_chunk[-1]
                # 块自带日期，不需要补时间上下文
                time_line = ""
            else:
                # 块里没有日期：继承之前记住的日期（如果有）
                inherited = last_date_by_source.get(source)
                # 有可继承的日期就生成时间上下文标注行，没有就留空
                time_line = f"〔时间上下文: {inherited}〕\n" if inherited else ""

            # ----- 拼接前缀 -----
            # 格式：《文档名》 + 可选的时间上下文行 + 原文
            chunk.page_content = f"《{doc_name}》\n{time_line}{chunk.page_content}"

        return chunks

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

            # 【调优新增】步骤 2.5: 块内容增强
            # 给每个块加《文档名》前缀，提升检索命中率和引用准确性
            chunks = self._enrich_chunks(chunks)

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

            # 【调优新增】块内容增强（同 ingest_document）
            chunks = self._enrich_chunks(chunks)

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

    def _rewrite_query(self, question: str) -> List[str]:
        """
        查询改写：让 LLM 把问题改写成几个「同义但用词不同」的问法

        为什么需要？（解决「同义词鸿沟」）
        - 用户问「评审人员有哪些职责」，但文档里写的是「审核方向注意：1、安全…」
        - 「职责」和「审核方向」语义相关但用词完全不同，
          向量检索和重排序都可能跨不过这个词汇差异
        - 让 LLM 先把问题改写成多种问法（如「审核代码要检查哪些方面」），
          每种问法各自检索再合并，能大幅提高召回覆盖面
        - 这个技巧叫 Multi-Query / RAG-Fusion

        Args:
            question: 原始问题

        Returns:
            改写后的问法列表（最多 2 个）；改写失败返回空列表
        """
        try:
            # 延迟导入 ChatSession（避免循环依赖）
            from chat.session import ChatSession

            # 创建一个专门做改写的临时会话
            rewrite_session = ChatSession(
                system_prompt="你是一个查询改写助手，只输出改写结果，不解释。"
            )
            # 改写要求低随机性，保证稳定
            rewrite_session.temperature = 0.3

            # 构造改写指令：要求 2 个不同表述、每行一个
            rewrite_prompt = (
                "请把下面的问题改写成2个语义相同但用词不同的问法"
                "（可以换角度、换同义词），每行一个，不要编号，不要解释：\n"
                f"{question}"
            )

            # stream=False 拿到完整文本
            reply = rewrite_session.chat(rewrite_prompt, stream=False)

            # 按行拆分，清洗掉空行和多余符号
            variants = []
            for line in reply.splitlines():
                # 去掉首尾空白和可能的列表符号（- 、1. 等）
                cleaned = line.strip().lstrip("-•1234567890. 、）)")
                # 过滤空行和太短的行
                if cleaned and len(cleaned) >= 4:
                    variants.append(cleaned)

            # 最多取 2 个改写（控制成本）
            return variants[:2]

        except Exception as e:
            # 改写失败不影响主流程，退回单查询模式
            print(f"⚠ 查询改写失败（退回单查询）: {str(e)}")
            return []

    def _retrieve_multi_query(self, question: str, k: int) -> List[tuple]:
        """
        多路检索：原问题 + 改写问法 各自检索，再用 RRF 融合排序

        合并策略——RRF（Reciprocal Rank Fusion，倒数排名融合）：
        - 每一路检索给每个块一个「名次」（第1名、第2名…）
        - 块的融合分 = 各路 1/(60+名次) 之和（60 是平滑常数，业界标准值）
        - 效果：在多路里「都出现」的块（真正相关）分数累加被推高；
          只在某一路偶然冒尖的噪声块只有单份分数，被压下去
        - 比「取最高分」更稳健：不受不同问法间分数波动的影响

        Args:
            question: 原始问题
            k: 目标检索数量

        Returns:
            融合排序后的 (Document, score) 列表
            score 保留的是该块在各路中的「最高重排序分」，
            供后续低置信度判断使用（量纲与单路检索一致）
        """
        # 第一步：生成改写问法（可能为空列表）
        variants = self._rewrite_query(question)
        if variants:
            print(f"   查询改写: {variants}")

        # 所有要检索的问法 = 原问题 + 改写
        all_queries = [question] + variants

        # 用字典做融合
        # 键 = (来源, 块序号)
        # 值 = {"doc": 文档, "best": 最高重排序分, "rrf": RRF 累计分}
        merged = {}

        # 逐个问法检索
        for q in all_queries:
            # enumerate 从 1 开始给出该路的名次
            for rank, (doc, score) in enumerate(
                self.retriever.retrieve(q, k=k), start=1
            ):
                # 构造去重键
                key = (doc.metadata.get("source"),
                       doc.metadata.get("chunk_index"))

                # setdefault：不存在则初始化，存在则取回已有条目
                entry = merged.setdefault(
                    key, {"doc": doc, "best": score, "rrf": 0.0}
                )
                # 记录该块拿到过的最高重排序分（用于置信度判断）
                entry["best"] = max(entry["best"], score)
                # RRF 累加：名次越靠前贡献越大，多路都出现则累加多份
                entry["rrf"] += 1.0 / (60 + rank)

        # 按 RRF 融合分从高到低排序
        ranked = sorted(merged.values(), key=lambda e: e["rrf"], reverse=True)

        # 截取前 k + 6 个（k 个主结果 + 邻居余量），控制上下文长度
        # 返回 (Document, 最高重排序分) 元组列表
        return [(e["doc"], e["best"]) for e in ranked[:k + 6]]

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
        # 【调优】使用多路检索：原问题 + LLM 改写的同义问法，合并结果
        # 解决「问法用词」和「文档用词」不一致导致的漏检
        print("\n🔍 步骤 1/3: 检索相关文档")
        k = k or self.retriever.search_k
        results = self._retrieve_multi_query(question, k=k)

        if not results:
            print("⚠ 未找到相关文档")
            return {
                "question": question,
                "answer": "根据现有文档无法回答该问题。",
                "sources": [],
                # 检索为空必然是低置信度
                "low_confidence": True,
                "context": "" if not return_context else ""
            }

        print(f"   检索到 {len(results)} 个相关文档")
        for doc, score in results:
            source = doc.metadata.get("source", "未知")
            print(f"   - [{score:.2f}] {source}")

        # 【调优新增】低置信度早退
        # results[0][1] 是最高相关度得分（结果按得分降序排列）
        # 阈值从 retriever 读取：重排序模式和纯向量模式的分数量纲不同
        # （重排序是 0~1 相关度概率，阈值 0.15；余弦相似度阈值 0.40）
        # 如果连最高分都低于阈值，说明知识库里几乎肯定没有相关内容
        # 直接返回标准回复，省掉一次注定失败的 LLM 调用（省时间省钱）
        threshold = self.retriever.low_score_threshold
        if results[0][1] < threshold:
            print(f"⚠ 最高相关度仅 {results[0][1]:.2f}（阈值 {threshold}），知识库中可能没有相关内容")
            return {
                "question": question,
                "answer": "根据现有文档无法回答该问题（知识库中没有找到相关内容）。",
                "sources": [],
                # 低置信度标志：调用方（main.py）可据此回退到普通对话
                "low_confidence": True,
                "context": "" if not return_context else ""
            }

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
            # 使用 RAG 专用 system prompt（与 RAGPromptBuilder 的要求保持一致）
            rag_system_prompt = """你是一个基于文档回答问题的助手。
请根据提供的参考文档回答问题，答案可能分散在多个片段中，需要综合归纳。
如果不同片段是不同时间的规定，以最新的为准。
只有所有片段都与问题无关时才回答「根据现有文档无法回答」。
严禁编造文档中不存在的规定。回答要准确、简洁，并标注信息来源。"""

            session = ChatSession(system_prompt=rag_system_prompt)

            # 【调优】降低温度：RAG 要求「忠实于文档」，随机性越低越好
            # 0.3 比默认的 0.7 更稳定，减少模型「自由发挥」
            session.temperature = 0.3

            # 【调优】放大历史 token 上限，防止长 RAG prompt 被截断
            # 原上限 4000：当检索内容较多时，整条 prompt 可能被
            # ChatSession 的历史截断逻辑删掉，导致 LLM 收不到任何文档！
            # DeepSeek 支持 64K 上下文，这里放大到 32000 绰绰有余
            session.max_history_tokens = 32000

            # 发送 Prompt 并获取回答
            answer = session.chat(prompt, stream=False)

            # 提取来源信息
            sources = self._extract_sources(results)

            # 【调优新增】低置信度标志
            # results[0][1] 是相关度最高的块的得分
            # 阈值同样从 retriever 读取（适配重排序/纯向量两种量纲）
            # main.py 可以根据这个标志回退到普通对话模式
            top_score = results[0][1] if results else 0.0

            # 构建结果
            result = {
                "question": question,
                "answer": answer,
                "sources": sources,
                # 低置信度标志：True 表示检索结果可能都不相关
                "low_confidence": top_score < self.retriever.low_score_threshold
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
