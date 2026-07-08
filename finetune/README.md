# V4：完全属于你的专属模型（微调 + 本地部署 + 多模态）

本目录是 V4 阶段的产物。V4 的目标是把「调用云 API 的助手」升级为
「用你自己的数据训练、在你自己电脑上运行的专属模型」。

> ⚠️ 重要前提：真正的**训练需要 GPU**（建议租用 [AutoDL](https://autodl.com) 云算力，
> RTX 3090 约 ¥1.5/小时）。本项目代码环境（普通电脑）**只负责数据准备和配置**，
> 训练与本地部署请在有 GPU 的机器上按下面步骤操作。

---

## 一、整体流程总览

```
你的对话历史 (data/history/*.json)
        │  ① 数据准备（本地，python data_prep.py）
        ▼
Alpaca 数据集 (finetune/data/alpaca_data.json)
        │  ② LoRA 微调（AutoDL GPU，llamafactory-cli train）
        ▼
LoRA 权重 (saves/qwen2-7b/lora/my-brain)
        │  ③ 合并导出 + 量化（AutoDL）
        ▼
GGUF 模型文件
        │  ④ Ollama 本地部署（你自己的电脑，ollama create）
        ▼
本地模型 my-brain
        │  ⑤ 接回项目（改 .env: LLM_PROVIDER=ollama）
        ▼
项目通过 OpenAI 兼容接口调用你的专属本地模型 🎉
```

---

## 二、① 数据准备（本地，无需 GPU）

用 V1 攒下的对话历史生成微调数据集：

```bash
python finetune/data_prep.py
```

- 它会读取 `data/history/*.json`，提取「用户提问 → 助手回答」配对
- 输出到 `finetune/data/alpaca_data.json`（Alpaca 格式）
- 建议至少 **500 条**样本再训练。样本不够时，可以：
  - 多用 V1/V2 对话并 `/save` 积累
  - 手工编辑 `alpaca_data.json` 补充高质量问答

Alpaca 每条样本长这样：

```json
{
  "instruction": "什么是 RAG？",
  "input": "",
  "output": "RAG 是检索增强生成……",
  "system": "你是一个 helpful 的 AI 助手。"
}
```

---

## 三、② 在 AutoDL 上做 LoRA 微调

1. **租实例**：在 AutoDL 选一台 RTX 3090（24GB 显存）实例，镜像选 PyTorch。

2. **装 LLaMA-Factory**：
   ```bash
   git clone https://github.com/hiyouga/LLaMA-Factory.git
   cd LLaMA-Factory
   pip install -e ".[torch,metrics]"
   ```

3. **放入数据集**：
   - 把本地生成的 `finetune/data/alpaca_data.json` 上传到 `LLaMA-Factory/data/`
   - 把本目录 `dataset_info.json` 里的 `my_notes` 条目，合并进
     `LLaMA-Factory/data/dataset_info.json`

4. **放入训练配置**：把本目录 `train_config.yaml` 上传到 LLaMA-Factory 目录。

5. **先做一次小测试**（20 步，确认环境正常）：
   ```bash
   llamafactory-cli train train_config.yaml max_steps=20
   ```

6. **正式训练**：
   ```bash
   llamafactory-cli train train_config.yaml
   ```
   - 完整微调约 8–12 小时（取决于数据量）
   - 产物在 `saves/qwen2-7b/lora/my-brain/`

---

## 四、③ 合并 LoRA 并导出为 GGUF（AutoDL）

LoRA 只是「插件权重」，要部署得先和基座模型合并，再转成 Ollama 能读的 GGUF 格式。

1. **合并 LoRA 到完整模型**（用 LLaMA-Factory 的 export）：
   ```bash
   llamafactory-cli export \
     --model_name_or_path Qwen/Qwen2-7B-Instruct \
     --adapter_name_or_path saves/qwen2-7b/lora/my-brain \
     --template qwen \
     --finetuning_type lora \
     --export_dir merged-my-brain \
     --export_size 2
   ```

2. **转 GGUF 并 4-bit 量化**（用 llama.cpp）：
   ```bash
   git clone https://github.com/ggerganov/llama.cpp.git
   cd llama.cpp && pip install -r requirements.txt
   # 转 GGUF
   python convert_hf_to_gguf.py ../merged-my-brain --outfile my-brain-f16.gguf
   # 量化到 4-bit（q4_k_m 是常用的平衡档）
   ./llama-quantize my-brain-f16.gguf my-brain-q4.gguf q4_k_m
   ```

3. 把 `my-brain-q4.gguf` 下载到你自己的电脑。

---

## 五、④ 用 Ollama 本地部署（你自己的电脑）

1. **安装 Ollama**：从 [ollama.ai](https://ollama.ai) 下载安装。

2. **写一个 `Modelfile`**（和 gguf 放同一目录）：

   ```dockerfile
   # 指向你的量化模型文件
   FROM ./my-brain-q4.gguf

   # 使用 Qwen 的对话模板
   TEMPLATE """{{ if .System }}<|im_start|>system
   {{ .System }}<|im_end|>
   {{ end }}{{ if .Prompt }}<|im_start|>user
   {{ .Prompt }}<|im_end|>
   {{ end }}<|im_start|>assistant
   {{ .Response }}<|im_end|>
   """

   # 默认系统提示（可选）
   SYSTEM """你是我的专属 AI 知识库助手。"""

   # 采样参数
   PARAMETER temperature 0.7
   PARAMETER stop "<|im_end|>"
   ```

3. **创建并运行模型**：
   ```bash
   ollama create my-brain -f Modelfile
   ollama run my-brain    # 测试对话
   ```

---

## 六、⑤ 把本地模型接回本项目

Ollama 提供 **OpenAI 兼容接口**，所以本项目**几乎零改动**就能调用它。
只需修改项目根目录的 `.env`：

```bash
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434/v1
OLLAMA_MODEL=my-brain
```

然后正常启动：

```bash
python main.py
```

此时所有对话都走你**本地训练的专属模型**，数据完全不出本机 ✅
（这对应文档里程碑：「Ollama 本地部署的模型通过 OpenAI 兼容接口被项目调用」。）

---

## 七、多模态：图片 OCR 入库（`rag/multimodal.py`）

V4 还支持把**手写笔记/截图**里的文字提取出来存进知识库：

```python
from rag.pipeline import RAGPipeline
from rag.multimodal import MultimodalProcessor

rag = RAGPipeline()
mm = MultimodalProcessor()

# 图片 → OCR 提取文字 → 存成 md → 入库（分块+向量化）
mm.ingest_image("data/docs/my_note.jpg", rag)
```

- OCR 使用多模态模型（默认 `gpt-4o`），复用 `.env` 里的 `OPENAI_API_KEY`
- 入库后即可像普通文档一样被 `/search` 检索、被问答引用
  （对应里程碑：「上传手写笔记图片，能自动进入知识库并被正确检索」）

---

## 八、里程碑验收对照

| 文档验收点 | 如何验证 |
|-----------|---------|
| 微调后模型领域答案质量优于基础模型 | 用相同领域问题分别问基础 Qwen 和 my-brain，对比 |
| Ollama 模型通过 OpenAI 兼容接口被调用 | 改 `.env` 为 `LLM_PROVIDER=ollama`，`python main.py` 正常对话 |
| 手写笔记图片自动入库并可检索 | `mm.ingest_image(...)` 后 `/search` 关键词能命中 |
