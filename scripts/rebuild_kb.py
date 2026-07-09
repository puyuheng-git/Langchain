#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
知识库重建脚本 (rebuild_kb.py)

什么时候需要重建知识库？
1. 修改了分块参数（chunk_size / chunk_overlap）——旧块的大小不会自动变
2. 更换了 Embedding 模型——新旧向量不在同一空间，混用会检索错乱
3. 修改了块内容增强逻辑（如加《文档名》前缀）——旧块没有前缀

重建 = 删掉旧集合 + 用当前配置重新入库所有文档

使用方法:
    python scripts/rebuild_kb.py 文档1.txt 文档2.txt ...
    python scripts/rebuild_kb.py E:\\python_project\\*.txt   (支持通配符)

注意：会调用 Embedding API（按量计费，通常几分钱以内）
"""

# 导入标准库
import sys
import glob
from pathlib import Path

# 把项目根目录加入模块搜索路径
# 本脚本在 scripts/ 目录下，parent.parent 回到项目根目录
sys.path.append(str(Path(__file__).parent.parent))

# 导入 Chroma 客户端（用于删除旧集合）
import chromadb
from chromadb.config import Settings

# 导入配置和 RAG Pipeline
from config import Config
from rag.pipeline import RAGPipeline


def rebuild(file_patterns):
    """
    重建知识库主流程

    Args:
        file_patterns: 文件路径或通配符模式的列表

    Returns:
        成功入库的文件数
    """
    # ----- 步骤 1: 展开通配符，收集所有要入库的文件 -----
    files = []
    for pattern in file_patterns:
        # glob.glob 展开通配符（如 *.txt → 所有 txt 文件）
        matched = glob.glob(pattern)
        if matched:
            files.extend(matched)
        else:
            # 没匹配到，可能是直接给的文件路径
            files.append(pattern)

    # 去重并只保留真实存在的文件
    files = [f for f in dict.fromkeys(files) if Path(f).is_file()]

    if not files:
        print("⚠ 没有找到任何要入库的文件")
        return 0

    print(f"待入库文件（{len(files)} 个）:")
    for f in files:
        print(f"  - {f}")

    # ----- 步骤 2: 删除旧的 documents 集合 -----
    print("\n删除旧集合...")
    client = chromadb.PersistentClient(
        path=str(Config.DATA_DIR / "chroma_db"),
        settings=Settings(anonymized_telemetry=False, allow_reset=True)
    )
    try:
        # delete_collection 彻底删除集合及其所有数据
        client.delete_collection("documents")
        print("✓ 旧集合已删除")
    except Exception:
        # 集合不存在时会抛异常，忽略即可
        print("  （旧集合不存在，跳过）")

    # 注意：必须先删集合再创建 Pipeline
    # 因为 Pipeline 初始化时会「获取或创建」集合
    # 先删掉，Pipeline 就会创建一个全新的空集合

    # ----- 步骤 3: 用当前配置重新入库 -----
    print("\n初始化 RAG Pipeline（使用当前调优参数）...")
    pipeline = RAGPipeline()

    # 逐个文件入库，统计成功数
    success = 0
    for f in files:
        if pipeline.ingest_document(f):
            success += 1

    # ----- 步骤 4: 打印重建结果 -----
    print(f"\n{'=' * 50}")
    print(f"重建完成: {success}/{len(files)} 个文件入库成功")
    print(f"知识库总块数: {pipeline.vectorstore.count()}")
    print(f"{'=' * 50}")

    return success


# ============================================
# 脚本入口
# ============================================

if __name__ == "__main__":
    # sys.argv 是命令行参数列表，第 0 个是脚本名，从第 1 个开始是用户参数
    if len(sys.argv) < 2:
        print("用法: python scripts/rebuild_kb.py <文件或通配符> ...")
        print("示例: python scripts/rebuild_kb.py E:\\python_project\\*.txt")
        sys.exit(1)

    # 把所有命令行参数（文件模式）传给重建函数
    rebuild(sys.argv[1:])
