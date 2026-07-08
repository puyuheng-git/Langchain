"""
RAG (Retrieval-Augmented Generation) 模块

RAG 是"检索增强生成"的缩写，是 V2 的核心技术。

工作原理：
1. 文档加载：从 PDF/TXT/MD 文件中提取文本
2. 文本分块：将长文档切分成小块（chunk），便于检索
3. 向量化：将文本块转换为向量（Embedding）
4. 向量存储：将向量存入 Chroma 数据库
5. 相似度检索：用户提问时，找出最相关的文档块
6. 生成回答：将检索结果作为上下文，让 LLM 生成回答

模块组成：
- embedder.py: 文本向量化（Embedding）
- vectorstore.py: 向量数据库操作（Chroma）
- loader.py: 文档加载（PDF/TXT/MD）
- chunker.py: 文本分块
- retriever.py: 相似度检索
- pipeline.py: RAG 流程编排

使用示例：
    from rag.pipeline import RAGPipeline

    # 创建 RAG 流程实例
    pipeline = RAGPipeline()

    # 添加文档
    pipeline.ingest_document("mydoc.pdf")

    # 查询
    result = pipeline.query("文档里说了什么？")
    print(result["answer"])
"""

# 从子模块导入主要类，方便外部使用
from .embedder import Embedder
from .vectorstore import VectorStore
from .loader import DocumentLoader
from .chunker import TextChunker
from .retriever import Retriever, RAGPromptBuilder
from .pipeline import RAGPipeline

# 【V4 新增】多模态处理器（图片 OCR）
# 依赖 openai（已是项目依赖），用 try/except 保险起见
try:
    from .multimodal import MultimodalProcessor
except Exception:
    MultimodalProcessor = None

# __all__ 定义了使用 "from rag import *" 时会导入的内容
__all__ = [
    'Embedder',
    'VectorStore',
    'DocumentLoader',
    'TextChunker',
    'Retriever',
    'RAGPromptBuilder',
    'RAGPipeline',
    'MultimodalProcessor'
]
