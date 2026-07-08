#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LangGraph Agent 编排 (graph.py) —— V3 核心

什么是 Agent（智能体）？
- 普通对话：用户问一句，AI 答一句，被动响应
- Agent：AI 会「主动规划」——先想「要完成这个任务，我需要分几步、用哪些工具」，
  然后一步步执行、观察结果、再决定下一步，直到任务完成

什么是 LangGraph？
- LangGraph 是 LangChain 团队做的「用图来编排 AI 流程」的框架
- 核心概念：
  * State（状态）：在整个流程中流转的数据（这里主要是对话消息列表）
  * Node（节点）：图上的一个处理步骤（一个函数），负责修改 State
  * Edge（边）：节点之间的连线，决定「下一步走到哪个节点」
  * 条件边（Conditional Edge）：根据当前 State 动态决定走向（if/else 分支）

本文件实现的图（对应文档的「规划 → 执行 → 反思」）：

        START
          │
          ▼
      ┌────────┐   有工具要调用   ┌─────────┐
      │  plan  │ ───────────────▶ │ execute │
      │ (规划) │ ◀─────────────── │ (执行)  │
      └────────┘   执行完再规划   └─────────┘
          │
          │ 没有工具要调用（得到答案了）
          ▼
      ┌─────────┐
      │ reflect │  （反思/收尾，检查答案质量）
      │ (反思)  │
      └─────────┘
          │
          ▼
         END

这个「规划↔执行」的来回循环，就是经典的 ReAct（推理+行动）模式。
"""

# 导入 sys 和 Path，用于把项目根目录加入模块搜索路径
import sys
from pathlib import Path

# 把项目根目录加入 sys.path
sys.path.append(str(Path(__file__).parent.parent))

# 导入类型提示工具
# Annotated: 给类型附加「额外信息」，LangGraph 用它指定「状态如何合并」
# TypedDict: 定义「带固定字段的字典」类型，用来描述 State 的结构
from typing import Annotated, TypedDict

# 从 langgraph 导入构图工具
# StateGraph: 状态图的构建器
# START / END: 图的起点和终点这两个特殊标记
from langgraph.graph import StateGraph, START, END

# add_messages 是一个「合并函数」（reducer）
# 当节点返回新消息时，它负责把新消息「追加」到已有消息列表，而不是覆盖
from langgraph.graph.message import add_messages

# 从 langchain_core 导入几种消息类型
# SystemMessage: 系统提示（设定 AI 角色）
# HumanMessage: 用户消息
# ToolMessage: 工具执行结果（喂回给大模型）
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage

# ChatOpenAI 是 LangChain 对 OpenAI 兼容接口的封装
# 我们让它指向 DeepSeek，用来做「带工具调用」的对话
from langchain_openai import ChatOpenAI

# 导入配置
from config import Config

# 导入工具工厂
from .tools import build_tools


# ============================================
# 定义 Agent 的状态（State）
# ============================================

class AgentState(TypedDict):
    """
    Agent 的状态结构

    这是在图的各个节点之间流转的数据。字段说明：
    - messages: 对话消息列表。Annotated[list, add_messages] 表示
                「节点返回的新消息会被追加进来」（而不是替换整个列表）
    - iterations: 已经循环了多少轮，用于防止无限循环
    """
    # 消息列表：用 add_messages 作为合并策略（追加而非覆盖）
    messages: Annotated[list, add_messages]
    # 循环计数器
    iterations: int


# ============================================
# KnowledgeAgent 主类
# ============================================

class KnowledgeAgent:
    """
    知识库智能体

    把「大模型 + 工具 + LangGraph 流程」封装成一个易用的对象。
    对外只暴露一个 run() 方法：给它一个任务，它自己规划、调用工具、给出结果。

    使用示例:
        agent = KnowledgeAgent(rag_pipeline, memory)
        answer = agent.run("帮我查一下 LangGraph 是什么，并存进知识库")
        print(answer)
    """

    def __init__(self, rag_pipeline=None, memory=None):
        """
        初始化 Agent

        Args:
            rag_pipeline: RAGPipeline 实例（知识库工具需要，可为 None）
            memory: LongTermMemory 实例（记忆功能需要，可为 None）
        """
        print("初始化 LangGraph Agent...")

        # 保存长期记忆对象，run() 时用来召回记忆
        self.memory = memory

        # ----- 步骤 1: 创建大模型客户端 -----
        # 从配置读取当前 provider 的 API 信息（DeepSeek / OpenAI / Ollama）
        api_config = Config.get_api_config()

        # ChatOpenAI 用 OpenAI 兼容协议，指向 DeepSeek
        # DeepSeek 支持「函数/工具调用」，所以可以驱动 Agent
        self.llm = ChatOpenAI(
            model=api_config["model"],        # 模型名称
            api_key=api_config["api_key"],    # API 密钥
            base_url=api_config["base_url"],  # API 地址
            temperature=Config.TEMPERATURE    # 随机性
        )

        # ----- 步骤 2: 创建工具 -----
        # build_tools 返回工具列表，并把知识库、记忆注入进去
        self.tools = build_tools(rag_pipeline, memory)

        # 建立「工具名 → 工具对象」的字典，执行节点用它按名字找到工具
        # 字典推导式：{键: 值 for 元素 in 列表}
        self.tools_by_name = {t.name: t for t in self.tools}

        # ----- 步骤 3: 把工具「绑定」到大模型 -----
        # bind_tools 之后，大模型在回答时就能返回「工具调用请求」
        self.llm_with_tools = self.llm.bind_tools(self.tools)

        # ----- 步骤 4: 构建并编译流程图 -----
        self.graph = self._build_graph()

        print(f"✓ Agent 就绪（已加载 {len(self.tools)} 个工具）")

    # ----------------------------------------
    # 构建流程图
    # ----------------------------------------

    def _build_graph(self):
        """
        构建 LangGraph 状态图

        Returns:
            编译后的图对象（可以用 .invoke() 运行）
        """
        # 创建一个以 AgentState 为状态类型的图构建器
        builder = StateGraph(AgentState)

        # 添加三个节点：名字 → 处理函数
        # add_node(节点名, 函数)
        builder.add_node("plan", self._plan_node)        # 规划
        builder.add_node("execute", self._execute_node)  # 执行
        builder.add_node("reflect", self._reflect_node)  # 反思

        # 起点连到 plan 节点：程序从规划开始
        builder.add_edge(START, "plan")

        # plan 之后是「条件边」：根据 _should_continue 的返回值决定去哪
        # 返回 "execute" → 去执行工具；返回 "reflect" → 去反思收尾
        builder.add_conditional_edges(
            "plan",
            self._should_continue,
            {
                "execute": "execute",   # 需要调用工具
                "reflect": "reflect"    # 已有最终答案
            }
        )

        # 执行完工具，回到 plan 继续规划（观察工具结果，决定下一步）
        # 这就是 ReAct 的「行动 → 再推理」回环
        builder.add_edge("execute", "plan")

        # 反思完成后，走到终点 END
        builder.add_edge("reflect", END)

        # compile() 把图「编译」成可运行的对象
        return builder.compile()

    # ----------------------------------------
    # 节点 1: 规划（plan）
    # ----------------------------------------

    def _plan_node(self, state: AgentState) -> dict:
        """
        规划节点：让大模型看当前对话，决定「下一步做什么」

        大模型可能：
        - 返回一段文字（表示已经想好答案，不需要工具）
        - 返回一个或多个「工具调用请求」（表示需要先用工具）

        Args:
            state: 当前状态（含消息列表）

        Returns:
            要合并进状态的字典：新增的 AI 消息 + 更新循环计数
        """
        print("🧠 [规划] 正在思考下一步...")

        # 让绑定了工具的大模型处理当前所有消息
        # 返回的 response 是一条 AIMessage，可能带 tool_calls
        response = self.llm_with_tools.invoke(state["messages"])

        # 返回：把这条 AI 消息追加进 messages，循环次数 +1
        # state.get("iterations", 0) 安全地取当前计数（没有就当 0）
        return {
            "messages": [response],
            "iterations": state.get("iterations", 0) + 1
        }

    # ----------------------------------------
    # 条件判断：接下来该执行工具还是反思？
    # ----------------------------------------

    def _should_continue(self, state: AgentState) -> str:
        """
        条件路由函数：决定 plan 之后走向哪个节点

        Args:
            state: 当前状态

        Returns:
            "execute"（去执行工具）或 "reflect"（去反思收尾）
        """
        # 取出最后一条消息（就是 plan 节点刚生成的 AI 消息）
        last_message = state["messages"][-1]

        # 判断这条 AI 消息里有没有「工具调用请求」
        # getattr(对象, 属性名, 默认值)：安全地取属性，没有就返回默认值
        tool_calls = getattr(last_message, "tool_calls", None)

        # 如果有工具要调用，且还没超过最大循环次数 → 去执行
        if tool_calls and state.get("iterations", 0) < Config.AGENT_MAX_ITERATIONS:
            return "execute"

        # 否则（没有工具要调用，或已达循环上限）→ 去反思收尾
        return "reflect"

    # ----------------------------------------
    # 节点 2: 执行（execute）
    # ----------------------------------------

    def _execute_node(self, state: AgentState) -> dict:
        """
        执行节点：真正运行大模型要求调用的工具

        Args:
            state: 当前状态

        Returns:
            要合并进状态的字典：每个工具的执行结果（ToolMessage 列表）
        """
        # 取出最后一条 AI 消息（里面有 tool_calls）
        last_message = state["messages"][-1]

        # 用来收集所有工具的执行结果
        tool_messages = []

        # 遍历大模型要求的每一个工具调用
        # 一次可能要调用多个工具，所以是列表
        for call in last_message.tool_calls:
            # 每个 call 是字典：name（工具名）、args（参数）、id（调用编号）
            tool_name = call["name"]
            tool_args = call["args"]
            call_id = call["id"]

            print(f"🔧 [执行] 调用工具: {tool_name}，参数: {tool_args}")

            # 按名字找到对应的工具对象
            tool = self.tools_by_name.get(tool_name)

            if tool is None:
                # 大模型「幻觉」出了一个不存在的工具
                result = f"错误：找不到名为 {tool_name} 的工具。"
            else:
                try:
                    # .invoke(参数字典) 执行工具，返回结果
                    result = tool.invoke(tool_args)
                except Exception as e:
                    # 工具执行出错时，把错误信息作为结果返回
                    # 这样大模型能「看到」错误，从而尝试重试或换策略
                    # （对应文档里程碑：工具失败时能自动重试或切换）
                    result = f"工具执行出错：{str(e)}"

            # 把结果包装成 ToolMessage
            # tool_call_id 必须和请求的 id 对应，大模型才知道这是哪次调用的结果
            tool_messages.append(
                ToolMessage(content=str(result), tool_call_id=call_id)
            )

        # 返回所有工具结果，它们会被追加进 messages，然后回到 plan 节点
        return {"messages": tool_messages}

    # ----------------------------------------
    # 节点 3: 反思（reflect）
    # ----------------------------------------

    def _reflect_node(self, state: AgentState) -> dict:
        """
        反思节点：在给出最终答案前，做一次质量自检

        设计说明：
        - 如果这次任务「用过工具」，说明答案是综合多步信息得来的，
          值得让大模型再审一遍是否完整准确 → 做一次自检
        - 如果全程「没用工具」（纯聊天式回答），plan 节点给的答案就是最终答案，
          不必再花一次调用 → 直接放行

        Args:
            state: 当前状态

        Returns:
            若做了自检，返回精炼后的最终答案；否则返回空字典（不改动状态）
        """
        messages = state["messages"]

        # 判断整个过程中是否出现过工具结果（ToolMessage）
        # any(...) 只要有一个满足条件就返回 True
        has_tool_use = any(isinstance(m, ToolMessage) for m in messages)

        # 没用过工具：直接放行，不额外调用大模型（省 token）
        if not has_tool_use:
            print("✅ [反思] 直接回答，无需自检")
            return {}

        print("🔍 [反思] 正在自检并整理最终答案...")

        # 用过工具：追加一条指令，让大模型审校并输出最终答案
        # 注意这里用「不带工具」的 self.llm，因为反思阶段不再调用工具
        review_instruction = SystemMessage(content=(
            "以上是你为解决用户问题所做的推理和工具调用过程。"
            "现在请检查：答案是否完整、准确地解决了用户的问题？"
            "如果已经很好，就把最终答案清晰地重述给用户；"
            "如果有遗漏或错误，请给出改进后的最终答案。"
            "只输出给用户看的最终回答，不要解释你的审校过程。"
        ))

        # 让大模型基于「完整对话 + 审校指令」生成最终答案
        final_message = self.llm.invoke(messages + [review_instruction])

        # 返回这条最终消息，它会成为对话的最后一条
        return {"messages": [final_message]}

    # ----------------------------------------
    # 对外主接口: run
    # ----------------------------------------

    def run(self, user_input: str) -> str:
        """
        运行 Agent，完成用户交给的任务

        Args:
            user_input: 用户的任务描述，例如「帮我查 X 并总结成笔记存入知识库」

        Returns:
            Agent 给出的最终回答（字符串）
        """
        # ----- 组装系统提示词（system prompt）-----
        # 这段话设定 Agent 的角色和行为准则
        base_prompt = (
            "你是一个会主动帮用户做事的 AI 助手，拥有网页搜索、代码执行、"
            "知识库读写、长期记忆、提醒等工具。"
            "面对任务时，请先规划步骤，需要外部信息或操作时主动调用合适的工具，"
            "拿到工具结果后再继续推理，直到任务完成。"
            "当你了解到用户的重要偏好或计划时，用 save_memory 记下来。"
        )

        # 如果有长期记忆模块，召回和当前任务相关的记忆，拼进系统提示词
        # 这样 Agent 就「记得」用户过去说过的话（跨对话记忆）
        if self.memory is not None:
            memory_text = self.memory.format_for_prompt(user_input)
            base_prompt += memory_text

        # ----- 组装初始状态 -----
        # 第一条是系统提示，第二条是用户的任务
        initial_state = {
            "messages": [
                SystemMessage(content=base_prompt),
                HumanMessage(content=user_input)
            ],
            "iterations": 0
        }

        # ----- 运行流程图 -----
        # config 里的 recursion_limit 是 LangGraph 的总步数上限（防呆保护）
        # 我们自己已经用 AGENT_MAX_ITERATIONS 控制循环，这里给个宽松值即可
        final_state = self.graph.invoke(
            initial_state,
            config={"recursion_limit": 50}
        )

        # 取出最后一条消息，它的 content 就是最终答案
        last_message = final_state["messages"][-1]

        # 有些模型返回的 content 可能不是纯字符串，用 str() 兜底
        return str(last_message.content)


# ============================================
# 测试代码
# ============================================

if __name__ == "__main__":
    print("=" * 50)
    print("测试 KnowledgeAgent（需要配置好 API Key 且已安装 langgraph）")
    print("=" * 50)

    try:
        # 不注入知识库/记忆，做一个最小化测试
        agent = KnowledgeAgent(rag_pipeline=None, memory=None)

        # 让 Agent 做一个需要用工具（代码执行）的任务
        print("\n任务: 计算 1 到 100 的和")
        answer = agent.run("请计算 1 加到 100 的结果是多少？用 Python 算。")
        print(f"\n最终答案:\n{answer}")

        print("\n✓ Agent 测试完成!")

    except Exception as e:
        print(f"\n✗ 测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
