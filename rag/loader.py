#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文档加载模块 (Loader)

支持多种文档格式的加载：PDF、TXT、Markdown

为什么需要文档加载？
- LLM 只能处理文本，不能直接从 PDF/Word 等格式中读取
- 文档加载器负责：文件读取 -> 格式解析 -> 提取纯文本

支持的格式：
1. PDF (.pdf): 使用 PyPDFLoader，提取每页文本
2. Markdown (.md): 使用 TextLoader，保留 Markdown 格式
3. 纯文本 (.txt): 使用 TextLoader

输出格式：
- 统一返回 List[Document]
- 每个 Document 包含：
  - page_content: 文本内容
  - metadata: {source: 文件名, page: 页码, type: 文件类型}

使用示例：
    loader = DocumentLoader()
    docs = loader.load("myfile.pdf")
    for doc in docs:
        print(f"页码: {doc.metadata.get('page')}")
        print(f"内容: {doc.page_content[:100]}...")
"""

import sys
from pathlib import Path

# 将父目录添加到 Python 路径
sys.path.append(str(Path(__file__).parent.parent))

from typing import List, Union
from pathlib import Path

# LangChain 的 Document 类型
from langchain_core.documents import Document

# LangChain 的文档加载器
# PyPDFLoader: 加载 PDF 文件
# TextLoader: 加载文本文件（TXT、MD 等）
from langchain_community.document_loaders import PyPDFLoader, TextLoader


class DocumentLoader:
    """
    文档加载器封装类

    提供统一的接口加载不同格式的文档。
    自动根据文件扩展名选择合适的加载器。

    支持的扩展名：
    - .pdf: PDF 文件
    - .txt: 纯文本文件
    - .md: Markdown 文件
    - .markdown: Markdown 文件（另一种扩展名）

    使用示例:
        loader = DocumentLoader()

        # 加载单个文件
        docs = loader.load("mydoc.pdf")

        # 加载目录中的所有支持文件
        docs = loader.load_directory("data/docs/")
    """

    # 类变量：定义支持的文件扩展名到加载器类型的映射
    # 这是一个字典（dict），键是扩展名，值是对应的处理方式
    SUPPORTED_EXTENSIONS = {
        ".pdf": "pdf",
        ".txt": "text",
        ".md": "text",
        ".markdown": "text"
    }

    def __init__(self):
        """
        初始化文档加载器

        目前不需要特殊初始化，主要是记录加载统计
        """
        # 统计信息，记录加载的文件数量和总页数/块数
        self.stats = {
            "files_processed": 0,  # 处理的文件数
            "total_chunks": 0      # 生成的文档块数
        }

        print("✓ DocumentLoader 初始化完成")

    def load(self, file_path: Union[str, Path]) -> List[Document]:
        """
        加载单个文档

        根据文件扩展名自动选择合适的加载器。

        Args:
            file_path: 文件路径（字符串或 Path 对象）

        Returns:
            Document 列表，每个元素代表一个文档块（PDF 的每页或文本文件的每个块）

        Raises:
            ValueError: 文件格式不支持或文件不存在
            FileNotFoundError: 文件不存在

        使用示例:
            docs = loader.load("mydoc.pdf")
            print(f"共 {len(docs)} 页/块")
        """
        # 去除路径中可能的引号
        # 用户输入时可能会加引号，如: "/path/to/file.txt"
        file_path = file_path.strip('"').strip("'")

        # 将路径转换为 Path 对象
        # Path(file_path) 可以接受字符串或 Path，统一处理
        path = Path(file_path)

        # 检查文件是否存在
        # .exists() 方法检查路径是否存在
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        # 检查是否是文件（不是目录）
        # .is_file() 方法检查路径是否是文件
        if not path.is_file():
            raise ValueError(f"路径不是文件: {file_path}")

        # 获取文件扩展名（小写）
        # .suffix 获取扩展名（如 ".pdf"）
        # .lower() 转为小写，确保大小写不敏感（.PDF 和 .pdf 一样处理）
        ext = path.suffix.lower()

        # 检查是否支持该扩展名
        # in 操作符检查键是否在字典中
        if ext not in self.SUPPORTED_EXTENSIONS:
            supported = ", ".join(self.SUPPORTED_EXTENSIONS.keys())
            raise ValueError(
                f"不支持的文件格式: {ext}\n"
                f"支持的格式: {supported}"
            )

        # 根据扩展名选择加载方式
        file_type = self.SUPPORTED_EXTENSIONS[ext]

        if file_type == "pdf":
            # 加载 PDF 文件
            return self._load_pdf(path)
        elif file_type == "text":
            # 加载文本文件（TXT、MD）
            return self._load_text(path)
        else:
            # 不应该到达这里，防御性编程
            raise ValueError(f"未知的文件类型: {file_type}")

    def _load_pdf(self, path: Path) -> List[Document]:
        """
        使用 PyPDFLoader 加载 PDF 文件

        PDF 加载特点：
        - 按页分割，每页生成一个 Document
        - metadata 中包含 page 字段（页码，从0开始）
        - 自动提取文本，但扫描版 PDF（图片）需要 OCR

        Args:
            path: PDF 文件路径（Path 对象）

        Returns:
            Document 列表，每个元素是一页的内容
        """
        print(f"📄 正在加载 PDF: {path.name}")

        # 创建 PyPDFLoader 实例
        # PyPDFLoader 使用 pypdf 库解析 PDF
        loader = PyPDFLoader(str(path))

        # .load() 方法执行实际的加载
        # 返回 List[Document]，每页一个 Document
        documents = loader.load()

        # 为每个文档添加额外的 metadata
        for i, doc in enumerate(documents):
            # 添加文件类型标记
            doc.metadata["type"] = "pdf"
            # 确保 source 字段存在（有些 loader 可能不设置）
            if "source" not in doc.metadata:
                doc.metadata["source"] = path.name
            # page 字段在 PyPDFLoader 中已存在（0-based）
            # 如果需要 1-based，可以在这里转换

        # 更新统计
        self.stats["files_processed"] += 1
        self.stats["total_chunks"] += len(documents)

        print(f"   ✓ 成功加载 {len(documents)} 页")
        return documents

    def _load_text(self, path: Path) -> List[Document]:
        """
        使用 TextLoader 加载文本文件（TXT、MD）

        文本加载特点：
        - 默认整个文件作为一个 Document
        - 可以配置按行分割（这里使用默认设置）
        - 自动检测编码（UTF-8）

        Args:
            path: 文本文件路径（Path 对象）

        Returns:
            Document 列表（通常只有1个元素）
        """
        print(f"📝 正在加载文本文件: {path.name}")

        # 创建 TextLoader 实例
        # TextLoader 支持多种编码，默认 UTF-8
        loader = TextLoader(
            str(path),
            encoding="utf-8"  # 显式指定编码，避免中文乱码
        )

        # 加载文件
        documents = loader.load()

        # 为每个文档添加 metadata
        for doc in documents:
            # 根据扩展名判断类型
            if path.suffix.lower() == ".md" or path.suffix.lower() == ".markdown":
                doc.metadata["type"] = "markdown"
            else:
                doc.metadata["type"] = "text"

            # 确保 source 字段存在
            if "source" not in doc.metadata:
                doc.metadata["source"] = path.name

        # 更新统计
        self.stats["files_processed"] += 1
        self.stats["total_chunks"] += len(documents)

        print(f"   ✓ 成功加载 {len(documents)} 个文本块")
        return documents

    def load_directory(
        self,
        dir_path: Union[str, Path],
        recursive: bool = True
    ) -> List[Document]:
        """
        加载目录中的所有支持格式的文档

        Args:
            dir_path: 目录路径
            recursive: 是否递归加载子目录，默认 True

        Returns:
            所有文档的 Document 列表（合并后的）

        使用示例:
            docs = loader.load_directory("data/docs/")
            print(f"共加载 {len(docs)} 个文档块")
        """
        # 转换路径
        dir_path = Path(dir_path)

        # 检查目录是否存在
        if not dir_path.exists():
            raise FileNotFoundError(f"目录不存在: {dir_path}")

        if not dir_path.is_dir():
            raise ValueError(f"路径不是目录: {dir_path}")

        print(f"📂 正在扫描目录: {dir_path}")

        # 收集所有支持的文件
        all_files = []

        # 获取支持的扩展名列表
        extensions = list(self.SUPPORTED_EXTENSIONS.keys())

        if recursive:
            # 递归遍历目录
            # rglob("*") 递归匹配所有文件和目录
            for ext in extensions:
                # 使用 rglob 匹配特定扩展名
                # f"**/*{ext}" 匹配任意深度的该扩展名文件
                all_files.extend(dir_path.rglob(f"*{ext}"))
        else:
            # 只遍历当前目录
            for ext in extensions:
                # glob 不匹配子目录
                all_files.extend(dir_path.glob(f"*{ext}"))

        # 去重并排序
        # set() 去重，sorted() 排序
        all_files = sorted(set(all_files))

        if not all_files:
            print(f"   ⚠ 目录中没有支持的文档")
            return []

        print(f"   发现 {len(all_files)} 个文件")

        # 逐个加载文件
        all_documents = []
        for file_path in all_files:
            try:
                docs = self.load(file_path)
                all_documents.extend(docs)
            except Exception as e:
                # 单个文件失败不影响其他文件
                print(f"   ✗ 加载失败 {file_path.name}: {str(e)}")
                continue

        print(f"\n✓ 目录加载完成，共 {len(all_documents)} 个文档块")
        return all_documents

    def get_stats(self) -> dict:
        """
        获取加载统计信息

        Returns:
            统计字典，包含 files_processed 和 total_chunks
        """
        return self.stats.copy()


# ============================================
# 测试代码
# ============================================

if __name__ == "__main__":
    print("=" * 50)
    print("测试 DocumentLoader 模块")
    print("=" * 50)

    # 创建测试目录和文件
    test_dir = Path("test_docs")
    test_dir.mkdir(exist_ok=True)

    # 创建测试文本文件
    test_txt = test_dir / "test.txt"
    test_txt.write_text("这是测试文本文件的第一行。\n这是第二行。", encoding="utf-8")

    # 创建测试 Markdown 文件
    test_md = test_dir / "test.md"
    test_md.write_text("# 测试标题\n\n这是 Markdown 内容。", encoding="utf-8")

    try:
        loader = DocumentLoader()

        print("\n1. 测试加载文本文件:")
        docs = loader.load(test_txt)
        print(f"   文件: {test_txt.name}")
        print(f"   块数: {len(docs)}")
        print(f"   内容预览: {docs[0].page_content[:30]}...")
        print(f"   metadata: {docs[0].metadata}")

        print("\n2. 测试加载 Markdown 文件:")
        docs = loader.load(test_md)
        print(f"   文件: {test_md.name}")
        print(f"   类型: {docs[0].metadata.get('type')}")

        print("\n3. 测试加载目录:")
        all_docs = loader.load_directory(test_dir, recursive=False)
        print(f"   总计: {len(all_docs)} 个文档块")

        print("\n4. 测试统计信息:")
        stats = loader.get_stats()
        print(f"   处理文件数: {stats['files_processed']}")
        print(f"   总文档块数: {stats['total_chunks']}")

        print("\n✓ 所有测试通过!")

    except Exception as e:
        print(f"\n✗ 测试失败: {str(e)}")
        import traceback
        traceback.print_exc()

    finally:
        # 清理测试文件
        import shutil
        if test_dir.exists():
            shutil.rmtree(test_dir)
            print(f"\n🧹 清理测试文件: {test_dir}")
