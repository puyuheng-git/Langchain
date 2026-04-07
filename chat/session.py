"""
对话会话管理模块
封装多轮对话、消息历史管理和流式输出

这个模块是 V1 版本的核心，实现了与 LLM API 的完整对话流程
"""

# 导入 json 模块，用于将对话历史保存为 JSON 格式
# JSON 是一种轻量级数据交换格式，人类可读且机器易解析
import json

# 从 datetime 模块导入 datetime 类
# datetime 用于获取当前时间，给消息添加时间戳
from datetime import datetime

# 从 pathlib 导入 Path 类，用于处理文件路径
# Path 比字符串路径更安全，且提供跨平台支持（Windows/Mac/Linux）
from pathlib import Path

# 从 typing 导入类型提示工具
# List, Dict, Any, Optional, Generator 都是类型提示，帮助 IDE 和开发者理解代码
# Optional[str] 表示可以是 str 或 None
# Generator 用于生成器函数的类型提示
from typing import List, Dict, Any, Optional, Generator

# 从 openai 库导入 OpenAI 类
# 这是 OpenAI 官方 Python SDK，用于调用 API
# 它也兼容其他 OpenAI 格式的 API（如 DeepSeek、硅基流动）
from openai import OpenAI

# 导入 sys 模块，用于修改 Python 的模块搜索路径
import sys

# sys.path 是一个列表，包含 Python 查找模块时会搜索的路径
# append() 向列表末尾添加新路径
# Path(__file__) 获取当前文件路径
# .parent.parent 获取上上级目录（即从 chat/session.py 到项目根目录）
# str() 将 Path 对象转换为字符串，因为 sys.path 需要字符串
sys.path.append(str(Path(__file__).parent.parent))

# 从 config 模块导入 Config 类
# Config 包含所有配置信息（API Key、模型参数等）
from config import Config


# ============================================
# ChatSession 类定义
# ============================================

class ChatSession:
    """
    对话会话类

    这是 V1 版本的核心类，封装了与 LLM API 交互的所有逻辑：
    - 维护对话历史（messages 列表）
    - 自动管理 Token 限制（超出时截断旧消息）
    - 支持流式输出（逐字显示）
    - 提供对话导出功能

    使用示例:
        session = ChatSession()  # 创建会话
        reply = session.chat("你好")  # 发送消息
        session.export_to_markdown()  # 导出对话
    """

    def __init__(self, system_prompt: Optional[str] = None):
        """
        初始化对话会话

        __init__ 是 Python 类的构造方法，创建对象时自动调用
        self 代表类的实例本身，必须作为第一个参数

        Args:
            system_prompt: 系统提示词，覆盖配置文件中的默认值
                          如果为 None，则使用 Config.SYSTEM_PROMPT
        """
        # ----------------------------------------
        # 初始化 API 客户端
        # ----------------------------------------

        # 调用 Config.get_api_config() 获取 API 配置（字典形式）
        # 包含 api_key, base_url, model 三个键
        api_config = Config.get_api_config()

        # 创建 OpenAI 客户端实例
        # OpenAI 类需要 api_key 和 base_url 来初始化
        # 这个 client 对象将用于所有后续的 API 调用
        self.client = OpenAI(
            api_key=api_config['api_key'],      # 从配置中获取 API Key
            base_url=api_config['base_url']     # 从配置中获取 API 地址
        )

        # 保存模型名称到实例变量
        # self.xxx 表示这是实例变量，每个对象有自己的一份
        self.model = api_config['model']

        # 从 Config 复制温度参数
        # temperature 控制生成随机性：0=最确定，2=最随机
        self.temperature = Config.TEMPERATURE

        # 从 Config 复制最大 Token 数
        # 限制 API 返回的最大长度，控制成本
        self.max_tokens = Config.MAX_TOKENS

        # 从 Config 复制历史 Token 上限
        # 当历史消息超过此值时，会自动删除旧消息
        self.max_history_tokens = Config.MAX_HISTORY_TOKENS

        # ----------------------------------------
        # 初始化消息历史
        # ----------------------------------------

        # 创建一个空列表，用于存储所有对话消息
        # List[Dict[str, str]] 是类型提示，表示这是一个字典列表
        # 每个字典包含 role 和 content 两个键
        self.messages: List[Dict[str, str]] = []

        # 确定要使用的 system_prompt
        # or 是逻辑运算符：如果左边为真（非空）就用左边，否则用右边
        # 这实现了"传入参数优先，否则用配置默认值"的逻辑
        self.system_prompt = system_prompt or Config.SYSTEM_PROMPT

        # 如果 system_prompt 不为空，添加到消息列表
        # system 消息是对话的第一条，定义 AI 的角色和行为
        if self.system_prompt:
            # 调用实例方法 add_message 添加消息
            # 'system' 是角色类型，self.system_prompt 是内容
            self.add_message('system', self.system_prompt)

        # ----------------------------------------
        # 初始化统计信息
        # ----------------------------------------

        # total_tokens_used 用于累计使用的 Token 数（目前未实际使用，预留）
        self.total_tokens_used = 0

    def add_message(self, role: str, content: str) -> None:
        """
        添加消息到历史

        这是内部方法，用于将用户输入或 AI 回复添加到 messages 列表

        Args:
            role: 角色，只能是 'system'、'user' 或 'assistant'
                  system = 系统提示，user = 用户，assistant = AI
            content: 消息的文本内容

        Returns:
            None（-> None 表示函数不返回有意义的值）
        """
        # list.append() 方法向列表末尾添加一个元素
        # 这里添加的是一个字典，包含三个键值对
        self.messages.append({
            'role': role,                           # 消息角色
            'content': content,                     # 消息内容
            'timestamp': datetime.now().isoformat() # 当前时间的 ISO 格式字符串
        })

    def get_messages(self) -> List[Dict[str, str]]:
        """
        获取当前消息列表（用于 API 调用）

        这个方法会：
        1. 先调用 _truncate_if_needed() 检查是否需要截断历史
        2. 返回符合 OpenAI API 格式的消息列表（移除 timestamp 字段）

        Returns:
            符合 OpenAI 格式的消息列表，每个元素是 {'role': xxx, 'content': yyy}
        """
        # 调用私有方法（以下划线开头的方法约定为内部使用）
        # 检查历史消息是否超过 Token 限制，如果超过则截断
        self._truncate_if_needed()

        # 列表推导式（list comprehension），一种简洁的创建列表的方式
        # 语法：[表达式 for 变量 in 可迭代对象]
        # 这行代码遍历 self.messages，为每条消息创建一个新字典
        # 新字典只包含 'role' 和 'content'，移除了 'timestamp'
        # 因为 OpenAI API 不需要 timestamp 字段
        return [{'role': m['role'], 'content': m['content']} for m in self.messages]

    def _estimate_tokens(self, text: str) -> int:
        """
        估算文本的 Token 数

        Token 是大语言模型的计费单位。实际计算需要 tiktoken 库，
        但这里使用简单估算：中文字符数 + 英文单词数 * 1.3

        为什么需要估算？
        - API 按 Token 计费，需要控制成本
        - 模型有最大上下文长度限制

        Args:
            text: 待估算的文本字符串

        Returns:
            估算的 token 数（整数）
        """
        # 导入 re 模块（正则表达式），用于文本匹配
        # 在方法内部导入是允许的，但通常习惯在文件顶部导入
        import re

        # re.findall() 使用正则表达式查找所有匹配项，返回列表
        # [\u4e00-\u9fff] 是 Unicode 范围，匹配所有中文字符
        # len() 计算列表长度，即中文字符数量
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))

        # [a-zA-Z]+ 匹配一个或多个英文字母（即英文单词）
        english_words = len(re.findall(r'[a-zA-Z]+', text))

        # 计算估算值：中文字符 1 token/字，英文单词约 1.3 tokens/词
        # int() 将结果转换为整数（向下取整）
        return int(chinese_chars + english_words * 1.3)

    def _truncate_if_needed(self) -> None:
        """
        当总 token 数超过限制时，截断最早的对话轮次

        截断策略：
        1. 永远保留 system prompt（第一条消息）
        2. 按对话轮次（user+assistant 对）从最早的开始移除
        3. 直到总 token 数低于限制

        这是成本管理的关键：历史消息也会计入 API 调用的 token 数
        """
        # '\n'.join() 将列表中的所有消息内容用换行符连接成一个字符串
        # 这是一个生成器表达式：m['content'] for m in self.messages
        # 它遍历 messages，提取每条消息的 content 字段
        total_text = '\n'.join([m['content'] for m in self.messages])

        # 调用 _estimate_tokens 估算当前总 token 数
        current_tokens = self._estimate_tokens(total_text)

        # 如果未超限，直接返回，不需要截断
        # <= 是"小于等于"比较运算符
        if current_tokens <= self.max_history_tokens:
            return  # return 语句结束函数执行

        # ----------------------------------------
        # 需要截断，按策略移除旧消息
        # ----------------------------------------

        # 先保存 system message（如果存在）
        # 条件表达式检查：messages 非空 且 第一条消息的 role 是 'system'
        system_message = self.messages[0] if self.messages and self.messages[0]['role'] == 'system' else None

        # 剩余的消息（需要可能被截断的对话内容）
        # 如果有 system_message，取 messages[1:]（从第二条开始）
        # 否则取全部 messages
        # Python 切片语法：列表[start:end]，省略 start 表示从开头，省略 end 表示到末尾
        conversation = self.messages[1:] if system_message else self.messages

        # while 循环：只要 conversation 非空且 token 数仍超限，就继续截断
        while conversation and current_tokens > self.max_history_tokens:

            # 找到第一个 user 消息的位置
            # enumerate() 返回索引和值的元组 (index, value)
            first_user_idx = None  # None 表示 Python 中的"空值"

            for i, msg in enumerate(conversation):
                # 检查消息的 role 是否为 'user'
                if msg['role'] == 'user':
                    first_user_idx = i  # 保存索引
                    break  # break 跳出当前循环

            # 如果没有找到 user 消息，退出循环
            # is None 是判断变量是否为 None 的推荐方式
            if first_user_idx is None:
                break

            # 找到这一轮的结束位置（即下一条 user 消息之前，或列表末尾）
            # 初始化 end_idx 为第一个 user 消息的后一个位置
            end_idx = first_user_idx + 1

            # 内层 while 循环：跳过非 user 消息（即 assistant 消息）
            # len(conversation) 获取列表长度
            # conversation[end_idx]['role'] 获取该位置消息的角色
            while end_idx < len(conversation) and conversation[end_idx]['role'] != 'user':
                end_idx += 1  # 自增运算符，相当于 end_idx = end_idx + 1

            # 切片获取要移除的消息
            # conversation[first_user_idx:end_idx] 获取从 first_user_idx 到 end_idx-1 的元素
            removed = conversation[first_user_idx:end_idx]

            # 计算被移除消息的 token 数
            removed_text = '\n'.join([m['content'] for m in removed])
            current_tokens -= self._estimate_tokens(removed_text)

            # 从 conversation 中移除这一轮
            # 切片赋值：保留 0 到 first_user_idx-1 的部分，加上 end_idx 之后的部分
            conversation = conversation[:first_user_idx] + conversation[end_idx:]

        # 重建消息列表
        # 如果有 system_message，放在最前面，后面接上剩余的 conversation
        # + 运算符用于列表拼接
        self.messages = ([system_message] if system_message else []) + conversation

    def chat(self, user_input: str, stream: bool = True) -> str:
        """
        发送用户消息并获取 AI 回复

        这是最主要的对外接口，处理完整的对话流程：
        1. 添加用户消息到历史
        2. 调用 API 获取回复
        3. 添加 AI 回复到历史
        4. 返回 AI 回复内容

        Args:
            user_input: 用户输入的消息文本
            stream: 是否使用流式输出，默认 True
                   流式输出 = 逐字显示，非流式 = 等全部生成后再显示

        Returns:
            AI 的完整回复内容（字符串）

        Raises:
            Exception: 当 API 调用失败时抛出异常
        """
        # 步骤 1: 添加用户消息到历史记录
        # 使用 add_message 方法，role='user' 表示这是用户输入
        self.add_message('user', user_input)

        # 步骤 2: 获取当前消息列表（会自动处理截断）
        messages = self.get_messages()

        # try-except 块用于捕获和处理异常
        # 如果 try 中的代码出错，不会崩溃，而是执行 except 中的代码
        try:
            # 步骤 3: 调用 OpenAI API
            # client.chat.completions.create() 是发送对话请求的方法
            response = self.client.chat.completions.create(
                model=self.model,              # 使用的模型名称
                messages=messages,             # 对话历史
                temperature=self.temperature,  # 随机性参数
                max_tokens=self.max_tokens,    # 最大生成长度
                stream=stream                  # 是否流式输出
            )

            # 步骤 4: 处理响应
            if stream:
                # ========== 流式输出处理 ==========
                # 初始化空字符串，用于累积完整回复
                assistant_content = ''

                # response 是一个生成器，每次 yield 一个数据块（chunk）
                # for 循环迭代生成器，逐块处理
                for chunk in response:
                    # chunk.choices 是响应的选择列表（通常只有 1 个）
                    # chunk.choices[0].delta.content 是这一块的文本内容
                    # 检查是否存在且不为空
                    if chunk.choices and chunk.choices[0].delta.content:
                        content = chunk.choices[0].delta.content

                        # 累积到完整回复中
                        assistant_content += content

                        # print() 输出内容
                        # end='' 表示不换行，flush=True 表示立即输出（不缓冲）
                        print(content, end='', flush=True)

                # 循环结束，输出换行符，让后续输出从新行开始
                print()

            else:
                # ========== 非流式输出处理 ==========
                # 直接获取完整的回复内容
                # response.choices[0] 是第一个（也是唯一一个）回复选择
                # .message.content 是 AI 回复的文本
                assistant_content = response.choices[0].message.content

                # 直接打印完整回复
                print(assistant_content)

            # 步骤 5: 将 AI 回复添加到历史记录
            # role='assistant' 表示这是 AI 的回复
            self.add_message('assistant', assistant_content)

            # 返回完整回复内容
            return assistant_content

        except Exception as e:
            # ========== 异常处理 ==========
            # 当 API 调用失败时执行这里

            # 构造错误信息，str(e) 将异常对象转换为字符串
            error_msg = f"API 调用失败: {str(e)}"

            # 打印错误信息，\n 是换行符转义字符
            print(f"\n[错误] {error_msg}")

            # 如果刚才添加的用户消息还在，把它移除
            # 这样对话历史保持干净，不记录失败的对话
            # 检查 messages 非空且最后一条是 user 消息
            if self.messages and self.messages[-1]['role'] == 'user':
                # list.pop() 移除并返回列表的最后一个元素
                self.messages.pop()

            # re-raise 异常，让调用者知道出错了
            # raise 单独使用会重新抛出当前捕获的异常
            raise

    def clear_history(self) -> None:
        """
        清空对话历史，保留 system prompt

        这个操作不会删除 system prompt（第一条消息），
        因为 system prompt 定义了 AI 的角色，通常需要保留
        """
        # 初始化 system_message 为 None
        system_message = None

        # 如果 messages 非空且第一条是 system 消息，保存它
        if self.messages and self.messages[0]['role'] == 'system':
            # 将第一条消息赋值给 system_message
            system_message = self.messages[0]

        # 重建 messages 列表
        # 如果有 system_message，列表只包含它；否则为空列表 []
        self.messages = [system_message] if system_message else []

        # 打印确认信息，✓ 是勾选符号
        print("✓ 对话历史已清空")

    def set_system_prompt(self, prompt: str) -> None:
        """
        设置新的 system prompt（切换 AI 角色）

        这个方法允许在对话过程中动态切换 AI 的角色。
        例如从"普通助手"切换到"Python 专家"

        Args:
            prompt: 新的系统提示词字符串
        """
        # 步骤 1: 移除旧的 system prompt（如果存在）
        # 检查 messages 非空且第一条是 system 消息
        if self.messages and self.messages[0]['role'] == 'system':
            # list.pop(0) 移除列表的第一个元素
            # 注意：pop(0) 对于长列表效率较低，但这里 messages 通常不长
            self.messages.pop(0)

        # 步骤 2: 保存新的 system prompt 到实例变量
        self.system_prompt = prompt

        # 步骤 3: 在列表开头插入新的 system 消息
        # list.insert(index, element) 在指定位置插入元素
        # index=0 表示插入到最前面
        self.messages.insert(0, {
            'role': 'system',                          # 角色为 system
            'content': prompt,                         # 内容为新的提示词
            'timestamp': datetime.now().isoformat()    # 当前时间戳
        })

        # 打印确认信息，[:50] 切片只显示前 50 个字符，... 表示截断
        print(f"✓ 已切换角色: {prompt[:50]}...")

    def export_to_markdown(self, filepath: Optional[str] = None) -> str:
        """
        导出对话历史为 Markdown 文件

        Markdown 是一种轻量级标记语言，适合人类阅读
        导出的文件可以用任何文本编辑器或 Markdown 阅读器打开

        Args:
            filepath: 保存路径，可以是字符串或 Path 对象
                     如果为 None，使用默认命名格式：chat_年月日_时分秒.md

        Returns:
            保存的文件路径（字符串形式）
        """
        # 如果 filepath 为 None，生成默认文件名
        if not filepath:
            # datetime.now() 获取当前日期时间
            # .strftime() 格式化日期时间为字符串
            # %Y=4位年, %m=月, %d=日, %H=时, %M=分, %S=秒
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

            # Config.HISTORY_DIR 是预定义的历史目录路径
            # / 运算符用于拼接路径（Path 类支持）
            filepath = Config.HISTORY_DIR / f"chat_{timestamp}.md"
        else:
            # 如果提供了 filepath，转换为 Path 对象
            # Path(filepath) 可以接受字符串或 Path 对象
            filepath = Path(filepath)

        # 再次确保 filepath 是 Path 对象（防御性编程）
        filepath = Path(filepath)

        # 确保父目录存在
        # .parent 获取文件的父目录
        # mkdir() 创建目录，parents=True 表示创建所有必要的父目录
        # exist_ok=True 表示如果目录已存在不报错
        filepath.parent.mkdir(parents=True, exist_ok=True)

        # ----------------------------------------
        # 构建 Markdown 内容
        # ----------------------------------------

        # 初始化列表，用于存储 Markdown 内容的各行
        lines = []

        # 添加标题行，\n 是换行符
        lines.append(f"# 对话记录\n")

        # 添加元信息
        lines.append(f"**时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        lines.append(f"**模型**: {self.model}\n")
        lines.append(f"**Provider**: {Config.LLM_PROVIDER}\n")

        # 添加分隔线，--- 是 Markdown 的分隔线语法
        lines.append(f"\n---\n")

        # 遍历所有消息，生成对应的 Markdown 格式
        for msg in self.messages:
            # 从消息字典中提取字段
            role = msg['role']           # 消息角色
            content = msg['content']     # 消息内容
            timestamp = msg.get('timestamp', '')  # 时间戳，如果不存在返回空字符串

            # 根据角色类型生成不同的 Markdown 格式
            if role == 'system':
                # system 消息用二级标题
                lines.append(f"## System Prompt\n{content}\n\n---\n")
            elif role == 'user':
                # user 消息用表情符号 + 三级标题
                lines.append(f"### 👤 User\n{content}\n")
            elif role == 'assistant':
                # assistant 消息用机器人表情 + 三级标题
                lines.append(f"### 🤖 Assistant\n{content}\n\n---\n")

        # ----------------------------------------
        # 写入文件
        # ----------------------------------------

        # 使用 with 语句打开文件
        # with 语句确保文件在使用后正确关闭，即使发生异常
        # 'w' 模式表示写入（会覆盖已有内容）
        # encoding='utf-8' 指定编码，支持中文
        with open(filepath, 'w', encoding='utf-8') as f:
            # '\n'.join(lines) 将列表中的所有字符串用换行符连接
            # 然后写入文件
            f.write('\n'.join(lines))

        # 打印确认信息
        print(f"✓ 对话已保存到: {filepath}")

        # 返回文件路径的字符串形式
        # str() 将 Path 对象转换为字符串
        return str(filepath)

    def export_to_json(self, filepath: Optional[str] = None) -> str:
        """
        导出对话历史为 JSON 文件

        JSON 格式适合程序读取，包含完整的结构化数据
        与 Markdown 不同，JSON 保留了所有元数据（如时间戳）

        Args:
            filepath: 保存路径，如果为 None 使用默认命名

        Returns:
            保存的文件路径（字符串形式）
        """
        # 如果 filepath 为 None，生成默认文件名
        if not filepath:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filepath = Config.HISTORY_DIR / f"chat_{timestamp}.json"
        else:
            filepath = Path(filepath)

        # 确保是 Path 对象
        filepath = Path(filepath)

        # 确保父目录存在
        filepath.parent.mkdir(parents=True, exist_ok=True)

        # ----------------------------------------
        # 构建 JSON 数据结构
        # ----------------------------------------

        # 创建一个字典，包含元数据和消息列表
        data = {
            # metadata 包含对话的整体信息
            'metadata': {
                'model': self.model,                    # 使用的模型
                'provider': Config.LLM_PROVIDER,        # 提供商
                'created_at': datetime.now().isoformat(), # 导出时间
                'message_count': len(self.messages)     # 消息总数
            },
            # messages 包含完整的对话历史（带时间戳）
            'messages': self.messages
        }

        # 使用 with 语句打开文件写入 JSON
        with open(filepath, 'w', encoding='utf-8') as f:
            # json.dump() 将 Python 对象序列化为 JSON 字符串写入文件
            # data: 要序列化的对象
            # f: 文件对象
            # ensure_ascii=False: 允许写入非 ASCII 字符（如中文），不转义为 \uXXXX
            # indent=2: 使用 2 个空格缩进，使 JSON 更易读
            json.dump(data, f, ensure_ascii=False, indent=2)

        # 打印确认信息
        print(f"✓ 对话已保存到: {filepath}")

        # 返回文件路径字符串
        return str(filepath)

    def get_stats(self) -> Dict[str, Any]:
        """
        获取会话统计信息

        用于了解当前对话的状态，如消息数量、token 使用等

        Returns:
            包含统计信息的字典，键包括：
            - total_messages: 总消息数
            - user_messages: 用户消息数
            - assistant_messages: AI 消息数
            - estimated_tokens: 估算的 token 数
            - max_history_tokens: token 上限
            - model: 当前模型
            - provider: 当前提供商
        """
        # 使用生成器表达式统计 user 消息数量
        # sum(1 for ...) 对满足条件的元素计数（每个计 1）
        # 这比 len([...]) 更节省内存，因为不需要创建完整列表
        user_count = sum(1 for m in self.messages if m['role'] == 'user')

        # 同样方法统计 assistant 消息数量
        assistant_count = sum(1 for m in self.messages if m['role'] == 'assistant')

        # 将所有消息内容连接成一个字符串
        total_text = '\n'.join([m['content'] for m in self.messages])

        # 估算总 token 数
        estimated_tokens = self._estimate_tokens(total_text)

        # 构建并返回统计字典
        return {
            'total_messages': len(self.messages),        # len() 获取列表长度
            'user_messages': user_count,
            'assistant_messages': assistant_count,
            'estimated_tokens': estimated_tokens,
            'max_history_tokens': self.max_history_tokens,
            'model': self.model,
            'provider': Config.LLM_PROVIDER
        }
