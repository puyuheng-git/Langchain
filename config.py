"""
全局配置加载器
从 .env 文件读取所有配置参数
"""

# 导入 os 模块，用于读取环境变量
# 环境变量是操作系统层面的变量，可以在程序外部设置
import os

# 从 pathlib 导入 Path 类
# Path 是 Python 3.6+ 推荐的路径处理方式，比字符串操作更安全
from pathlib import Path

# 从 python-dotenv 库导入 load_dotenv 函数
# python-dotenv 用于从 .env 文件加载环境变量到系统环境变量中
from dotenv import load_dotenv

# ============================================
# 加载 .env 文件
# ============================================

# __file__ 是一个特殊变量，表示当前文件的路径
# Path(__file__) 将其转换为 Path 对象
# .parent 获取父目录（即当前文件所在的文件夹）
# '/' 是 Path 对象的路径连接符，等同于 os.path.join()
env_path = Path(__file__).parent / '.env'

# load_dotenv() 函数读取 .env 文件，将其中的键值对加载到环境变量中
# dotenv_path 参数指定 .env 文件的路径
# 加载后可以通过 os.getenv() 读取这些变量
load_dotenv(dotenv_path=env_path)


# ============================================
# 配置类定义
# ============================================

class Config:
    """
    配置类，集中管理所有环境变量

    使用类变量存储配置，方便全局访问
    所有配置项都有默认值，确保即使 .env 文件缺失也能运行
    """

    # ----------------------------------------
    # LLM 提供商配置
    # ----------------------------------------

    # os.getenv() 从环境变量读取值
    # 第一个参数是变量名，第二个是默认值（如果变量不存在）
    # LLM_PROVIDER 决定使用哪个大模型提供商：'deepseek' 或 'openai'
    LLM_PROVIDER = os.getenv('LLM_PROVIDER', 'deepseek')

    # ----------------------------------------
    # DeepSeek 配置
    # ----------------------------------------

    # DEEPSEEK_API_KEY 是访问 DeepSeek API 的密钥
    # 默认空字符串，必须在 .env 文件中设置真实值
    DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY', '')

    # DEEPSEEK_BASE_URL 是 DeepSeek API 的基础 URL
    # 所有 API 请求都会发送到这个地址
    DEEPSEEK_BASE_URL = os.getenv('DEEPSEEK_BASE_URL', 'https://api.deepseek.com/v1')

    # ----------------------------------------
    # OpenAI 配置（作为备选）
    # ----------------------------------------

    # OPENAI_API_KEY 是访问 OpenAI API 的密钥
    # 也兼容其他 OpenAI 格式的 API（如硅基流动）
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')

    # OPENAI_BASE_URL 是 OpenAI API 的基础 URL
    # 默认是 OpenAI 官方地址，可以改为其他兼容服务的地址
    OPENAI_BASE_URL = os.getenv('OPENAI_BASE_URL', 'https://api.openai.com/v1')

    # ----------------------------------------
    # 模型行为配置
    # ----------------------------------------

    # DEFAULT_MODEL 指定默认使用的模型名称
    # DeepSeek 的默认模型是 'deepseek-chat'
    DEFAULT_MODEL = os.getenv('DEFAULT_MODEL', 'deepseek-chat')

    # TEMPERATURE 控制生成文本的随机性
    # 取值范围 0-2，值越低输出越确定，值越高越有创意
    # float() 将字符串转换为浮点数
    TEMPERATURE = float(os.getenv('TEMPERATURE', '0.7'))

    # MAX_TOKENS 限制每次回复的最大 token 数
    # token 是大语言模型的计费单位，约等于 1 个中文字符
    # int() 将字符串转换为整数
    MAX_TOKENS = int(os.getenv('MAX_TOKENS', '2000'))

    # ----------------------------------------
    # 历史记录配置
    # ----------------------------------------

    # MAX_HISTORY_TOKENS 是历史消息的 token 上限
    # 当历史消息超过这个值时，最早的消息会被自动删除
    # 这是为了控制 API 调用成本，因为历史消息也会计费
    MAX_HISTORY_TOKENS = int(os.getenv('MAX_HISTORY_TOKENS', '4000'))

    # ----------------------------------------
    # 系统提示词配置
    # ----------------------------------------

    # SYSTEM_PROMPT 定义 AI 助手的默认角色和行为
    # 这是对话的第一条消息，role="system"
    SYSTEM_PROMPT = os.getenv('SYSTEM_PROMPT', '你是一个 helpful 的 AI 助手。')

    # ----------------------------------------
    # 路径配置
    # ----------------------------------------

    # DATA_DIR 是数据存储的根目录
    # Path(__file__).parent 获取当前文件所在目录
    # / 'data' 在该目录下创建 data 子目录
    DATA_DIR = Path(__file__).parent / 'data'

    # HISTORY_DIR 是对话历史存储目录
    # 位于 DATA_DIR 下的 history 子目录
    HISTORY_DIR = DATA_DIR / 'history'

    # DOCS_DIR 是原始文档存储目录（V2 使用，V3 知识库写入工具也会用到）
    # 位于 DATA_DIR 下的 docs 子目录
    DOCS_DIR = DATA_DIR / 'docs'

    # REMINDERS_FILE 是提醒事项的存储文件（V3 新增）
    # Agent 的「日历提醒」工具会把待办写入这个 JSON 文件
    # 程序启动时会读取它，实现「主动提醒」功能
    REMINDERS_FILE = DATA_DIR / 'reminders.json'

    # ----------------------------------------
    # 【V3 新增】Ollama 本地模型配置
    # ----------------------------------------

    # OLLAMA_BASE_URL 是本地 Ollama 服务的地址
    # Ollama 提供 OpenAI 兼容接口，所以可以复用现有的 ChatSession
    # 默认 http://localhost:11434/v1（Ollama 的标准本地地址）
    # V4 微调完成后，把 LLM_PROVIDER 改成 ollama 即可用本地模型
    OLLAMA_BASE_URL = os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434/v1')

    # OLLAMA_MODEL 是要使用的本地模型名称
    # 例如 qwen2.5:7b，或微调导出后你自己命名的模型（如 my-brain）
    OLLAMA_MODEL = os.getenv('OLLAMA_MODEL', 'qwen2.5:7b')

    # ----------------------------------------
    # 【V3 新增】工具相关配置
    # ----------------------------------------

    # TAVILY_API_KEY 是 Tavily 网页搜索服务的密钥
    # Tavily 每月有 1000 次免费额度，专为 AI Agent 设计
    # 注册地址：https://tavily.com
    # 如果不填，网页搜索工具会返回友好提示而不是报错
    TAVILY_API_KEY = os.getenv('TAVILY_API_KEY', '')

    # AGENT_MAX_ITERATIONS 是 Agent 的最大循环次数
    # Agent 会「思考→调用工具→再思考」循环，这个值防止无限循环
    # 达到上限后会强制进入收尾（反思）节点，避免卡死和费用失控
    AGENT_MAX_ITERATIONS = int(os.getenv('AGENT_MAX_ITERATIONS', '5'))

    # MEMORY_COLLECTION 是长期记忆在 Chroma 中的集合名称
    # 它与知识库文档（documents 集合）分开存储，互不干扰
    MEMORY_COLLECTION = os.getenv('MEMORY_COLLECTION', 'long_term_memory')

    # ----------------------------------------
    # 【V4 新增】多模态（图片 OCR）配置
    # ----------------------------------------

    # VISION_MODEL 是用于图片文字识别（OCR）的多模态模型名称
    # 默认 gpt-4o，它能「看懂」图片并提取文字
    # 复用 OPENAI_API_KEY / OPENAI_BASE_URL（因为是 OpenAI 兼容接口）
    VISION_MODEL = os.getenv('VISION_MODEL', 'gpt-4o')

    # ========================================
    # 类方法
    # ========================================

    @classmethod
    def get_api_config(cls):
        """
        根据 LLM_PROVIDER 返回对应的 API 配置

        类方法（@classmethod）可以通过类名直接调用，不需要创建实例
        cls 参数代表类本身（这里是 Config 类）

        Returns:
            dict: 包含 api_key, base_url, model 的字典

        Raises:
            ValueError: 当 LLM_PROVIDER 不支持或 API Key 未设置时抛出
        """
        # 检查 LLM_PROVIDER 的值，使用 if-elif-else 结构
        # == 是 Python 中的相等比较运算符

        if cls.LLM_PROVIDER == 'deepseek':
            # 检查 API Key 是否已设置
            # not 是逻辑非运算符，空字符串会被视为 False
            if not cls.DEEPSEEK_API_KEY:
                # raise 用于抛出异常，程序会停止执行并显示错误信息
                raise ValueError("DEEPSEEK_API_KEY 未设置，请在 .env 文件中配置")

            # 返回字典（dict），包含三个键值对
            # 字典是 Python 中常用的数据结构，用 {} 表示
            return {
                'api_key': cls.DEEPSEEK_API_KEY,      # API 密钥
                'base_url': cls.DEEPSEEK_BASE_URL,    # API 基础地址
                # 条件表达式：如果 DEFAULT_MODEL 包含 'deepseek' 就用它，否则用默认值
                # 'deepseek' in cls.DEFAULT_MODEL 返回布尔值（True/False）
                'model': cls.DEFAULT_MODEL if 'deepseek' in cls.DEFAULT_MODEL else 'deepseek-chat'
            }

        elif cls.LLM_PROVIDER == 'openai':
            # 同样检查 OpenAI 的 API Key
            if not cls.OPENAI_API_KEY:
                raise ValueError("OPENAI_API_KEY 未设置，请在 .env 文件中配置")

            return {
                'api_key': cls.OPENAI_API_KEY,
                'base_url': cls.OPENAI_BASE_URL,
                # 检查 DEFAULT_MODEL 是否包含 'gpt'，这是 OpenAI 模型的特征
                'model': cls.DEFAULT_MODEL if 'gpt' in cls.DEFAULT_MODEL else 'gpt-3.5-turbo'
            }

        elif cls.LLM_PROVIDER == 'ollama':
            # 【V3/V4 新增】Ollama 本地模型分支
            # Ollama 是本地运行大模型的工具，提供 OpenAI 兼容接口
            # 因为是本地服务，不需要真实 API Key，但 OpenAI SDK 要求非空
            # 所以这里填一个占位字符串 'ollama'
            return {
                'api_key': 'ollama',                 # 占位符，本地服务不校验
                'base_url': cls.OLLAMA_BASE_URL,     # 本地 Ollama 地址
                'model': cls.OLLAMA_MODEL            # 本地模型名称
            }

        else:
            # f-string（格式化字符串）用于在字符串中嵌入变量
            # {cls.LLM_PROVIDER} 会被替换为实际的值
            raise ValueError(f"不支持的 LLM_PROVIDER: {cls.LLM_PROVIDER}")

    @classmethod
    def ensure_directories(cls):
        """
        确保必要的目录存在

        如果目录不存在则自动创建，避免后续操作因目录不存在而报错
        """
        # mkdir() 创建目录
        # exist_ok=True 表示如果目录已存在则不报错（避免 FileExistsError）
        # parents=True 表示如果需要则自动创建父目录
        cls.DATA_DIR.mkdir(exist_ok=True)
        cls.HISTORY_DIR.mkdir(exist_ok=True)
        # 【V2/V3】确保文档目录存在（知识库写入工具会用到）
        cls.DOCS_DIR.mkdir(exist_ok=True)


# ============================================
# 模块初始化时执行的代码
# ============================================

# 调用类方法，确保 data/ 和 data/history/ 目录存在
# 这行代码在导入 config 模块时就会自动执行
Config.ensure_directories()

# ============================================
# 测试代码
# ============================================

# __name__ 是 Python 的内置变量
# 当直接运行文件时，__name__ == '__main__'
# 当作为模块被导入时，__name__ == 'config'（模块名）
# 这个判断确保测试代码只在直接运行文件时执行，导入时不会执行
if __name__ == '__main__':

    # print() 函数输出内容到控制台
    # ✓ 是一个 Unicode 字符，表示勾选/成功
    print("✓ 配置加载成功")

    # f-string 格式化输出，{变量} 会被替换为实际值
    # 前面加两个空格是为了对齐输出
    print(f"  LLM_PROVIDER: {Config.LLM_PROVIDER}")
    print(f"  DEFAULT_MODEL: {Config.DEFAULT_MODEL}")
    print(f"  MAX_HISTORY_TOKENS: {Config.MAX_HISTORY_TOKENS}")

    # try-except 结构用于异常处理
    # 如果 try 块中的代码抛出异常，程序不会崩溃，而是执行 except 块
    try:
        # 调用类方法获取 API 配置
        api_config = Config.get_api_config()

        # 打印 API 基础地址
        print(f"  API Base URL: {api_config['base_url']}")

        # 安全地显示 API Key（只显示后4位，前面用星号代替）
        # '*' * 10 生成 10 个星号字符串
        # [-4:] 切片操作，获取字符串的最后 4 个字符
        # if-else 三元表达式：如果有 api_key 就显示部分，否则显示"未设置"
        api_key_display = ('*' * 10) + api_config['api_key'][-4:] if api_config['api_key'] else '未设置'
        print(f"  API Key: {api_key_display}")

    except ValueError as e:
        # 捕获 ValueError 异常，e 是异常对象，包含错误信息
        # ⚠ 是警告符号
        print(f"  ⚠ {e}")
