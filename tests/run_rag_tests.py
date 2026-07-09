#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RAG 自动化测试脚本 (run_rag_tests.py)

作用：批量运行 tests/rag_test_cases.json 里的测试用例，
      自动判定 RAG 回答是否包含参考答案的关键信息。

判定规则（关键词分组匹配）：
- 每个用例的 keywords 是「分组列表」，例如 [["4","四"], ["空格"]]
- 每一组内是「同义候选词」，答案命中组内任意一个词即该组通过
- 所有组都通过 → 用例 PASS；任何一组没命中 → FAIL
- 这样既能容忍表述差异（"4个空格" vs "四个空格"），又保证要点齐全

使用方法:
    python tests/run_rag_tests.py           # 跑全部用例
    python tests/run_rag_tests.py 1 5 9     # 只跑指定编号的用例

注意：每个用例会调用一次 Embedding + 一次 LLM（DeepSeek），
      跑完 21 个用例约花费几分钱、耗时 3~5 分钟。
"""

# 导入标准库
import sys
import json
import io
import contextlib
from pathlib import Path
from datetime import datetime

# 把项目根目录加入模块搜索路径（tests/ 的上一级）
sys.path.append(str(Path(__file__).parent.parent))

# 导入 RAG Pipeline
from rag.pipeline import RAGPipeline

# 测试用例文件路径（和本脚本同目录）
CASES_FILE = Path(__file__).parent / "rag_test_cases.json"

# 测试报告输出路径（JSON 格式，供复查失败原因）
REPORT_FILE = Path(__file__).parent / "last_report.json"


def check_answer(answer: str, keyword_groups) -> tuple:
    """
    判定回答是否命中所有关键词组

    Args:
        answer: RAG 生成的回答文本
        keyword_groups: 关键词分组列表，如 [["4","四"], ["空格"]]

    Returns:
        (是否通过, 未命中的组列表)
    """
    # 统一转小写做大小写不敏感匹配
    ans = answer.lower()

    # 收集没有命中的组
    missed = []

    # 遍历每一组关键词
    for group in keyword_groups:
        # any() 只要组内任意一个词出现在答案里就算命中
        if not any(kw.lower() in ans for kw in group):
            missed.append(group)

    # 所有组都命中才算通过
    return (len(missed) == 0, missed)


def run_tests(case_ids=None):
    """
    运行测试主流程

    Args:
        case_ids: 要运行的用例编号列表；None 表示全部运行

    Returns:
        (通过数, 总数)
    """
    # ----- 加载测试用例 -----
    cases = json.loads(CASES_FILE.read_text(encoding="utf-8"))

    # 如果指定了编号，只保留对应的用例
    if case_ids:
        cases = [c for c in cases if c["id"] in case_ids]

    print(f"{'=' * 60}")
    print(f"RAG 自动化测试：共 {len(cases)} 个用例")
    print(f"{'=' * 60}\n")

    # ----- 初始化 Pipeline（静默模式：吞掉初始化打印）-----
    # RAGPipeline 初始化会打印很多信息，用 redirect_stdout 收进缓冲区
    # 这样测试报告更干净
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        pipeline = RAGPipeline()

    # ----- 逐个运行用例 -----
    results = []       # 收集每个用例的结果
    passed_count = 0   # 通过计数

    for case in cases:
        qid = case["id"]
        question = case["question"]
        # 用例可以指定检索数量 k，没指定就用 None（走 pipeline 默认值）
        k = case.get("k")

        # 运行查询（同样吞掉 pipeline 的过程打印）
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                result = pipeline.query(question, k=k)
            answer = result["answer"]
        except Exception as e:
            # 查询出错也记为失败，但不中断整个测试
            answer = f"[查询异常] {e}"

        # 判定是否通过
        ok, missed = check_answer(answer, case["keywords"])
        if ok:
            passed_count += 1

        # 打印单行结果（PASS/FAIL + 用例信息）
        status = "✅ PASS" if ok else "❌ FAIL"
        print(f"{status}  [{qid:>2}] {case['level']}  {question}")

        # 失败时打印细节，方便定位
        if not ok:
            print(f"      未命中关键词组: {missed}")
            print(f"      回答: {answer[:150]}...")

        # 保存到结果列表
        results.append({
            "id": qid,
            "level": case["level"],
            "question": question,
            "pass": ok,
            "missed_keywords": missed,
            "answer": answer,
            "reference": case["reference"]
        })

    # ----- 输出汇总 -----
    print(f"\n{'=' * 60}")
    print(f"测试完成: {passed_count}/{len(cases)} 通过 "
          f"({passed_count / len(cases) * 100:.0f}%)")
    print(f"{'=' * 60}")

    # ----- 保存详细报告（JSON）-----
    report = {
        "time": datetime.now().isoformat(),
        "passed": passed_count,
        "total": len(cases),
        "results": results
    }
    REPORT_FILE.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"详细报告已保存: {REPORT_FILE}")

    return passed_count, len(cases)


# ============================================
# 脚本入口
# ============================================

if __name__ == "__main__":
    # 解析命令行参数：可选的用例编号列表
    # 例如 python tests/run_rag_tests.py 1 5 9
    ids = [int(a) for a in sys.argv[1:] if a.isdigit()] or None

    # 运行测试
    run_tests(ids)
