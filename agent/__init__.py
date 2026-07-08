"""
Agent 模块 (agent) —— V3 新增

这个包实现了「会主动帮你做事」的智能体（Agent）能力：
- graph.py: 用 LangGraph 编排「规划 → 执行 → 反思」的流程，封装成 KnowledgeAgent
- tools.py: Agent 可以调用的工具集（网页搜索、代码执行、知识库读写、记忆、提醒）

与 V1/V2 的关系：
- V1 是被动对话，V2 能读文档，V3 则让 AI 主动规划并调用工具完成多步任务

使用示例:
    from agent import KnowledgeAgent

    agent = KnowledgeAgent(rag_pipeline, memory)
    answer = agent.run("帮我查一下 LangGraph 并总结成笔记存进知识库")
    print(answer)

注意：本包依赖 langgraph 和 langchain-openai。
如果这两个库没安装，导入会失败——调用方（main.py）已用 try/except 优雅处理。
"""

# 从子模块导入主要类，方便外部直接 from agent import KnowledgeAgent
from .graph import KnowledgeAgent
from .tools import build_tools

# 声明本包对外公开的名称
__all__ = ['KnowledgeAgent', 'build_tools']
