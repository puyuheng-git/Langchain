#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agent 工具注册表 (Tools) —— V3 新增

什么是「工具」（Tool）？
- 普通聊天：AI 只能用「脑子里」的知识回答，不能上网、不能算数、不能存东西
- 有了工具：AI 可以「主动调用」外部能力，比如搜索网页、运行代码、写入知识库
- 这就是 Agent（智能体）和普通对话最大的区别：Agent 会「动手做事」

工具是怎么被 AI 调用的？
1. 我们把每个工具的「名字、功能说明、参数」告诉大模型
2. 大模型在回答时，如果觉得需要某个工具，就会返回一个「工具调用请求」
3. 我们的程序执行这个工具，把结果再喂回给大模型
4. 大模型根据工具结果继续思考或给出最终答案

本文件用「工厂函数」build_tools 创建工具：
- 因为有些工具需要访问 RAG 知识库、长期记忆等对象
- 工厂函数把这些对象「注入」进去，工具内部就能用（这叫依赖注入）

用到的关键库：
- langchain_core.tools.tool: 一个装饰器，把普通函数变成大模型能识别的「工具」
  函数的 docstring（说明）和类型注解（参数）会自动变成工具的「说明书」
"""

# 导入 sys 和 Path，用于把项目根目录加入模块搜索路径
import sys
import json
from pathlib import Path

# 把项目根目录加入 sys.path
sys.path.append(str(Path(__file__).parent.parent))

# 导入类型提示工具
from typing import List

# 从 langchain_core 导入 tool 装饰器
# @tool 会读取被装饰函数的 docstring 和参数类型，生成大模型可用的工具描述
# langchain-core 在 V2 就已经是项目依赖，所以这个导入很轻量
from langchain_core.tools import tool

# 导入配置
from config import Config


def build_tools(rag_pipeline=None, memory=None) -> List:
    """
    工具工厂：创建并返回所有可用的 Agent 工具

    为什么用工厂函数而不是直接定义工具？
    - 有些工具需要用到 rag_pipeline（知识库）和 memory（长期记忆）对象
    - 通过参数把它们传进来，工具函数内部就能「闭包」访问这些对象
    - 「闭包」= 内部函数能记住并使用外部函数的变量

    Args:
        rag_pipeline: RAGPipeline 实例（可为 None，此时知识库工具会提示不可用）
        memory: LongTermMemory 实例（可为 None，此时记忆工具会提示不可用）

    Returns:
        工具列表，每个元素是被 @tool 装饰过的可调用对象
        列表可以直接传给 ChatOpenAI 的 bind_tools 方法

    使用示例:
        tools = build_tools(rag_pipeline, memory)
        llm_with_tools = llm.bind_tools(tools)
    """

    # ----------------------------------------
    # 工具 1: 网页搜索（Tavily）
    # ----------------------------------------

    @tool
    def web_search(query: str) -> str:
        """当需要获取最新的、实时的或你不知道的外部信息时，用这个工具在互联网上搜索。

        参数:
            query: 搜索关键词或问题，例如 "LangGraph 最新版本特性"

        返回: 搜索到的网页摘要文本。
        """
        # 检查是否配置了 Tavily API Key
        # 没配置就返回友好提示，而不是报错崩溃（优雅降级）
        if not Config.TAVILY_API_KEY:
            return "（网页搜索不可用：未配置 TAVILY_API_KEY。请在 .env 中填入，注册地址 https://tavily.com）"

        try:
            # 在函数内部导入 tavily，避免没装这个库时整个模块无法加载
            from tavily import TavilyClient

            # 创建 Tavily 客户端
            client = TavilyClient(api_key=Config.TAVILY_API_KEY)

            # 执行搜索
            # max_results=3 表示最多返回 3 条结果，够用且省 token
            response = client.search(query=query, max_results=3)

            # response["results"] 是结果列表，每条含 title、url、content
            results = response.get("results", [])

            # 如果没搜到，返回提示
            if not results:
                return f"没有搜索到关于 '{query}' 的结果。"

            # 把结果拼成一段文本返回给大模型
            lines = [f"关于 '{query}' 的搜索结果："]
            for i, r in enumerate(results, start=1):
                # 每条结果：标题 + 内容摘要 + 来源链接
                lines.append(f"{i}. {r.get('title', '无标题')}")
                lines.append(f"   {r.get('content', '')[:200]}")
                lines.append(f"   来源: {r.get('url', '')}")
            return "\n".join(lines)

        except ImportError:
            # 没安装 tavily-python 库
            return "（网页搜索不可用：未安装 tavily-python，请运行 pip install tavily-python）"
        except Exception as e:
            # 其他错误（网络、额度等）
            return f"（网页搜索出错：{str(e)}）"

    # ----------------------------------------
    # 工具 2: Python 代码执行（REPL）
    # ----------------------------------------

    @tool
    def python_repl(code: str) -> str:
        """当需要做数学计算、数据处理或运行一小段 Python 代码来得到结果时，用这个工具。

        参数:
            code: 要执行的 Python 代码字符串。
                  想输出结果，请在代码里用 print()，例如 "print(2 ** 10)"

        返回: 代码的标准输出（print 的内容）或错误信息。

        ⚠️ 安全提示: 这个工具会真实执行代码，仅供个人本地学习使用。
        """
        # ⚠️ 安全警告（给开发者看的）：
        # exec 会执行任意 Python 代码，理论上可以删文件、访问网络等。
        # 本项目是「个人本地学习工具」，用户自己控制输入，所以可接受。
        # 生产环境绝对不能这样做，需要专业沙箱（如 Docker、gVisor）隔离。

        # 导入用于捕获 print 输出的工具
        import io
        import contextlib

        # 创建一个「字符串缓冲区」，把 print 的内容写到这里而不是屏幕
        output_buffer = io.StringIO()

        try:
            # redirect_stdout 把标准输出临时重定向到我们的缓冲区
            # with 语句结束后会自动恢复，print 又会正常打印到屏幕
            with contextlib.redirect_stdout(output_buffer):
                # exec 执行代码字符串
                # 第二个参数 {} 是一个空的命名空间（全局变量字典）
                # 用独立命名空间，避免污染我们程序自己的变量
                exec(code, {})

            # 取出缓冲区里捕获到的文本
            result = output_buffer.getvalue()

            # 如果代码没有任何 print 输出，给个提示
            if not result.strip():
                return "代码执行成功，但没有任何输出。提示：用 print() 才能看到结果。"

            return f"代码输出：\n{result}"

        except Exception as e:
            # 代码运行出错（语法错误、除零等），返回错误类型和信息
            # type(e).__name__ 是异常类名，如 ZeroDivisionError
            return f"代码执行出错：{type(e).__name__}: {str(e)}"

    # ----------------------------------------
    # 工具 3: 知识库检索
    # ----------------------------------------

    @tool
    def knowledge_base_search(query: str) -> str:
        """当问题可能和用户已经上传的私人文档/笔记有关时，用这个工具在个人知识库里检索。

        参数:
            query: 要检索的问题或关键词

        返回: 知识库中最相关的几段内容及其来源。
        """
        # 知识库可能没初始化（缺依赖或没配 Embedding Key）
        if rag_pipeline is None:
            return "（知识库不可用：RAG 未初始化）"

        try:
            # 复用 RAGPipeline 的 search_only：只检索不生成回答
            results = rag_pipeline.search_only(query, k=4)

            # 没检索到相关内容
            if not results:
                return f"知识库中没有找到关于 '{query}' 的内容。"

            # 把检索结果拼成文本
            lines = [f"知识库中关于 '{query}' 的相关内容："]
            for i, r in enumerate(results, start=1):
                # r 是字典：content（内容）、metadata（元数据）、score（相似度）
                source = r["metadata"].get("source", "未知来源")
                content = r["content"][:200]  # 只取前 200 字，省 token
                lines.append(f"{i}. [来自 {source}] {content}")
            return "\n".join(lines)

        except Exception as e:
            return f"（知识库检索出错：{str(e)}）"

    # ----------------------------------------
    # 工具 4: 知识库写入
    # ----------------------------------------

    @tool
    def knowledge_base_write(title: str, content: str) -> str:
        """当用户让你把某些信息「记到知识库」「存成笔记」时，用这个工具把内容写入个人知识库。

        参数:
            title: 笔记标题（会作为文件名），例如 "LangGraph 学习笔记"
            content: 笔记正文内容

        返回: 写入结果说明。
        """
        if rag_pipeline is None:
            return "（知识库不可用：RAG 未初始化，无法写入）"

        try:
            # 把标题里可能导致文件名非法的字符替换掉
            # 只保留常见安全字符，其余用下划线代替
            safe_title = "".join(
                c if c.isalnum() or c in (" ", "-", "_", "（", "）", "(", ")") else "_"
                for c in title
            ).strip()

            # 如果处理后标题为空，用默认名
            if not safe_title:
                safe_title = "笔记"

            # 构造保存路径：data/docs/标题.md
            file_path = Config.DOCS_DIR / f"{safe_title}.md"

            # 把内容写成 Markdown 文件
            # 加一个一级标题，让笔记更规整
            file_path.write_text(f"# {title}\n\n{content}\n", encoding="utf-8")

            # 调用 RAGPipeline 把这个新文件入库（分块+向量化+存储）
            # 复用现有入库全流程，写完立刻就能被检索到
            rag_pipeline.ingest_document(str(file_path))

            return f"✓ 已把《{title}》写入知识库（保存在 {file_path.name}）。"

        except Exception as e:
            return f"（写入知识库出错：{str(e)}）"

    # ----------------------------------------
    # 工具 5: 保存长期记忆
    # ----------------------------------------

    @tool
    def save_memory(content: str, category: str = "fact") -> str:
        """当你了解到关于用户的重要、值得长期记住的信息（偏好、计划、常用概念）时，用这个工具保存下来，以后跨对话都能记得。

        参数:
            content: 要记住的信息，例如 "用户在学习 LangChain"
            category: 分类，可选 preference（偏好）/ concept（概念）/ plan（计划）/ fact（事实）

        返回: 保存结果说明。
        """
        if memory is None:
            return "（长期记忆不可用：memory 未初始化）"

        try:
            # 调用长期记忆模块保存
            memory.remember(content, category=category)
            return f"✓ 已记住（{category}）：{content}"
        except Exception as e:
            return f"（保存记忆出错：{str(e)}）"

    # ----------------------------------------
    # 工具 6: 添加提醒事项
    # ----------------------------------------

    @tool
    def add_reminder(task: str, when: str = "") -> str:
        """当用户提到「要做某事」「提醒我…」这类待办时，用这个工具把它记到提醒清单里。程序下次启动会主动提醒。

        参数:
            task: 待办内容，例如 "复习 LangChain"
            when: 时间描述（可选），例如 "明天" 或 "2026-07-10"

        返回: 添加结果说明。
        """
        try:
            # 提醒存在一个本地 JSON 文件里（无需任何外部服务）
            reminders_file = Config.REMINDERS_FILE

            # 先读出已有的提醒列表
            # 如果文件存在就读，不存在就用空列表
            if reminders_file.exists():
                # json.loads 把 JSON 字符串解析成 Python 对象
                reminders = json.loads(reminders_file.read_text(encoding="utf-8"))
            else:
                reminders = []

            # 导入 datetime 记录创建时间
            from datetime import datetime

            # 追加一条新提醒
            reminders.append({
                "task": task,                                # 待办内容
                "when": when,                                # 时间描述
                "created_at": datetime.now().isoformat(),    # 创建时间
                "done": False                                # 是否已完成
            })

            # 把更新后的列表写回文件
            # ensure_ascii=False 让中文正常显示，indent=2 便于阅读
            reminders_file.write_text(
                json.dumps(reminders, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )

            # 组装返回信息
            when_text = f"（时间：{when}）" if when else ""
            return f"✓ 已添加提醒：{task} {when_text}"

        except Exception as e:
            return f"（添加提醒出错：{str(e)}）"

    # ----------------------------------------
    # 汇总所有工具，返回列表
    # ----------------------------------------

    # 把上面定义的所有工具放进列表返回
    # 这个列表会被传给大模型，告诉它「你有这些能力可以用」
    return [
        web_search,
        python_repl,
        knowledge_base_search,
        knowledge_base_write,
        save_memory,
        add_reminder,
    ]


# ============================================
# 测试代码
# ============================================

if __name__ == "__main__":
    print("=" * 50)
    print("测试 Agent 工具注册表")
    print("=" * 50)

    # 不注入 rag_pipeline / memory，测试工具的降级行为
    tools = build_tools(rag_pipeline=None, memory=None)

    print(f"\n共注册 {len(tools)} 个工具：")
    for t in tools:
        # 每个工具都有 name（名字）和 description（说明）
        print(f"  - {t.name}: {t.description[:40]}...")

    # 测试 python_repl 工具（不依赖任何外部服务）
    print("\n测试 python_repl 工具:")
    # 用 .invoke 调用工具，参数用字典传入
    result = tools[1].invoke({"code": "print(sum(range(1, 101)))"})
    print(f"  1+2+...+100 = {result}")

    print("\n✓ 工具注册表测试通过!")
