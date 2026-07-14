# 企业智能管理工作台

本项目是一个本地优先的企业业务审阅与管理工作台，覆盖审计与合同、人力、行政和财务场景。

业务人员通过 Streamlit 浏览器界面上传材料。系统会保存原始文件、结构化结果、风险发现、报告、任务、审批及人工复核记录，下次启动后可以继续查看和处理。

原有 AI 知识库、RAG、Agent、长期记忆和合同 `/review` 命令继续保留。

## 核心能力

| 领域 | 工作流 | 主要结果 |
|---|---|---|
| 审计与合同 | 商业合同审阅 | 签约方、金额、付款、验收、违约、争议解决和异常条款 |
| 人力 | 劳动合同审阅 | 合同期限、工资、工时、社保、试用期、竞业限制和生命周期建议 |
| 人力 | 招聘匹配 | 技能、经验、项目、行业证据评分，支持盲审，不自动淘汰候选人 |
| 行政 | 制度审阅 | 制度版本、范围、归口、审批、职责分离、例外和留存规则 |
| 行政 | 会议事项 | 决定、负责人、截止日期、逾期风险和任务中心同步 |
| 财务 | 费用审阅 | 重复票据、限额、预算、附件、日期、拆分报销和审批冲突 |
| 财务 | 预算分析 | 执行率、余额、差异、超支、零预算支出和低执行项目 |

操作台还提供：

- 统一案件历史和原始附件下载；
- 高、中、低风险发现及来源证据；
- Markdown 报告和 JSON 明细下载；
- 会议任务与人工任务跟踪；
- 最终动作审批及申请人/审批人职责分离；
- 逐条人工复核、整改和案件状态管理；
- 虚构标准样本生成。
- 公司章程、部门制度、业务规范和会议决议的统一知识资料库；
- 每次分析自动对照本板块知识与历史案件，并保存引用原文、版本和相关度；
- 经负责人标记“已确认/已关闭”的案件沉淀为可供后续同类分析召回的历史记忆；
- 酒店集团的九份规划基线样本（不代表企业现行制度）。
- 系统管理页面可配置 L1/L2/L3 路由策略、本地/外部模型、API Key、Base URL、模型名和超时；
- 运行监控页面统一展示当前任务、按钮操作结果、模型路线、耗时和错误。

酒店集团四大职能板块的负责人视角和建设阶段见 [酒店集团职能管理 RAG 工作台规划](docs/hotel-management-rag-plan.md)。

## 数据与 AI 安全

专业流程采用固定的确定性管道：

```text
归档文件 -> 本地解析 -> 结构化提取 -> 确定性规则/计算
         -> 制度/章程/历史案例检索对照 -> 可选模型摘要
         -> 持久化与报告 -> 人工复核 -> 已确认历史记忆
```

- 员工、简历、工资、劳动合同、发票、费用和预算按 L3 敏感数据处理。
- 内部制度和会议纪要按 L2 数据处理。
- 默认不调用模型，文档解析、规则检查和财务计算仍可完整运行。
- 启用 AI 时优先调用 Ollama 本地模型。
- 本地模型失败后不会静默外发。
- 只有用户在单次操作中明确授权，系统才会先脱敏，再调用外部模型。
- 财务权威数字始终由本地代码计算，大模型不得覆盖。
- Agent 任意 Python 代码执行默认关闭。

系统不会自动完成以下最终决定：

- 录用或淘汰候选人；
- 签署商业合同或劳动合同；
- 发布制度；
- 批准费用或执行付款；
- 调整预算；
- 关闭风险和整改事项。

## 快速开始

### 环境要求

- Python 3.11 及以上；
- Windows、macOS 或 Linux；
- Ollama 为可选依赖，未安装时仍可使用全部确定性功能。

### 安装依赖

使用 `pip`：

```powershell
python -m pip install -r requirements.txt
```

或使用已提交的 `uv.lock` 创建可复现环境：

```powershell
uv sync --extra legacy --extra dev
```

### 配置

```powershell
Copy-Item .env.example .env
```

只使用本地确定性分析时，不需要配置任何 API Key。

使用 Ollama 时，在 `.env` 中配置：

```dotenv
OLLAMA_BASE_URL=http://localhost:11434/v1
OLLAMA_MODEL=qwen2.5:7b
ENTERPRISE_MODEL_TIMEOUT=20
```

然后准备本地模型：

```powershell
ollama pull qwen2.5:7b
```

外部模型是可选项，且只有页面单次明确授权后才会使用：

```dotenv
ENTERPRISE_EXTERNAL_PROVIDER=deepseek
ENTERPRISE_EXTERNAL_MODEL=deepseek-chat
DEEPSEEK_API_KEY=your_key_here
```

环境变量作为首次启动默认值。系统管理页面保存的普通配置会写入本地企业数据库并即时覆盖环境默认值，无需重启服务。API Key 在 Windows 使用当前用户 DPAPI 加密，在其他系统写入系统 Keyring；企业数据库只保存密钥引用，密钥不会写入操作日志或分析报告。

### 启动操作台

```powershell
streamlit run enterprise_app.py
```

浏览器访问：

```text
http://localhost:8501
```

原审计入口已兼容到同一操作台：

```powershell
streamlit run audit_app.py
```

## 操作流程

1. 在左侧填写当前操作人。
2. 进入审计与合同、人力、行政或财务模块。
3. 选择业务流程并上传材料。
4. 按需启用 Ollama 或授权脱敏外部调用。
5. 点击“保存材料并执行”。
6. 查看结构化结果、明细、风险、RAG 知识对照、证据和报告。
7. 在“历史与复核”记录人工结论或重新执行。
8. 在“运行监控”查看操作、当前任务和模型调用，在“任务中心”跟踪行动项和最终动作审批。

## 数据保存

默认数据保存在 `data/enterprise/`，该目录已被 Git 忽略：

```text
data/enterprise/
├── enterprise.db       # 案件、执行、配置、运行事件、知识资料、任务、审批和审计日志
├── knowledge_sources/  # 知识资料上传原件
├── uploads/<case_id>/  # 每次上传的原始文件
├── reports/            # Markdown 报告
└── samples/            # 虚构标准样本及 expected.json
```

每个上传文件都会：

- 清理文件名，阻止路径穿越；
- 归档到独立案件目录；
- 计算 SHA-256；
- 与执行结果和操作人关联；
- 在执行失败时保留错误记录。

## 标准样本

在“系统管理”中点击“生成或更新标准样本”，系统会生成：

- 20 份劳动合同；
- 5 份岗位说明；
- 30 份简历；
- 10 份制度；
- 20 份会议纪要；
- 200 条费用记录；
- 49 条预算与实际记录；
- 一份机器可读的 `expected.json`。

所有样本中的人物、单位、账号和金额均为虚构数据。

## 原知识库助手

原 CLI 入口仍然可用：

```powershell
python main.py
```

常用命令：

| 命令 | 说明 |
|---|---|
| `/ingest <路径>` | 将 PDF、TXT 或 Markdown 加入知识库 |
| `/docs` | 查看已索引文档 |
| `/search <查询>` | 只执行知识库检索 |
| `/agent <任务>` | 使用 LangGraph Agent；任意代码工具默认关闭 |
| `/remember <内容>` | 保存长期记忆 |
| `/review <文件或目录>` | 使用统一工作区审阅商业合同并保存历史 |

RAG 重复入库会先删除同来源的旧分块，避免修改后的文档继续检索到过期内容。Embedding 维度读取不会在初始化阶段发送测试 API 请求。

## 项目结构

```text
.
├── enterprise_app.py       # 企业操作台入口
├── audit_app.py            # 兼容入口
├── enterprise/
│   ├── core/               # 统一模型、工作区、SQLite、报告
│   ├── ai/                 # Ollama/外部模型网关和脱敏
│   ├── adapters/           # PDF、DOCX、TXT、CSV、XLSX 解析
│   ├── domains/            # 合同、人力、行政、财务工作流
│   └── sample_data.py      # 标准样本生成器
├── audit/                  # 原合同审阅兼容包
├── rag/                    # RAG 与 Chroma 向量库
├── agent/                  # LangGraph Agent 和工具
├── chat/                   # 对话与长期记忆
├── finetune/               # LoRA 数据准备和训练配置
├── tests/                  # 工作区、财务计算、安全和 RAG 回归测试
├── docs/                   # 使用说明和 ADR
├── pyproject.toml          # 项目和工具配置
└── uv.lock                 # 锁定依赖
```

## 开发与验证

```powershell
ruff check enterprise enterprise_app.py audit/pipeline.py audit_app.py
python -m pytest -q
```

当前自动化测试覆盖：

- 七个业务流程离线执行；
- 上传持久化和案件重新执行；
- 失败操作留痕；
- 敏感信息脱敏；
- 费用和预算权威计算；
- 审批职责分离；
- RAG 同来源重复入库替换；
- Embedding 初始化不发网络请求。

## 当前边界

当前版本是单机 MVP。“当前操作人”用于留痕和职责分离演示，不是正式身份认证。

部署到多用户局域网或生产环境前，需要增加：

- 统一登录和服务端 RBAC；
- PostgreSQL 等服务端数据库；
- 数据库备份、恢复和加密；
- 文件病毒扫描与更严格的上传限制；
- 不可篡改审计日志；
- 正式审批权限、电子签章和财务系统集成。

## 文档

- [企业工作台使用说明](docs/enterprise-workbench.md)
- [ADR-0001：审阅采用确定性专用管道](docs/adr/0001-review-command-architecture.md)
- [ADR-0003：统一持久化工作区与本地优先模型网关](docs/adr/0003-enterprise-workbench-architecture.md)
- [LoRA 微调说明](finetune/README.md)
