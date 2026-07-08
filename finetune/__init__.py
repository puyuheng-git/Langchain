"""
微调模块 (finetune) —— V4 新增

这个包负责「训练一个属于你自己的模型」相关的准备工作：
- data_prep.py: 把你的对话历史整理成微调所需的 Alpaca 格式数据集
- train_config.yaml: LLaMA-Factory 的 LoRA 微调配置
- dataset_info.json: 告诉 LLaMA-Factory 去哪里找数据集
- README.md: 从数据准备 → 云端训练 → 本地部署的完整步骤

微调 vs RAG（重要概念）：
- RAG（V2）：给模型「外挂知识库」，更新的是「知道什么」
- 微调（V4）：调整模型参数，改变的是「说话风格/行为方式」
- 两者互补：RAG 让模型知道新知识，微调让模型「更像你」

注意：真正的训练需要 GPU（建议租用 AutoDL 云算力），
本包只负责「数据准备」和「配置」，训练命令在 README.md 中说明。
"""
