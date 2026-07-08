# 🤖 个人 AI 知识库助手（my-brain）

> 一个项目，四次进化，构建你的 AI 第二大脑。

从一个命令行聊天机器人，逐步进化为**会读文档、会主动做事、完全属于你**的私人 AI 助手。
面向 Python 初学者，代码逐行中文注释，边做边学。

---

## ✨ 四个阶段

| 版本 | 主题 | 能力 |
|------|------|------|
| **V1** ✅ | 会聊天的笔记本 | 多轮对话、角色切换、流式输出、历史保存 |
| **V2** ✅ | 能读懂你的文档 | RAG 向量知识库、语义检索、来源引用 |
| **V3** ✅ | 会主动帮你做事 | Agent + 工具调用（搜索/代码/知识库）+ 长期记忆 |
| **V4** ✅ | 完全属于你的模型 | LoRA 微调 + 图片 OCR + Ollama 本地部署 |

---

## 🚀 快速开始

### 1. 安装依赖

```bash
# 需要 Python 3.11+
pip install -r requirements.txt
```

### 2. 配置 API Key

```bash
# 复制配置模板
cp .env.example .env      # Windows: copy .env.example .env
```

然后编辑 `.env`，至少填入 **DeepSeek API Key**（[注册地址](https://platform.deepseek.com)，国内可直接用）：

```bash
DEEPSEEK_API_KEY=sk-你的密钥
```

> 想用 V2 知识库？再填 `OPENAI_API_KEY`（或[硅基流动](https://cloud.siliconflow.cn) Key）做 Embedding。
> 想用 V3 网页搜索？再填 `TAVILY_API_KEY`（[免费 1000 次/月](https://tavily.com)）。

### 3. 运行

```bash
python main.py
```

> 💡 中文 Windows 若遇到 emoji 编码报错，运行前设 `set PYTHONUTF8=1`（或用支持 UTF-8 的终端/IDE）。

---

## 💬 CLI 命令

| 命令 | 说明 | 版本 |
|------|------|------|
| `/help` | 显示帮助 | V1 |
| `/system <prompt>` | 切换 AI 角色 | V1 |
| `/clear` | 清空对话历史 | V1 |
| `/save [名称]` | 保存对话到 `data/history/` | V1 |
| `/history` · `/load <文件>` | 查看 / 加载历史对话 | V1 |
| `/stats` · `/model` | 查看统计 / 当前模型 | V1 |
| `/ingest <路径>` | 索引文档（PDF/TXT/MD） | V2 |
| `/docs` · `/delete <名>` | 查看 / 删除已索引文档 | V2 |
| `/search <关键词>` | 测试检索（不生成回答） | V2 |
| `/agent <任务>` | 让智能体规划+调用工具完成任务 | V3 |
| `/remember <内容>` | 存入长期记忆（跨对话） | V3 |
| `/memories` · `/recall <查询>` | 查看 / 召回长期记忆 | V3 |
| `/reminders` | 查看提醒清单 | V3 |
| `exit` / `quit` | 退出 | — |

---

## 📖 使用示例

```bash
$ python main.py

# V2：加文档后自动基于文档回答
> /ingest data/docs/python_tutorial.pdf
> Python 的装饰器是什么？          # 自动检索文档并附来源引用

# V3：让智能体自主做事（多步骤）
> /agent 帮我查一下 LangGraph 是什么，并总结成笔记存进知识库

# V3：长期记忆（关掉程序也记得）
> /remember 我在学习 LangChain 和 LangGraph
> /recall 我在学什么
```

---

## 🗂️ 项目结构

```
my-brain/
├── main.py              # CLI 入口
├── config.py            # 统一配置（从 .env 加载，支持 deepseek/openai/ollama）
├── chat/                # V1 对话 + V3 记忆
│   ├── session.py       #   ChatSession 多轮对话管理
│   └── memory.py        #   LongTermMemory 长期记忆
├── rag/                 # V2 检索增强 + V4 多模态
│   ├── loader/chunker/embedder/vectorstore/retriever/pipeline.py
│   └── multimodal.py    #   图片 OCR → 入库
├── agent/               # V3 智能体
│   ├── tools.py         #   工具注册表（搜索/代码/知识库/记忆/提醒）
│   └── graph.py         #   LangGraph 规划→执行→反思
├── finetune/            # V4 微调（详见 finetune/README.md）
│   ├── data_prep.py     #   对话历史 → Alpaca 数据集
│   ├── train_config.yaml#   LLaMA-Factory LoRA 配置
│   └── README.md        #   训练 + Ollama 部署完整步骤
└── data/                # 文档 / 向量库 / 历史（不提交 Git）
```

---

## 🧠 核心概念速览

- **RAG（检索增强生成）**：先检索相关文档，再基于文档生成回答，让 AI 能用你的私有资料
- **Embedding（向量化）**：把文本变成向量，语义相近的文本向量距离也近，是语义检索的基础
- **Agent（智能体）**：能主动「规划 → 调用工具 → 观察结果 → 再规划」，而不只是被动应答
- **LangGraph**：用有向图编排 Agent 的规划/执行/反思流程，比传统方式更可控
- **长期记忆**：跨对话持久化的用户偏好/计划，存在 Chroma 里按语义召回
- **微调 vs RAG**：RAG 更新「知道什么」，微调改变「说话风格/行为」，二者互补
- **LoRA / Ollama**：LoRA 高效微调只训练少量参数；Ollama 一条命令本地跑模型，数据不出本机

---

## 🛠️ 技术栈

| 类别 | 选用 |
|------|------|
| 语言 | Python 3.11+ |
| 主力模型 | DeepSeek API（中文优，价格约 OpenAI 的 1/10） |
| Embedding | text-embedding-3-small / bge-m3 |
| RAG 框架 | LangChain |
| 向量库 | Chroma（本地零配置） |
| Agent 框架 | LangGraph |
| 微调 / 部署 | LLaMA-Factory / Ollama |
| 界面 | CLI（Rich 美化） |

---

## 📦 V4：训练你的专属模型

V4 涉及 GPU 训练与本地部署，完整步骤（数据准备 → AutoDL 微调 → 量化 → Ollama 部署 → 接回项目）见
👉 **[finetune/README.md](finetune/README.md)**

训练完成后，只需在 `.env` 改一行即可调用你的本地模型：

```bash
LLM_PROVIDER=ollama
OLLAMA_MODEL=my-brain
```

---

## ⚠️ 注意事项

1. **API Key 安全**：真实密钥只放 `.env`（已被 `.gitignore` 忽略），永不提交 Git
2. **Token 成本**：注意 `.env` 中的 `MAX_HISTORY_TOKENS`，历史越长调用越贵
3. **网络**：DeepSeek 国内可直接访问；OpenAI 可用硅基流动等兼容平台替代
4. **可选依赖优雅降级**：缺某个库时对应功能自动禁用并给出提示，不影响其他功能

---

## 📄 许可

个人学习项目，欢迎参考学习。
