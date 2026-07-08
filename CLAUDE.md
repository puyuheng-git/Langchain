# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 代码注释规则 (Code Comment Rules)

**重要**: 用户正在学习 Python，因此所有代码必须遵循以下注释规范：

1. **每一行代码都要有注释**: 每个逻辑行（包括空行）上方或行尾都要有解释
2. **注释要详细**: 解释这行代码"在做什么"以及"为什么这样做"
3. **对初学者友好**: 避免使用过于专业的术语，必要时解释 Python 语法
4. **中文注释**: 所有注释使用中文
5. **函数/类文档**: 每个函数和类必须有 docstring，说明功能、参数、返回值

示例:
```python
# 从操作系统环境变量中读取 API Key
# os.getenv() 用于获取环境变量的值，如果变量不存在则返回默认值
api_key = os.getenv('API_KEY', '')
```

## 项目概述

这是一个"个人 AI 知识库助手"项目，通过四个阶段迭代构建：

- **V1** ✓: 会聊天的笔记本 - 多轮对话 CLI
- **V2** ✓: 能读懂你的文档 - RAG 向量知识库
- **V3** ✓: 会主动帮你做事 - Agent + 工具调用 + 长期记忆
- **V4** ✓: 完全属于你的模型 - LoRA 微调 + 多模态 + 本地部署（代码与配置已就绪，训练/部署需 GPU/Ollama）

## 运行方式

```bash
# 1. 配置环境变量
# 复制模板文件为实际配置文件
copy .env.example .env
# 编辑 .env 填入 DeepSeek API Key

# 2. 安装依赖
pip install -r requirements.txt

# 3. 运行程序
python main.py
```

## 项目结构

```
LangChain/
├── main.py              # CLI 入口点
├── config.py            # 配置管理，从 .env 加载
├── .env                 # API Key 等敏感配置（不提交 Git）
├── .env.example         # 环境变量模板
├── requirements.txt     # Python 依赖清单
├── .gitignore           # Git 忽略规则
├── chat/                # 【V1】对话模块包
│   ├── __init__.py
│   ├── session.py       # ChatSession 类
│   └── memory.py        # 【V3 新增】LongTermMemory 长期记忆（基于 Chroma）
├── rag/                 # 【V2 新增】RAG 模块包
│   ├── __init__.py
│   ├── loader.py        # 文档加载（PDF/TXT/MD）
│   ├── chunker.py       # 文本分块
│   ├── embedder.py      # Embedding 向量化
│   ├── vectorstore.py   # Chroma 向量数据库
│   ├── retriever.py     # 相似度检索
│   ├── pipeline.py      # RAG 流程编排
│   └── multimodal.py    # 【V4 新增】图片 OCR → 入库
├── agent/               # 【V3 新增】Agent 模块包
│   ├── __init__.py
│   ├── tools.py         # 工具注册表（搜索/代码/知识库/记忆/提醒）
│   └── graph.py         # LangGraph StateGraph + KnowledgeAgent
├── finetune/            # 【V4 新增】微调模块包
│   ├── __init__.py
│   ├── data_prep.py     # 对话历史 → Alpaca 格式数据集
│   ├── train_config.yaml# LLaMA-Factory LoRA 配置
│   ├── dataset_info.json# 数据集注册
│   └── README.md        # 训练 + Ollama 部署完整步骤
└── data/                # 数据目录（自动创建）
    ├── docs/            # 【V2】用户上传的原始文档
    ├── chroma_db/       # 【V2/V3】向量库（文档 + 长期记忆两个集合）
    ├── history/         # 对话历史存储
    └── reminders.json   # 【V3】提醒清单
```

## CLI 命令

在 `main.py` 运行后，支持以下命令：

### V1 基础命令

| 命令 | 说明 |
|------|------|
| `/help` | 显示帮助信息 |
| `/system <prompt>` | 切换系统提示词（角色扮演） |
| `/clear` | 清空对话历史 |
| `/save [文件名]` | 保存对话到 `data/history/` |
| `/history` | 查看历史对话列表 |
| `/load <文件名>` | 加载历史对话 |
| `/stats` | 显示对话统计信息 |
| `/model` | 显示当前模型配置 |
| `exit` / `quit` | 退出程序 |

### V2 文档知识库命令

| 命令 | 说明 |
|------|------|
| `/ingest <路径>` | 上传/索引文档（支持 PDF/TXT/MD） |
| `/docs` | 查看已索引的文档列表 |
| `/delete <文档名>` | 删除指定文档 |
| `/search <关键词>` | 测试检索（不生成回答） |

### V3 智能体与记忆命令

| 命令 | 说明 |
|------|------|
| `/agent <任务>` | 让智能体自主规划、调用工具完成多步任务 |
| `/remember <内容>` | 把一条信息存入长期记忆（跨对话记住） |
| `/memories` | 查看所有长期记忆 |
| `/recall <查询>` | 测试记忆召回（按语义找相关记忆） |
| `/reminders` | 查看提醒清单 |

## 使用示例

### 文档知识库工作流程

```bash
# 1. 启动程序
$ python main.py

# 2. 添加文档到知识库
> /ingest data/docs/python_tutorial.pdf

# 3. 查看已索引文档
> /docs

# 4. 提问（自动基于文档回答）
> Python 的装饰器是什么？
[AI 会基于文档内容回答，并显示来源]

# 5. 测试检索（不生成回答）
> /search 装饰器
```

## 历史对话功能

### 启动时加载
程序启动时会自动检查是否有历史对话文件，并询问是否加载：
- 输入 `1-N`: 加载对应编号的历史对话
- 输入 `a`: 查看完整历史列表
- 直接回车: 开始新对话

### 手动加载
在对话中随时可以使用 `/load <文件名>` 加载历史对话，例如：
```
/load chat_20240115_143022.json
```

### 保存位置
所有历史文件保存在 `data/history/` 目录：
- `.json` 文件：包含完整对话数据（用于加载）
- `.md` 文件：Markdown 格式（用于阅读）

### 示例工作流程
1. 第一次对话，使用 `/save` 保存
2. 退出程序 `exit`
3. 下次启动时，选择加载之前的对话
4. 继续之前的对话上下文

## 架构说明

### 配置层 (config.py)
- 使用 `python-dotenv` 从 `.env` 文件加载配置
- 支持 DeepSeek 和 OpenAI 两种提供商切换
- 集中管理所有环境变量

### 对话层 (chat/session.py)
- `ChatSession` 类封装所有对话逻辑
- 维护 `messages` 列表存储对话历史
- 自动 Token 估算和消息截断
- 支持流式输出（逐字显示）
- 提供导出功能（Markdown/JSON）

### RAG 层 (rag/)

**DocumentLoader (loader.py)**
- 支持 PDF、TXT、Markdown 格式
- 使用 LangChain Loaders 提取文本和元数据

**TextChunker (chunker.py)**
- 使用 RecursiveCharacterTextSplitter
- 智能分块：优先按段落，其次按句子
- 支持重叠（overlap）保持上下文

**Embedder (embedder.py)**
- 文本向量化：文本 → 向量（Embedding）
- 支持 OpenAI text-embedding-3-small
- 支持本地 bge-m3 模型（可选）

**VectorStore (vectorstore.py)**
- 基于 Chroma 向量数据库
- 本地文件存储，零配置
- 支持相似度搜索和 CRUD 操作

**Retriever (retriever.py)**
- 检索器：查询 → 向量 → 相似度搜索
- 格式化上下文用于 Prompt 构建

**RAGPipeline (pipeline.py)**
- 整合所有组件
- 提供 `ingest_document()` 和 `query()` 接口

### Agent 层 (agent/) 【V3】

**工具注册表 (tools.py)**
- `build_tools(rag_pipeline, memory)` 工厂函数，用依赖注入创建工具
- 工具：网页搜索(Tavily)、Python 代码执行、知识库读/写、保存记忆、添加提醒
- 每个工具用 `@tool` 装饰，docstring 即「给 LLM 看的说明书」

**LangGraph 编排 (graph.py)**
- `AgentState`：在节点间流转的状态（messages + iterations）
- 三节点：`plan`(规划) → `execute`(执行工具) → `reflect`(反思收尾)
- 条件路由：plan 后若有工具调用则 execute，execute 后回到 plan（ReAct 回环）
- `KnowledgeAgent.run()`：召回长期记忆注入 system prompt，再跑图
- 用 `ChatOpenAI` 指向 DeepSeek 驱动工具调用

### 记忆层 (chat/memory.py) 【V3】

**LongTermMemory**
- 复用 Embedder + VectorStore（独立集合 `long_term_memory`）
- 跨对话记住用户偏好/概念/计划，按语义召回
- 每条记忆用唯一 `mem_UUID` 作 source，避免 ID 冲突

### 多模态层 (rag/multimodal.py) 【V4】

**MultimodalProcessor**
- `ocr_image()`：用视觉模型(gpt-4o)把图片文字提取出来
- `ingest_image()`：OCR → 存 md → 入库，让图片笔记可被检索

### 模型层切换 (config.py) 【V4】

- `LLM_PROVIDER=ollama` 时，`get_api_config()` 返回本地 Ollama 地址
- Ollama 提供 OpenAI 兼容接口，现有 ChatSession/Agent 零改动即可用本地模型

### 入口层 (main.py)
- CLI 界面循环
- 命令解析和处理
- 集成 Rich 库美化输出（可选）
- 自动切换：有文档用 RAG，无文档用普通对话

## 关键概念

### RAG (Retrieval-Augmented Generation)

**什么是 RAG？**
- RAG = 检索增强生成
- 原理：先检索相关文档，再基于文档生成回答
- 优势：让 AI 能够基于私有/最新文档回答

**RAG 工作流程**：
1. 用户提问
2. 查询向量化（Embedding）
3. 向量相似度检索（找出相关文档块）
4. 构建 Prompt（文档 + 问题）
5. LLM 生成回答
6. 显示回答 + 来源引用

### 向量与 Embedding

**Embedding（嵌入）**
- 将文本转换为数值向量
- 语义相似的文本，向量距离相近
- 类比：文本是地址，Embedding 是 GPS 坐标

**相似度计算**
- 使用余弦相似度（Cosine Similarity）
- 范围：-1 到 1，通常 0.7+ 算相似

### 文本分块策略

**为什么分块？**
- 向量模型有输入长度限制
- 小块检索更精确
- 控制成本（按 token 计费）

**分块参数**：
- `chunk_size`: 块大小（推荐 1000 字符）
- `chunk_overlap`: 重叠（推荐 10-20%，即 100-200 字符）

**重叠的作用**：
- 避免关键信息被切分在边界
- 保持上下文连贯性

### 其他概念

**System Prompt**: 系统提示词，定义 AI 助手的角色和行为。例如"你是一位 Python 专家"

**Messages 格式**: OpenAI API 使用的消息格式，每条消息包含 `role` 和 `content`:
- `role="system"`: 系统提示
- `role="user"`: 用户输入
- `role="assistant"`: AI 回复

**Token**: 大语言模型的计费单位，约等于 1 个中文字符或 0.75 个英文单词

**流式输出 (Streaming)**: API 逐字返回结果，而不是等全部生成后再返回，用户体验更好

### V3/V4 关键概念

**Agent（智能体）**
- 与普通对话的区别：普通对话是「被动响应」，Agent 会「主动规划 + 调用工具做事」
- 工作模式 ReAct：推理(Reasoning) → 行动(Acting) → 观察结果 → 再推理，循环直到完成

**LangGraph**
- 用「有向图」建模 Agent 流程：State(状态)、Node(节点)、Edge(边)、条件边
- 比传统 AgentExecutor 更可控，能清晰表达「规划→执行→反思」的循环

**工具调用 (Tool Calling)**
- 把工具的「名字/功能/参数」告诉大模型，模型决定何时调用哪个工具
- 程序执行工具，把结果喂回模型，模型据此继续或给出答案

**短期记忆 vs 长期记忆**
- 短期记忆：本次对话的 messages（关程序即消失）
- 长期记忆：存入 Chroma、跨对话持久化的用户偏好/计划/概念

**微调 vs RAG（互补）**
- RAG：给模型「外挂知识库」，更新的是「知道什么」
- 微调：调整模型参数，改变的是「说话风格/行为方式」

**LoRA / QLoRA**
- LoRA：只训练少量「插件」参数，省显存、快、产物小
- QLoRA：在 LoRA 基础上把基座模型 4-bit 量化加载，进一步省显存

**Ollama 本地部署**
- 一条命令在本机跑大模型，提供 OpenAI 兼容接口
- 本项目只需把 `LLM_PROVIDER` 改成 `ollama` 即可调用本地模型，数据不出本机

## 依赖说明

### V1 基础依赖

| 包名 | 用途 |
|------|------|
| `openai` | 调用 DeepSeek/OpenAI API |
| `python-dotenv` | 从 .env 文件加载环境变量 |
| `rich` | 美化 CLI 输出（彩色、表格、面板） |
| `streamlit` | Web UI 框架（V3+ 使用） |

### V2 RAG 依赖

| 包名 | 用途 |
|------|------|
| `langchain` | RAG 框架，提供文档处理抽象 |
| `langchain-community` | 社区组件（Loaders、Chroma） |
| `chromadb` | 向量数据库，本地存储 |
| `pypdf` | PDF 文档解析 |
| `python-magic` | 文件类型检测 |

### V3 Agent 依赖

| 包名 | 用途 |
|------|------|
| `langgraph` | 用有向图编排 Agent 的规划/执行/反思流程 |
| `langchain-openai` | `ChatOpenAI` 驱动 DeepSeek 做工具调用（V2 已装） |
| `tavily-python` | 网页搜索 API（每月 1000 次免费） |

### V4 多模态/微调/部署依赖

| 名称 | 用途 | 安装方式 |
|------|------|---------|
| `pillow` | 图片处理（多模态 OCR） | pip |
| LLaMA-Factory | LoRA 微调工具 | AutoDL GPU 机器单独装 |
| Ollama | 本地模型部署 | 本机单独装（ollama.ai） |
| llama.cpp | 模型量化/转 GGUF | AutoDL 单独装 |

## 注意事项

1. **API Key 安全**: 永远不要将真实的 API Key 提交到 Git，使用 `.env` 文件
2. **Token 限制**: 免费账户有 Token 使用限制，注意 `MAX_HISTORY_TOKENS` 配置
3. **网络要求**: 访问 DeepSeek API 需要网络连接，国内可直接访问
4. **Python 版本**: 需要 Python 3.11+
