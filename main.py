#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 知识库助手 - V1
会聊天的笔记本
命令行对话入口

这是整个项目的入口文件，运行这个文件启动 CLI 对话界面。
"""

# ============================================
# 导入标准库模块
# ============================================

# sys 模块提供与 Python 解释器和系统交互的功能
# 这里主要用于 sys.exit() 退出程序和 sys.path 路径管理
import sys

# Path 类用于处理文件系统路径，比字符串操作更安全、跨平台
from pathlib import Path

# datetime 模块用于处理日期和时间
from datetime import datetime

# ============================================
# 尝试导入 Rich 库（CLI 美化）
# ============================================

# try-except 结构用于处理可选依赖
# 如果 Rich 库未安装，程序也能正常运行，只是没有彩色输出

try:
    # Rich 是一个用于在终端显示富文本（颜色、样式、面板等）的库
    # Console 是 Rich 的核心类，用于输出格式化文本
    from rich.console import Console
    # Panel 用于在终端显示带边框的面板
    from rich.panel import Panel
    # Text 用于创建带样式的文本
    from rich.text import Text

    # 设置标志变量，表示 Rich 可用
    # 这种设计模式称为"功能开关"，后续代码根据这个变量决定是否使用 Rich
    USE_RICH = True

except ImportError:
    # 如果导入失败（Rich 未安装），捕获 ImportError 异常
    # 设置标志为 False，表示不使用 Rich
    USE_RICH = False

# ============================================
# 导入项目内部模块
# ============================================

# 从 chat 包导入 ChatSession 类
# ChatSession 是对话管理的核心类，封装了所有与 LLM 交互的逻辑
from chat.session import ChatSession

# 从 config 模块导入 Config 类
# Config 包含所有配置信息（API Key、模型参数、路径设置等）
from config import Config

# 【V2 新增】导入 RAG Pipeline
# RAGPipeline 是文档知识库的核心，整合了加载、分块、向量化、检索全流程
from rag.pipeline import RAGPipeline

# 【V3 新增】导入 Agent 和长期记忆（可选依赖，用 try/except 优雅降级）
# KnowledgeAgent 依赖 langgraph、langchain-openai；LongTermMemory 依赖 rag 组件
# 如果这些库没安装，AGENT_AVAILABLE 会是 False，程序退回到 V1/V2 功能
try:
    # 从 agent 包导入智能体主类
    from agent import KnowledgeAgent
    # 从 chat 包导入长期记忆类
    from chat.memory import LongTermMemory
    # 标志：Agent 相关功能是否可用
    AGENT_AVAILABLE = True
except Exception as _agent_import_error:
    # 导入失败（缺依赖等），记录标志并保存错误原因
    AGENT_AVAILABLE = False
    # 保存错误信息，稍后初始化时给用户提示
    _AGENT_IMPORT_ERROR = str(_agent_import_error)


# ============================================
# 初始化 Rich 控制台
# ============================================

# 根据 USE_RICH 标志决定是否创建 Console 实例
# 如果 Rich 可用，创建 Console 对象；否则为 None
# 三元表达式：值1 if 条件 else 值2
console = Console() if USE_RICH else None


# ============================================
# 辅助函数定义
# ============================================

def print_banner():
    """
    打印欢迎信息

    在程序启动时显示，包含：
    - 程序名称和版本
    - 当前使用的 LLM 提供商和模型
    - 基本使用提示
    """
    # 使用三引号字符串（多行字符串）定义横幅内容
    # .format() 方法用于格式化字符串，将 {} 占位符替换为实际值
    # 【V2 更新】检查是否有文档在知识库中
    doc_count = 0
    if 'rag_pipeline' in globals() and rag_pipeline:
        doc_count = rag_pipeline.vectorstore.count()

    # 根据是否有文档，显示不同的副标题
    if doc_count > 0:
        subtitle = f"主动帮你做事 | 知识库: {doc_count} 个块"
    else:
        subtitle = "主动帮你做事 | /agent 启动智能体"

    banner_text = """
╔════════════════════════════════════════╗
║     🤖 AI 知识库助手 - V3               ║
║     {subtitle: <24}     ║
╚════════════════════════════════════════╝

Provider: {provider}
Model: {model}

输入 /help 查看可用命令
输入 exit 或 quit 退出
""".format(
        # 从 Config 类获取当前配置
        provider=Config.LLM_PROVIDER,    # 提供商名称（deepseek/openai）
        model=Config.DEFAULT_MODEL,      # 模型名称
        subtitle=subtitle                # 动态副标题
    )

    # 根据是否可用 Rich 选择不同的输出方式
    if USE_RICH:
        # 使用 Rich 的 Panel 显示带边框的面板
        # border_style="blue" 设置边框颜色为蓝色
        console.print(Panel(banner_text, title="Welcome", border_style="blue"))
    else:
        # 普通 print 输出
        print(banner_text)


def print_help():
    """
    打印帮助信息

    当用户输入 /help 时显示，列出所有可用命令
    """
    # 定义帮助文本，使用缩进对齐
    help_text = """
可用命令:
  /help              显示此帮助信息
  /system <prompt>   切换系统提示词（角色）
  /clear             清空对话历史
  /save [name]       保存对话到 data/history/
  /history           查看历史对话列表
  /load <文件名>     加载历史对话

  # --- V2 文档知识库命令 ---
  /ingest <路径>     上传/索引文档（支持 PDF/TXT/MD）
  /docs              查看已索引的文档列表
  /delete <文档名>   删除指定文档
  /search <关键词>   测试检索（不生成回答）

  # --- V3 智能体与记忆命令 ---
  /agent <任务>      让智能体自主规划、调用工具完成多步任务
  /remember <内容>   把一条信息存入长期记忆（跨对话记住）
  /memories          查看所有长期记忆
  /recall <查询>     测试记忆召回（按语义找相关记忆）
  /reminders         查看提醒清单

  /stats             显示对话统计信息
  /model             显示当前模型信息
  exit / quit        退出程序

快捷键:
  Ctrl+C             中断当前响应
  Ctrl+D             退出程序（Unix/Linux）
"""
    # 同样根据 Rich 可用性选择输出方式
    if USE_RICH:
        console.print(Panel(help_text, title="Commands", border_style="green"))
    else:
        print(help_text)


def print_stats(session: ChatSession):
    """
    打印对话统计信息

    Args:
        session: ChatSession 实例，用于获取统计数据
    """
    # 调用 session 的 get_stats() 方法获取统计字典
    stats = session.get_stats()

    # 使用 f-string 格式化统计信息
    # f-string 是在字符串前加 f，可以在 {} 中直接嵌入变量和表达式
    stats_text = f"""
对话统计:
  总消息数: {stats['total_messages']}
  用户消息: {stats['user_messages']}
  助手消息: {stats['assistant_messages']}
  估算 Token: {stats['estimated_tokens']} / {stats['max_history_tokens']}
  当前模型: {stats['model']}
  提供商: {stats['provider']}
"""
    if USE_RICH:
        console.print(Panel(stats_text, title="Statistics", border_style="yellow"))
    else:
        print(stats_text)


def print_history_list():
    """
    打印历史对话列表

    显示最近保存的对话文件，供用户选择加载
    """
    # 调用类方法获取历史文件列表
    # 不需要实例，直接用类名调用
    history_files = ChatSession.list_history_files(limit=10)

    # 如果没有历史文件
    if not history_files:
        print("\n📂 暂无历史对话")
        print("提示: 使用 /save 命令保存当前对话")
        return

    # 构建显示文本
    lines = ["\n📂 历史对话列表（最近 10 个）:", ""]

    # enumerate() 返回索引和值，start=1 让索引从 1 开始
    for idx, file_info in enumerate(history_files, start=1):
        # 格式化文件大小
        size = file_info['size']
        if size < 1024:
            size_str = f"{size}B"
        elif size < 1024 * 1024:
            size_str = f"{size / 1024:.1f}KB"
        else:
            size_str = f"{size / (1024 * 1024):.1f}MB"

        # 添加文件信息行
        lines.append(f"  {idx}. {file_info['filename']}")
        lines.append(f"     修改时间: {file_info['modified_time']} | 大小: {size_str}")
        lines.append("")

    # 添加使用提示
    lines.append("💡 使用 /load <文件名> 加载对话")
    lines.append("   例如: /load chat_20240101_120000.json")

    # 输出
    text = '\n'.join(lines)
    if USE_RICH:
        console.print(Panel(text, title="History", border_style="cyan"))
    else:
        print(text)


def ask_load_history(session: ChatSession):
    """
    启动时询问是否加载历史对话

    如果有历史文件，显示列表并询问用户是否加载

    Args:
        session: ChatSession 实例，用于加载历史

    Returns:
        bool: 是否成功加载了历史
    """
    # 获取历史文件列表（只取最新的 5 个）
    history_files = ChatSession.list_history_files(limit=5)

    # 如果没有历史文件，直接返回
    if not history_files:
        return False

    # 显示发现的历史文件
    print(f"\n💾 发现 {len(history_files)} 个历史对话:")
    for idx, file_info in enumerate(history_files[:3], start=1):  # 只显示前 3 个
        print(f"  {idx}. {file_info['filename']} ({file_info['modified_time']})")

    # 询问用户
    if len(history_files) > 3:
        print(f"  ... 还有 {len(history_files) - 3} 个")

    print("\n是否加载历史对话?")
    print("  1-N: 加载对应编号的对话")
    print("  a: 查看全部列表 (/history)")
    print("  回车: 不加载，开始新对话")

    try:
        # 获取用户选择
        choice = input("> ").strip()

        # 如果用户直接回车，不加载
        if not choice:
            print("→ 开始新对话")
            return False

        # 如果输入 'a'，显示完整列表
        if choice.lower() == 'a':
            print_history_list()
            return False

        # 尝试解析为数字
        try:
            idx = int(choice)
            if 1 <= idx <= len(history_files):
                # 加载选中的文件
                selected_file = history_files[idx - 1]  # 列表索引从 0 开始
                return session.load_from_json(selected_file['path'])
            else:
                print(f"⚠ 请输入 1-{len(history_files)} 之间的数字")
                return False
        except ValueError:
            # 不是数字，可能是文件名
            return session.load_from_json(choice)

    except (KeyboardInterrupt, EOFError):
        # 用户按 Ctrl+C 或 Ctrl+D
        print("\n→ 开始新对话")
        return False


def show_startup_reminders(memory=None):
    """
    【V3 新增】启动时的「主动提醒」

    这是 Agent 从「被动响应」走向「主动帮忙」的体现：
    程序一启动，就主动检查有没有待办提醒、有没有之前记下的学习计划，
    然后主动问用户「要不要现在开始？」

    Args:
        memory: LongTermMemory 实例（可为 None），用于召回学习计划类记忆
    """
    # ----- 第一部分: 读取提醒清单 -----
    # 提醒存在 Config.REMINDERS_FILE 指定的 JSON 文件里
    reminders_file = Config.REMINDERS_FILE

    # 只有文件存在时才读取
    if reminders_file.exists():
        try:
            # 导入 json 用于解析文件内容
            import json
            # 读取并解析 JSON（得到一个列表）
            reminders = json.loads(reminders_file.read_text(encoding="utf-8"))

            # 过滤出「还没完成」的提醒（done 为 False）
            # 列表推导式：只保留满足条件的元素
            pending = [r for r in reminders if not r.get("done", False)]

            # 如果有未完成的提醒，主动显示
            if pending:
                print("\n🔔 你还有未完成的提醒:")
                # 最多显示 5 条，避免刷屏
                for r in pending[:5]:
                    # 拼出时间描述（如果有）
                    when_text = f"（{r['when']}）" if r.get("when") else ""
                    print(f"   • {r['task']} {when_text}")
        except Exception:
            # 读取/解析失败就静默跳过，不影响启动
            pass

    # ----- 第二部分: 根据长期记忆主动提及学习计划 -----
    # 如果有记忆模块，召回「plan（计划）」类的记忆
    if memory is not None:
        try:
            # 用与「计划」相关的查询，召回 plan 类的记忆
            plans = memory.recall("学习计划 打算 要做", k=2, category="plan")

            # 如果找到了计划，主动提及
            if plans:
                print("\n💡 我记得你之前提到:")
                for p in plans:
                    print(f"   • {p['content']}")
                # 主动询问，体现「主动帮你做事」
                print("   要现在开始吗？（可以用 /agent 让我帮你）")
        except Exception:
            # 召回失败静默跳过
            pass


# ============================================
# 主函数
# ============================================

def main():
    """
    主函数 - 程序入口点

    整个程序的流程：
    1. 检查配置（API Key 是否设置）
    2. 初始化 ChatSession
    3. 显示欢迎信息
    4. 进入主循环，等待用户输入
    5. 根据输入执行相应命令或发送给 AI
    6. 循环直到用户退出
    """

    # ----------------------------------------
    # 步骤 1: 检查配置
    # ----------------------------------------

    try:
        # 尝试获取 API 配置
        # 如果 API Key 未设置，会抛出 ValueError
        Config.get_api_config()

    except ValueError as e:
        # 捕获配置错误，显示友好的错误信息和解决步骤
        print(f"[错误] {e}")
        print("\n请按照以下步骤配置:")
        print("1. 复制 .env.example 为 .env")
        print("2. 在 .env 文件中填入你的 API Key")
        print("3. 重新运行程序")

        # sys.exit(1) 退出程序，返回码 1 表示出错
        # 返回码 0 通常表示成功，非零表示各种错误
        sys.exit(1)

    # ----------------------------------------
    # 步骤 2: 初始化对话会话
    # ----------------------------------------

    # 创建 ChatSession 实例
    # 这会从 .env 加载配置，初始化 OpenAI 客户端
    session = ChatSession()

    # 【V2 新增】初始化 RAG Pipeline
    # 用于文档知识库的加载、检索和问答
    # 如果初始化失败（如缺少依赖），不影响 V1 的对话功能
    rag_pipeline = None
    try:
        rag_pipeline = RAGPipeline()
    except Exception as e:
        print(f"⚠ RAG Pipeline 初始化失败: {str(e)}")
        print("  文档知识库功能不可用，但多轮对话仍可正常使用")

    # 【V3 新增】初始化长期记忆和智能体（Agent）
    # 同样用 try/except 优雅降级：任一失败都不影响 V1/V2 功能
    memory = None   # 长期记忆对象
    agent = None    # 智能体对象
    if AGENT_AVAILABLE:
        # 依赖库已安装，尝试真正初始化
        try:
            # 先建长期记忆（Agent 需要用到它）
            memory = LongTermMemory()
        except Exception as e:
            print(f"⚠ 长期记忆初始化失败: {str(e)}")
            print("  记忆功能不可用（通常是缺少 Embedding 配置）")

        try:
            # 再建智能体，把知识库和记忆注入进去
            agent = KnowledgeAgent(rag_pipeline=rag_pipeline, memory=memory)
        except Exception as e:
            print(f"⚠ Agent 初始化失败: {str(e)}")
            print("  /agent 命令不可用，但其他功能正常")
    else:
        # 依赖库没装，提示用户（不影响 V1/V2）
        print("ℹ Agent 功能未启用（缺少 langgraph 等依赖）")
        print("  如需使用 /agent，请运行: pip install langgraph langchain-openai tavily-python")

    # ----------------------------------------
    # 步骤 3: 显示欢迎信息
    # ----------------------------------------

    print_banner()

    # 启动时询问是否加载历史对话
    # 这会检查是否有保存的历史文件，并询问用户是否加载
    ask_load_history(session)

    # 【V3 新增】启动时主动提醒
    # 检查提醒清单和长期记忆里的学习计划，主动提及
    show_startup_reminders(memory)

    # ----------------------------------------
    # 步骤 4: 主循环
    # ----------------------------------------

    # while True 创建无限循环，直到遇到 break 或 return
    while True:
        try:
            # ===== 获取用户输入 =====

            if USE_RICH:
                # 使用 Rich 的 input 方法，带颜色样式
                # [bold cyan]...[/bold cyan] 是 Rich 的标记，表示粗体青色
                user_input = console.input("[bold cyan]\n👤 You: [/bold cyan]").strip()
            else:
                # 普通 input 函数，显示提示符并等待用户输入
                # \n 是换行符，strip() 移除首尾空白字符
                user_input = input("\n👤 You: ").strip()

            # 如果输入为空（用户直接按回车），跳过本次循环
            # continue 语句跳过当前循环的剩余部分，直接进入下一次循环
            if not user_input:
                continue

            # ===== 命令处理 =====

            # .lower() 将字符串转为小写，实现大小写不敏感比较
            # in 操作符检查值是否在列表中
            if user_input.lower() in ['exit', 'quit', '/exit', '/quit']:
                print("👋 再见！")
                # break 跳出循环，结束程序
                break

            # 检查是否为 /help 命令
            if user_input == '/help':
                print_help()
                # continue 继续下一次循环，不执行后面的代码
                continue

            # 检查是否为 /clear 命令
            if user_input == '/clear':
                session.clear_history()
                continue

            # 检查是否为 /system 命令（切换角色）
            # .startswith() 方法检查字符串是否以指定前缀开头
            if user_input.startswith('/system '):
                # 提取命令后面的内容
                # [8:] 切片，从第8个字符开始到末尾
                # 为什么是8？因为 '/system ' 有8个字符
                new_prompt = user_input[8:].strip()

                if new_prompt:
                    # 如果提供了新的提示词，调用方法设置
                    session.set_system_prompt(new_prompt)
                else:
                    # 如果没有提供提示词，显示警告
                    print("⚠ 请提供系统提示词，例如: /system 你是一位 Python 专家")
                continue

            # 检查是否为 /stats 命令
            if user_input == '/stats':
                print_stats(session)
                continue

            # 检查是否为 /model 命令（显示配置）
            if user_input == '/model':
                api_config = Config.get_api_config()
                print(f"\n当前配置:")
                print(f"  Provider: {Config.LLM_PROVIDER}")
                print(f"  Model: {api_config['model']}")
                print(f"  Base URL: {api_config['base_url']}")
                print(f"  Temperature: {Config.TEMPERATURE}")
                print(f"  Max Tokens: {Config.MAX_TOKENS}")
                continue

            # 检查是否为 /save 命令（保存对话）
            if user_input.startswith('/save'):
                # .split(maxsplit=1) 按空白分割字符串，最多分割1次
                # 结果是一个列表，第一个元素是命令，第二个是参数
                parts = user_input.split(maxsplit=1)

                # len(parts) 获取列表长度
                if len(parts) > 1:
                    # 用户提供了文件名参数
                    filename = parts[1]

                    # 检查文件名是否以 .md 结尾
                    # 如果没有，自动添加
                    if not filename.endswith('.md'):
                        filename += '.md'

                    # 拼接完整路径
                    filepath = Config.HISTORY_DIR / filename
                else:
                    # 用户没有提供文件名，使用 None（会使用默认命名）
                    filepath = None

                # 同时导出 Markdown 和 JSON 两种格式
                # Markdown 适合人类阅读，JSON 适合程序处理
                md_path = session.export_to_markdown(filepath)

                # 对于 JSON，替换 .md 为 .json
                # if 表达式：如果 filepath 不为 None 则替换，否则传 None
                json_path = session.export_to_json(
                    filepath.replace('.md', '.json') if filepath else None
                )
                continue

            # 检查是否为 /history 命令（查看历史列表）
            if user_input == '/history':
                # 调用函数显示历史文件列表
                print_history_list()
                continue

            # 检查是否为 /load 命令（加载历史对话）
            if user_input.startswith('/load '):
                # 提取文件名参数
                parts = user_input.split(maxsplit=1)

                if len(parts) > 1:
                    filename = parts[1]
                    # 调用 session 的加载方法
                    # 如果成功，messages 会被替换为文件中的内容
                    session.load_from_json(filename)
                else:
                    print("⚠ 请提供文件名，例如: /load chat_20240101_120000.json")
                continue

            # ========== 【V2 新增】文档知识库命令 ==========

            # 检查是否为 /ingest 命令（文档入库）
            if user_input.startswith('/ingest '):
                # 检查 RAG Pipeline 是否可用
                if rag_pipeline is None:
                    print("⚠ RAG Pipeline 未初始化，无法使用文档功能")
                    print("  请检查依赖是否安装: pip install -r requirements.txt")
                    continue

                # 提取文件路径参数
                parts = user_input.split(maxsplit=1)
                if len(parts) > 1:
                    file_path = parts[1]
                    # 去除路径中可能的引号
                    # 用户输入时常会加引号，如: "/path/to/file.txt"
                    file_path = file_path.strip('"').strip("'")
                    # 调用 RAG Pipeline 的入库方法
                    rag_pipeline.ingest_document(file_path)
                else:
                    print("⚠ 请提供文档路径，例如: /ingest data/docs/myfile.pdf")
                continue

            # 检查是否为 /docs 命令（查看已索引文档）
            if user_input == '/docs':
                if rag_pipeline is None:
                    print("⚠ RAG Pipeline 未初始化")
                    continue

                # 获取已索引的文档列表
                docs = rag_pipeline.list_documents()
                if not docs:
                    print("\n📂 知识库中没有文档")
                    print("  使用 /ingest <路径> 添加文档")
                else:
                    print(f"\n📚 知识库中的文档（共 {len(docs)} 个）:")
                    for doc in docs:
                        print(f"  - {doc['source']}: {doc['count']} 个块")
                continue

            # 检查是否为 /delete 命令（删除文档）
            if user_input.startswith('/delete '):
                if rag_pipeline is None:
                    print("⚠ RAG Pipeline 未初始化")
                    continue

                parts = user_input.split(maxsplit=1)
                if len(parts) > 1:
                    source = parts[1]
                    # 删除指定文档
                    deleted_count = rag_pipeline.delete_document(source)
                    if deleted_count > 0:
                        print(f"✓ 已删除文档 '{source}'（{deleted_count} 个块）")
                    else:
                        print(f"⚠ 未找到文档 '{source}'")
                else:
                    print("⚠ 请提供文档名，例如: /delete mydoc.pdf")
                continue

            # 检查是否为 /search 命令（测试检索）
            if user_input.startswith('/search '):
                if rag_pipeline is None:
                    print("⚠ RAG Pipeline 未初始化")
                    continue

                parts = user_input.split(maxsplit=1)
                if len(parts) > 1:
                    query = parts[1]
                    print(f"\n🔍 检索: '{query}'")
                    # 执行检索（不生成回答）
                    results = rag_pipeline.search_only(query, k=4)
                    if results:
                        print(f"  找到 {len(results)} 个相关文档块:\n")
                        for i, r in enumerate(results, 1):
                            print(f"  [{i}] 相似度: {r['score']:.4f}")
                            print(f"      来源: {r['metadata'].get('source', '未知')}")
                            content = r['content'][:100].replace('\n', ' ')
                            print(f"      内容: {content}...\n")
                    else:
                        print("  未找到相关文档")
                else:
                    print("⚠ 请提供检索关键词，例如: /search Python")
                continue

            # ========== 【V3 新增】智能体与记忆命令 ==========

            # 检查是否为 /agent 命令（运行智能体完成任务）
            if user_input.startswith('/agent '):
                # 检查 Agent 是否可用
                if agent is None:
                    print("⚠ Agent 不可用（缺少 langgraph 依赖或初始化失败）")
                    print("  请运行: pip install langgraph langchain-openai tavily-python")
                    continue

                # 提取任务描述
                parts = user_input.split(maxsplit=1)
                if len(parts) > 1:
                    task = parts[1]
                    print(f"\n🤖 智能体开始处理任务: {task}\n")
                    try:
                        # 调用 Agent 的 run 方法，它会自主规划并调用工具
                        answer = agent.run(task)
                        # 打印最终答案
                        if USE_RICH:
                            console.print("[bold green]🤖 Assistant: [/bold green]")
                        else:
                            print("\n🤖 Assistant:")
                        print(answer)
                    except Exception as e:
                        print(f"\n[错误] Agent 执行失败: {str(e)}")
                else:
                    print("⚠ 请提供任务，例如: /agent 帮我查 LangGraph 并总结成笔记")
                continue

            # 检查是否为 /remember 命令（存长期记忆）
            if user_input.startswith('/remember '):
                if memory is None:
                    print("⚠ 长期记忆不可用（缺少依赖或 Embedding 配置）")
                    continue

                parts = user_input.split(maxsplit=1)
                if len(parts) > 1:
                    content = parts[1]
                    # 手动存入的记忆统一归为 fact 类
                    memory.remember(content, category="fact")
                else:
                    print("⚠ 请提供内容，例如: /remember 我在学 LangChain")
                continue

            # 检查是否为 /memories 命令（列出所有记忆）
            if user_input == '/memories':
                if memory is None:
                    print("⚠ 长期记忆不可用")
                    continue

                # 获取所有记忆
                mems = memory.list_memories()
                if not mems:
                    print("\n🧠 还没有任何长期记忆")
                    print("  使用 /remember <内容> 添加，或让 Agent 用 save_memory 自动记")
                else:
                    print(f"\n🧠 长期记忆（共 {len(mems)} 条）:")
                    for m in mems:
                        # 显示分类和内容
                        print(f"  • [{m['category']}] {m['content']}")
                continue

            # 检查是否为 /recall 命令（测试记忆召回）
            if user_input.startswith('/recall '):
                if memory is None:
                    print("⚠ 长期记忆不可用")
                    continue

                parts = user_input.split(maxsplit=1)
                if len(parts) > 1:
                    query = parts[1]
                    print(f"\n🔍 召回与 '{query}' 相关的记忆:")
                    # 按语义召回
                    results = memory.recall(query, k=3)
                    if results:
                        for r in results:
                            print(f"  • [{r['score']:.3f}] ({r['category']}) {r['content']}")
                    else:
                        print("  没有找到相关记忆")
                else:
                    print("⚠ 请提供查询，例如: /recall 学习计划")
                continue

            # 检查是否为 /reminders 命令（查看提醒清单）
            if user_input == '/reminders':
                # 提醒功能不依赖 Agent，直接读文件即可
                reminders_file = Config.REMINDERS_FILE
                if not reminders_file.exists():
                    print("\n🔔 还没有任何提醒")
                    print("  让 Agent 用 add_reminder 工具添加，例如: /agent 提醒我明天复习 LangChain")
                else:
                    import json
                    reminders = json.loads(reminders_file.read_text(encoding="utf-8"))
                    # 过滤未完成的
                    pending = [r for r in reminders if not r.get("done", False)]
                    if not pending:
                        print("\n🔔 所有提醒都已完成 🎉")
                    else:
                        print(f"\n🔔 待办提醒（共 {len(pending)} 条）:")
                        for r in pending:
                            when_text = f"（{r['when']}）" if r.get("when") else ""
                            print(f"  • {r['task']} {when_text}")
                continue

            # 检查是否为其他以 / 开头的未知命令
            if user_input.startswith('/'):
                print(f"⚠ 未知命令: {user_input}")
                print("输入 /help 查看可用命令")
                continue

            # ===== 正常对话处理 =====

            # 检查是否有文档在知识库中
            # 如果有，使用 RAG 模式回答；否则使用普通对话
            use_rag = (
                rag_pipeline is not None and
                rag_pipeline.vectorstore.count() > 0
            )

            if use_rag:
                # ===== RAG 模式：基于文档回答 =====
                print("\n🔍 正在检索相关文档...")

                try:
                    # 调用 RAG Pipeline 查询
                    result = rag_pipeline.query(user_input, k=4)

                    # 显示回答
                    if USE_RICH:
                        console.print("[bold green]🤖 Assistant: [/bold green]")
                    else:
                        print("\n🤖 Assistant:")

                    print(result['answer'])

                    # 显示来源（如果有）
                    if result['sources']:
                        print("\n📚 参考来源:")
                        for src in result['sources']:
                            source_name = src['source']
                            if 'page' in src:
                                print(f"  - 《{source_name}》第{src['page']}页")
                            else:
                                print(f"  - 《{source_name}》")

                    # 将问答添加到对话历史（可选）
                    # 这样用户可以在 RAG 回答后继续追问
                    session.add_message('user', user_input)
                    session.add_message('assistant', result['answer'])

                except Exception as e:
                    print(f"\n[错误] RAG 查询失败: {str(e)}")

            else:
                # ===== 普通对话模式 =====
                if USE_RICH:
                    console.print("[bold green]🤖 Assistant: [/bold green]", end="")
                else:
                    print("🤖 Assistant: ", end="")

                try:
                    # 调用 session.chat() 发送消息给 AI
                    session.chat(user_input, stream=True)
                except Exception as e:
                    pass

        # ----------------------------------------
        # 异常处理
        # ----------------------------------------

        except KeyboardInterrupt:
            # Ctrl+C 会抛出 KeyboardInterrupt 异常
            print("\n\n[中断] 收到 Ctrl+C，继续输入或输入 exit 退出")
            # continue 继续循环，给用户重新输入的机会
            continue

        except EOFError:
            # Ctrl+D（Unix/Linux）会抛出 EOFError，表示输入结束
            print("\n👋 再见！")
            break

        except Exception as e:
            # 捕获其他所有异常，防止程序崩溃
            print(f"\n[错误] {str(e)}")


# ============================================
# 程序入口点
# ============================================

# 当直接运行这个文件时（不是作为模块导入），__name__ 等于 '__main__'
# 这是 Python 的惯用法，确保某些代码只在直接运行时执行
if __name__ == '__main__':
    # 调用主函数，启动程序
    main()
