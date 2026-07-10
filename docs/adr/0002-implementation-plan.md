# 审合同模块 — 实施方案

## 新增模块结构

```
audit/                          # 【审计】模块包（新建）
├── __init__.py
├── contract_parser.py          # 合同解析器：PDF → 结构化文本
├── extractor.py                # 结构化提取：LLM 提取关键字段
├── risk_analyzer.py            # 风险识别：标记异常条款
└── report_generator.py         # 报告生成：文字报告 + 表格
```

## 执行流程

```
/review 购销合同.pdf
  │
  ├─ ① contract_parser.load_and_chunk()
  │   复用现有 loader + chunker，专为合同优化分块策略
  │
  ├─ ② extractor.extract_fields(chunks)
  │   调用 LLM 提取：签约方、金额、期限、违约、管辖等字段
  │   输出：结构化 dict（可转表格）
  │
  ├─ ③ risk_analyzer.analyze(extracted)
  │   调用 LLM 逐条判断风险："违约金比例 30% → 偏高风险"
  │   输出：风险条目列表
  │
  └─ ④ report_generator.generate(extracted, risks)
      输出：文字总结 + 关键字段表格 + 风险清单
```

## 改动点

| 文件 | 改动 |
|------|------|
| `main.py` | 新增 `/review` 命令处理分支，约 30 行 |
| `audit/` (新建) | 4 个模块，共约 300 行 |
| `CONTEXT.md` | ✅ 已创建 |
| `docs/adr/` | ✅ 已创建 |

## 总工作量

约 **300~400 行新代码**，零改动现有功能，全部增量添加。

## 后续扩展方向（不做现在）

1. **批量审**：`/review ./contracts/` → 遍历目录逐个审 + 汇总报告
2. **风险规则库**：把 Prompt 里的业务规则外移到配置文件或数据库
3. **分析性复核**：`/analyze 科目余额表.xlsx` → 审财务数字
4. **可视化 UI**：用 Streamlit 或 FastAPI + 前端，复用 audit/ 模块逻辑
