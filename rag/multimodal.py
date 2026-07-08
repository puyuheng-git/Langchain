#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多模态处理模块 (Multimodal) —— V4 新增

什么是「多模态」？
- 单模态：只处理一种数据，比如纯文字
- 多模态：能同时理解多种数据，比如文字 + 图片 + 语音
- 本模块聚焦「图片 → 文字」：让 AI「看懂」图片里的文字（OCR）

典型场景：
- 你有一张手写笔记的照片、一张 PPT 截图、一张扫描的文档
- 用多模态模型（如 GPT-4o）把图片里的文字提取出来
- 再把提取的文字送进 RAG 知识库，就能像普通文档一样被检索了

技术原理：
- 多模态大模型（GPT-4o / GPT-4V）能同时接收「文字 + 图片」
- 我们把图片转成 base64 编码，连同「请提取文字」的指令一起发给模型
- 模型返回图片中的文字内容

依赖说明：
- 复用 OpenAI 兼容接口（OPENAI_API_KEY / OPENAI_BASE_URL / VISION_MODEL）
- 国内可用支持 GPT-4V 类模型的平台（如 OpenAI、部分中转服务）
- 如果没配置 Key，本模块会优雅降级（返回提示而非报错）
"""

import sys
from pathlib import Path

# 把项目根目录加入 sys.path，才能 import config
sys.path.append(str(Path(__file__).parent.parent))

# base64 用于把图片的二进制内容编码成文本字符串
# 因为 API 只能传文本，图片必须先编码成 base64
import base64

# 导入类型提示
from typing import Optional

# 导入 OpenAI SDK（项目里 ChatSession 也是用它，风格统一）
from openai import OpenAI

# 导入配置
from config import Config


class MultimodalProcessor:
    """
    多模态处理器：把图片转成文字，并可入库

    使用示例:
        mm = MultimodalProcessor()

        # 只做 OCR，拿到文字
        text = mm.ocr_image("data/docs/handwriting.jpg")

        # OCR 后直接入库（需要传入 rag_pipeline）
        mm.ingest_image("data/docs/note.png", rag_pipeline)
    """

    def __init__(self):
        """
        初始化多模态处理器

        创建一个指向多模态模型的 OpenAI 客户端。
        """
        # 保存要使用的多模态模型名称（如 gpt-4o）
        self.model = Config.VISION_MODEL

        # 记录 Key 是否配置好（用于优雅降级）
        # 视觉 OCR 复用 OpenAI 的配置
        self.available = bool(
            Config.OPENAI_API_KEY
            and Config.OPENAI_API_KEY != "your_openai_api_key_here"
        )

        # 如果配置可用，创建客户端；否则先不创建
        if self.available:
            # 创建 OpenAI 客户端，指向配置的地址（支持中转/兼容服务）
            self.client = OpenAI(
                api_key=Config.OPENAI_API_KEY,
                base_url=Config.OPENAI_BASE_URL
            )
            print(f"✓ 多模态处理器就绪（模型: {self.model}）")
        else:
            # 没配置 Key，标记为不可用
            self.client = None
            print("⚠ 多模态处理器：未配置 OPENAI_API_KEY，OCR 功能不可用")

    def _encode_image(self, image_path: str) -> str:
        """
        把图片文件编码成 base64 字符串

        Args:
            image_path: 图片文件路径

        Returns:
            base64 编码后的字符串
        """
        # 以「二进制读」模式打开图片文件
        # 'rb' = read binary，图片是二进制数据，不能用文本模式打开
        with open(image_path, "rb") as image_file:
            # image_file.read() 读出全部二进制内容
            # base64.b64encode() 把二进制编码成 base64（还是二进制形式）
            # .decode("utf-8") 再转成普通字符串，才能放进 JSON 请求
            return base64.b64encode(image_file.read()).decode("utf-8")

    def ocr_image(self, image_path: str, prompt: Optional[str] = None) -> str:
        """
        对单张图片做 OCR（文字识别）

        Args:
            image_path: 图片路径（支持 jpg/png 等常见格式）
            prompt: 自定义指令（可选），默认让模型提取所有文字

        Returns:
            识别出的文字内容；不可用或出错时返回提示字符串

        使用示例:
            text = mm.ocr_image("note.jpg")
        """
        # 优雅降级：没配置好就直接返回提示
        if not self.available:
            return "（OCR 不可用：未配置 OPENAI_API_KEY / VISION_MODEL）"

        # 检查文件是否存在
        path = Path(image_path)
        if not path.exists():
            return f"（图片不存在: {image_path}）"

        # 默认的 OCR 指令
        # 如果调用者没传 prompt，就用这句
        if prompt is None:
            prompt = (
                "请仔细识别并提取这张图片中的所有文字内容，"
                "保持原有的段落结构，只输出文字本身，不要加任何解释。"
            )

        try:
            # 步骤 1: 把图片编码成 base64
            base64_image = self._encode_image(image_path)

            # 步骤 2: 根据后缀推断图片类型（jpeg/png 等）
            # path.suffix 是文件后缀（如 ".jpg"），去掉点并转小写
            image_type = path.suffix.lower().replace(".", "")
            # jpg 的标准 MIME 类型是 jpeg，做一下映射
            if image_type == "jpg":
                image_type = "jpeg"

            # 步骤 3: 调用多模态模型
            # messages 里的 content 是一个「列表」，可以混合文字和图片
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            # 第一部分：文字指令
                            {"type": "text", "text": prompt},
                            # 第二部分：图片（用 data URL 格式内嵌 base64）
                            {
                                "type": "image_url",
                                "image_url": {
                                    # data:image/类型;base64,编码内容
                                    "url": f"data:image/{image_type};base64,{base64_image}"
                                }
                            }
                        ]
                    }
                ],
                max_tokens=Config.MAX_TOKENS
            )

            # 步骤 4: 取出模型返回的文字
            text = response.choices[0].message.content
            return text

        except Exception as e:
            # 出错（网络、模型不支持视觉、额度等）返回提示
            return f"（OCR 出错: {str(e)}）"

    def ingest_image(self, image_path: str, rag_pipeline) -> bool:
        """
        OCR 图片并把识别出的文字存入知识库

        完整流程：图片 → OCR 提取文字 → 存成 Markdown → 入库（分块+向量化）

        Args:
            image_path: 图片路径
            rag_pipeline: RAGPipeline 实例，用来把文字入库

        Returns:
            成功返回 True，失败返回 False

        使用示例:
            mm.ingest_image("data/docs/note.jpg", rag_pipeline)
        """
        # 知识库不可用就直接返回
        if rag_pipeline is None:
            print("⚠ 知识库不可用，无法入库")
            return False

        print(f"\n📷 处理图片: {Path(image_path).name}")

        # 步骤 1: OCR 提取文字
        print("   步骤 1/2: 识别图片文字...")
        text = self.ocr_image(image_path)

        # 如果 OCR 返回的是错误提示（以「（」开头的降级信息），终止
        if text.startswith("（"):
            print(f"   {text}")
            return False

        print(f"   识别到 {len(text)} 个字符")

        try:
            # 步骤 2: 把识别出的文字存成 Markdown 文件，再入库
            print("   步骤 2/2: 存入知识库...")

            # 用图片文件名（去掉后缀）作为笔记名
            note_name = Path(image_path).stem
            # 保存到 data/docs/ 目录，加 _ocr 后缀区分
            md_path = Config.DOCS_DIR / f"{note_name}_ocr.md"

            # 写入文件：标题 + 来源说明 + 正文
            md_path.write_text(
                f"# {note_name}（图片 OCR）\n\n"
                f"> 来源图片: {Path(image_path).name}\n\n"
                f"{text}\n",
                encoding="utf-8"
            )

            # 调用 RAGPipeline 入库（复用现有全流程）
            rag_pipeline.ingest_document(str(md_path))

            print(f"✓ 图片内容已入库: {md_path.name}")
            return True

        except Exception as e:
            print(f"✗ 入库失败: {str(e)}")
            return False


# ============================================
# 测试代码
# ============================================

if __name__ == "__main__":
    print("=" * 50)
    print("测试多模态处理器")
    print("=" * 50)

    # 创建处理器（会打印是否可用）
    mm = MultimodalProcessor()

    # 如果可用且提供了测试图片，可以试跑
    # 这里只做初始化验证，实际 OCR 需要真实图片和 API Key
    print(f"\n可用状态: {mm.available}")
    print(f"使用模型: {mm.model}")
    print("\n提示: 把图片路径传给 mm.ocr_image('图片路径') 即可测试 OCR")
