#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微调数据准备脚本 (data_prep.py) —— V4 新增

作用：把你在 V1 攒下的对话历史（data/history/*.json），
      转换成微调工具（LLaMA-Factory）需要的「Alpaca 格式」数据集。

什么是 Alpaca 格式？
- 它是微调界最常用的一种数据格式，每条样本长这样：
    {
        "instruction": "用户说的话（指令）",
        "input": "补充输入（通常留空）",
        "output": "AI 应该给出的回答",
        "system": "系统提示（可选）"
    }
- 模型通过学习「看到 instruction → 应该输出 output」，逐渐模仿这种问答风格

本脚本做的事：
1. 读取 data/history/ 下所有对话 JSON 文件
2. 把每一组「用户提问 → 助手回答」提取成一条训练样本
3. 汇总写入 finetune/data/alpaca_data.json

这个脚本纯用 Python 标准库，可以直接本地运行：
    python finetune/data_prep.py
"""

# 导入标准库
# json: 读写 JSON 文件
# sys: 用于路径处理
import json
import sys

# Path: 处理文件路径
from pathlib import Path

# 类型提示
from typing import List, Dict


# ----------------------------------------
# 路径定义
# ----------------------------------------

# 本脚本所在目录（finetune/）
_THIS_DIR = Path(__file__).parent

# 项目根目录（finetune 的上一级）
_ROOT = _THIS_DIR.parent

# 对话历史目录：data/history/
HISTORY_DIR = _ROOT / "data" / "history"

# 输出目录：finetune/data/
OUTPUT_DIR = _THIS_DIR / "data"

# 输出文件：finetune/data/alpaca_data.json
OUTPUT_FILE = OUTPUT_DIR / "alpaca_data.json"


def convert_conversation(messages: List[Dict]) -> List[Dict]:
    """
    把一次对话的消息列表，转换成若干条 Alpaca 训练样本

    转换逻辑：
    - 遍历消息，找「user 消息」紧跟着「assistant 消息」的配对
    - user 内容 → instruction，assistant 内容 → output
    - 如果对话开头有 system 消息，就作为每条样本的 system 字段

    Args:
        messages: 一次对话的消息列表，每个元素是 {role, content, ...}

    Returns:
        Alpaca 格式样本列表
    """
    # 用来存放这次对话生成的所有样本
    samples = []

    # 先找出 system 提示（如果第一条是 system）
    # 三元表达式：条件成立取前者，否则取空字符串
    system_prompt = ""
    if messages and messages[0].get("role") == "system":
        system_prompt = messages[0].get("content", "")

    # 遍历消息，寻找 user → assistant 的配对
    # range(len(messages) - 1) 保证 i+1 不会越界
    for i in range(len(messages) - 1):
        current = messages[i]        # 当前消息
        nxt = messages[i + 1]        # 下一条消息

        # 如果「当前是 user，下一条是 assistant」，就是一组问答
        if current.get("role") == "user" and nxt.get("role") == "assistant":
            # 取出问和答的文本
            instruction = current.get("content", "").strip()
            output = nxt.get("content", "").strip()

            # 跳过空的问答（没意义的样本）
            if not instruction or not output:
                continue

            # 组装一条 Alpaca 样本
            sample = {
                "instruction": instruction,   # 用户提问
                "input": "",                  # Alpaca 的 input 字段，这里留空
                "output": output              # 期望的回答
            }

            # 如果有 system 提示，加上（LLaMA-Factory 支持 system 列）
            if system_prompt:
                sample["system"] = system_prompt

            # 加入样本列表
            samples.append(sample)

    return samples


def prepare_dataset() -> int:
    """
    主流程：读取所有历史对话，转换并写出 Alpaca 数据集

    Returns:
        生成的样本总数
    """
    print("=" * 50)
    print("微调数据准备：对话历史 → Alpaca 格式")
    print("=" * 50)

    # 检查历史目录是否存在
    if not HISTORY_DIR.exists():
        print(f"⚠ 历史目录不存在: {HISTORY_DIR}")
        print("  请先用 V1 对话并 /save 保存一些对话，再运行本脚本")
        return 0

    # 找出所有 .json 历史文件
    # glob("*.json") 匹配目录下所有 json 文件
    json_files = list(HISTORY_DIR.glob("*.json"))

    if not json_files:
        print(f"⚠ {HISTORY_DIR} 中没有对话记录（*.json）")
        print("  请先用 V1 对话并 /save 保存一些对话")
        return 0

    print(f"\n找到 {len(json_files)} 个历史对话文件")

    # 用来汇总所有样本
    all_samples = []

    # 逐个处理每个历史文件
    for json_file in json_files:
        try:
            # 读取并解析 JSON
            data = json.loads(json_file.read_text(encoding="utf-8"))

            # 取出消息列表（历史文件结构是 {"metadata":..., "messages":[...]}）
            messages = data.get("messages", [])

            # 转换成样本
            samples = convert_conversation(messages)

            # 累加到总列表
            all_samples.extend(samples)

            print(f"  ✓ {json_file.name}: 提取 {len(samples)} 条样本")

        except Exception as e:
            # 单个文件出错不影响其他文件
            print(f"  ✗ {json_file.name}: 解析失败 ({str(e)})")

    # 如果一条样本都没有，提示并退出
    if not all_samples:
        print("\n⚠ 没有提取到任何有效样本")
        return 0

    # 确保输出目录存在
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 写出 Alpaca 数据集
    # ensure_ascii=False 让中文正常显示，indent=2 便于人工检查
    OUTPUT_FILE.write_text(
        json.dumps(all_samples, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print(f"\n✅ 完成！共生成 {len(all_samples)} 条训练样本")
    print(f"   输出文件: {OUTPUT_FILE}")
    print(f"\n提示: 微调建议至少 500 条样本。当前 {len(all_samples)} 条，"
          f"{'已达标' if len(all_samples) >= 500 else '偏少，可多积累对话或手工补充'}。")

    return len(all_samples)


# ============================================
# 脚本入口
# ============================================

# 直接运行本文件时执行数据准备
if __name__ == "__main__":
    prepare_dataset()
