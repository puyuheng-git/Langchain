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

- **V1** (当前): 会聊天的笔记本 - 多轮对话 CLI
- **V2**: 能读懂你的文档 - RAG 向量知识库
- **V3**: 会主动帮你做事 - Agent + 工具调用
- **V4**: 完全属于你的模型 - LoRA 微调 + 本地部署

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
├── chat/                # 对话模块包
│   ├── __init__.py      # 包初始化文件
│   └── session.py       # ChatSession 类，核心对话逻辑
└── data/                # 数据目录（自动创建）
    └── history/         # 对话历史存储
```

## CLI 命令

在 `main.py` 运行后，支持以下命令：

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

### 入口层 (main.py)
- CLI 界面循环
- 命令解析和处理
- 集成 Rich 库美化输出（可选）

## 关键概念

**System Prompt**: 系统提示词，定义 AI 助手的角色和行为。例如"你是一位 Python 专家"

**Messages 格式**: OpenAI API 使用的消息格式，每条消息包含 `role` 和 `content`:
- `role="system"`: 系统提示
- `role="user"`: 用户输入
- `role="assistant"`: AI 回复

**Token**: 大语言模型的计费单位，约等于 1 个中文字符或 0.75 个英文单词

**流式输出 (Streaming)**: API 逐字返回结果，而不是等全部生成后再返回，用户体验更好

## 依赖说明

| 包名 | 用途 |
|------|------|
| `openai` | 调用 DeepSeek/OpenAI API |
| `python-dotenv` | 从 .env 文件加载环境变量 |
| `rich` | 美化 CLI 输出（彩色、表格、面板） |
| `streamlit` | Web UI 框架（V2+ 使用） |

## 注意事项

1. **API Key 安全**: 永远不要将真实的 API Key 提交到 Git，使用 `.env` 文件
2. **Token 限制**: 免费账户有 Token 使用限制，注意 `MAX_HISTORY_TOKENS` 配置
3. **网络要求**: 访问 DeepSeek API 需要网络连接，国内可直接访问
4. **Python 版本**: 需要 Python 3.11+
